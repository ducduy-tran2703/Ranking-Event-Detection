"""Đặt tên mọi sự kiện của một thư mục sự kiện (đầu ra gom cụm) bằng ViT5 đã fine-tune → ten_su_kien.csv.

    uv run --group embed python -m eventrank.naming.predict                    # data/events/v1/ → ten_su_kien.csv cùng chỗ
    uv run --group embed python -m eventrank.naming.predict --bench 32         # đo tốc độ lô 1 / 4 / 8 / 16 trên CPU
    uv run --group embed python -m eventrank.naming.predict --migrate-cache    # chuyển đệm khoá cũ sang khoá mới

Cấu hình: mục `naming` của configs/pipeline.yaml (đường dẫn mô hình, naming_version, lô, beam, …).

Luật đặt tên:
- Cụm 1 bài → tiêu đề bài (đã bỏ tiền tố "Video:", "Clip:"…), nguon=`title`, không chạy mô hình. Tiêu đề dài hơn
  `max_syllables` (22) âm tiết → `text.shorten_v2`, nguon vẫn `title`, ly_do_fallback=`rut_gon`.
- Cụm ≥ 2 bài → ViT5. Đầu vào GIỐNG HỆT lúc train: `dataset.block(e)` → `text.clean_input` (medoid đầu, bỏ tiêu đề trùng,
  ≤ 12 tiêu đề, ≤ 3 sapo khác báo cắt 240 ký tự). Sinh beam 4, max_new_tokens 48, no_repeat_ngram_size 3 (như notebook).
- Hậu kiểm tên mô hình (`postcheck`): NFC, gộp khoảng trắng, `text.fix_decode` ("U2 3" → "U23", " ," → ","); rơi về
  **medoid rút gọn** (`text.shorten_v2`, cắt ở ranh giới cụm từ, nguon=`medoid`) nếu rỗng (`rong`), > 22 âm tiết
  (`qua_dai`), có số / từ viết hoa không có trong đầu vào (`khong_trung_thuc`, theo `text.faithful_v2`: so theo token,
  ngày khác định dạng vẫn khớp, có bảng viết tắt) hoặc lặp thực thể kiểu "Man City thua Man City" (`lap_thuc_the`).
  Nhiều lý do → nối bằng `+`. Tên gốc của mô hình giữ ở `ten_mo_hinh`. Hậu kiểm KHÔNG nằm trong khoá đệm → đổi hậu kiểm
  không phải sinh lại.

Lưu đệm: data/naming/cache/<naming_version>.jsonl, mỗi dòng là tên THÔ của mô hình, khoá = (sha1 đầu vào `src` sau
clean_input, naming_version, `gen_hash` = băm tham số sinh + đường dẫn/kích thước mô hình). Đổi đầu vào (sapo, số tiêu đề…),
tham số sinh hay mô hình → khoá đổi → sinh lại; gom cụm lại mà cụm giữ nguyên đầu vào → dùng lại dù event_id đổi. Ghi nối
đuôi sau mỗi lô → dừng giữa chừng không mất. Dòng khoá cũ (event_id + băm tập bài, trước 03/11/2026) bị bỏ qua; dùng
`--migrate-cache` để chuyển sang khoá mới (cùng đầu vào → cùng tên thô) thay vì sinh lại ~1 giờ.
`max_generate` (cấu hình / --max-generate): số cụm tối đa được sinh trong một lần chạy, quá thì dừng TRƯỚC khi nạp mô hình.

Đầu ra `ten_su_kien.csv`: event_id, ten, nguon (model | medoid | title), ly_do_fallback, ten_mo_hinh (chỉ ghi khi bị
thay), so_am_tiet (tách khoảng trắng), naming_version.

Máy 7,6 GB RAM: mô hình fp32 ~0,9 GB + bộ nhớ đệm cross-attention tăng theo lô × beam × độ dài đầu vào → lô 8 là vừa
(đo 03/11 trên 64 cụm, CPU 8 luồng: lô 1 ≈ 1,6 s/cụm, lô 8 ≈ 1,0 s/cụm, tên trùng 100%); nạp mô hình một lần, giải phóng
ngay khi xong (`Vit5Namer.close`).
"""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

