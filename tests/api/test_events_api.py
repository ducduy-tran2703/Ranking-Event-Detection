"""API sự kiện (web demo) trên một lần chạy pipeline tí hon tự dựng trong tmp — không phụ thuộc data/ (gitignored).

Trọng tâm: tên mô hình của sự kiện giao cửa sổ ẩn tên (14–15/09) KHÔNG xuất hiện trong bất kỳ phản hồi nào.
"""
import csv
import json
from collections import Counter
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from eventrank.serving import store as ES
from eventrank.serving.store import EventStore, fold, parse_hide_window
from eventrank.trending import score as trending

WINDOW = parse_hide_window(ES.DEFAULT_HIDE_WINDOW)
# Tên mô hình của sự kiện TRONG cửa sổ: không được lộ (dùng từ lạ để dò được cả khi bị cắt/ghép chuỗi).
SECRET_NAMES = ["Zyxquor đổ bộ Quảng Ninh gây mưa lớn", "Vexmorrid tăng giá kỷ lục phiên sáng",
                "Glabbertine được công bố chiều 15/9"]
# Tên mô hình bị LOẠI (rơi về medoid) của một sự kiện trong cửa sổ — chỉ có trong ten_su_kien.csv (cột ten_mo_hinh).
REJECTED = {"E20260915-0000aaaa": "Quintarbex khánh thành cầu mới"}
SECRET_WORDS = ["zyxquor", "vexmorrid", "glabbertine", "quintarbex"]
FAR_NAME = "Giá vàng tăng nhẹ phiên sáng nay"   # chung 4 âm tiết với một tên ẩn, Jaccard 0,4 < 0,6 → vẫn hiển thị
PUBLIC_NAME = "Mưa lớn gây ngập nhiều tuyến phố Hà Nội"           # mô hình, NGOÀI cửa sổ → hiển thị bình thường

# event_id, ten (đầu ra pipeline), nguon, medoid_title, [(article_id, published_at, source)]
EVENTS = [
    ("E20260913-aaaaaaaa", PUBLIC_NAME, "model", "Hà Nội ngập sau mưa lớn",
     [("a1", "2026-09-13T08:00:00+07:00", "vnexpress"), ("x2", "2026-09-13T08:40:00+07:00", "tuoitre"),
      ("x3", "2026-09-13T10:10:00+07:00", "tuoitre")]),
    ("E20260914-bbbbbbbb", SECRET_NAMES[0], "model", "Bão số 3 đổ bộ Quảng Ninh",
     [("y1", "2026-09-14T09:00:00+07:00", "vnexpress"), ("y2", "2026-09-14T09:30:00+07:00", "nhandan"),
      ("y3", "2026-09-14T11:00:00+07:00", "tuoitre")]),
    ("E20260913-cccccccc", SECRET_NAMES[1], "model", "Giá vàng tăng mạnh",          # 13/09 22h → 14/09 01h: giao cửa sổ
     [("z1", "2026-09-13T22:00:00+07:00", "nhandan"), ("z2", "2026-09-14T01:00:00+07:00", "vnexpress")]),
    ("E20260915-dddddddd", SECRET_NAMES[2], "model", "Công bố kết quả thi chiều 15/9",  # 15/09 23h → 16/09: giao
     [("w1", "2026-09-15T23:00:00+07:00", "tuoitre"), ("w2", "2026-09-16T00:30:00+07:00", "nhandan")]),
    ("E20260916-eeeeeeee", "Giá xăng giảm từ chiều nay", "title", "Giá xăng giảm từ chiều nay",
     [("b1", "2026-09-16T07:07:00+07:00", "baochinhphu")]),
    ("E20260912-ffffffff", "Khai mạc hội chợ quốc tế", "medoid", "Khai mạc hội chợ quốc tế",
     [("v1", "2026-09-12T09:00:00+07:00", "tuoitre"), ("v2", "2026-09-12T09:20:00+07:00", "tuoitre")]),
    # NGOÀI cửa sổ nhưng mô hình sinh đúng tên của một sự kiện trong cửa sổ (cùng câu chuyện) → cũng phải ẩn
    ("E20260917-abcdef01", SECRET_NAMES[0], "model", "Bão số 3 suy yếu thành áp thấp",
     [("u1", "2026-09-17T08:00:00+07:00", "thanhnien"), ("u2", "2026-09-17T09:00:00+07:00", "thanhnien")]),
    # trong cửa sổ, tên mô hình bị loại → tên = medoid; tên bị loại vẫn là bí mật
    ("E20260915-0000aaaa", "Khánh thành cầu Rạch Miễu 2", "medoid", "Khánh thành cầu Rạch Miễu 2",
     [("k1", "2026-09-15T10:00:00+07:00", "thanhnien"), ("k2", "2026-09-15T11:00:00+07:00", "thanhnien")]),
    # NGOÀI cửa sổ, tên GẦN trùng (Jaccard âm tiết ≥ 0,6) một tên ẩn → phải ẩn
    ("E20260820-0000bbbb", "Vexmorrid tăng giá kỷ lục phiên chiều", "model", "Giá cổ phiếu lập đỉnh",   # 6/8 = 0,75
     [("n1", "2026-08-20T08:00:00+07:00", "tuoitre"), ("n2", "2026-08-20T09:00:00+07:00", "tuoitre")]),
    ("E20260821-0000cccc", "Quintarbex khánh thành cầu mới ở Huế", "model", "Thông xe cầu ở Huế",   # 5/7 với tên bị loại
     [("n3", "2026-08-21T08:00:00+07:00", "tuoitre"), ("n4", "2026-08-21T09:00:00+07:00", "tuoitre")]),
    # NGOÀI cửa sổ, chung vài âm tiết nhưng dưới ngưỡng → hiển thị bình thường
    ("E20260822-0000dddd", FAR_NAME, "model", "Giá vàng nhích nhẹ",
     [("n5", "2026-08-22T08:00:00+07:00", "tuoitre"), ("n6", "2026-08-22T09:00:00+07:00", "tuoitre")]),
]


