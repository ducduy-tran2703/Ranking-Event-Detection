"""Pinned model configuration and authenticated HTTP inference, independent of Modal SDK."""

import hashlib
import json
import math
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


def load_model_config(env=None):
    env = os.environ if env is None else env
    if env.get("EVENTRANK_MODEL_CONFIG"):
        config = json.loads(env["EVENTRANK_MODEL_CONFIG"])
    else:
        import yaml

        path = Path(__file__).resolve().parents[3] / "configs" / "rag.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))["models"]
    for name in ("embedding", "llm"):
        spec = config[name]
        prefix = f"RAG_{name.upper()}_"
        model = env.get(prefix + "MODEL", spec["model"])
        if model != spec["model"] and not env.get(prefix + "REVISION"):
            raise ValueError(f"Changing {prefix}MODEL requires {prefix}REVISION")
        spec["model"] = model
        spec["revision"] = env.get(prefix + "REVISION", spec["revision"])
        spec["gpu"] = env.get(prefix + "GPU", spec["gpu"])
        if not re.fullmatch(r"[0-9a-f]{40}", spec["revision"]):
            raise ValueError(f"{name}: revision must be a full commit SHA")
    return config


def embedding_version(spec):
    fields = {k: spec[k] for k in ("model", "revision", "dimension", "max_length", "instruction")}
    fields["pooling"] = "last-token-l2-v1"
    return "emb-" + hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:20]


def snapshot_path(spec):
    return f"/models/hf/hub/models--{spec['model'].replace('/', '--')}/snapshots/{spec['revision']}"


def llm_command(spec):
    return [
        "vllm", "serve", snapshot_path(spec), "--served-model-name", spec["model"],
        "--host", "0.0.0.0", "--port", "8000", "--max-model-len", str(spec["max_model_len"]),
        "--max-num-seqs", "1", "--gpu-memory-utilization", str(spec["gpu_memory_utilization"]),
        "--generation-config", "vllm", "--limit-mm-per-prompt", '{"image":0,"audio":0,"video":0}',
    ] + (
        # Parser gemma4 có sẵn từ vLLM 0.33.0. Giữ chat template của model (đã hỗ trợ tool) để
        # GemmaTokenCounter phía client đếm đúng cùng template với server.
        ["--enable-auto-tool-choice", "--tool-call-parser", "gemma4"] if spec.get("tool_calling") else []
    )


def _check_vectors(vectors, count, dimension):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError("Embedding response count mismatch")
    for vector in vectors:
        if len(vector) != dimension or any(not math.isfinite(x) for x in vector):
            raise ValueError("Embedding response dimension or finite-value mismatch")
        if not math.isclose(sum(x * x for x in vector), 1.0, abs_tol=0.02):
            raise ValueError("Embedding is not L2 normalized")


@contextmanager
def keep_alive(ping, *, interval, max_seconds):
    """Ping while the body runs, then once on exit so the idle timer restarts from that moment.

    A failed ping never affects the body. max_seconds caps GPU spend if the body hangs,
    and pings stop by themselves when this process dies.
    """
    stats = {"pings": 0, "failures": 0}
    stop = threading.Event()
    deadline = time.monotonic() + max_seconds

    def send():
        try:
            alive = ping()
        except Exception:  # noqa: BLE001 -- best effort; never surface client errors
            alive = False
        stats["pings"] += 1
        stats["failures"] += not alive

    def loop():
        while not stop.wait(interval) and time.monotonic() < deadline:
            send()

    worker = threading.Thread(target=loop, name="model-keepalive", daemon=True)
    worker.start()
    try:
        yield stats
    finally:
        stop.set()
        worker.join()
        if time.monotonic() < deadline:
            send()


