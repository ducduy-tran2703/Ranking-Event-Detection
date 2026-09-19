import pytest
from fastapi.testclient import TestClient

from apps.api.main import WEB_DIST, create_app


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


def test_moi_endpoint_du_lieu_deu_co_kieu_tra_ve(client):
    """Web React sinh kiểu từ OpenAPI: endpoint nào thiếu kiểu thì frontend mất kiểm tra kiểu."""
    paths = client.get("/openapi.json").json()["paths"]
    missing = []
    for path, ops in paths.items():
        for method, op in ops.items():
            schema = op["responses"]["200"]["content"]["application/json"]["schema"]
            if schema == {} or schema.get("additionalProperties") is True:
                missing.append(f"{method.upper()} {path}")
    assert missing == []


def test_do_tuoi_du_lieu_vua_nap_la_moi_nhat(client):
    body = client.get("/api/freshness").json()
    assert body["has_newer_data"] is False and body["newer_files"] == []
    assert body["loaded_at"] is not None and body["remote_latest_modified"] is not None


def test_nap_lai_tra_ve_thoi_diem_nap(client):
    body = client.post("/api/admin/reload").json()
    assert body["rows"] == 5 and body["loaded_at"]


def test_cac_thong_ke_khop_kieu_da_khai_bao(client):
    for path in ["/api/stats/timeline", "/api/stats/hour-of-day", "/api/stats/categories",
                 "/api/stats/quality", "/api/files"]:
        assert client.get(path).status_code == 200, path


def test_trang_kiem_soat_noi_bo_o_legacy(client):
    r = client.get("/legacy/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


@pytest.mark.skipif(not (WEB_DIST / "index.html").exists(),
                    reason="chưa chạy `make build` nên không có bản đóng gói web React")
def test_duong_dan_con_cua_web_react_tra_ve_index(store):
    """React tự định tuyến ở phía trình duyệt: mọi URL không phải API đều phải trả index.html."""
    c = TestClient(create_app(store))
    for path in ["/", "/quality", "/articles/khong-co-that"]:
        r = c.get(path)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"], path
    assert c.get("/api/khong-co").status_code == 404


def test_khong_dat_mat_khau_thi_khong_hoi_dang_nhap(client):
    assert client.get("/api/health").status_code == 200


def test_dat_mat_khau_thi_bat_buoc_dang_nhap(store, monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "nhom")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "mat-khau-manh")
    c = TestClient(create_app(store))

    assert c.get("/api/health").status_code == 401                      # chưa đăng nhập
    assert c.get("/api/health", auth=("nhom", "sai")).status_code == 401  # sai mật khẩu
    ok = c.get("/api/health", auth=("nhom", "mat-khau-manh"))
    assert ok.status_code == 200 and ok.json()["rows"] == 5
