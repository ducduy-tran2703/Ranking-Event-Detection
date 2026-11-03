import csv
import json

import pytest

from eventrank.naming import predict as P
from eventrank.naming.dataset import build_events

CFG = {**P.DEFAULTS, "naming_version": "vt", "model": "khong-dung", "batch_size": 2}


def _job(eid, size, src="Tiêu đề: Bão số 5 vào Quảng Ninh .", ids=("a",)):
    return {"event_id": eid, "size": size, "hash": P.article_hash(list(ids)), "src": src,
            "medoid": "Video: Bão số 5 vào Quảng Ninh", "title": f"tiêu đề {eid}"}


def _quiet(s):
    return None


def test_article_hash_khong_phu_thuoc_thu_tu():
    assert P.article_hash(["b", "a"]) == P.article_hash(["a", "b"]) != P.article_hash(["a"])


def test_postcheck():
    src = "Tiêu đề: Bão số 5 vào Quảng Ninh ngày 14.9.2026 ."
    med = "Video: Bão số 5 vào Quảng Ninh"
    ok = P.postcheck("  Bão  số 5 vào Quảng Ninh 14/9 ", src, med)              # ngày khác định dạng vẫn đạt
    assert ok == {"ten": "Bão số 5 vào Quảng Ninh 14/9", "nguon": "model", "ly_do_fallback": "", "ten_mo_hinh": ""}
    bad = P.postcheck("Bão số 6 vào Hải Phòng", src, med)
    assert bad["nguon"] == "medoid" and bad["ten"] == "Bão số 5 vào Quảng Ninh"
    assert bad["ly_do_fallback"] == "khong_trung_thuc" and bad["ten_mo_hinh"] == "Bão số 6 vào Hải Phòng"
    assert P.postcheck("bão " * 22, src, med)["nguon"] == "model"                 # ngưỡng 22 âm tiết
    assert P.postcheck("bão " * 23, src, med)["ly_do_fallback"] == "qua_dai"
    assert P.postcheck("", src, med)["ly_do_fallback"] == "rong"
    assert P.postcheck("Quảng Ninh, Quảng Ninh đón bão số 5", src, med)["ly_do_fallback"] == "lap_thuc_the"
    assert P.postcheck("U2 3 Quảng Ninh đón bão số 5 , mưa to", "Tiêu đề: U23 Quảng Ninh, bão số 5 .",
                       med)["ten"] == "U23 Quảng Ninh đón bão số 5, mưa to"


def test_title_name_rut_gon():
    short = P.title_name("Giá vàng giảm")
    assert short == {"ten": "Giá vàng giảm", "nguon": "title", "ly_do_fallback": "", "ten_mo_hinh": ""}
    t = "Thủ tướng chủ trì hội nghị toàn quốc về phát triển kinh tế tư nhân, " + "nhấn mạnh vai trò " * 5
    r = P.title_name(t, 22)
    assert r["nguon"] == "title" and r["ly_do_fallback"] == "rut_gon"
    assert r["ten"] == "Thủ tướng chủ trì hội nghị toàn quốc về phát triển kinh tế tư nhân"


def test_name_jobs_lo_cache_va_tieu_de(tmp_path):
    calls = []

    def gen(xs):
        calls.append(len(xs))
        return ["Bão số 5 vào Quảng Ninh"] * len(xs)

    jobs = [_job("E1", 1), _job("E2", 2), _job("E3", 3, src="Tiêu đề: Bão số 5 vào Quảng Ninh . Tóm tắt: dài hơn"),
            _job("E4", 2, src="Tiêu đề: Bão số 5 vào Quảng Ninh | Bão vào bờ ."),
            _job("E5", 2)]                                             # cùng đầu vào với E2 → sinh một lần
    cache = tmp_path / "c" / "vt.jsonl"
    rows, st = P.name_jobs(jobs, CFG, gen, cache, log=_quiet)
    assert [r["nguon"] for r in rows] == ["title", "model", "model", "model", "model"]
    assert rows[0]["ten"] == "tiêu đề E1" and rows[1]["so_am_tiet"] == 6
    assert calls == [2, 1] and st["n_generated"] == 3                       # lô 2: 3 đầu vào khác nhau → 2 lô
    assert len(cache.read_text(encoding="utf-8").splitlines()) == 3
    # chạy lại: đổi tập bài nhưng đầu vào giữ nguyên → dùng đệm; đổi đầu vào của E4 → chỉ sinh lại E4
    calls.clear()
    jobs[1] = _job("E2-moi", 2, ids=("a", "b"))
    jobs[3] = _job("E4", 2, src="Tiêu đề: Bão số 5 vào Quảng Ninh | Bão đổ bộ .")
    rows2, st2 = P.name_jobs(jobs, CFG, gen, cache, log=_quiet)
    assert calls == [1] and st2["n_cached"] == 3 and rows2[2] == rows[2]


def test_doi_tham_so_sinh_thi_bo_dem(tmp_path):
    cache = tmp_path / "vt.jsonl"
    gen = lambda xs: ["Bão số 5"] * len(xs)
    P.name_jobs([_job("E2", 2)], CFG, gen, cache, log=_quiet)
    for cfg in ({**CFG, "num_beams": 2}, {**CFG, "model": "mo-hinh-khac"}, {**CFG, "naming_version": "khac"}):
        assert P.gen_hash(cfg) != P.gen_hash(CFG) or cfg["naming_version"] != CFG["naming_version"]
        _, st = P.name_jobs([_job("E2", 2)], cfg, gen, cache, log=_quiet)
        assert st["n_generated"] == 1, cfg
    _, st = P.name_jobs([_job("E2", 2)], {**CFG, "batch_size": 1}, gen, cache, log=_quiet)   # lô không vào khoá
    assert st["n_generated"] == 0


