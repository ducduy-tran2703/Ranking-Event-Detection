"""Nhập mô hình fine-tune tải từ Kaggle về data/models/<tag>_<ngày>/ (gitignored), rồi in lệnh so với mô hình gốc.

    .venv/bin/python training/import_kaggle_run.py ~/Downloads/best_model_bkai-v4-cosent-s44.zip
    .venv/bin/python training/import_kaggle_run.py ~/Downloads/output/        # cả thư mục Output → mọi seed

Đầu vào: file `best_model_<tag>.zip` (ô cuối notebook) hoặc thư mục chứa `models/<tag>/`. File `results_*.json`
nằm cạnh (hoặc truyền `--results`) được chép vào từng thư mục mô hình — số đo đi cùng trọng số.
Không ghi đè thư mục đã có.
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "data/models"
NEED = ("model.safetensors", "config_sentence_transformers.json", "modules.json")


def find_models(root: Path) -> list[Path]:
    """Mọi thư mục SentenceTransformer đủ file dưới root (bỏ checkpoints/ trung gian)."""
    return sorted(p.parent for p in root.rglob("model.safetensors")
                  if all((p.parent / f).exists() for f in NEED) and "checkpoints" not in p.parts)


def compare_arg(model_dir: Path) -> str:
    prep = "query" if "e5" in model_dir.name.lower() else "pyvi"
    return f"{model_dir.name}={model_dir.relative_to(ROOT) if model_dir.is_relative_to(ROOT) else model_dir}:{prep}"


def import_run(src: str | Path, models_dir: str | Path = MODELS, results: str | Path | None = None,
               stamp: str | None = None) -> list[Path]:
    src, models_dir = Path(src).expanduser(), Path(models_dir)
    stamp = stamp or datetime.now(timezone(timedelta(hours=7))).date().isoformat()     # giờ VN
    results = Path(results) if results else None
    if results is None:
        near = sorted((src.parent if src.is_file() else src).glob("results_*.json"))
        results = near[0] if near else None
    with tempfile.TemporaryDirectory() as tmp:
        root = src
        if src.is_file():
            with zipfile.ZipFile(src) as z:
                z.extractall(tmp)                          # zipfile bỏ phần ".." và "/" đầu đường dẫn
            root = Path(tmp)
        found = find_models(root)
        if not found:
            raise FileNotFoundError(f"không thấy thư mục mô hình (cần {', '.join(NEED)}) trong {src}")
        dests = [models_dir / f"{m.name}_{stamp}" for m in found]
        if clash := [d for d in dests if d.exists()]:
            raise FileExistsError(f"đã có, không ghi đè: {', '.join(map(str, clash))}")
        for m, d in zip(found, dests):
            shutil.copytree(m, d)
            if results:
                shutil.copy2(results, d / results.name)
    return dests


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src", help="best_model_<tag>.zip hoặc thư mục Output của Kaggle")
    ap.add_argument("--results", help="results_*.json (mặc định: tìm cạnh src)")
    ap.add_argument("--models-dir", default=str(MODELS))
    a = ap.parse_args()
    dests = import_run(a.src, a.models_dir, a.results)
    for d in dests:
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6
        print(f"→ {d}  ({size:.0f} MB){'' if any(d.glob('results_*.json')) else '  ⚠️ chưa kèm results_*.json'}")
    print("\nSo với mô hình gốc:\n  make compare ARGS='" + " ".join(f"--model {compare_arg(d)}" for d in dests) + "'")


if __name__ == "__main__":
    main()
