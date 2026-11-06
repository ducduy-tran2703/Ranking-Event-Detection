"""Nạp một lần chạy pipeline vào Postgres (`eventrank.serving.db_import`, migration 002_events.sql).

Run tí hon tự dựng trong tmp (bài thật trong DB tạm qua ingest.sink). Trọng tâm: tên mô hình của sự kiện bị ẩn và tên
mô hình bị loại KHÔNG nằm ở bất kỳ bảng nào; điểm xu hướng trong DB khớp xu_huong.csv. Cần TEST_DATABASE_URL.
"""
import csv
import json
from collections import Counter
from datetime import UTC, datetime

import numpy as np
import pytest

from eventrank.ingest import contract, sink
from eventrank.serving import db_import
from eventrank.trending import score as trending

SECRET = "Zyxquor đổ bộ Quảng Ninh gây mưa lớn"          # tên mô hình, sự kiện trong cửa sổ 14–15/09
REJECTED = "Quintarbex khánh thành cầu mới"               # tên mô hình bị loại (rơi về medoid), sự kiện ngoài cửa sổ
SECRET_WORDS = ["zyxquor", "quintarbex"]
PUBLIC = "Mưa lớn gây ngập nhiều tuyến phố Hà Nội"

# khoá, ten, nguon, ly_do_fallback, ten_mo_hinh, [(khoá bài, published_at, source)]  — bài đầu = medoid
EVENTS = [
    ("pub", PUBLIC, "model", "", "",
     [(1, "2026-09-13T08:00:00+07:00", "vnexpress"), (2, "2026-09-13T08:40:00+07:00", "tuoitre"),
      (3, "2026-09-13T10:10:00+07:00", "tuoitre")]),
    ("sec", SECRET, "model", "", "",
     [(4, "2026-09-14T09:00:00+07:00", "vnexpress"), (5, "2026-09-14T09:30:00+07:00", "tuoitre")]),
    ("rej", "Thông xe cầu ở Huế", "medoid", "khong_trung_thuc", REJECTED,
     [(6, "2026-09-12T08:00:00+07:00", "tuoitre"), (7, "2026-09-12T09:00:00+07:00", "vnexpress")]),
    ("one", "Giá xăng giảm từ chiều nay", "title", "", "", [(8, "2026-09-16T07:07:00+07:00", "tuoitre")]),
]


def _art(i, t, s):
    host = {"tuoitre": "tuoitre.vn", "vnexpress": "vnexpress.net"}[s]
    return contract.validate_article(
        {"url": f"https://{host}/bai-{i}.htm", "source": s, "category": "Thời sự" if i % 2 else "Thế Giới",
         "title": f"Bài {i}", "sapo": "Sapo.", "author": None, "published_at": t, "content_text": "Nội dung " * 100},
        known_sources={"tuoitre", "vnexpress"}, now=datetime(2026, 9, 20, tzinfo=UTC))