def _write(path, rows, fields):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def make_run(root):
    """Dựng thư mục lần chạy giống `eventrank.serving.pipeline` (xu hướng tính bằng trending.score thật)."""
    d = root / "2026-11-03_test"
    d.mkdir(parents=True)
    bai = [{"event_id": eid, "article_id": aid, "published_at": t, "source": s, "category": "Thời sự",
            "title": f"Bài {aid} về {medoid}", "is_medoid": int(i == 0)}
           for eid, _, _, medoid, arts in EVENTS for i, (aid, t, s) in enumerate(arts)]
    _write(d / "bai_su_kien.csv", bai, ["event_id", "article_id", "published_at", "source", "category", "title",
                                        "is_medoid"])
    cfg = {**trending.DEFAULTS, "start": "2026-09-12", "end": "2026-09-17", "baseline_start": "2026-09-12",
           "baseline_end": "2026-09-17"}
    meta = trending.run(d, cfg, d, log=lambda s: None)
    with open(d / "diem_su_kien.csv", encoding="utf-8") as f:
        diem = {r["event_id"]: r for r in csv.DictReader(f)}
    rows = []
    for eid, ten, nguon, medoid, arts in EVENTS:
        src = Counter(s for _, _, s in arts)
        ds = diem.get(eid, {})
        rows.append({"event_id": eid, "ten": ten, "nguon": nguon, "size": len(arts), "n_sources": len(src),
                     "sources": " ".join(f"{s}:{n}" for s, n in sorted(src.items())),
                     "first_seen": arts[0][1], "last_seen": arts[-1][1], "medoid_title": medoid,
                     **{k: ds.get(k, "") for k in ("tong_diem", "diem_cao_nhat", "luc_cao_nhat", "so_gio_trong_top10")}})
    _write(d / "su_kien.csv", rows, ["event_id", "ten", "nguon", "size", "n_sources", "sources", "first_seen",
                                     "last_seen", "medoid_title", "tong_diem", "diem_cao_nhat", "luc_cao_nhat",
                                     "so_gio_trong_top10"])
    # các file chứa tên mô hình chưa lọc — API không được đọc/phục vụ chúng
    (d / "events.json").write_text(json.dumps({"su_kien": [{"ten": n} for n in SECRET_NAMES]}, ensure_ascii=False),
                                   encoding="utf-8")
    _write(d / "ten_su_kien.csv", [{"event_id": e[0], "ten": e[1], "nguon": e[2],
                                    "ly_do_fallback": "khong_trung_thuc" if e[0] in REJECTED else "",
                                    "ten_mo_hinh": REJECTED.get(e[0], "")} for e in EVENTS],
           ["event_id", "ten", "nguon", "ly_do_fallback", "ten_mo_hinh"])
    manifest = {"run_id": d.name, "versions": {"model_version": "m", "algo_version": "v1", "naming_version": "n",
                                               "trend_version": "t2"},
                "config": {"trending": cfg, "export": {"latest_min_candidates": 1}}, "range": {"start": None, "end": None},
                "steps": {"trend": meta, "export": {"finished_at": "2026-11-03T16:37:12+00:00"}}}
    (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return d


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    return make_run(tmp_path_factory.mktemp("runs"))


@pytest.fixture(scope="module")
def events(run_dir):
    return EventStore(run_dir, WINDOW)


@pytest.fixture(scope="module")
def client(store, events):
    return TestClient(create_app(store, events))


def _all_times(client):
    tt = client.get("/api/trending/times").json()
    start = datetime.fromisoformat(tt["dau"]).timestamp()
    return [datetime.fromtimestamp(start + i * tt["buoc_gio"] * 3600, trending.VN).isoformat()
            for i in range(tt["so_moc"])]


# ---------------------------------------------------------------- ẩn tên (BẮT BUỘC)
def test_cua_so_mac_dinh_la_14_den_het_15_09():
    lo, hi = WINDOW
    assert lo.isoformat() == "2026-09-14T00:00:00+07:00" and hi.isoformat() == "2026-09-16T00:00:00+07:00"
    with pytest.raises(ValueError):
        parse_hide_window("14/09/2026")
    with pytest.raises(ValueError):
        parse_hide_window("2026-09-15..2026-09-14")


def test_su_kien_giao_cua_so_bi_an_ten(events):
    hidden = {e.event_id for e in events.events.values() if e.ten_bi_an}
    assert hidden == {"E20260914-bbbbbbbb", "E20260913-cccccccc", "E20260915-dddddddd", "E20260917-abcdef01",
                      "E20260915-0000aaaa", "E20260820-0000bbbb", "E20260821-0000cccc"}
    assert events.events["E20260820-0000bbbb"].ten == "Giá cổ phiếu lập đỉnh"           # gần trùng → medoid
    assert events.events["E20260822-0000dddd"].ten == FAR_NAME and not events.events["E20260822-0000dddd"].ten_bi_an
    assert events.events["E20260917-abcdef01"].ten == "Bão số 3 suy yếu thành áp thấp"
    e = events.events["E20260914-bbbbbbbb"]
    assert e.ten == "Bão số 3 đổ bộ Quảng Ninh" and e.nguon_ten == "an"
    assert events.events["E20260913-aaaaaaaa"].ten == PUBLIC_NAME            # ngoài cửa sổ: tên mô hình bình thường
    # tên mô hình bị bỏ ngay lúc nạp: không còn ở đâu trong bộ nhớ của EventStore
    assert _leaks(repr(vars(events))) == []


def _leaks(text: str) -> list[str]:
    low, folded = text.lower(), fold(text)
    return [w for w in SECRET_WORDS if w in low or w in folded] + [n for n in SECRET_NAMES if n in text]


def test_ten_mo_hinh_trong_cua_so_khong_lo_o_bat_ky_endpoint_nao(client, events):
    """Duyệt MỌI endpoint sự kiện (mọi mốc xu hướng, mọi trang danh sách, mọi chi tiết, tìm kiếm) + OpenAPI."""
    urls = ["/api/runs/current", "/api/trending/times", "/api/trending", "/openapi.json", "/api/events/stats",
            "/api/events/map/dates"]
    urls += [f"/api/trending?t={t.replace('+', '%2B')}" for t in _all_times(client)]
    for sort in ("hot", "newest", "size", "first_seen"):
        urls += [f"/api/events?min_size=1&sort={sort}&page={p}&page_size=2" for p in range(1, 5)]
    urls += [f"/api/events?min_size=1&q={w}" for w in SECRET_WORDS + [n.split()[0] for n in SECRET_NAMES]]
    urls += [f"/api/events/{eid}" for eid in events.events]
    seen_public = False
    for u in urls:
        r = client.get(u)
        assert r.status_code == 200, u
        assert _leaks(r.text) == [], u
        seen_public = seen_public or (u.startswith("/api/events") and PUBLIC_NAME in r.text)
    assert seen_public                     # đối chứng: tên mô hình NGOÀI cửa sổ vẫn hiển thị qua cùng các endpoint
    assert FAR_NAME in client.get("/api/events/E20260822-0000dddd").text


def test_tim_kiem_chi_khop_ten_dang_hien_thi(client):
    for w in SECRET_WORDS:
        assert client.get("/api/events", params={"q": w, "min_size": 1}).json()["total"] == 0
    # tên đang hiển thị (tiêu đề bài đại diện) thì tìm được, kể cả gõ không dấu
    body = client.get("/api/events", params={"q": "bao so 3 do bo", "min_size": 1}).json()
    assert [i["event_id"] for i in body["items"]] == ["E20260914-bbbbbbbb"] and body["items"][0]["ten_bi_an"]


def test_bang_xu_huong_trong_cua_so_dung_ten_an(client):
    r = client.get("/api/trending", params={"t": "2026-09-14T11:00"}).json()
    item = next(i for i in r["items"] if i["event_id"] == "E20260914-bbbbbbbb")
    assert item["ten"] == "Bão số 3 đổ bộ Quảng Ninh" and item["nguon_ten"] == "an" and item["ten_bi_an"]


def test_tat_cua_so_thi_hien_ten_mo_hinh(run_dir, store):
    """Đối chứng cho phép dò lộ tên: cùng dữ liệu, tắt cửa sổ → tên mô hình hiện ra (bộ dò bắt được)."""
    c = TestClient(create_app(store, EventStore(run_dir, None)))
    r = c.get("/api/events/E20260914-bbbbbbbb")
    assert r.json()["ten"] == SECRET_NAMES[0] and _leaks(r.text)


def test_bien_moi_truong_chon_run_va_cua_so(run_dir, monkeypatch):
    monkeypatch.setenv("EVENTS_RUN_DIR", str(run_dir))
    monkeypatch.delenv("EVENTS_HIDE_NAMES_WINDOW", raising=False)
    assert EventStore.from_env().events["E20260914-bbbbbbbb"].ten_bi_an          # chưa đặt → mặc định 14–15/09
    monkeypatch.setenv("EVENTS_HIDE_NAMES_WINDOW", "")
    assert EventStore.from_env().events["E20260914-bbbbbbbb"].ten_bi_an          # rỗng = mặc định, KHÔNG tắt
    monkeypatch.setenv("EVENTS_HIDE_NAMES_WINDOW", "2026-09-13")
    assert EventStore.from_env().events["E20260913-aaaaaaaa"].ten_bi_an
    monkeypatch.setenv("EVENTS_HIDE_NAMES_WINDOW", "sai")
    with pytest.raises(ValueError):
        EventStore.from_env()


def test_tim_run_moi_nhat(tmp_path, run_dir):
    assert ES.find_run_dir(tmp_path / "khong-co") is None
    assert ES.find_run_dir(run_dir.parent) == run_dir


# ---------------------------------------------------------------- không có run
def test_khong_co_run_thi_503_con_trang_cu_van_chay(store, monkeypatch, tmp_path):
    monkeypatch.setenv("EVENTS_RUN_DIR", str(tmp_path / "khong-co"))
    with TestClient(create_app(store, load_events=True)) as c:
        for u in ["/api/events", "/api/trending", "/api/trending/times", "/api/runs/current",
                  "/api/events/E20260913-aaaaaaaa"]:
            r = c.get(u)
            assert r.status_code == 503, u
            assert "make pipeline" in r.json()["detail"]
        assert c.get("/api/health").status_code == 200


def test_test_truyen_store_khong_tu_nap_run(store):
    assert TestClient(create_app(store)).get("/api/events").status_code == 503


# ---------------------------------------------------------------- từng endpoint
def test_run_hien_tai(client):
    b = client.get("/api/runs/current").json()
    assert b["run_id"] == "2026-11-03_test" and b["versions"]["trend_version"] == "t2"
    assert b["n_su_kien"] == 11 and b["n_su_kien_nhieu_bai"] == 10 and b["n_bai"] == 23
    assert b["cua_so_an_ten"] == {"tu_ngay": "2026-09-14", "den_ngay": "2026-09-15"} and b["n_su_kien_bi_an"] == 7
    assert b["du_lieu_tu"] == "2026-08-20T08:00:00+07:00" and b["du_lieu_den"] == "2026-09-17T09:00:00+07:00"
    assert b["pham_vi_tu"] is None and b["pham_vi_den"] is None
    assert any("chưa được đánh giá" in g.lower() for g in b["ghi_chu"])


def test_moc_xu_huong(client, run_dir):
    tt = client.get("/api/trending/times").json()
    assert tt["dau"] == "2026-09-12T01:00:00+07:00" and tt["cuoi"] == "2026-09-17T00:00:00+07:00"
    assert tt["so_moc"] == len(tt["so_su_kien"]) == 120
    with open(run_dir / "xu_huong.csv", encoding="utf-8") as f:
        assert sum(tt["so_su_kien"]) == sum(1 for _ in csv.DictReader(f))


def test_xu_huong_mac_dinh_va_lam_tron_gio(client):
    d = client.get("/api/trending").json()
    assert d["t"] == d["mac_dinh"] and d["items"]                        # mốc cuối có ≥ 1 sự kiện (fixture)
    r = client.get("/api/trending", params={"t": "2026-09-13T10:45"}).json()   # không múi giờ = giờ VN, làm tròn xuống
    assert r["t"] == "2026-09-13T10:00:00+07:00"
    assert r["t_truoc"] == "2026-09-13T09:00:00+07:00" and r["t_sau"] == "2026-09-13T11:00:00+07:00"
    assert [i["hang"] for i in r["items"]] == list(range(1, len(r["items"]) + 1))
    assert r["items"][0]["event_id"] == "E20260913-aaaaaaaa" and r["items"][0]["ten"] == PUBLIC_NAME
    assert client.get("/api/trending", params={"t": "2026-09-12T01:00:00+07:00"}).json()["t_truoc"] is None


@pytest.mark.parametrize("t", ["hom-qua", "2026-08-01T05:00", "2026-12-01"])
def test_xu_huong_moc_sai_tra_422(client, t):
    assert client.get("/api/trending", params={"t": t}).status_code == 422


def test_danh_sach_mac_dinh_su_kien_tu_2_bai_sap_theo_do_nong(client, events):
    b = client.get("/api/events").json()
    assert b["total"] == 10 and all(i["size"] >= 2 for i in b["items"])
    diem = [i["tong_diem"] or 0 for i in b["items"]]
    assert diem == sorted(diem, reverse=True)


def test_danh_sach_loc_va_phan_trang(client):
    p1 = client.get("/api/events", params={"min_size": 1, "page_size": 4, "sort": "newest"}).json()
    p2 = client.get("/api/events", params={"min_size": 1, "page_size": 4, "sort": "newest", "page": 2}).json()
    p3 = client.get("/api/events", params={"min_size": 1, "page_size": 4, "sort": "newest", "page": 3}).json()
    assert p1["total"] == 11 and len(p1["items"]) == 4 and len(p2["items"]) == 4 and len(p3["items"]) == 3
    ids = [i["event_id"] for i in p1["items"] + p2["items"] + p3["items"]]
    assert len(set(ids)) == 11 and ids[:2] == ["E20260917-abcdef01", "E20260916-eeeeeeee"]
    by_size = client.get("/api/events", params={"sort": "size"}).json()["items"]
    assert [i["size"] for i in by_size] == sorted([i["size"] for i in by_size], reverse=True)
    src = client.get("/api/events", params={"source": "nhandan"}).json()["items"]
    assert {i["event_id"] for i in src} == {"E20260914-bbbbbbbb", "E20260913-cccccccc", "E20260915-dddddddd"}
    # khoảng ngày: sự kiện GIAO khoảng (13/09 22h → 14/09 01h nằm trong cả ngày 13 lẫn 14)
    d13 = client.get("/api/events", params={"date_from": "2026-09-13", "date_to": "2026-09-13"}).json()["items"]
    assert {i["event_id"] for i in d13} == {"E20260913-aaaaaaaa", "E20260913-cccccccc"}
    assert client.get("/api/events", params={"page": 9}).json()["items"] == []


@pytest.mark.parametrize("params", [{"sort": "bad"}, {"page_size": 101}, {"page": 0}, {"date_from": "13/09/2026"},
                                    {"min_size": 0}])
def test_danh_sach_tham_so_sai_tra_422(client, params):
    assert client.get("/api/events", params=params).status_code == 422


def test_chi_tiet_su_kien(client, run_dir):
    d = client.get("/api/events/E20260913-aaaaaaaa").json()
    assert d["ten"] == PUBLIC_NAME and d["nguon_ten"] == "model" and d["size"] == 3
    assert d["sources"] == [{"source": "tuoitre", "n": 2}, {"source": "vnexpress", "n": 1}]
    assert [a["article_id"] for a in d["bai"]] == ["a1", "x2", "x3"]
    assert d["bai"][0]["url"] == "https://vnexpress.net/a1.html" and d["bai"][1]["url"] is None   # URL lấy từ Silver
    assert sum(p["so_bai"] for p in d["chuoi"]) == 3 and d["chuoi"][0]["so_bai"] == 0
    assert d["chuoi"][-1]["diem"] == 0 and not d["chuoi_bi_cat"]
    # điểm tính lại khớp ĐÚNG bảng top-K của bước trend ở mọi mốc sự kiện có mặt
    pts = {p["t"]: p for p in d["chuoi"]}
    with open(run_dir / "xu_huong.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["event_id"] == d["event_id"]]
    assert rows
    for r in rows:
        assert pts[r["t"]]["diem"] == pytest.approx(float(r["score"]), abs=1e-6)
        assert pts[r["t"]]["hang"] == int(r["hang"])
    assert sum(p["diem"] for p in d["chuoi"]) == pytest.approx(d["tong_diem"], abs=1e-4)


def test_chi_tiet_404_va_422(client):
    assert client.get("/api/events/E20990101-00000000").status_code == 404
    for bad in ["abc", "E2026091-aaaaaaaa", "E20260913-AAAAAAAA", "..%2F..%2Fmanifest"]:
        assert client.get(f"/api/events/{bad}").status_code in (404, 422), bad
    assert client.get("/api/events/abc").status_code == 422


def test_mat_khau_ap_cho_ca_endpoint_su_kien(store, events, monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "nhom")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "mat-khau-manh")
    c = TestClient(create_app(store, events))
    for u in ["/api/trending", "/api/events", "/api/events/E20260913-aaaaaaaa", "/api/runs/current"]:
        assert c.get(u).status_code == 401, u
        assert c.get(u, auth=("nhom", "mat-khau-manh")).status_code == 200, u


# ---------------------------------------------------------------- đợt sửa sau kiểm tra độc lập (V1, V2, N1, N2, N6)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_bien_rong_hoac_khong_dat_dung_cua_so_mac_dinh(value):
    assert parse_hide_window(value) == WINDOW


@pytest.mark.parametrize("value", ["off", "OFF", " Off "])
def test_chi_off_moi_tat_an_ten_va_co_canh_bao(value, caplog):
    with caplog.at_level("WARNING", logger="eventrank.serving.store"):
        assert parse_hide_window(value) is None
    assert any("TẮT" in r.getMessage() for r in caplog.records)


def test_ba_truong_hop_bien_moi_truong(run_dir, monkeypatch):
    monkeypatch.setenv("EVENTS_RUN_DIR", str(run_dir))
    eid = "E20260914-bbbbbbbb"
    monkeypatch.delenv("EVENTS_HIDE_NAMES_WINDOW", raising=False)
    assert EventStore.from_env().events[eid].ten_bi_an                     # không đặt → mặc định
    monkeypatch.setenv("EVENTS_HIDE_NAMES_WINDOW", "")
    assert EventStore.from_env().events[eid].ten_bi_an                     # rỗng → mặc định
    monkeypatch.setenv("EVENTS_HIDE_NAMES_WINDOW", "off")
    assert not EventStore.from_env().events[eid].ten_bi_an                 # chỉ "off" mới tắt


@pytest.mark.parametrize("a,b,expected", [
    ("Vexmorrid tăng giá kỷ lục phiên chiều", "Vexmorrid tăng giá kỷ lục phiên sáng", 0.75),
    ("Giá vàng tăng nhẹ phiên sáng nay", "Vexmorrid tăng giá kỷ lục phiên sáng", 0.4),
    ("Hà Nội: mưa lớn!", "ha noi mua LON", 1.0),           # chữ thường, bỏ dấu câu, bỏ dấu thanh
])
def test_do_giong_am_tiet(a, b, expected):
    assert ES.syllable_jaccard(ES.syllables(a), ES.syllables(b)) == pytest.approx(expected)


def test_nguong_gan_trung_la_hang_so():
    assert ES.NEAR_DUP_JACCARD == 0.6


def test_khong_doc_ten_su_kien_van_an_theo_cua_so(run_dir, tmp_path):
    """Thiếu ten_su_kien.csv (run cũ): vẫn ẩn theo cửa sổ + gần trùng với tên đang dùng; chỉ mất tên bị loại."""
    import shutil
    d = tmp_path / "run"
    shutil.copytree(run_dir, d)
    (d / "ten_su_kien.csv").unlink()
    ev = EventStore(d, WINDOW)
    assert ev.events["E20260820-0000bbbb"].ten_bi_an and not ev.events["E20260821-0000cccc"].ten_bi_an


def test_thong_bao_503_khong_lo_duong_dan_tuyet_doi(store, monkeypatch, tmp_path):
    empty = tmp_path / "run_rong"
    empty.mkdir()
    for target in (empty, tmp_path / "khong-co"):
        monkeypatch.setenv("EVENTS_RUN_DIR", str(target))
        with TestClient(create_app(store, load_events=True)) as c:
            detail = c.get("/api/events").json()["detail"]
        assert str(tmp_path) not in detail and "/home/" not in detail and "make pipeline" in detail, detail
        assert target.name in detail


def _fake_run(root, name, finished, start=None, end=None):
    d = root / name
    d.mkdir()
    (d / "su_kien.csv").write_text("event_id\n", encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"run_id": name, "range": {"start": start, "end": end},
                                                 "steps": {"cluster": {"finished_at": "2026-11-01T00:00:00+00:00"},
                                                           "export": {"finished_at": finished}}}), encoding="utf-8")
    return d


