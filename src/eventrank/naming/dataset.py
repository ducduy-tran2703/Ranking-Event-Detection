"""Bộ dữ liệu đặt tên sự kiện v1: mỗi sự kiện ≥ 2 bài của pipeline gom cụm → một tên, do 2 agent xem xét.

    uv run --group embed python -m eventrank.naming.dataset prep                 → data/naming/v1/{events.json, parts/gen_XX.md}
    # agent ĐẶT TÊN đọc gen_XX.md → ghi parts/gen_XX.json
    uv run --group embed python -m eventrank.naming.dataset prep-check           → parts/check_XX.md (cho mọi gen_XX.json đã có)
    # agent KIỂM TRA (agent khác) đọc check_XX.md → ghi parts/check_XX.json
    uv run --group embed python -m eventrank.naming.dataset merge                → naming_v1.csv (để người duyệt) + {train,dev}.jsonl

Nguồn: data/events/<algo_version>/ (pipeline gom cụm) + Silver (tiêu đề, sapo). Chỉ lấy sự kiện có bài đầu tiên trước
11/09/2026 — cửa sổ 14–15/09 là tập test (tên người viết mù, làm riêng). train = trước 08/09, dev = 08–10/09.
Tên cuối = tên agent kiểm tra sửa (nếu sửa) hoặc tên agent đặt tên; cột `nguoi_duyet` để trống cho người kiểm tra.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from eventrank.clustering.pipeline import OUT as EVENTS_DIR
from eventrank.clustering.pipeline import SILVER, load_silver

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data/naming/v1"
DEV_START, TEST_START = "2026-09-08", "2026-09-11"
MAX_TITLES, MAX_SAPOS, SAPO_CHARS = 25, 3, 240

HUONG_DAN = """\
## Hướng dẫn đặt tên sự kiện (bộ dữ liệu đặt tên v1)

Mỗi khối dưới đây là MỘT sự kiện tin tức do hệ thống gom cụm tự động: nhiều bài báo (nhiều báo khác nhau) cùng nói về
một việc. Tên sự kiện sẽ hiện trên app như tiêu đề của cả cụm.

1. **Đủ nghĩa cho CẢ cụm**, không chỉ cho bài đầu tiên hay bài medoid. Đọc hết các tiêu đề. Nếu cụm gồm nhiều hoạt động
   của một chương trình / chuyến thăm / giải đấu / vụ việc → tên nêu chương trình / chuyến thăm / vụ việc đó.
2. **Khung:** ai / cái gì + làm gì / chuyện gì + (kết quả, đối tượng) + (bối cảnh: nơi, giải, dịp — chỉ khi cần để hiểu
   hoặc phân biệt). Người đọc chỉ xem tên phải biết chuyện gì đã xảy ra.
3. **Độ dài:** không gò dưới 10 từ, nhưng không dài — thường 8–16 âm tiết, **tối đa 20 âm tiết** (khoảng một dòng tít
   báo). Bỏ chi tiết phụ trước khi bỏ ý chính.
4. **Trung thực:** mọi tên riêng, con số, tỉ số, ngày trong tên phải có trong tiêu đề/sapo của cụm. Không suy đoán, không
   thêm kiến thức ngoài. Các bài lệch nhau về số liệu → dùng số đa số bài, hoặc bỏ số.
5. **Đúng thời điểm của cụm:** cụm đã có kết quả → nêu kết quả (trận đấu: tỉ số, thắng/thua/hoà). Cụm chỉ có bài trước
   sự kiện → nêu sự kiện sắp diễn ra ("gặp", "sẽ", "chuẩn bị").
6. **Văn phong trung tính, dạng tít tin:** không câu view ("bất ngờ", "sốc", "rất hay", "gây bão"), không câu hỏi,
   không dấu hai chấm kiểu tít báo, không tiền tố "Video:", "Clip:", "Trực tiếp:", không ngoặc kép cảm thán, không dấu
   chấm cuối.
7. **Ngày tháng:** chỉ thêm khi là chuỗi định kỳ (giá vàng, tỷ giá, chứng khoán, thời tiết, xổ số — mỗi phiên/ngày là
   một sự kiện) hoặc thật cần để phân biệt. Viết dạng "14/9".
8. **Tên người, tổ chức:** chức danh ngắn + họ tên ở lần nhắc (Thủ tướng Lê Minh Hưng, HLV Hoàng Văn Phúc). Tên nước,
   đội nước ngoài theo cách gọi của đa số bài.
