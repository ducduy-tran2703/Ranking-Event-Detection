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
    # Eager mode keeps ~19 token/s; compile cost at cold start is accepted for the demo.
    assert "--enforce-eager" not in args


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


# ---------------------------------------------------------------- tool calling (vLLM parser gemma4)
def test_llm_bat_tool_parser_gemma4_khi_cau_hinh_bat():
    cfg = load_model_config(env={})
    spec = {**cfg["llm"], "tool_calling": True}
    args = llm_command(spec)
    assert "--enable-auto-tool-choice" in args
    assert args[args.index("--tool-call-parser") + 1] == "gemma4"
    # Giữ chat template của model: bộ đếm token phía client dùng đúng template đó.
    assert "--chat-template" not in args
    assert "--tool-call-parser" not in llm_command({**cfg["llm"], "tool_calling": False})


_TOOLS = [{"type": "function", "function": {"name": "corpus_info", "description": "Phạm vi kho.",
                                            "parameters": {"type": "object", "properties": {}}}}]


def _tool_client(response, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response)

    return ModelClient(llm_url='https://example.modal.run', proxy_id='test', proxy_secret='test',
                       transport=httpx.MockTransport(handler))


def test_chat_gui_tools_va_tra_tool_calls_da_parse():
    seen = []
    response = {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "count_articles", "arguments": "{\"source\": \"vnexpress\"}"}}]}}],
        "usage": {"prompt_tokens": 10}}
    client = _tool_client(response, seen)
    try:
        out = client.chat([{"role": "user", "content": "x"}], tools=_TOOLS, tool_choice="auto", temperature=0.0)
    finally:
        client.close()
    assert seen[0]["tools"] == _TOOLS and seen[0]["tool_choice"] == "auto"
    assert "response_format" not in seen[0]
    assert out["content"] == "" and out["finish_reason"] == "tool_calls"
    assert out["tool_calls"] == [{"id": "call_1", "name": "count_articles", "arguments": {"source": "vnexpress"},
                                  "error": None}]


def test_chat_tool_call_doi_so_hong_khong_nem_loi_ma_ghi_error():
    seen = []
    response = {"choices": [{"finish_reason": "tool_calls", "message": {"content": "", "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": "x", "arguments": "{khong phai json"}},
        {"id": "d", "type": "function", "function": {"name": "y", "arguments": "[1, 2]"}}]}}]}
    client = _tool_client(response, seen)
    try:
        out = client.chat([{"role": "user", "content": "x"}], tools=_TOOLS)
    finally:
        client.close()
    assert [c["error"] for c in out["tool_calls"]] == ["invalid_json_arguments", "arguments_not_object"]
    assert all(c["arguments"] == {} for c in out["tool_calls"])


def test_chat_khong_tools_van_tra_tool_calls_rong():
    seen = []
    client = _tool_client({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}, seen)
    try:
        out = client.chat([{"role": "user", "content": "x"}])
    finally:
        client.close()
    assert out["tool_calls"] == [] and "tools" not in seen[0]


def test_chat_khong_cho_vua_tools_vua_response_schema():
    client = _tool_client({}, [])
    try:
        with pytest.raises(ValueError):
            client.chat([{"role": "user", "content": "x"}], tools=_TOOLS, response_schema={"type": "object"})
    finally:
        client.close()


def test_bo_kenh_suy_nghi_rong_cua_gemma_khoi_noi_dung():
    # Gặp thật 22/11: khi không gọi tool, content mở đầu bằng kênh suy nghĩ rỗng của template Gemma 4.
    seen = []
    raw = '<|channel>thought\n<channel|>Tôi xin lỗi, nhưng tôi không tìm thấy bài báo nào.'
    client = _tool_client({"choices": [{"finish_reason": "stop", "message": {"content": raw}}]}, seen)
    try:
        out = client.chat([{"role": "user", "content": "x"}], tools=_TOOLS)
    finally:
        client.close()
    assert out["content"] == 'Tôi xin lỗi, nhưng tôi không tìm thấy bài báo nào.'


def test_giu_nguyen_noi_dung_khong_co_kenh_suy_nghi():
    seen = []
    client = _tool_client({"choices": [{"finish_reason": "stop", "message": {"content": '{"a": "<|x>"}'}}]}, seen)
    try:
        assert client.chat([{"role": "user", "content": "x"}])["content"] == '{"a": "<|x>"}'
    finally:
        client.close()