def test_chon_run_day_du_moi_nhat_theo_manifest(tmp_path):
    import os
    full_old = _fake_run(tmp_path, "2026-11-03_v1", "2026-11-03T10:00:00+00:00")
    full_new = _fake_run(tmp_path, "2026-11-03_v2", "2026-11-03T16:00:00+07:00")    # = 09:00 UTC, CŨ hơn v1
    _fake_run(tmp_path, "2026-11-04_thu", "2026-11-04T10:00:00+00:00", start="2026-09-15", end="2026-09-17")
    os.utime(full_new / "su_kien.csv", (1, 1))                    # thời điểm sửa file không được ảnh hưởng
    assert ES.find_run_dir(tmp_path) == full_old                  # finished_at so theo thời điểm thật (múi giờ)
    assert ES.find_run_dir(tmp_path / "khong-co") is None


def test_ngay_khong_co_tren_lich_tra_422(client):
    for p in ({"date_from": "2026-02-30"}, {"date_to": "2026-13-01"}):
        assert client.get("/api/events", params=p).status_code == 422


# ---------------------------------------------------------------- chuyên mục, "mới xuất hiện", thống kê, bản đồ 2D
def test_chuan_hoa_chuyen_muc_giua_cac_bao():
    assert ES.norm_category("Khoa học - Công Nghệ") == ES.norm_category("Khoa học - Công nghệ")
    assert ES.norm_category("Y Tế") == ES.norm_category("Sức Khỏe") == "Sức khỏe"
    assert ES.norm_category("Quốc Tế") == "Thế giới"
    assert ES.norm_category("THỜI SỰ") == "Thời sự" and ES.norm_category("  ") is None