9. **Cụm lẫn:** nếu cụm rõ ràng gồm ≥ 2 sự kiện khác nhau (không phải các diễn biến của cùng một việc) → đặt tên theo
   sự kiện chiếm nhiều bài nhất, đặt `cum_lan: true` và ghi số thứ tự các bài lạc vào `ghi_chu`. Cụm bản tin tổng hợp
   nhiều tin không liên quan → cũng `cum_lan: true`.

Ví dụ (từ dữ liệu khác, chỉ để thấy văn phong):
- "Tuyển nữ Việt Nam thua Đài Loan 1-2 trận ra quân ASIAD"
- "Tổng Bí thư, Chủ tịch nước Tô Lâm thăm chính thức Pháp"
- "Giá vàng trong nước giảm sâu phiên 14/9"
- "Hà Nội ngập nhiều tuyến phố sau mưa lớn đêm 14/9"
- "Apple phát hành iOS 27 cho iPhone"
"""

GEN_TASK = """\
# Đặt tên sự kiện — phần {part}

Bạn là agent ĐẶT TÊN. File có {n} sự kiện. Đọc hướng dẫn rồi đọc HẾT các sự kiện (file dài → đọc tiếp bằng offset cho
tới dòng cuối). Mỗi sự kiện đặt một tên theo hướng dẫn.

Ghi kết quả ra `{out}` — JSON, một mảng, đúng {n} phần tử, đúng thứ tự, mỗi phần tử:
`{{"event_id": "...", "ten": "...", "cum_lan": false, "ghi_chu": ""}}`
(`ghi_chu` để trống trừ khi cụm lẫn hoặc có điều cần người duyệt biết, tối đa một câu.)
Không dùng script/LLM khác để sinh tên; tự đọc và tự viết. Ghi xong kiểm tra lại file là JSON hợp lệ, đủ {n} phần tử.
Trả lời cuối: số sự kiện đã đặt tên, số cụm lẫn, vài ví dụ khó.

{huong_dan}
---

# Các sự kiện
"""

CHECK_TASK = """\
# Kiểm tra tên sự kiện — phần {part}

Bạn là agent KIỂM TRA, độc lập với agent đã đặt tên. File có {n} sự kiện; mỗi sự kiện kèm dòng **Tên đề xuất**. Đọc
hướng dẫn rồi đọc HẾT các sự kiện (file dài → đọc tiếp bằng offset cho tới dòng cuối). Với mỗi tên, kiểm tra:

(a) bao quát cả cụm (không chỉ một bài); (b) trung thực — mọi tên riêng, con số, tỉ số, ngày có trong tiêu đề/sapo;
(c) độ dài ≤ 20 âm tiết và đủ nghĩa; (d) trung tính, không câu view, đúng văn phong mục 6; (e) đúng thời điểm (mục 5);
(f) chính tả, tên riêng viết đúng như bài; (g) cờ cụm lẫn có đúng không.

`ket_luan`: `"dat"` nếu không vi phạm tiêu chí nào; `"sua"` nếu vi phạm — khi đó viết `ten_sua` theo hướng dẫn và `ly_do`
(một câu, nêu tiêu chí bị vi phạm). Chỉ sửa khi vi phạm thật, KHÔNG sửa vì khác gu diễn đạt. `cum_lan` = đánh giá của
CHÍNH bạn (có thể khác agent đặt tên).

Ghi kết quả ra `{out}` — JSON, một mảng, đúng {n} phần tử, đúng thứ tự, mỗi phần tử:
`{{"event_id": "...", "ket_luan": "dat", "ten_sua": "", "ly_do": "", "cum_lan": false}}`
Không dùng script/LLM khác; tự đọc và tự quyết. Ghi xong kiểm tra lại file là JSON hợp lệ, đủ {n} phần tử.
Trả lời cuối: số đạt / sửa, số cụm lẫn, các lỗi hay gặp của agent đặt tên.

{huong_dan}
---

