"""Pinned model configuration and authenticated HTTP inference, independent of Modal SDK."""

import hashlib
import json
import math
import os
import re
import time
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
        "--enforce-eager",
    ]


def _check_vectors(vectors, count, dimension):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError("Embedding response count mismatch")
    for vector in vectors:
        if len(vector) != dimension or any(not math.isfinite(x) for x in vector):
            raise ValueError("Embedding response dimension or finite-value mismatch")
        if not math.isclose(sum(x * x for x in vector), 1.0, abs_tol=0.02):
            raise ValueError("Embedding is not L2 normalized")


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

    def chat(self, messages, *, max_tokens=None, response_schema=None, temperature=0.2):
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
        if response_schema is not None:
            if not isinstance(response_schema, dict):
                raise ValueError('response_schema must be a JSON schema dictionary')
            payload['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'grounded_news_answer', 'strict': True, 'schema': response_schema}}
        body = self._post(self.llm_url, "/v1/chat/completions", payload)
        choice = body["choices"][0]
        return {"content": choice["message"].get("content", ""),
                "finish_reason": choice["finish_reason"], "usage": body.get("usage", {})}


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
