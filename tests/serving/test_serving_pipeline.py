"""Đầu-cuối với dữ liệu tí hon + encoder / bộ sinh tên giả (không mạng, không tải mô hình)."""
import csv
import json

import numpy as np
import pytest

from eventrank.serving import pipeline as SP


def _art(aid, t, title, source="vnexpress", sapo=""):
    return {"article_id": aid, "published_at": t, "source": source, "title": title, "sapo": sapo, "category": "X"}


def _encoder(xs):
    return np.array([[1.0, 0.0] if x.startswith("Bão") else [0.0, 1.0] for x in xs], dtype=np.float32)


def _gen(xs):
    return ["Bão số 5 đổ bộ Quảng Ninh" if "Bão" in x else "Giá vàng lập đỉnh 2027" for x in xs]


def _cfg(tmp_path):
    cfg = SP.load_config()                                                   # file thật của repo phải hợp lệ
    cfg["clustering"]["params"] = {"algo_version": "vt", "model": "fake", "model_version": "fake", "prep": "raw",
                                   "algo": "agglo", "threshold": 0.8, "window_hours": 48}
    cfg["clustering"]["cache_dir"] = str(tmp_path / "emb_cache")
    cfg["naming"].update(cache_dir=str(tmp_path / "name_cache"), naming_version="vt")
    cfg["trending"].update(baseline_start="2026-09-15", baseline_end="2026-09-17")
    return cfg


def test_pipeline_dau_cuoi(tmp_path):
    rows = [_art("1", "2026-09-15T08:00:00+07:00", "Bão số 5 vào bờ", sapo="Bão mạnh ở Quảng Ninh."),
            _art("2", "2026-09-15T09:00:00+07:00", "Bão số 5 gây mưa Quảng Ninh", "tuoitre"),
            _art("3", "2026-09-15T10:00:00+07:00", "Giá vàng giảm", "nhandan"),
            _art("4", "2026-09-15T10:30:00+07:00", "Giá vàng lập đỉnh", "tuoitre"),
            _art("5", "2026-09-15T11:00:00+07:00", "Bão số 5 suy yếu", "vietnamnet"),
            _art("9", "2026-09-20T08:00:00+07:00", "Bão số 6 hình thành")]     # ngoài khoảng --end
    d = tmp_path / "silver" / "s"
    d.mkdir(parents=True)
    (d / "a.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    g = str(tmp_path / "silver" / "*" / "*.jsonl")
    out = SP.run(_cfg(tmp_path), "thu", list(SP.STEPS), "2026-09-15", "2026-09-17", g, tmp_path / "runs",
                 encoder=_encoder, generator=_gen, log=lambda s: None)
    for f in ("manifest.json", "su_kien.csv", "bai_su_kien.csv", "xu_huong.csv", "xu_huong_moc.csv",
              "ten_su_kien.csv", "diem_su_kien.csv", "events.json", "README.md", "cum/su_kien.csv"):
        assert (out / f).exists(), f
    with open(out / "su_kien.csv", encoding="utf-8") as f:
        ev = list(csv.DictReader(f))
    assert list(ev[0]) == SP.EVENT_FIELDS and [int(e["size"]) for e in ev] == [3, 2]
    assert ev[0]["ten"] == "Bão số 5 đổ bộ Quảng Ninh" and ev[0]["nguon"] == "model" and ev[0]["diem_cao_nhat"]
    assert ev[1]["nguon"] == "medoid"                         # "2027" không có trong đầu vào → rơi về medoid
    assert ev[0]["tong_diem"] and ev[0]["so_gio_trong_top10"]
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["versions"] == {"model_version": "fake", "algo_version": "vt", "naming_version": "vt",
                             "trend_version": m["config"]["trending"]["trend_version"]}
    assert m["silver"]["n_articles"] == 5 and len(m["silver"]["article_ids_sha256"]) == 64
    assert set(m["steps"]) == set(SP.STEPS) and all("seconds" in s for s in m["steps"].values())
    assert m["steps"]["name"]["stats"]["ly_do_fallback"] == {"khong_trung_thuc": 1}
    doc = json.loads((out / "events.json").read_text(encoding="utf-8"))
    assert len(doc["su_kien"]) == 2 and doc["xu_huong_moi_nhat"]["top"][0]["ten"]

    # chạy lại riêng bước name + export: tên lấy từ đệm, không gọi mô hình
    def boom(xs):
        raise AssertionError("không được gọi mô hình khi đã có đệm")
    SP.run(_cfg(tmp_path), "thu", ["name", "export"], "2026-09-15", "2026-09-17", g, tmp_path / "runs",
           generator=boom, log=lambda s: None)
    m2 = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m2["steps"]["name"]["stats"]["n_cached"] == 2 and "cluster" in m2["steps"]

    # run_id đã có: chạy lại cả bước cluster bị từ chối trừ khi force
    with pytest.raises(FileExistsError):
        SP.run(_cfg(tmp_path), "thu", list(SP.STEPS), "2026-09-15", "2026-09-17", g, tmp_path / "runs",
               encoder=_encoder, generator=_gen, log=lambda s: None)
    SP.run(_cfg(tmp_path), "thu", ["cluster"], "2026-09-15", "2026-09-17", g, tmp_path / "runs",
           encoder=_encoder, log=lambda s: None, force=True)

    # tên thiếu → export báo lỗi, không ghi chuỗi rỗng âm thầm
    lines = (out / "ten_su_kien.csv").read_text(encoding="utf-8").splitlines()
    (out / "ten_su_kien.csv").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="không có tên"):
        SP.run(_cfg(tmp_path), "thu", ["export"], silver_glob=g, runs_root=tmp_path / "runs", log=lambda s: None)