# Các sự kiện
"""

_PREFIX = re.compile(r"^(video|clip|nóng|trực tiếp|live|infographic|ảnh|photo)\s*[:|-]\s*", re.IGNORECASE)


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"


def _spread(idx: list[int], k: int) -> list[int]:
    """k phần tử rải đều theo thứ tự (giữ đầu và cuối)."""
    if len(idx) <= k:
        return idx
    return [idx[round(j * (len(idx) - 1) / (k - 1))] for j in range(k)]


def build_events(events_dir: Path, silver_glob: str = SILVER, min_size: int = 2,
                 before: str | None = TEST_START) -> list[dict]:
    """Sự kiện ≥ `min_size` bài, bài đầu tiên trước ngày `before` (None = mọi thời điểm), kèm bài (tiêu đề, sapo) sắp
    theo thời gian. Mặc định = bộ dữ liệu đặt tên v1 (≥ 2 bài, trước TEST_START; sapo chỉ đọc từ bài trước TEST_START).
    Lúc suy luận (naming/predict.py) gọi với min_size=1, before=None."""
    end = before or "9999"
    with open(events_dir / "su_kien.csv", encoding="utf-8") as f:
        ev = {e["event_id"]: e for e in csv.DictReader(f)
              if int(e["size"]) >= min_size and e["first_seen"][:10] < end}
    members: dict[str, list[dict]] = {k: [] for k in ev}
    with open(events_dir / "bai_su_kien.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["event_id"] in members:
                members[r["event_id"]].append(r)
    text = {a["id"]: a for a in load_silver(silver_glob, end=end)}
    out = []
    for eid, e in ev.items():
        arts = []
        for r in sorted(members[eid], key=lambda r: (r["published_at"], r["article_id"])):
            a = text.get(r["article_id"], {})
            arts.append({"id": r["article_id"], "t": r["published_at"], "source": r["source"],
                         "title": _PREFIX.sub("", r["title"]), "sapo": a.get("sapo", ""),
                         "medoid": r["is_medoid"] == "1"})
        out.append({"event_id": eid, "split": "dev" if e["first_seen"][:10] >= DEV_START else "train",
                    "size": int(e["size"]), "n_sources": int(e["n_sources"]), "first_seen": e["first_seen"],
                    "last_seen": e["last_seen"], "medoid_title": e["medoid_title"], "articles": arts})
    out.sort(key=lambda e: (e["first_seen"], e["event_id"]))
    return out


def block(e: dict) -> str:
    """Khối văn bản của một sự kiện cho agent: mọi tiêu đề (rải đều nếu nhiều) + sapo của vài bài khác báo."""
    arts = e["articles"]
    lines = [(f"## {e['event_id']} · {e['size']} bài · {e['n_sources']} báo · "
              f"{e['first_seen'][8:10]}/{e['first_seen'][5:7]}/{e['first_seen'][:4]} → "
              f"{e['last_seen'][8:10]}/{e['last_seen'][5:7]}"), "Tiêu đề:"]
    shown = _spread(list(range(len(arts))), MAX_TITLES)
    for i in shown:
        a = arts[i]
        lines.append(f"{i + 1}. [{a['source']} {a['t'][8:10]}/{a['t'][5:7]} {a['t'][11:16]}] {a['title']}"
                     + (" (medoid)" if a["medoid"] else ""))
    if len(shown) < len(arts):
        lines.append(f"(… hiện {len(shown)}/{len(arts)} tiêu đề, rải đều theo thời gian)")
    # sapo: medoid trước, rồi mỗi báo khác một bài
    order = sorted(range(len(arts)), key=lambda i: not arts[i]["medoid"])
    picked, seen = [], set()
    for i in order:
        if arts[i]["sapo"] and arts[i]["source"] not in seen:
            picked.append(i)
            seen.add(arts[i]["source"])
        if len(picked) == MAX_SAPOS:
            break
    if picked:
        lines.append("Sapo:")
        lines += [f"- ({i + 1}) {_short(arts[i]['sapo'], SAPO_CHARS)}" for i in picked]
    return "\n".join(lines)


def prep(out: Path, per_part: int, events_dir: Path) -> None:
    events = build_events(events_dir)
    (out / "parts").mkdir(parents=True, exist_ok=True)
    (out / "events.json").write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    parts = [events[k:k + per_part] for k in range(0, len(events), per_part)]
    for p, chunk in enumerate(parts, 1):
        head = GEN_TASK.format(part=f"{p:02d}", n=len(chunk), out=out / f"parts/gen_{p:02d}.json",
                               huong_dan=HUONG_DAN)
        (out / f"parts/gen_{p:02d}.md").write_text(head + "\n\n".join(block(e) for e in chunk) + "\n",
                                                   encoding="utf-8")
    n_dev = sum(e["split"] == "dev" for e in events)
    print(f"{len(events)} sự kiện (train {len(events) - n_dev}, dev {n_dev}) → {len(parts)} phần ở {out / 'parts'}")


def _load_part(path: Path, ids: list[str]) -> dict:
    rows = json.loads(path.read_text(encoding="utf-8"))
    got = {r["event_id"]: r for r in rows}
    if [r["event_id"] for r in rows] != ids:
        missing = [i for i in ids if i not in got]
        raise ValueError(f"{path.name}: {len(rows)}/{len(ids)} phần tử, thiếu {missing[:5]}, hoặc sai thứ tự")
    return got


def _parts(out: Path) -> list[tuple[str, list[dict]]]:
    events = json.loads((out / "events.json").read_text(encoding="utf-8"))
    n = len(list((out / "parts").glob("gen_*.md")))
    per = -(-len(events) // n)
    return [(f"{p:02d}", events[(p - 1) * per:p * per]) for p in range(1, n + 1)]


def prep_check(out: Path, only: list[str] | None = None) -> None:
    """File cho agent kiểm tra. `only` = các phần mà agent đặt tên đã báo xong (gen_XX.json có thể còn đang được ghi)."""
    for part, chunk in _parts(out):
        gen_path, md = out / f"parts/gen_{part}.json", out / f"parts/check_{part}.md"
        if (only and part not in only) or not gen_path.exists() or md.exists():
            continue
        gen = _load_part(gen_path, [e["event_id"] for e in chunk])
        head = CHECK_TASK.format(part=part, n=len(chunk), out=out / f"parts/check_{part}.json", huong_dan=HUONG_DAN)
        body = []
        for e in chunk:
            g = gen[e["event_id"]]
            flag = f" · agent đặt tên gắn cờ cụm lẫn: {g.get('ghi_chu', '')}" if g.get("cum_lan") else ""
            body.append(block(e) + f"\n**Tên đề xuất:** {g['ten']}{flag}")
        md.write_text(head + "\n\n".join(body) + "\n", encoding="utf-8")
        print(f"→ {md}")


def _syllables(s: str) -> int:
    return len(s.split())


REVIEW_TASK = """\
# Duyệt tên sự kiện (vòng 3) — phần {part}

