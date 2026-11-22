import re
import threading
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from eventrank.rag import models as rag_models


def _spec():
    return {"model": "sample/model", "revision": "a" * 40, "dimension": 3,
            "max_length": 16, "batch_size": 2, "instruction": "Retrieve news."}


def _client(handler, url="https://embedding.modal.run"):
    return rag_models.ModelClient(embedding_url=url, proxy_id="wk-test", proxy_secret="ws-private",
                                  config={"embedding": _spec()}, transport=httpx.MockTransport(handler))


def test_cau_hinh_tat_sau_120_giay_va_gioi_han_keepalive():
    cfg = rag_models.load_model_config(env={})
    assert cfg["scaledown_window"] == 120
    assert 0 < cfg["keepalive"]["interval_seconds"] < cfg["scaledown_window"]
    assert cfg["keepalive"]["max_seconds"] == 900


def test_ca_hai_service_modal_dung_scaledown_trong_cau_hinh():
    source = Path("infra/modal_models.py").read_text("utf-8")
    assert len(re.findall(r'scaledown_window=CONFIG\["scaledown_window"\]', source)) == 2
    assert "scaledown_window=60" not in source


def test_health_khong_chay_encoder():
    def encode(texts, input_type):
        raise AssertionError("health must not use the GPU encoder")

    response = TestClient(rag_models.create_embedding_api(_spec(), encode)).get("/health")
    assert response.status_code == 200


def test_ping_embedding_goi_health_co_proxy_auth():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "ok"})

    assert _client(handler).ping_embedding() is True
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/health")]
    assert seen[0].headers["Modal-Key"] == "wk-test"


def test_ping_loi_chi_tra_false_khong_nem_loi():
    def refused(request):
        raise httpx.ConnectError("ws-private unreachable")

    assert _client(refused).ping_embedding() is False
    assert _client(lambda r: httpx.Response(503)).ping_embedding() is False
    assert _client(lambda r: httpx.Response(200), url="").ping_embedding() is False


def test_keep_alive_ping_dinh_ky_trong_luc_cho():
    calls = []
    enough = threading.Event()

    def ping():
        calls.append(time.monotonic())
        if len(calls) >= 2:
            enough.set()
        return True

    with rag_models.keep_alive(ping, interval=0.01, max_seconds=30) as stats:
        assert enough.wait(5)
    assert stats["pings"] == len(calls) and stats["failures"] == 0


def test_keep_alive_ping_lan_cuoi_ngay_khi_ket_thuc():
    calls = []
    with rag_models.keep_alive(lambda: calls.append(1) or True, interval=60, max_seconds=30):
        assert calls == []
    assert calls == [1]


def test_keep_alive_ping_lan_cuoi_ca_khi_gemma_loi():
    calls = []
    try:
        with rag_models.keep_alive(lambda: calls.append(1) or True, interval=60, max_seconds=30):
            raise RuntimeError("generation failed")
    except RuntimeError:
        pass
    assert calls == [1]


def test_keep_alive_dung_han_khi_qua_gioi_han_cung():
    calls = []
    with rag_models.keep_alive(lambda: calls.append(1) or True, interval=0.01, max_seconds=0.05):
        time.sleep(0.3)
        settled = len(calls)
        time.sleep(0.1)
        assert len(calls) == settled
    assert len(calls) == settled


def test_keep_alive_ping_loi_khong_lam_hong_cau_tra_loi():
    def ping():
        raise RuntimeError("ws-private")

    with rag_models.keep_alive(ping, interval=60, max_seconds=30) as stats:
        pass
    assert stats == {"pings": 1, "failures": 1}
