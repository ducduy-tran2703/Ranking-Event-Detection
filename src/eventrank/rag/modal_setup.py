"""Deploy protected inference endpoints and export a client-only dotenv file.

No credentials are printed, forwarded into model containers, or included in images.
"""

import argparse
import importlib
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv, set_key

from eventrank.rag.models import ModelClient, embedding_version, load_model_config

CLIENT_KEYS = ("MODAL_PROXY_TOKEN_ID", "MODAL_PROXY_TOKEN_SECRET",
               "RAG_EMBEDDING_URL", "RAG_LLM_URL", "RAG_EMBEDDING_MODEL",
               "RAG_EMBEDDING_REVISION", "RAG_EMBEDDING_GPU", "RAG_LLM_MODEL",
               "RAG_LLM_REVISION", "RAG_LLM_GPU")


def export_client(path, values):
    """Export an explicit allowlist; never copy the owner's entire environment."""
    path = Path(path)
    path.write_text("# Inference only. Keep this file private.\n", encoding="utf-8")
    for key in CLIENT_KEYS:
        if values.get(key):
            set_key(str(path), key, values[key])


def _save(values):
    for key, value in values.items():
        set_key(".env", key, value)
        os.environ[key] = value


def configure_proxy_access(manager, token_id, environment):
    token = next((t for t in manager.list() if t.token_id == token_id), None)
    if token is None:
        raise ValueError("Configured proxy token is not present in this workspace")
    if token.scoped:
        manager.allow(token_id, environment)
    return "environment" if token.scoped else "workspace"


def deploy():
    import modal

    config = load_model_config()
    environment = os.getenv("MODAL_ENVIRONMENT", "main")
    if not all(os.getenv(k) for k in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")):
        raise ValueError("Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET in .env before deployment")
    root = Path(__file__).resolve().parents[3]
    import sys
    sys.path.insert(0, str(root))
    module = importlib.import_module("infra.modal_models")
    with modal.enable_output():
        module.app.deploy(environment_name=environment)
    urls = {}
    for key, name in (("RAG_EMBEDDING_URL", "embedding_service"), ("RAG_LLM_URL", "llm_service")):
        function = modal.Function.from_name(config["app_name"], name, environment_name=environment)
        urls[key] = function.get_web_url()
        if not urls[key]:
            raise RuntimeError(f"Missing URL for {name}")
    _save(urls)
    if not all(os.getenv(k) for k in ("MODAL_PROXY_TOKEN_ID", "MODAL_PROXY_TOKEN_SECRET")):
        workspace = modal.Workspace.from_context()
        token = workspace.proxy_tokens.create(name="eventrank-rag-clients")
        # Save immediately: token secrets cannot be fetched later.
        _save({"MODAL_PROXY_TOKEN_ID": token.token_id,
               "MODAL_PROXY_TOKEN_SECRET": token.token_secret})
    configure_proxy_access(modal.Workspace.from_context().proxy_tokens,
                           os.environ["MODAL_PROXY_TOKEN_ID"], environment)
    export_client(".env.client", os.environ)
    print("Deployment complete; URLs and proxy credentials saved to .env and .env.client.")


def cache_weights():
    import modal

    config = load_model_config()
    function = modal.Function.from_name(config["app_name"], "cache_weights",
                                        environment_name=os.getenv("MODAL_ENVIRONMENT", "main"))
    with modal.enable_output():
        result = function.remote()
    print(json.dumps({"cached": result}))


def smoke():
    client = ModelClient.from_env()
    config = client.config
    result = {"embedding_version": embedding_version(config["embedding"])}
    try:
        started = time.monotonic()
        for input_type in ("document", "query"):
            text = "Hà Nội là thủ đô Việt Nam." if input_type == "document" else "Thủ đô Việt Nam là gì?"
            vectors = client.embed([text], input_type=input_type)
            result[input_type] = {"vectors": len(vectors), "dimension": len(vectors[0])}
            print(f"Embedding {input_type}: {len(vectors)} vector, {len(vectors[0])} dimensions.",
                  flush=True)
        result["embedding_seconds"] = round(time.monotonic() - started, 2)
        started = time.monotonic()
        print("Calling Gemma chat completion...", flush=True)
        result["llm"] = client.chat([
            {"role": "system", "content": "Answer briefly in Vietnamese using only the evidence."},
            {"role": "user", "content": "Nguồn [1]: Hà Nội là thủ đô Việt Nam. "
             "Câu hỏi: Thủ đô Việt Nam là gì? Dẫn nguồn [1]."},
        ], max_tokens=128)
        if not result["llm"]["content"]:
            raise RuntimeError("LLM returned empty content")
        result["llm_seconds"] = round(time.monotonic() - started, 2)
    finally:
        client.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["deploy", "cache", "smoke"])
    args = parser.parse_args()
    load_dotenv(".env", override=True)
    {"deploy": deploy, "cache": cache_weights, "smoke": smoke}[args.action]()


if __name__ == "__main__":
    main()