Bạn là người DUYỆT CUỐI bộ dữ liệu đặt tên. Mỗi sự kiện đã qua 2 agent: một agent ĐẶT TÊN và một agent KIỂM TRA (có
thể đã sửa tên và gắn cờ cụm lẫn). File có {n} sự kiện thuộc 3 nhóm:
- `sua` — agent kiểm tra đã sửa tên (hoặc tên cuối còn dấu hai chấm / > 20 âm tiết): xem tên sửa có đúng và tốt hơn không.
- `lan` — có ít nhất một agent gắn cờ cụm lẫn: quyết định giữ hay loại cụm khỏi dữ liệu train.
- `mau` — mẫu ngẫu nhiên các tên không bị sửa, không bị gắn cờ: kiểm tra độc lập để ước lượng tỉ lệ lỗi còn sót.

Đọc hướng dẫn đặt tên rồi đọc HẾT các sự kiện (file dài → đọc tiếp bằng offset tới dòng cuối). Với mỗi sự kiện quyết định:
- `dat`: tên hiện tại (**Tên cuối**) đúng hướng dẫn, dùng được làm nhãn train.
- `sua`: tên cuối có lỗi thật → viết `ten_nguoi_duyet` đúng hướng dẫn (tối đa 20 âm tiết, không dấu hai chấm).
- `loai`: bỏ khỏi dữ liệu train.

Quy tắc cụm lẫn (theo quy tắc ranh giới R1–R6 của đề tài): **loai** khi cụm gồm các vụ việc / trận đấu / phiên định kỳ
khác nhau mà bài lạc chiếm > 1/4 số bài hoặc không có tên chung nào trung thực, và khi là bản tin tổng hợp nhiều tin.
**Giữ** (`dat`/`sua`) khi bài lạc ≤ 1/4 và tên nói đúng sự kiện chính; hoặc cụm dạng R3 (cùng đợt công bố / cùng
chương trình, nhiều chủ thể — vd nhiều trường cùng công bố điểm chuẩn) nếu có tên bao quát trung thực. Cờ của các agent
chỉ là gợi ý; tự đọc tiêu đề/sapo để quyết.

Chỉ sửa khi vi phạm thật (bao quát, trung thực, độ dài, văn phong, thời điểm, chính tả tên riêng), không sửa vì khác gu.
`loi` = một nhãn lỗi của TÊN CUỐI trước khi bạn sửa: `""` (không lỗi), `bao_quat`, `trung_thuc`, `do_dai`, `van_phong`,
`thoi_diem`, `chinh_ta`, `cum_lan`.