def _write(path, rows, fields):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def make_run(root, conn, run_id="2026-11-03_test"):
    """Ghi bài vào DB + dựng thư mục run giống serving.pipeline (xu hướng bằng trending.score thật) + đệm vector."""
    sink.sync_sources(conn, [{"source": s, "display_name": s, "enabled": False} for s in ("tuoitre", "vnexpress")])
    arts = {i: _art(i, t, s) for *_, xs in EVENTS for i, t, s in xs}
    sink.upsert_articles(conn, arts.values(), via="import_jsonl")
    d = root / run_id
    d.mkdir(parents=True)
    ev, bai = [], []
    for _, ten, nguon, ly_do, ten_mo_hinh, xs in EVENTS:
        a0 = arts[xs[0][0]]
        eid = f"E{xs[0][1][:10].replace('-', '')}-{a0.article_id[:8]}"
        src = Counter(s for *_, s in xs)
        ev.append({"event_id": eid, "ten": ten, "nguon": nguon, "ly_do_fallback": ly_do, "ten_mo_hinh": ten_mo_hinh,
                   "size": len(xs), "n_sources": len(src), "sources": " ".join(f"{k}:{n}" for k, n in sorted(src.items())),
                   "first_seen": xs[0][1], "last_seen": xs[-1][1], "medoid_title": a0.title})
        bai += [{"event_id": eid, "article_id": arts[i].article_id, "published_at": t, "source": s,
                 "category": arts[i].category, "title": arts[i].title, "is_medoid": int(k == 0)}
                for k, (i, t, s) in enumerate(xs)]
    _write(d / "bai_su_kien.csv", bai, list(bai[0]))
    cfg = {**trending.DEFAULTS, "start": "2026-09-12", "end": "2026-09-17", "baseline_start": "2026-09-12",
           "baseline_end": "2026-09-17"}
    meta = trending.run(d, cfg, d, log=lambda s: None)
    with open(d / "diem_su_kien.csv", encoding="utf-8") as f:
        diem = {r["event_id"]: r for r in csv.DictReader(f)}
    keys = ["tong_diem", "diem_cao_nhat", "luc_cao_nhat", "so_gio_trong_top10"]
    _write(d / "su_kien.csv", [{**{k: e[k] for k in ("event_id", "ten", "nguon", "size", "n_sources", "sources",
                                                       "first_seen", "last_seen", "medoid_title")},
                                **{k: diem.get(e["event_id"], {}).get(k, "") for k in keys}} for e in ev],
           ["event_id", "ten", "nguon", "size", "n_sources", "sources", "first_seen", "last_seen", "medoid_title", *keys])
    _write(d / "ten_su_kien.csv", [{k: e[k] for k in ("event_id", "ten", "nguon", "ly_do_fallback", "ten_mo_hinh")}
                                   for e in ev], ["event_id", "ten", "nguon", "ly_do_fallback", "ten_mo_hinh"])
    manifest = {"run_id": run_id, "versions": {"model_version": "m_test", "algo_version": "v1",
                                               "naming_version": "n_test", "trend_version": "t2"},
                "config": {"trending": cfg, "export": {"latest_min_candidates": 1}}, "range": {"start": None, "end": None},
                "steps": {"trend": meta, "export": {"finished_at": "2026-11-03T16:37:12+00:00"}}}
    (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    rng = np.random.default_rng(0)
    ids = sorted(a.article_id for a in arts.values())
    E = rng.normal(size=(len(ids), 8)).astype(np.float32)
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    np.savez(d / "emb.npz", ids=np.array(ids), E=E, path="m_test", prep="pyvi")
    return d, {e["ten"]: e["event_id"] for e in ev}, dict(zip(ids, E, strict=True))


@pytest.fixture
def run(pg_conn, tmp_path):
    return make_run(tmp_path, pg_conn)


def _import(conn, d, **kw):
    return db_import.import_run(conn, d, embeddings=d / "emb.npz", log=lambda s: None, **kw)


def _count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_nap_run_ghi_du_cac_bang(pg_conn, run):
    d, eid, _ = run
    st = _import(pg_conn, d)
    assert (st["events"], st["event_articles"], st["event_names"], st["article_embeddings"]) == (4, 8, 4, 8)
    assert _count(pg_conn, "event_assignment_log") == 8
    assert _count(pg_conn, "trend_baselines") == 24
    r = pg_conn.execute("SELECT display_name, name_source, name_hidden, size, n_sources, sources, medoid_title, "
                        "category_std, algo_version, model_version FROM events WHERE event_id = %s",
                        (eid[PUBLIC],)).fetchone()
    assert r == (PUBLIC, "model", False, 3, 2, {"tuoitre": 2, "vnexpress": 1}, "Bài 1", "Thời sự", "v1", "m_test")
    medoid = pg_conn.execute("SELECT a.title FROM event_articles ea JOIN articles a USING (article_id) "
                             "WHERE ea.event_id = %s AND ea.is_medoid", (eid[PUBLIC],)).fetchall()
    assert medoid == [("Bài 1",)]
    run_row = pg_conn.execute("SELECT step, status, versions->>'run_id' FROM worker_runs").fetchall()
    assert run_row == [("import", "ok", "2026-11-03_test")]
    # sự kiện kết thúc > 48h trước bài muộn nhất của run (16/09 07:07) → closed
    status = dict(pg_conn.execute("SELECT event_id, status FROM events").fetchall())
    assert status[eid[PUBLIC]] == "closed" and status[eid["Giá xăng giảm từ chiều nay"]] == "open"


def test_ten_mo_hinh_bi_an_va_bi_loai_khong_nam_o_bang_nao(pg_conn, run):
    d, eid, _ = run
    _import(pg_conn, d)
    r = pg_conn.execute("SELECT display_name, name_source, name_hidden FROM events WHERE event_id = %s",
                        (eid[SECRET],)).fetchone()
    assert r == ("Bài 4", "medoid", True)
    names = pg_conn.execute("SELECT name, source, naming_version, checks FROM event_names WHERE event_id = %s",
                            (eid[SECRET],)).fetchall()
    assert names == [("Bài 4", "medoid", None, {"an_ten": True})]
    assert pg_conn.execute("SELECT checks FROM event_names WHERE event_id = %s",
                           (eid["Thông xe cầu ở Huế"],)).fetchone()[0] == {"ly_do_fallback": "khong_trung_thuc"}
    tables = [r[0] for r in pg_conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()]
    for tb in tables:
        dump = " ".join(r[0] for r in pg_conn.execute(f"SELECT t::text FROM {tb} t").fetchall()).lower()
        for w in SECRET_WORDS:
            assert w not in dump, f"{w} lọt vào bảng {tb}"


def test_diem_xu_huong_khop_file_cua_run_va_du_moi_ung_vien(pg_conn, run):
    d, _, _ = run
    _import(pg_conn, d)
    with open(d / "xu_huong.csv", encoding="utf-8") as f:
        ref = [(r["t"], int(r["hang"]), r["event_id"], float(r["score"])) for r in csv.DictReader(f)]
    got = pg_conn.execute("SELECT t, rank, event_id, score FROM trend_scores WHERE rank <= 20 ORDER BY t, rank").fetchall()
    assert len(got) == len(ref) > 0
    for (t, k, e, s), (rt, rk, re_, rs) in zip(got, ref, strict=True):
        assert (t, k, e) == (datetime.fromisoformat(rt), rk, re_)
        assert s == pytest.approx(rs, rel=1e-6)
    peak = pg_conn.execute("SELECT max(score) FROM trend_scores").fetchone()[0]
    assert pg_conn.execute("SELECT max(peak_score) FROM events").fetchone()[0] == pytest.approx(peak, rel=1e-6)


def test_vector_doc_lai_dung_va_similarity_trong_cum(pg_conn, run):
    d, eid, vec = run
    _import(pg_conn, d)
    rows = pg_conn.execute("SELECT e.article_id, e.vec, e.dim FROM article_embeddings e "
                           "JOIN articles a USING (article_id) WHERE e.content_hash = a.content_hash").fetchall()
    assert len(rows) == 8
    for aid, blob, dim in rows:
        assert dim == 8
        np.testing.assert_array_equal(np.frombuffer(blob, dtype="<f4"), vec[aid])
    sims = pg_conn.execute("SELECT similarity FROM event_articles WHERE event_id = %s",
                           (eid["Giá xăng giảm từ chiều nay"],)).fetchall()
    assert sims == [(None,)]                                    # sự kiện một bài: không có cosine trong cụm
    (a, sa), (b, sb) = pg_conn.execute("SELECT article_id, similarity FROM event_articles WHERE event_id = %s",
                                       (eid[SECRET],)).fetchall()     # 2 bài: similarity = cosine giữa hai bài
    assert sa == sb == pytest.approx(float(vec[a] @ vec[b]), abs=1e-6)


def test_nap_lai_cung_run_idempotent_run_khac_can_replace(pg_conn, run, tmp_path):
    d, _, _ = run
    _import(pg_conn, d)
    before = {tb: _count(pg_conn, tb) for tb in ("events", "event_articles", "event_names", "trend_scores")}
    _import(pg_conn, d)
    assert {tb: _count(pg_conn, tb) for tb in before} == before
    d2 = tmp_path / "2026-11-04_khac"
    d2.mkdir()
    for f in d.iterdir():
        (d2 / f.name).write_bytes(f.read_bytes())
    m = json.loads((d2 / "manifest.json").read_text(encoding="utf-8"))
    (d2 / "manifest.json").write_text(json.dumps({**m, "run_id": d2.name}), encoding="utf-8")
    with pytest.raises(db_import.RunImportError, match="--replace"):
        _import(pg_conn, d2)
    _import(pg_conn, d2, replace=True)
    assert {tb: _count(pg_conn, tb) for tb in before} == before
    assert pg_conn.execute("SELECT versions->>'run_id' FROM worker_runs ORDER BY run_id DESC LIMIT 1").fetchone()[0] \
        == d2.name


def test_bai_chua_co_trong_db_thi_dung_khong_ghi_gi(pg_conn, run):
    d, _, _ = run
    pg_conn.execute("DELETE FROM articles WHERE title = 'Bài 8'")
    with pytest.raises(db_import.RunImportError, match="1/8 bài"):
        _import(pg_conn, d)
    assert _count(pg_conn, "events") == 0 and _count(pg_conn, "worker_runs") == 0


def test_lech_xu_huong_thi_rollback_va_ghi_that_bai(pg_conn, run):
    d, _, _ = run
    with open(d / "xu_huong.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows[0]["score"] = str(float(rows[0]["score"]) + 1)
    _write(d / "xu_huong.csv", rows, list(rows[0]))
    with pytest.raises(db_import.RunImportError, match="lệch xu_huong.csv"):
        _import(pg_conn, d)
    assert _count(pg_conn, "events") == 0


def test_replace_khong_xoa_lan_sang_bang_ngoai_tro_vao_events(pg_conn, run, tmp_path):
    """Khi đã có bảng người dùng trỏ vào events (bookmark…), nạp run khác phải bị chặn, không xoá lan."""
    import psycopg
    d, eid, _ = run
    _import(pg_conn, d)
    pg_conn.execute("CREATE TABLE bookmark_thu (event_id text REFERENCES events (event_id))")
    pg_conn.execute("INSERT INTO bookmark_thu VALUES (%s)", (eid[PUBLIC],))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _import(pg_conn, d)
    assert _count(pg_conn, "events") == 4 and _count(pg_conn, "bookmark_thu") == 1


def test_nap_lai_khong_xoa_bookmark_nguoi_dung(pg_conn, run):
    """Migration 004 có FK thật: bảng rỗng cho nạp lại, bookmark có dữ liệu thì rollback."""
    import psycopg

    d, eid, _ = run
    _import(pg_conn, d)
    uid = pg_conn.execute(
        "INSERT INTO users (email, display_name, terms_accepted_at) "
        "VALUES ('reader@example.test', 'Reader', now()) RETURNING user_id"
    ).fetchone()[0]
    pg_conn.execute("INSERT INTO event_bookmarks (user_id,event_id) VALUES (%s,%s)",
                    (uid, eid[PUBLIC]))
    before = {tb: _count(pg_conn, tb) for tb in
              ("events", "event_articles", "event_names", "trend_scores")}
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _import(pg_conn, d)
    assert {tb: _count(pg_conn, tb) for tb in before} == before
    assert pg_conn.execute("SELECT user_id,event_id FROM event_bookmarks").fetchall() == [
        (uid, eid[PUBLIC])]