def test_cache_bo_qua_dong_do_dang_va_khoa_cu(tmp_path):
    cache = tmp_path / "vt.jsonl"
    h = P.article_hash(["a"])
    cache.write_text(json.dumps({"event_id": "E2", "article_hash": h, "naming_version": "vt", "raw": "x"}) + "\n"
                     + '{"event_id": "E2", "art', encoding="utf-8")
    rows, st = P.name_jobs([_job("E2", 2)], CFG, lambda xs: ["Bão số 5"] * len(xs), cache, log=_quiet)
    assert st["n_generated"] == 1 and rows[0]["ten"] == "Bão số 5"


def test_migrate_cache_khong_can_sinh_lai(tmp_path):
    cache = tmp_path / "vt.jsonl"
    old = [{"event_id": "E2", "article_hash": P.article_hash(["a"]), "naming_version": "vt", "raw": "Bão số 5"},
           {"event_id": "E9", "article_hash": "khac", "naming_version": "vt", "raw": "không thuộc lần chạy"}]
    cache.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in old), encoding="utf-8")
    jobs = [_job("E1", 1), _job("E2", 2)]
    assert P.migrate_cache(jobs, CFG, cache, log=_quiet) == 1
    assert P.migrate_cache(jobs, CFG, cache, log=_quiet) == 0                 # chạy lại không nhân đôi

    def boom(xs):
        raise AssertionError("không được sinh")
    rows, st = P.name_jobs(jobs, {**CFG, "max_generate": 0}, boom, cache, log=_quiet)
    assert st["n_generated"] == 0 and rows[1]["ten"] == "Bão số 5"


def test_max_generate_dung_truoc_khi_nap_mo_hinh(tmp_path):
    with pytest.raises(RuntimeError, match="max_generate"):
        P.name_jobs([_job("E2", 2)], {**CFG, "max_generate": 0}, None, tmp_path / "vt.jsonl", log=_quiet)


def _events_dir(tmp_path):
    """Thư mục sự kiện tí hon (như đầu ra gom cụm) + Silver tương ứng."""
    arts = [("a1", "E1", "2026-09-05T08:00:00+07:00", "vnexpress", "Video: Bão số 5 vào Quảng Ninh", "Bão mạnh.", 1),
            ("a2", "E1", "2026-09-05T09:00:00+07:00", "tuoitre", "Bão số 5 đổ bộ Quảng Ninh", "Gió giật cấp 12.", 0),
            ("a3", "E2", "2026-09-15T10:00:00+07:00", "nhandan", "Clip: Giá vàng giảm mạnh", "Vàng giảm.", 1)]
    ev = tmp_path / "ev"
    ev.mkdir()
    with open(ev / "bai_su_kien.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "article_id", "published_at", "source", "category", "title", "is_medoid"])
        for a, e, t, s, ti, _, m in arts:
            w.writerow([e, a, t, s, "X", ti, m])
    with open(ev / "su_kien.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "size", "n_sources", "sources", "first_seen", "last_seen", "medoid_article_id",
                    "medoid_title"])
        w.writerow(["E1", 2, 2, "tuoitre:1 vnexpress:1", arts[0][2], arts[1][2], "a1", arts[0][4]])
        w.writerow(["E2", 1, 1, "nhandan:1", arts[2][2], arts[2][2], "a3", arts[2][4]])
    sil = tmp_path / "silver" / "s"
    sil.mkdir(parents=True)
    (sil / "a.jsonl").write_text("\n".join(json.dumps({"article_id": a, "published_at": t, "source": s, "title": ti,
                                                       "sapo": sp, "category": "X"}, ensure_ascii=False)
                                           for a, _, t, s, ti, sp, _ in arts) + "\n", encoding="utf-8")
    return ev, str(tmp_path / "silver" / "*" / "*.jsonl")


def test_build_events_mac_dinh_va_moi_kich_thuoc(tmp_path):
    ev, g = _events_dir(tmp_path)
    assert [e["event_id"] for e in build_events(ev, g)] == ["E1"]          # mặc định (bộ v1): ≥ 2 bài, trước 11/09
    allev = build_events(ev, g, min_size=1, before=None)
    assert [e["event_id"] for e in allev] == ["E1", "E2"]
    assert allev[0]["articles"][0]["title"] == "Bão số 5 vào Quảng Ninh"   # bỏ tiền tố "Video:"
    assert allev[0]["articles"][1]["sapo"] == "Gió giật cấp 12."


def test_run_ghi_ten_su_kien(tmp_path):
    ev, g = _events_dir(tmp_path)
    seen = []

    def gen(xs):
        seen.extend(xs)
        return ["Bão số 5 đổ bộ Quảng Ninh"] * len(xs)

    cfg = {**CFG, "cache_dir": str(tmp_path / "cache")}
    st = P.run(ev, cfg, tmp_path / "out", g, generator=gen, log=lambda s: None)
    assert seen == [("Tiêu đề: Bão số 5 vào Quảng Ninh | Bão số 5 đổ bộ Quảng Ninh . "
                     "Tóm tắt: Bão mạnh. | Gió giật cấp 12.")]
    with open(tmp_path / "out" / "ten_su_kien.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == P.FIELDS
    assert [(r["event_id"], r["nguon"], r["ten"]) for r in rows] == [
        ("E1", "model", "Bão số 5 đổ bộ Quảng Ninh"), ("E2", "title", "Giá vàng giảm mạnh")]
    assert st["nguon"] == {"model": 1, "title": 1} and st["n_generated"] == 1