def test_chuyen_muc_chinh_va_loc_theo_chuyen_muc(client):
    body = client.get("/api/events", params={"min_size": 1, "category": "thoi su", "page_size": 100}).json()
    assert body["total"] == len(EVENTS) and {i["chuyen_muc_chinh"] for i in body["items"]} == {"Thời sự"}
    assert client.get("/api/events", params={"min_size": 1, "category": "Thể thao"}).json()["total"] == 0
    item = client.get("/api/trending", params={"t": "2026-09-13T09:00"}).json()["items"][0]
    assert item["chuyen_muc_chinh"] == "Thời sự" and item["first_seen"].startswith("2026-09-13T08:00")


def test_moi_xuat_hien_loc_theo_bai_dau_va_sap_muon_truoc(client):
    body = client.get("/api/events", params={"min_size": 1, "sort": "first_seen", "first_from": "2026-09-13",
                                             "first_to": "2026-09-13T23:59"}).json()
    assert [i["event_id"] for i in body["items"]] == ["E20260913-cccccccc", "E20260913-aaaaaaaa"]   # 22h trước 8h
    body = client.get("/api/events", params={"min_size": 1, "first_from": "2026-09-13", "first_to": "2026-09-13T09:00"})
    assert [i["event_id"] for i in body.json()["items"]] == ["E20260913-aaaaaaaa"]                  # chưa tới 22h
    assert client.get("/api/events", params={"first_from": "hôm qua"}).status_code == 422