Ghi kết quả ra `{out}` — JSON, một mảng, đúng {n} phần tử, đúng thứ tự:
`{{"event_id": "...", "nhom": "sua", "quyet_dinh": "dat", "ten_nguoi_duyet": "", "loi": "", "ly_do": ""}}`
(`ten_nguoi_duyet` bắt buộc khi `sua`; `ly_do` một câu khi `sua`/`loai`.) Không dùng script/LLM khác để quyết; tự đọc.
Ghi xong kiểm tra JSON hợp lệ, đủ {n} phần tử, mọi `ten_nguoi_duyet` ≤ 20 âm tiết (đếm bằng python, tách khoảng trắng).
Trả lời cuối: số dat/sua/loai theo từng nhóm, số lỗi theo nhãn ở nhóm `mau`, các lỗi đáng chú ý của 2 agent trước.

{huong_dan}
---

# Các sự kiện
"""


def prep_review(out: Path, n_parts: int, sample: int, seed: int) -> None:
    """Vòng duyệt 3: nhóm sua (agent kiểm tra đã sửa, hoặc tên cuối còn ':' / > 20 âm tiết), lan (có cờ cụm lẫn),
    mau (mẫu ngẫu nhiên phần còn lại). Cần naming_v1.csv (chạy merge trước)."""
    import random

    with open(out / "naming_v1.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    events = {e["event_id"]: e for e in json.loads((out / "events.json").read_text(encoding="utf-8"))}

    def group(r: dict) -> str:
        if r["ket_luan_kiem_tra"] == "sua" or ":" in r["ten_cuoi"] or int(r["so_am_tiet"]) > 20:
            return "sua"
        return "lan" if r["cum_lan_dat"] == "1" or r["cum_lan_kiem"] == "1" else ""

    picked = [(group(r), r) for r in rows if group(r)]
    rest = [r for r in rows if not group(r)]
    picked += [("mau", r) for r in random.Random(seed).sample(rest, sample)]
    (out / "review").mkdir(exist_ok=True)
    per = -(-len(picked) // n_parts)
    for p in range(n_parts):
        chunk = picked[p * per:(p + 1) * per]
        body = []
        for g, r in chunk:
            check = (f"sua → \"{r['ten_sua']}\" (lý do: {r['ly_do']})" if r["ket_luan_kiem_tra"] == "sua" else "dat")
            body.append(block(events[r["event_id"]]) + f"\n**Nhóm:** {g} · **Tên agent đặt:** {r['ten_dat']}"
                        f"\n**Agent kiểm tra:** {check}"
                        f"\n**Cờ cụm lẫn:** agent đặt tên {'CÓ' if r['cum_lan_dat'] == '1' else 'không'}"
                        f" · agent kiểm tra {'CÓ' if r['cum_lan_kiem'] == '1' else 'không'}"
                        + (f" · ghi chú: {r['ghi_chu']}" if r["ghi_chu"] else "")
                        + f"\n**Tên cuối:** {r['ten_cuoi']} ({r['so_am_tiet']} âm tiết)")
        head = REVIEW_TASK.format(part=f"{p + 1:02d}", n=len(chunk), out=out / f"review/r_{p + 1:02d}.json",
                                  huong_dan=HUONG_DAN)
        (out / f"review/r_{p + 1:02d}.md").write_text(head + "\n\n".join(body) + "\n", encoding="utf-8")
    counts = Counter(g for g, _ in picked)
    print(f"{len(picked)} sự kiện ({dict(counts)}) → {n_parts} phần ở {out / 'review'}")


def collect_review(out: Path) -> None:
    """review/r_XX.json → duyet_claude_v1.csv (cùng định dạng CSV xuất từ duyet_ten.html, thêm nhom/loi/ly_do)."""
    rows = []
    for path in sorted((out / "review").glob("r_*.json")):
        md = path.with_suffix(".md").read_text(encoding="utf-8")
        ids = re.findall(r"^## (E\S+)", md, re.MULTILINE)
        got = json.loads(path.read_text(encoding="utf-8"))
        if [r["event_id"] for r in got] != ids:
            raise ValueError(f"{path.name}: {len(got)}/{len(ids)} phần tử hoặc sai thứ tự")
        rows += got
    with open(out / "duyet_claude_v1.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "nhom", "quyet_dinh", "ten_nguoi_duyet", "loi", "ly_do"])
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in w.fieldnames} for r in rows)
    by = Counter((r["nhom"], r["quyet_dinh"]) for r in rows)
    print(f"{len(rows)} quyết định {dict(sorted(by.items()))} → {out / 'duyet_claude_v1.csv'}")


def _load_review(path: Path | None) -> dict:
    """CSV quyết định: event_id, quyet_dinh (dat | sua | loai), ten_nguoi_duyet (+ ly_do nếu có) — xuất từ
    duyet_ten.html hoặc từ vòng duyệt 3 (`collect-review` → duyet_claude_v1.csv)."""
    if not path:
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return {r["event_id"]: r for r in csv.DictReader(f) if r.get("quyet_dinh")}


def merge(out: Path, review: Path | None = None) -> None:
    """Gộp tên của 2 agent (+ quyết định của người duyệt nếu có) → naming_v1.csv, train/dev.jsonl, duyet_ten.html.

    Vào train/dev: người duyệt "dat"/"sua" → luôn vào (tên người sửa nếu có); "loai" → không; chưa duyệt → vào nếu
    agent kiểm tra KHÔNG gắn cờ cụm lẫn (cờ của agent kiểm tra là ý kiến sau cùng, nó được gỡ cờ của agent đặt tên).
    """
    rv = _load_review(review)
    rows, train, dev, cards = [], [], [], []
    for part, chunk in _parts(out):
        ids = [e["event_id"] for e in chunk]
        gen = _load_part(out / f"parts/gen_{part}.json", ids)
        chk = _load_part(out / f"parts/check_{part}.json", ids)
        for e in chunk:
            g, c = gen[e["event_id"]], chk[e["event_id"]]
            final = c["ten_sua"].strip() if c["ket_luan"] == "sua" and c.get("ten_sua", "").strip() else g["ten"]
            r = rv.get(e["event_id"], {})
            decision, human = r.get("quyet_dinh", ""), (r.get("ten_nguoi_duyet") or "").strip()
            target = human if decision == "sua" and human else final
            rows.append({"event_id": e["event_id"], "split": e["split"], "phan": part, "size": e["size"],
                         "n_sources": e["n_sources"], "first_seen": e["first_seen"], "medoid_title": e["medoid_title"],
                         "ten_dat": g["ten"], "ket_luan_kiem_tra": c["ket_luan"], "ten_sua": c.get("ten_sua", ""),
                         "ly_do": c.get("ly_do", ""), "ten_cuoi": final, "so_am_tiet": _syllables(final),
                         "cum_lan_dat": int(bool(g.get("cum_lan"))), "cum_lan_kiem": int(bool(c.get("cum_lan"))),
                         "ghi_chu": g.get("ghi_chu", ""), "nguoi_duyet": decision, "ten_nguoi_sua": human})
            keep = decision in ("dat", "sua") or (not decision and not c.get("cum_lan"))
            if keep:
                ex = {"event_id": e["event_id"], "input": block(e), "target": target}
                (dev if e["split"] == "dev" else train).append(ex)
            cards.append(_card(e, rows[-1], r))
    (out / "duyet_ten.html").write_text(_review_page(cards), encoding="utf-8")
    with open(out / "naming_v1.csv", "w", encoding="utf-8-sig", newline="") as f:   # BOM: Excel mở đúng dấu
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for name, data in (("train", train), ("dev", dev)):
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in data)
    n_fix = sum(r["ket_luan_kiem_tra"] == "sua" for r in rows)
    n_mix = sum(r["cum_lan_kiem"] for r in rows)
    print(f"{len(rows)} sự kiện · kiểm tra sửa {n_fix} · cụm lẫn (agent kiểm tra) {n_mix} · người duyệt {len(rv)}"
          f" · train {len(train)} · dev {len(dev)} → {out / 'naming_v1.csv'}, {out / 'duyet_ten.html'}")


def _card(e: dict, row: dict, rv: dict) -> dict:
    """Dữ liệu một sự kiện cho trang duyệt (mọi tiêu đề, sapo các bài có sapo, quyết định vòng duyệt trước nếu có)."""
    return {"id": e["event_id"], "split": e["split"], "size": e["size"], "src": e["n_sources"],
            "t0": e["first_seen"][:16], "t1": e["last_seen"][:16],
            "arts": [[a["source"], a["t"][5:16], a["title"], int(a["medoid"]), _short(a["sapo"], 300)]
                     for a in e["articles"]],
            "dat": row["ten_dat"], "kl": row["ket_luan_kiem_tra"], "sua": row["ten_sua"], "lydo": row["ly_do"],
            "cuoi": row["ten_cuoi"], "cl1": row["cum_lan_dat"], "cl2": row["cum_lan_kiem"], "chu": row["ghi_chu"],
            "rv": rv.get("quyet_dinh", ""), "rvten": rv.get("ten_nguoi_duyet", ""), "rvly": rv.get("ly_do", "")}


def _review_page(cards: list[dict]) -> str:
    data = json.dumps(cards, ensure_ascii=False).replace("</", "<\\/")
    return REVIEW_HTML.replace("/*DATA*/[]", data)


REVIEW_HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Duyệt tên sự kiện</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1b;--mute:#6b6b66;--line:#e2e1dc;--acc:#2f6fdb;--ok:#2e7d4f;--warn:#b26a00;
--bad:#b3261e;--chip:#efeee9}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--fg:#ecebe6;--mute:#a09f98;--line:#33332f;
--acc:#7aa7ff;--ok:#6cc58f;--warn:#e0a54a;--bad:#ff8a80;--chip:#2a2a27}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px}
h1{font-size:17px;margin:0 0 6px}.bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
button,select,input[type=search]{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);
border-radius:6px;padding:4px 10px;cursor:pointer}button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
#stat{color:var(--mute);font-size:13px;margin-left:auto}main{max-width:980px;margin:0 auto;padding:12px 16px 60px}
.c{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.c.dat{border-left:4px solid var(--ok)}.c.sua{border-left:4px solid var(--acc)}.c.loai{border-left:4px solid var(--bad);opacity:.75}
.meta{color:var(--mute);font-size:12.5px;display:flex;flex-wrap:wrap;gap:8px}.chip{background:var(--chip);border-radius:4px;padding:0 6px}
.chip.w{color:var(--warn)}.chip.b{color:var(--bad)}.name{width:100%;font:600 16px/1.4 system-ui,sans-serif;margin:8px 0 4px;
padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.old{color:var(--mute);font-size:13.5px}.old s{color:var(--bad)}.why{color:var(--warn);font-size:13px}
.acts{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap}details{margin-top:6px}summary{cursor:pointer;color:var(--acc);font-size:13px}
ol{margin:6px 0;padding-left:22px;font-size:13.5px}li .s{color:var(--mute);font-size:12px}li .sp{display:block;color:var(--mute);
font-size:12.5px}.md{font-weight:600}#more{display:block;margin:16px auto}
</style></head><body>
<header><h1>Duyệt tên sự kiện — bộ đặt tên v1</h1><div class="bar">
<button data-f="all" class="on">Tất cả</button><button data-f="sua">Agent kiểm tra đã sửa</button>
<button data-f="lan">Cụm lẫn</button><button data-f="dai">&gt; 16 âm tiết</button><button data-f="chua">Chưa duyệt</button>
<select id="split"><option value="">train + dev</option><option>train</option><option>dev</option></select>
<input type="search" id="q" placeholder="Tìm trong tên / tiêu đề…">
<button id="exp">Xuất CSV quyết định</button><span id="stat"></span></div></header>
<main id="list"></main><button id="more">Xem thêm 50</button>
<script>
const D=/*DATA*/[];const KEY='duyet_ten_v1';let S={};try{S=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}stat()};
let F='all',N=50;const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const syl=s=>s.trim().split(/\\s+/).filter(Boolean).length;
function pass(d){const sp=document.getElementById('split').value,q=document.getElementById('q').value.trim().toLowerCase();
if(sp&&d.split!==sp)return false;if(F==='sua'&&d.kl!=='sua')return false;if(F==='lan'&&!(d.cl1||d.cl2))return false;
if(F==='dai'&&syl(d.cuoi)<=16)return false;if(F==='chua'&&S[d.id])return false;
if(q&&!(d.cuoi+' '+d.dat+' '+d.arts.map(a=>a[2]).join(' ')).toLowerCase().includes(q))return false;return true}
function card(d){const s=S[d.id]||{},name=s.ten??d.cuoi,cls=s.qd||'';
const fl=[d.cl2?'<span class="chip b">cụm lẫn (kiểm tra)</span>':'',d.cl1&&!d.cl2?'<span class="chip w">cụm lẫn (chỉ agent đặt tên)</span>':'',
`<span class="chip">${syl(name)} âm tiết</span>`].join('');
const old=d.kl==='sua'?`<div class="old">Agent đặt tên: <s>${esc(d.dat)}</s></div><div class="why">Lý do sửa: ${esc(d.lydo)}</div>`:'';
const arts=d.arts.map((a,i)=>`<li class="${a[3]?'md':''}">${esc(a[2])} <span class="s">${esc(a[0])} ${esc(a[1])}${a[3]?' · medoid':''}</span>${a[4]?`<span class="sp">${esc(a[4])}</span>`:''}</li>`).join('');
return `<div class="c ${cls}" data-id="${d.id}"><div class="meta"><b>${d.id}</b><span>${d.size} bài · ${d.src} báo</span>
<span>${esc(d.t0)} → ${esc(d.t1)}</span><span class="chip">${d.split}</span>${fl}</div>
<input class="name" value="${esc(name)}">${old}${d.chu?`<div class="old">Ghi chú agent: ${esc(d.chu)}</div>`:''}
${d.rv?`<div class="why">Vòng duyệt trước: <b>${d.rv}</b>${d.rvten?' → '+esc(d.rvten):''}${d.rvly?' — '+esc(d.rvly):''}</div>`:''}
<div class="acts"><button data-a="dat">✓ Đạt</button><button data-a="sua">✎ Lưu tên đã sửa</button><button data-a="loai">✗ Loại</button>
<button data-a="xoa">↺ Bỏ quyết định</button></div>
<details${d.size<=4?' open':''}><summary>${d.size} bài trong cụm</summary><ol>${arts}</ol></details></div>`}
function render(){const L=D.filter(pass);document.getElementById('list').innerHTML=L.slice(0,N).map(card).join('');
document.getElementById('more').style.display=L.length>N?'block':'none';stat(L.length)}
function stat(n){const v=Object.values(S),c=k=>v.filter(x=>x.qd===k).length;
document.getElementById('stat').textContent=`${n??''}${n!=null?' đang lọc · ':''}đã duyệt ${v.length}/${D.length} (đạt ${c('dat')}, sửa ${c('sua')}, loại ${c('loai')})`}
document.querySelectorAll('[data-f]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-f]').forEach(x=>x.classList.remove('on'));
b.classList.add('on');F=b.dataset.f;N=50;render()});
document.getElementById('split').onchange=()=>{N=50;render()};let t;document.getElementById('q').oninput=()=>{clearTimeout(t);t=setTimeout(()=>{N=50;render()},250)};
document.getElementById('more').onclick=()=>{N+=50;render()};
document.getElementById('list').onclick=ev=>{const b=ev.target.closest('button');if(!b)return;const c=b.closest('.c'),id=c.dataset.id,
d=D.find(x=>x.id===id),v=c.querySelector('.name').value.trim();const a=b.dataset.a;
if(a==='xoa')delete S[id];else if(a==='dat')S[id]={qd:v===d.cuoi?'dat':'sua',ten:v};else if(a==='sua')S[id]={qd:'sua',ten:v};
else S[id]={qd:'loai',ten:v};c.className='c '+(S[id]?.qd||'');save()};
document.getElementById('exp').onclick=()=>{const rows=[['event_id','quyet_dinh','ten_nguoi_duyet']].concat(
Object.entries(S).map(([k,v])=>[k,v.qd,v.qd==='sua'?v.ten:'']));const csv='\\ufeff'+rows.map(r=>r.map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(',')).join('\\n');
const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='duyet_ten_v1.csv';a.click()};
render();
</script></body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep")
    p.add_argument("--per-part", type=int, default=170)
    p.add_argument("--events", type=Path, default=EVENTS_DIR / "v1")
    p = sub.add_parser("prep-check")
    p.add_argument("--parts", nargs="*", help="vd 03 06; bỏ trống = mọi phần đã có gen_XX.json")
    p = sub.add_parser("merge")
    p.add_argument("--review", type=Path, help="CSV quyết định (duyet_ten.html hoặc duyet_claude_v1.csv), tuỳ chọn")
    p = sub.add_parser("prep-review")
    p.add_argument("--parts", type=int, default=4)
    p.add_argument("--sample", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    sub.add_parser("collect-review")
    a = ap.parse_args()
    if a.cmd == "prep":
        prep(a.out, a.per_part, a.events)
    elif a.cmd == "prep-check":
        prep_check(a.out, a.parts)
    elif a.cmd == "prep-review":
        prep_review(a.out, a.parts, a.sample, a.seed)
    elif a.cmd == "collect-review":
        collect_review(a.out)
    else:
        merge(a.out, a.review)


if __name__ == "__main__":
    main()