from eventrank.clustering.pipeline import OUT as EVENTS_DIR
from eventrank.clustering.pipeline import SILVER
from eventrank.naming.dataset import block, build_events
from eventrank.naming.text import (
    clean_input,
    faithful_v2_reasons,
    fix_decode,
    medoid_title,
    nfc,
    shorten_v2,
)

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "configs/pipeline.yaml"
FIELDS = ["event_id", "ten", "nguon", "ly_do_fallback", "ten_mo_hinh", "so_am_tiet", "naming_version"]
DEFAULTS = {"batch_size": 8, "num_beams": 4, "max_new_tokens": 48, "no_repeat_ngram_size": 3, "max_source_len": 512,
            "max_titles": 12, "max_sapos": 3, "max_syllables": 22, "device": "auto",
            "cache_dir": "data/naming/cache", "max_generate": None}
GEN_KEYS = ("num_beams", "max_new_tokens", "no_repeat_ngram_size", "max_source_len")

Generator = Callable[[list[str]], list[str]]


def load_config(path: str | Path = CONFIG) -> dict:
    """Mục `naming` của configs/pipeline.yaml, bổ sung giá trị mặc định."""
    import yaml

    with open(path, encoding="utf-8") as f:
        cfg = {**DEFAULTS, **(yaml.safe_load(f) or {}).get("naming", {})}
    missing = {"model", "naming_version"} - set(cfg)
    if missing:
        raise ValueError(f"thiếu khoá cấu hình naming: {sorted(missing)}")
    return cfg


def _path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def article_hash(ids: list[str]) -> str:
    """Băm tập article_id (không phụ thuộc thứ tự) — khoá đệm CŨ, chỉ dùng khi chuyển đệm (`migrate_cache`)."""
    return hashlib.sha1("\n".join(sorted(ids)).encode()).hexdigest()[:16]


def src_hash(src: str) -> str:
    return hashlib.sha1(src.encode()).hexdigest()


def gen_hash(cfg: dict) -> str:
    """Băm tham số sinh + mô hình (đường dẫn như trong cấu hình + kích thước model.safetensors)."""
    w = _path(cfg["model"]) / "model.safetensors"
    key = {**{k: cfg[k] for k in GEN_KEYS}, "early_stopping": True, "model": str(cfg["model"]),
           "model_bytes": w.stat().st_size if w.exists() else None}
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def postcheck(raw: str, src: str, medoid: str, max_syllables: int = 22) -> dict:
    """Tên thô của mô hình → dòng kết quả (giữ tên mô hình hoặc rơi về medoid rút gọn, kèm lý do)."""
    ten = fix_decode(" ".join(nfc(raw or "").split()))
    reasons = []
    if not ten:
        reasons.append("rong")
    else:
        if len(ten.split()) > max_syllables:
            reasons.append("qua_dai")
        why = faithful_v2_reasons(ten, src)
        if {"so", "ten_rieng"} & set(why):
            reasons.append("khong_trung_thuc")
        if "lap_thuc_the" in why:
            reasons.append("lap_thuc_the")
    if not reasons:
        return {"ten": ten, "nguon": "model", "ly_do_fallback": "", "ten_mo_hinh": ""}
    return {"ten": fix_decode(shorten_v2(medoid, max_syllables)), "nguon": "medoid",
            "ly_do_fallback": "+".join(reasons), "ten_mo_hinh": ten}


def title_name(title: str, max_syllables: int = 22) -> dict:
    """Tên cụm 1 bài = tiêu đề; dài hơn max_syllables → rút gọn ở ranh giới cụm từ (ly_do `rut_gon`)."""
    if len(title.split()) <= max_syllables:
        return {"ten": title, "nguon": "title", "ly_do_fallback": "", "ten_mo_hinh": ""}
    return {"ten": shorten_v2(title, max_syllables), "nguon": "title", "ly_do_fallback": "rut_gon", "ten_mo_hinh": ""}