class ModelClient:
    def __init__(self, *, embedding_url="", llm_url="", proxy_id="", proxy_secret="",
                 config=None, transport=None):
        self.config = load_model_config() if config is None else config
        self.embedding_url = embedding_url.rstrip("/")
        self.llm_url = llm_url.rstrip("/")
        for url in (self.embedding_url, self.llm_url):
            if url:
                parsed = urlsplit(url)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query:
                    raise ValueError("Inference URL must be HTTPS without credentials or query")
        if not proxy_id or not proxy_secret:
            raise ValueError("Missing Modal proxy credentials")
        self._http = httpx.Client(
            headers={"Modal-Key": proxy_id, "Modal-Secret": proxy_secret},
            timeout=httpx.Timeout(600, connect=30), trust_env=False, follow_redirects=False,
            transport=transport if transport is not None else httpx.HTTPTransport(retries=2),
        )

    @classmethod
    def from_env(cls):
        return cls(embedding_url=os.getenv("RAG_EMBEDDING_URL", ""),
                   llm_url=os.getenv("RAG_LLM_URL", ""),
                   proxy_id=os.getenv("MODAL_PROXY_TOKEN_ID", ""),
                   proxy_secret=os.getenv("MODAL_PROXY_TOKEN_SECRET", ""))

    def close(self):
        self._http.close()

    def _post(self, base, path, payload):
        if not base:
            raise ValueError("Inference URL is not configured")
        try:
            deadline = time.monotonic() + 900
            response = self._http.post(base + path, json=payload)
            # Modal returns a same-origin result URL after 150s, including during cold starts.
            # Poll that URL without resubmitting the inference or leaking headers to another host.
            for _ in range(6):
                if response.status_code != 303:
                    break
                location = response.headers.get("Location")
                target = urljoin(str(response.url), location or "")
                original, redirected = urlsplit(base), urlsplit(target)
                if (not location or redirected.scheme != "https"
                        or redirected.netloc != original.netloc):
                    raise RuntimeError("Refusing model redirect outside the configured origin")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Model service exceeded cold-start deadline")
                response = self._http.get(target, timeout=min(600, remaining))
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Model service connection failed ({type(exc).__name__})") from None
        if response.status_code != 200:
            raise RuntimeError(f"Model service returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise RuntimeError("Model service returned invalid JSON") from None

    def ping_embedding(self):
        """Reset the embedding container's idle timer; report failure instead of raising."""
        if not self.embedding_url:
            return False
        try:
            return self._http.get(self.embedding_url + "/health", timeout=15).status_code == 200
        except httpx.HTTPError:
            return False

    def embed(self, texts, *, input_type="document"):
        if input_type not in ("query", "document") or not texts or len(texts) > 32:
            raise ValueError("Expected 1..32 texts and query/document input_type")
        spec = self.config["embedding"]
        body = self._post(self.embedding_url, "/embed", {
            "model": spec["model"], "texts": texts, "input_type": input_type,
        })
        expected = {"model": spec["model"], "revision": spec["revision"],
                    "embedding_version": embedding_version(spec), "dimension": spec["dimension"]}
        if any(body.get(k) != v for k, v in expected.items()):
            raise ValueError("Embedding service version mismatch; reindex before switching models")
        vectors = body.get("vectors")
        _check_vectors(vectors, len(texts), spec["dimension"])
        return vectors

    def chat(self, messages, *, max_tokens=None, response_schema=None, temperature=0.2,
             tools=None, tool_choice=None):
        spec = self.config["llm"]
        max_tokens = spec["max_output_tokens"] if max_tokens is None else max_tokens
        if not 1 <= max_tokens <= spec["max_output_tokens"]:
            raise ValueError("Output token limit exceeds configured maximum")
        if not isinstance(temperature, (int, float)) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError('temperature must be finite and between 0 and 2')
        payload = {
            "model": spec["model"], "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "stream": False,
            "add_special_tokens": False, "add_generation_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if tools is not None and response_schema is not None:
            # Lượt gọi tool và lượt trả lời JSON cuối là hai request riêng (tài liệu vLLM không bảo đảm kết hợp).
            raise ValueError('tools and response_schema cannot be combined in one request')
        if tools is not None:
            payload['tools'] = tools
            if tool_choice is not None:
                payload['tool_choice'] = tool_choice
        if response_schema is not None:
            if not isinstance(response_schema, dict):
                raise ValueError('response_schema must be a JSON schema dictionary')
            payload['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'grounded_news_answer', 'strict': True, 'schema': response_schema}}
        body = self._post(self.llm_url, "/v1/chat/completions", payload)
        choice = body["choices"][0]
        message = choice["message"]
        content = _THOUGHT.sub("", message.get("content") or "", count=1)
        return {"content": content, "finish_reason": choice["finish_reason"],
                "usage": body.get("usage", {}), "tool_calls": _parse_tool_calls(message.get("tool_calls"))}


# Template Gemma 4 có thể mở đầu câu trả lời bằng kênh suy nghĩ (rỗng khi enable_thinking=False). Lọc ở client
# thay vì bật --reasoning-parser: không đổi hành vi server với structured output của pipeline snapshot.
_THOUGHT = re.compile(r"\A\s*<\|channel>thought.*?<channel\|>\s*", re.DOTALL)


def _parse_tool_calls(raw):
    """OpenAI tool_calls → [{id, name, arguments: dict, error}]; đối số hỏng không ném lỗi, để vòng tool báo lại model."""
    calls = []
    for item in raw or []:
        function = item.get("function") or {}
        arguments, error = {}, None
        try:
            parsed = json.loads(function.get("arguments") or "{}")
        except (TypeError, ValueError):
            error = "invalid_json_arguments"
        else:
            if isinstance(parsed, dict):
                arguments = parsed
            else:
                error = "arguments_not_object"
        calls.append({"id": str(item.get("id") or ""), "name": str(function.get("name") or ""),
                      "arguments": arguments, "error": error})
    return calls


class EmbedRequest(BaseModel):
    model: str
    texts: Annotated[list[Annotated[str, Field(min_length=1, max_length=40000)]],
                     Field(min_length=1, max_length=32)]
    input_type: Literal["query", "document"] = "document"


class EmbedResponse(BaseModel):
    model: str
    revision: str
    embedding_version: str
    dimension: int
    vectors: list[list[float]]
    token_counts: list[int]


def create_embedding_api(spec, encoder):
    api = FastAPI(title="Eventrank embedding", docs_url=None, redoc_url=None)

    @api.get("/health")
    def health():
        return {"status": "ok"}

    @api.post("/embed", response_model=EmbedResponse)
    def embed(request: EmbedRequest):
        if request.model != spec["model"]:
            raise HTTPException(409, "Requested model differs from deployment")
        try:
            vectors, counts = encoder(request.texts, request.input_type)
        except ValueError:
            raise HTTPException(413, "Input exceeds embedding token limit") from None
        _check_vectors(vectors, len(request.texts), spec["dimension"])
        return EmbedResponse(model=spec["model"], revision=spec["revision"],
                             embedding_version=embedding_version(spec), dimension=spec["dimension"],
                             vectors=vectors, token_counts=counts)

    return api