def test_thong_ke_su_kien_va_so_lieu_mot_ngay(client):
    d = client.get("/api/events/stats", params={"date": "2026-09-13"}).json()
    assert d["n_su_kien"] == len(EVENTS) and sum(b["n"] for b in d["kich_thuoc"]) == len(EVENTS)
    assert d["kich_thuoc"][0] == {"nhan": "1 bài", "n": 1} and sum(b["n"] for b in d["so_bao"]) == d["n_su_kien_nhieu_bai"]
    # 13/09: 3 bài của aaaaaaaa + 1 bài 22h của cccccccc → 2 sự kiện, 1 sự kiện có ≥ 2 bài trong ngày, 3 báo
    assert d["ngay"] == {"date": "2026-09-13", "so_bai": 4, "so_su_kien": 2, "so_su_kien_nhieu_bai": 1, "so_bao": 3}
    assert client.get("/api/events/stats").json()["ngay"] is None
    assert _leaks(client.get("/api/events/stats", params={"date": "2026-09-14"}).text) == []


def _write_map(run_dir, date, top, diem):
    d = run_dir / ES.MAP_DIR
    d.mkdir(exist_ok=True)
    (d / f"{date}.json").write_text(json.dumps({"date": date, "run_id": run_dir.name, "model_version": "m",
                                                "tsne": {"perplexity": 25}, "n_bai": len(diem), "n_su_kien": 2,
                                                "n_su_kien_nhieu_bai": 1, "top": top, "diem": diem}), encoding="utf-8")


