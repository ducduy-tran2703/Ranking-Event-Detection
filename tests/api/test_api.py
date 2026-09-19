import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture(scope="module")
def client(store):
    return TestClient(create_app(store))


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["rows"] == 5


def test_meta_cho_biet_nguon_du_lieu(client):
    assert client.get("/api/meta").json()["dataset"].startswith("local:")


def test_mo_ta_cau_hinh_khong_chua_khoa():
    from eventrank.common.config import LakeConfig
    cfg = LakeConfig(backend="r2", bucket="bkt", silver_glob="silver/*/*.jsonl", local_root="",
                     account_id="ACC-123", access_key_id="AKID-456", secret_access_key="SEC-789")
    text = cfg.describe()
    assert text == "r2://bkt/silver/*/*.jsonl"
    assert not any(v in text for v in ("ACC-123", "AKID-456", "SEC-789"))


def test_tong_quan_theo_nguon(client):
    per = {r["source"]: r for r in client.get("/api/stats/overview").json()["per_source"]}
    assert per["vnexpress"]["articles"] == 3 and per["baochinhphu"]["articles"] == 2


def test_duyet_bai_voi_bo_loc(client):
    r = client.get("/api/articles", params={"source": "BAOCHINHPHU", "issue": "empty_content"})
    assert r.status_code == 200
    assert [i["article_id"] for i in r.json()["items"]] == ["b2"]


def test_chi_tiet_bai_va_404(client):
    assert client.get("/api/articles/a1").json()["n_words"] == 300
    assert client.get("/api/articles/khong-co").status_code == 404


@pytest.mark.parametrize("path,params", [
    ("/api/articles", {"sort": "bad"}),
    ("/api/articles", {"issue": "bad"}),
    ("/api/stats/timeline", {"granularity": "minute"}),
])
def test_tham_so_sai_tra_ve_400(client, path, params):
    assert client.get(path, params=params).status_code == 400


def test_ngay_sai_dinh_dang_bi_tu_choi(client):
    assert client.get("/api/articles", params={"date_from": "16/09/2026"}).status_code == 422


def test_trang_giao_dien_duoc_phuc_vu(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
