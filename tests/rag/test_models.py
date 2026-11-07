import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from eventrank.rag.models import (
    ModelClient,
    create_embedding_api,
    embedding_version,
    llm_command,
    load_model_config,
)


def test_config_model_revision_va_version_embedding():
    cfg = load_model_config(env={})
    assert cfg["embedding"]["model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert len(cfg["embedding"]["revision"]) == 40
    v = embedding_version(cfg["embedding"])
    assert v
    changed = copy.deepcopy(cfg["embedding"])
    changed["instruction"] += " Different task."
    assert embedding_version(changed) != v
    with pytest.raises(ValueError):
        load_model_config(env={"RAG_EMBEDDING_MODEL": "other/model"})


def test_llm_args_pin_revision_context_va_single_sequence():
    cfg = load_model_config(env={})
    args = llm_command(cfg["llm"])
    assert args[:2] == ["vllm", "serve"]
    assert "--served-model-name" in args and cfg["llm"]["model"] in args
    assert args[args.index("--max-num-seqs") + 1] == "1"
    assert args[args.index("--max-model-len") + 1] == "8192"


def _spec():
    return {"model": "sample/model", "revision": "a" * 40, "dimension": 3,
            "max_length": 16, "batch_size": 2, "instruction": "Retrieve news."}


def test_embedding_api_routes_va_tu_choi_input_qua_dai():
    def encode(texts, input_type):
        if any(len(t) > 10 for t in texts):
            raise ValueError("Input exceeds max_length")
        return [[1.0, 0.0, 0.0] for _ in texts], [4] * len(texts)

    client = TestClient(create_embedding_api(_spec(), encode))
    body = {"texts": ["Tin mới"], "input_type": "query", "model": "sample/model"}
    r = client.post("/embed", json=body)
    assert r.status_code == 200
    assert r.json()["vectors"] == [[1.0, 0.0, 0.0]]
    assert r.json()["embedding_version"] == embedding_version(_spec())
    assert client.post("/embed", json={**body, "model": "wrong"}).status_code == 409
    assert client.post("/embed", json={**body, "texts": []}).status_code == 422
    assert client.post("/embed", json={**body, "texts": ["x" * 20]}).status_code == 413


def test_http_client_gui_proxy_khong_gui_admin_va_kiem_vector_version():
    cfg = {"embedding": _spec(), "llm": {"model": "sample/llm", "max_output_tokens": 20}}

    def handler(request):
        assert request.headers["Modal-Key"] == "wk-test"
        assert request.headers["Modal-Secret"] == "ws-test-secret"
        assert "ak-admin" not in request.content.decode()
        payload = json.loads(request.content)
        if request.url.path == "/embed":
            assert payload["input_type"] == "document"
            return httpx.Response(200, json={"model": "sample/model", "revision": "a" * 40,
                "embedding_version": embedding_version(_spec()), "dimension": 3,
                "vectors": [[1.0, 0.0, 0.0]], "token_counts": [4]})
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        return httpx.Response(200, json={"choices": [{"message": {"content": "Có nguồn."},
                                                    "finish_reason": "stop"}], "usage": {}})

    client = ModelClient(embedding_url="https://embedding.modal.run", llm_url="https://llm.modal.run",
                         proxy_id="wk-test", proxy_secret="ws-test-secret", config=cfg,
                         transport=httpx.MockTransport(handler))
    assert "ws-test-secret" not in repr(client)
    assert client.embed(["Tin mới"]) == [[1.0, 0.0, 0.0]]
    assert client.chat([{"role": "user", "content": "Tin gì?"}])["content"] == "Có nguồn."


def test_client_tu_choi_vector_sai_dimension_va_loi_khong_lo_key():
    cfg = {"embedding": _spec(), "llm": {"model": "sample/llm", "max_output_tokens": 20}}
    response = {"model": "sample/model", "revision": "a" * 40,
                "embedding_version": embedding_version(_spec()), "dimension": 3,
                "vectors": [[1.0, 0.0]], "token_counts": [4]}
    client = ModelClient(embedding_url="https://embedding.modal.run", proxy_id="wk-test",
                         proxy_secret="ws-private", config=cfg,
                         transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response)))
    with pytest.raises(ValueError):
        client.embed(["Tin"])
    denied = ModelClient(embedding_url="https://embedding.modal.run", proxy_id="wk-test",
                         proxy_secret="ws-private", config=cfg,
                         transport=httpx.MockTransport(lambda r: httpx.Response(403, text="ws-private")))
    with pytest.raises(RuntimeError) as exc:
        denied.embed(["Tin"])
    assert "ws-private" not in str(exc.value)


def test_modal_cold_start_303_chi_theo_redirect_cung_origin():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(303, headers={"Location": "/embed?result=example"})
        return httpx.Response(200, json={"ok": True})

    client = ModelClient(proxy_id="wk-example", proxy_secret="ws-example",
                         transport=httpx.MockTransport(handler))
    assert client._post("https://example.modal.run", "/embed", {}) == {"ok": True}
    assert [r.method for r in requests] == ["POST", "GET"]


def test_redirect_khac_host_khong_nhan_proxy_token():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(303, headers={"Location": "https://other.example/private"})

    client = ModelClient(proxy_id="wk-example", proxy_secret="ws-example",
                         transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        client._post("https://example.modal.run", "/embed", {})
    assert len(requests) == 1


def test_chat_requests_schema_and_deterministic_generation():
    from eventrank.rag.generation import output_schema

    schema = output_schema()

    def handler(request):
        payload = json.loads(request.content)
        assert payload['temperature'] == 0.0
        assert payload['add_special_tokens'] is False
        assert payload['response_format']['json_schema']['schema'] == schema
        assert payload['response_format']['json_schema']['strict'] is True
        return httpx.Response(200, json={'choices': [{'message': {'content': '{}'},
                                                    'finish_reason': 'stop'}]})

    client = ModelClient(llm_url='https://example.modal.run', proxy_id='test', proxy_secret='test',
                         transport=httpx.MockTransport(handler))
    try:
        client.chat([{'role': 'user', 'content': 'test'}], response_schema=schema, temperature=0.0)
    finally:
        client.close()