def test_ban_do_dung_ten_dang_hien_thi_va_tu_choi_ngay_trong_cua_so(client, run_dir):
    # 20/08: sự kiện ngoài cửa sổ nhưng tên mô hình gần trùng tên ẩn → bản đồ phải dùng tên medoid
    _write_map(run_dir, "2026-08-20", [{"event_id": "E20260820-0000bbbb", "n": 2}, {"event_id": "E20990101-deadbeef", "n": 1}],
               [[1.0, 2.0, 0], [3.0, 4.0, 0], [50.0, 50.0, 1], [9.0, 9.0, -1]])
    _write_map(run_dir, "2026-09-14", [{"event_id": "E20260914-bbbbbbbb", "n": 3}], [[1.0, 1.0, 0]])
    m = client.get("/api/events/map", params={"date": "2026-08-20"})
    assert m.status_code == 200 and _leaks(m.text) == []
    body = m.json()
    assert [e["ten"] for e in body["su_kien"]] == ["Giá cổ phiếu lập đỉnh"] and body["su_kien"][0]["ten_bi_an"]
    assert [p[2] for p in body["diem"]] == [0, 0, -1, -1]           # sự kiện không có trong run → bỏ màu
    assert body["ngay_co_san"] == ["2026-08-20"]                     # 14/09 có file nhưng không được liệt kê
    r = client.get("/api/events/map", params={"date": "2026-09-14"})
    assert r.status_code == 403 and _leaks(r.text) == []
    assert client.get("/api/events/map", params={"date": "2026-09-01"}).status_code == 404
    assert client.get("/api/events/map", params={"date": "10/09"}).status_code == 422
    assert client.get("/api/events/map/dates").json() == {"dates": ["2026-08-20"], "mac_dinh": "2026-08-20"}


