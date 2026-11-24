"""Kiểm tra (đợt audit P1-api): route bắt-tất-cả của web React `/{full_path:path}` trong apps/api/main.py.

Không cần Postgres, không cần `make build`: dựng một thư mục dist giả trong tmp_path rồi trỏ WEB_DIST vào đó.
"""
import pytest
from fastapi.testclient import TestClient

from apps.api import main as M

INDEX = "<!doctype html><title>web</title>"


@pytest.fixture
def spa(store, tmp_path, monkeypatch):
    dist = tmp_path / "web" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "web" / "bi-mat.txt").write_text("BI-MAT-NGOAI-DIST", encoding="utf-8")
    monkeypatch.setattr(M, "WEB_DIST", dist)
    return TestClient(M.create_app(store), raise_server_exceptions=False)


def test_file_tinh_va_duong_dan_react(spa):
    assert spa.get("/robots.txt").text == "User-agent: *"
    assert spa.get("/assets/app.js").status_code == 200
    for path in ("/", "/su-kien/E20260913-aaaaaaaa", "/du-lieu/may-chu"):
        r = spa.get(path)
        assert r.status_code == 200 and r.text == INDEX, path


@pytest.mark.parametrize("path", [
    "/../bi-mat.txt", "/%2e%2e/bi-mat.txt", "/..%2Fbi-mat.txt", "/assets/../../bi-mat.txt",
    "/%2e%2e%2fbi-mat.txt", "/....//bi-mat.txt",
])
def test_khong_doc_duoc_file_ngoai_dist(spa, path):
    r = spa.get(path)
    assert "BI-MAT-NGOAI-DIST" not in r.text


def test_api_khong_ton_tai_tra_404_json_khong_phai_html(spa):
    r = spa.get("/api/khong-ton-tai")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
    assert spa.get("/api/rag/ask").status_code == 404          # route chỉ có POST: GET không rơi vào index.html


@pytest.mark.xfail(strict=True, reason="AUDIT-P1-api-12: '/api' (không có '/') rơi vào SPA → 200 index.html")
def test_api_khong_co_gach_cheo_khong_tra_html(spa):
    r = spa.get("/api")
    assert r.status_code == 404


@pytest.mark.xfail(strict=True, reason="AUDIT-P1-api-12: POST /api/khong-ton-tai trả 405 (route SPA chỉ GET) thay vì 404")
def test_post_api_khong_ton_tai_la_404(spa):
    assert spa.post("/api/khong-ton-tai", json={}).status_code == 404