class Vit5Namer:
    """Bọc ViT5 đã fine-tune: danh sách đầu vào đã làm sạch → danh sách tên thô. Gọi `close()` để giải phóng RAM."""

    def __init__(self, cfg: dict, log: Callable[[str], None] = print):
        import torch
        from transformers import AutoModelForSeq2SeqLM, PreTrainedTokenizerFast
        from transformers.utils import logging as hf_logging

        hf_logging.disable_progress_bar()                            # thanh tiến độ làm rối pipeline.log

        self.torch, self.cfg = torch, cfg
        dev = cfg.get("device", "auto")
        self.device = torch.device("cuda" if dev == "auto" and torch.cuda.is_available() else
                                   ("cpu" if dev == "auto" else dev))
        m = _path(cfg["model"])
        # transformers 5.x không dựng được tokenizer ViT5 bằng AutoTokenizer → nạp thẳng tokenizer.json (README mô hình)
        self.tok = PreTrainedTokenizerFast(tokenizer_file=str(m / "tokenizer.json"),
                                           eos_token="</s>", unk_token="<unk>", pad_token="<pad>")
        if self.tok("a").input_ids[-1] != self.tok.eos_token_id:
            raise RuntimeError("tokenizer không thêm </s> — khác lúc train")
        self.model = AutoModelForSeq2SeqLM.from_pretrained(m).to(self.device).eval()
        log(f"nạp {m.name} lên {self.device} ({torch.get_num_threads()} luồng CPU)")

    def __call__(self, xs: list[str]) -> list[str]:
        c = self.cfg
        with self.torch.inference_mode():
            enc = self.tok(xs, max_length=c["max_source_len"], truncation=True, padding=True,
                           return_tensors="pt").to(self.device)
            out = self.model.generate(**enc, num_beams=c["num_beams"], max_new_tokens=c["max_new_tokens"],
                                      no_repeat_ngram_size=c["no_repeat_ngram_size"], early_stopping=True)
        return self.tok.batch_decode(out, skip_special_tokens=True)

    def close(self) -> None:
        del self.model
        gc.collect()
        if self.device.type == "cuda":
            self.torch.cuda.empty_cache()


def _read_jsonl(path: Path):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:                         # dòng cuối dở dang khi bị ngắt
                    continue


def _load_cache(path: Path, version: str, ghash: str) -> dict[str, str]:
    """{sha1(src): tên thô} của các dòng cùng naming_version và gen_hash (dòng khoá cũ / khoá khác bị bỏ qua)."""
    return {r["src_hash"]: r["raw"] for r in _read_jsonl(path)
            if r.get("naming_version") == version and r.get("gen_hash") == ghash and "src_hash" in r}


def _cache_line(j: dict, raw: str, version: str, ghash: str) -> str:
    return json.dumps({"src_hash": src_hash(j["src"]), "gen_hash": ghash, "naming_version": version,
                       "event_id": j["event_id"], "raw": raw}, ensure_ascii=False) + "\n"


def prepare(events: list[dict], cfg: dict) -> list[dict]:
    """Sự kiện (build_events) → việc cần đặt tên: đầu vào mô hình, medoid, tiêu đề (cụm 1 bài)."""
    jobs = []
    for e in events:
        b = block(e)
        jobs.append({"event_id": e["event_id"], "size": e["size"], "hash": article_hash([a["id"] for a in e["articles"]]),
                     "src": clean_input(b, cfg["max_titles"], cfg["max_sapos"]), "medoid": medoid_title(b),
                     "title": " ".join(nfc(e["articles"][0]["title"]).split())})
    return jobs


def migrate_cache(jobs: list[dict], cfg: dict, cache: Path, log: Callable[[str], None] = print) -> int:
    """Chuyển dòng đệm khoá cũ (event_id, băm tập bài) của `jobs` sang khoá mới (sha1 src + gen_hash), nối vào cùng file.
    Hợp lệ khi đầu vào và tham số sinh không đổi kể từ lúc sinh (cùng naming_version) — cùng đầu vào thì cùng tên thô."""
    version, ghash = cfg["naming_version"], gen_hash(cfg)
    old = {(r["event_id"], r["article_hash"]): r["raw"] for r in _read_jsonl(cache)
           if r.get("naming_version") == version and "article_hash" in r}
    have = _load_cache(cache, version, ghash)
    lines = [_cache_line(j, old[(j["event_id"], j["hash"])], version, ghash) for j in jobs
             if j["size"] >= 2 and (j["event_id"], j["hash"]) in old and src_hash(j["src"]) not in have]
    with open(cache, "a", encoding="utf-8") as f:
        f.writelines(lines)
    log(f"chuyển {len(lines)} dòng đệm sang khoá mới ({len(old)} dòng khoá cũ, {len(have)} đã có khoá mới) → {cache}")
    return len(lines)