def test_dung_ban_do_tu_vector_dem(run_dir, tmp_path, monkeypatch):
    import numpy as np

    from eventrank.evaluation import event_map

    monkeypatch.delenv("EVENTS_HIDE_NAMES_WINDOW", raising=False)
    with open(run_dir / "bai_su_kien.csv", encoding="utf-8") as f:
        ids = [r["article_id"] for r in csv.DictReader(f)]
    rng = np.random.default_rng(0)
    E = rng.normal(size=(len(ids), 8)).astype(np.float32)
    np.savez(tmp_path / "emb.npz", ids=np.array(ids), E=E)
    m = event_map.build_map(run_dir, "2026-09-13", tmp_path / "emb.npz", top=1)
    assert m["n_bai"] == 4 and m["n_su_kien"] == 2 and m["n_su_kien_nhieu_bai"] == 1
    assert m["top"] == [{"event_id": "E20260913-aaaaaaaa", "n": 3}]
    assert sorted(p[2] for p in m["diem"]) == [-1, 0, 0, 0]
    assert all(0 <= p[0] <= 100 and 0 <= p[1] <= 100 for p in m["diem"])
    assert "ten" not in json.dumps(m) and _leaks(json.dumps(m, ensure_ascii=False)) == []   # file không chứa tên
    with pytest.raises(ValueError, match="cửa sổ ẩn tên"):
        event_map.build_map(run_dir, "2026-09-15", tmp_path / "emb.npz")


