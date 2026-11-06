"""Modal hosts inference only; article data and indexes stay on the local machine.

Deploy through: python -m eventrank.rag.modal_setup deploy
"""

import json
import socket
import subprocess
import time

import modal

from eventrank.rag.models import (
    create_embedding_api,
    llm_command,
    load_model_config,
    snapshot_path,
)

CONFIG = load_model_config()
app = modal.App(CONFIG["app_name"])
cache = modal.Volume.from_name(CONFIG["cache_volume"], create_if_missing=True, version=2)
ENV = {
    "EVENTRANK_MODEL_CONFIG": json.dumps(CONFIG),
    "HF_HOME": "/models/hf",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_XET": "1",
    "TOKENIZERS_PARALLELISM": "false",
}
base = modal.Image.debian_slim(python_version="3.12").uv_pip_install(
    "fastapi==0.135.2", "httpx==0.28.1", "pyyaml==6.0.3", "python-dotenv==1.2.2",
)
cache_image = base.uv_pip_install("huggingface-hub==0.36.0").add_local_python_source("eventrank")
embedding_image = (
    base.uv_pip_install("torch==2.8.0", "sentence-transformers==6.2.0",
                        "transformers==5.22.1", "fastapi==0.135.2", "pyyaml==6.0.3")
    .add_local_python_source("eventrank")
)
llm_image = (
    # FlashInfer JIT needs nvcc and CUDA headers, which PyTorch runtime wheels do not provide.
    modal.Image.from_registry("nvidia/cuda:13.0.2-devel-ubuntu24.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install("vllm==0.33.0", "pyyaml==6.0.3", "python-dotenv==1.2.2", "httpx==0.28.1")
    .add_local_python_source("eventrank")
)


@app.function(image=cache_image, env=ENV, volumes={"/models": cache},
              cpu=4, memory=8192, timeout=1800, max_containers=1)
def cache_weights():
    from pathlib import Path

    from huggingface_hub import snapshot_download

    result = {}
    for name in ("embedding", "llm"):
        spec = CONFIG[name]
        # Xet may leave a nonsequential partial file. Restart that file for HTTP downloads.
        repo_cache = Path("/models/hf/hub") / ("models--" + spec["model"].replace("/", "--"))
        restart_partial = any((repo_cache / "blobs").glob("*.incomplete"))
        snapshot_download(repo_id=spec["model"], revision=spec["revision"],
                          cache_dir="/models/hf/hub",
                          force_download=restart_partial,
                          allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt",
                                          "*.jinja", "*.tiktoken"])
        result[name] = {"model": spec["model"], "revision": spec["revision"]}
        cache.commit()
    return result


@app.function(image=embedding_image, gpu=CONFIG["embedding"]["gpu"], env=ENV,
              volumes={"/models": cache}, cpu=2, memory=8192, min_containers=0,
              max_containers=CONFIG["embedding"].get("max_containers", 1),
              buffer_containers=CONFIG["embedding"].get("buffer_containers", 0),
              scaledown_window=60, timeout=600, startup_timeout=600)
@modal.concurrent(max_inputs=1)
@modal.asgi_app(requires_proxy_auth=True)
def embedding_service():
    import torch
    from sentence_transformers import SentenceTransformer

    spec = CONFIG["embedding"]
    model = SentenceTransformer(snapshot_path(spec), device="cuda", local_files_only=True,
                                model_kwargs={"torch_dtype": torch.float16},
                                tokenizer_kwargs={"padding_side": "left"})
    model.max_seq_length = spec["max_length"]

    def encode(texts, input_type):
        prefix = f"Instruct: {spec['instruction']}\nQuery: " if input_type == "query" else ""
        rendered = [prefix + text for text in texts]
        tokens = model.tokenizer(rendered, truncation=False, padding=False)["input_ids"]
        counts = [len(ids) for ids in tokens]
        if max(counts) > spec["max_length"]:
            raise ValueError("Input exceeds max_length; split the input before embedding")
        vectors = model.encode(texts, prompt=prefix, batch_size=spec["batch_size"],
                               normalize_embeddings=True, convert_to_numpy=True,
                               show_progress_bar=False)
        return vectors.tolist(), counts

    return create_embedding_api(spec, encode)


@app.function(image=llm_image, gpu=CONFIG["llm"]["gpu"], env=ENV,
              volumes={"/models": cache}, cpu=4, memory=32768, min_containers=0,
              max_containers=1, scaledown_window=60, timeout=600, startup_timeout=900)
@modal.web_server(8000, startup_timeout=840, requires_proxy_auth=True)
def llm_service():
    process = subprocess.Popen(llm_command(CONFIG["llm"]))
    deadline = time.monotonic() + 800
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"vLLM exited during startup (code {process.returncode}); see container logs")
        try:
            with socket.create_connection(("127.0.0.1", 8000), timeout=1):
                return
        except OSError:
            time.sleep(1)
    process.terminate()
    raise TimeoutError("vLLM did not open its inference port before startup deadline")