def name_jobs(jobs: list[dict], cfg: dict, generator: Generator | None = None, cache: Path | None = None,
              log: Callable[[str], None] = print) -> tuple[list[dict], dict]:
    """Đặt tên cho các việc; trả (dòng ten_su_kien theo thứ tự `jobs`, thống kê)."""
    version, bs, ghash = cfg["naming_version"], int(cfg["batch_size"]), gen_hash(cfg)
    done = _load_cache(cache, version, ghash) if cache else {}
    todo, seen = [], set()
    for j in jobs:
        h = src_hash(j["src"])
        if j["size"] >= 2 and h not in done and h not in seen:
            seen.add(h)
            todo.append(j)
    todo.sort(key=lambda j: len(j["src"]))                           # độ dài gần nhau trong một lô → ít đệm
    n_multi = sum(j["size"] >= 2 for j in jobs)
    log(f"{len(jobs)} sự kiện: {n_multi} cụm ≥ 2 bài ({n_multi - len(todo)} có trong đệm, cần sinh {len(todo)}), "
        f"{len(jobs) - n_multi} cụm 1 bài dùng tiêu đề")
    limit = cfg.get("max_generate")
    if limit is not None and len(todo) > int(limit):
        raise RuntimeError(f"cần sinh {len(todo)} cụm > max_generate={limit} — dừng trước khi nạp mô hình "
                           "(kiểm tra khoá đệm / chạy --migrate-cache, hoặc nâng max_generate)")
    t0, own = time.perf_counter(), None
    if todo:
        if generator is None:
            generator = own = Vit5Namer(cfg, log)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            f = stack.enter_context(open(cache, "a", encoding="utf-8")) if cache else None
            if own is not None:
                stack.callback(own.close)                            # giải phóng mô hình kể cả khi bị ngắt
            for k in range(0, len(todo), bs):
                part = todo[k:k + bs]
                outs = generator([j["src"] for j in part])
                for j, raw in zip(part, outs, strict=True):
                    done[src_hash(j["src"])] = raw
                    if f:
                        f.write(_cache_line(j, raw, version, ghash))
                if f:
                    f.flush()
                n = min(k + bs, len(todo))
                if n == len(todo) or (k // bs) % 10 == 0:
                    sec = time.perf_counter() - t0
                    log(f"  {n}/{len(todo)} cụm · {sec / n:.2f} s/cụm · còn ~{(len(todo) - n) * sec / n / 60:.0f} phút")
    rows = []
    mx = int(cfg["max_syllables"])
    for j in jobs:
        if j["size"] < 2:
            r = title_name(j["title"], mx)
        else:
            r = postcheck(done[src_hash(j["src"])], j["src"], j["medoid"], mx)
        rows.append({"event_id": j["event_id"], **r, "so_am_tiet": len(r["ten"].split()), "naming_version": version})
    sec = time.perf_counter() - t0
    nguon = Counter(r["nguon"] for r in rows)
    reasons = Counter(x for r in rows if r["nguon"] == "medoid" for x in r["ly_do_fallback"].split("+") if x)
    stats = {"n_events": len(rows), "n_multi": n_multi, "n_generated": len(todo), "n_cached": n_multi - len(todo),
             "nguon": dict(nguon), "ly_do_fallback": dict(reasons),
             "n_title_rut_gon": sum(r["ly_do_fallback"] == "rut_gon" for r in rows),
             "fallback_rate_multi": round(nguon["medoid"] / n_multi, 4) if n_multi else None,
             "gen_hash": ghash, "seconds_generate": round(sec, 1),
             "sec_per_cluster": round(sec / len(todo), 3) if todo else None}
    log(f"nguồn tên: {dict(nguon)} · lý do rơi về medoid: {dict(reasons)} · tiêu đề rút gọn: {stats['n_title_rut_gon']}")
    return rows, stats


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _cache_path(cfg: dict) -> Path:
    return _path(cfg["cache_dir"]) / f"{cfg['naming_version']}.jsonl"


def run(events_dir: str | Path, cfg: dict, out_dir: str | Path | None = None, silver_glob: str = SILVER,
        generator: Generator | None = None, log: Callable[[str], None] = print) -> dict:
    """Đặt tên mọi sự kiện của `events_dir` (su_kien.csv + bai_su_kien.csv) → out_dir/ten_su_kien.csv."""
    events_dir = Path(events_dir)
    out_dir = Path(out_dir) if out_dir else events_dir
    events = build_events(events_dir, silver_glob, min_size=1, before=None)
    cache = _cache_path(cfg)
    rows, stats = name_jobs(prepare(events, cfg), cfg, generator, cache, log)
    write_csv(out_dir / "ten_su_kien.csv", rows, FIELDS)
    log(f"→ {out_dir / 'ten_su_kien.csv'}")
    return stats | {"cache": str(cache)}


def bench(events_dir: str | Path, cfg: dict, n: int, batch_sizes: list[int], silver_glob: str = SILVER,
          log: Callable[[str], None] = print) -> dict:
    """Đo tốc độ sinh theo cỡ lô trên `n` cụm ≥ 2 bài rải đều (không ghi đệm). Báo tỉ lệ tên trùng với lô 1."""
    events = [e for e in build_events(Path(events_dir), silver_glob, min_size=2, before=None)]
    events = [events[round(k * (len(events) - 1) / max(n - 1, 1))] for k in range(n)]
    jobs = sorted(prepare(events, cfg), key=lambda j: len(j["src"]))
    gen = Vit5Namer(cfg, log)
    try:
        gen([jobs[0]["src"]])                                        # khởi động
        res, ref = {}, None
        for bs in batch_sizes:
            t0, outs = time.perf_counter(), []
            for k in range(0, len(jobs), bs):
                outs += gen([j["src"] for j in jobs[k:k + bs]])
            sec = time.perf_counter() - t0
            ref = ref or outs
            same = sum(a == b for a, b in zip(outs, ref)) / len(outs)
            res[bs] = {"sec_per_cluster": round(sec / len(jobs), 3), "same_as_first": round(same, 3)}
            log(f"lô {bs:2d}: {sec / len(jobs):.2f} s/cụm · trùng tên với lô {batch_sizes[0]}: {same:.0%}")
    finally:
        gen.close()
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--events-dir", default=str(EVENTS_DIR / "v1"), help="thư mục có su_kien.csv + bai_su_kien.csv")
    ap.add_argument("--out", default="", help="thư mục ghi ten_su_kien.csv (mặc định = --events-dir)")
    ap.add_argument("--silver-glob", default=SILVER)
    ap.add_argument("--batch-size", type=int, default=0, help="ghi đè batch_size trong cấu hình")
    ap.add_argument("--bench", type=int, default=0, help="chỉ đo tốc độ trên N cụm, không ghi gì")
    ap.add_argument("--batch-sizes", default="1,4,8,16", help="các cỡ lô để đo (với --bench)")
    ap.add_argument("--max-generate", type=int, default=None, help="dừng nếu cần sinh nhiều hơn N cụm")
    ap.add_argument("--migrate-cache", action="store_true",
                    help="chuyển đệm khoá cũ của các cụm trong --events-dir sang khoá mới rồi thoát")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.batch_size:
        cfg["batch_size"] = a.batch_size
    if a.max_generate is not None:
        cfg["max_generate"] = a.max_generate
    if a.migrate_cache:
        events = build_events(Path(a.events_dir), a.silver_glob, min_size=2, before=None)
        migrate_cache(prepare(events, cfg), cfg, _cache_path(cfg))
    elif a.bench:
        print(json.dumps(bench(a.events_dir, cfg, a.bench, [int(x) for x in a.batch_sizes.split(",")], a.silver_glob)))
    else:
        run(a.events_dir, cfg, a.out or None, a.silver_glob, log=lambda m: print(m, flush=True))


if __name__ == "__main__":
    main()