def _sources_24h(store, k, min_articles):
    hi = store._t(k).timestamp()
    by = Counter(a["source"] for arts in store.articles.values() for a in arts if hi - 86400 < a["ts"] <= hi)
    return sum(n >= min_articles for n in by.values())


def test_moc_mac_dinh_can_du_bao_trong_24_gio(run_dir):
    """Mốc mặc định = mốc muộn nhất có đủ sự kiện VÀ đủ báo (mỗi báo ≥ N bài) trong 24 giờ; không có mốc nào đạt → luật cũ."""
    old = EventStore(run_dir, WINDOW, default_min_sources=0)
    assert old.default_k == max(old.trend)                      # fixture: latest_min_candidates = 1 → mốc có bảng muộn nhất
    # mọi cặp ngưỡng: mốc chọn ra = mốc muộn nhất đạt điều kiện (không mốc nào đạt → luật cũ)
    lui = 0
    for ms in (1, 2, 3):
        for ma in (1, 2, 3):
            s = EventStore(run_dir, WINDOW, default_min_sources=ms, default_min_articles=ma)
            ok = [k for k in s.trend if _sources_24h(s, k, ma) >= ms]
            assert s.default_k == (max(ok) if ok else old.default_k), (ms, ma)
            lui += s.default_k < old.default_k
    assert lui > 0                                              # có trường hợp phải lùi về mốc sớm hơn
    assert s.trend_times()["mac_dinh"] == s.trending()["t"]
    none = EventStore(run_dir, WINDOW, default_min_sources=6, default_min_articles=50)   # không mốc nào đạt
    assert none.default_k == old.default_k


def test_chuyen_muc_cua_cac_bai_dung_ten_da_gop(client):
    d = client.get("/api/events/E20260913-aaaaaaaa").json()
    assert d["chuyen_muc"] == [{"category": "Thời sự", "n": 3}]
