"""Script upload bundle RAG snapshot (Postgres dump, Qdrant snapshot, BM25 zip) lên Cloudflare R2.

Yêu cầu trong .env phải có R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY có quyền Object Read & Write.
"""

import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

R2_BUCKET = os.environ.get("R2_BUCKET", "vietnam-news-datalake")
PREFIX = "rag_NguyenDinhHieu/v1/"

FILES_TO_UPLOAD = [
    {
        "local_path": REPO_ROOT / "data/db_dump/eventrank_rag_20261107.dump",
        "r2_key": f"{PREFIX}eventrank_rag_20261107.dump",
    },
    {
        "local_path": REPO_ROOT
        / "data/rag/qdrant/snapshots/rag_v1_qwen_text_v1/rag_v1_qwen_text_v1-2638666312007-2026-11-07-08-07-19-0.snapshot",
        "r2_key": f"{PREFIX}rag_v1_qwen_text_v1-2638666312007-2026-11-07-08-07-19-0.snapshot",
    },
    {
        "local_path": REPO_ROOT / "data/rag/bm25_snapshot_20261107.zip",
        "r2_key": f"{PREFIX}bm25_snapshot_20261107.zip",
    },
    {
        "local_path": REPO_ROOT / "data/rag/SHA256SUMS_RAG_20261107.txt",
        "r2_key": f"{PREFIX}SHA256SUMS",
    },
]


class ProgressCallback:
    def __init__(self, filename, total_bytes):
        self.filename = filename
        self.total_bytes = total_bytes
        self.transferred = 0
        self.last_percent = -1

    def __call__(self, bytes_amount):
        self.transferred += bytes_amount
        percent = int((self.transferred / self.total_bytes) * 100)
        if percent != self.last_percent and percent % 10 == 0:
            print(
                f"  {self.filename}: {percent}% ({self.transferred / (1024 * 1024):.1f}/{self.total_bytes / (1024 * 1024):.1f} MB)"
            )
            self.last_percent = percent


def main():
    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")

    if not all([account_id, access_key, secret_key]):
        print("Lỗi: Thiếu R2 credentials trong .env.")
        sys.exit(1)

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )

    # 1. Kiểm tra quyền ghi trước
    probe_key = f"{PREFIX}.probe"
    try:
        s3.put_object(Bucket=R2_BUCKET, Key=probe_key, Body=b"probe")
        s3.delete_object(Bucket=R2_BUCKET, Key=probe_key)
        print(f"Đã xác thực quyền ghi vào bucket: {R2_BUCKET}, prefix: {PREFIX}")
    except ClientError as e:
        print(f"Lỗi phân quyền R2: {e}")
        print(
            'Khoá R2 hiện tại trong .env có thể là "Object Read only". Cần khoá có quyền Object Read & Write.'
        )
        sys.exit(1)

    # 2. Upload từng file
    for item in FILES_TO_UPLOAD:
        path = item["local_path"]
        key = item["r2_key"]
        if not path.exists():
            print(f"Lỗi: Không tìm thấy file {path}")
            sys.exit(1)

        size = path.stat().st_size
        print(
            f"\nĐang upload: {path.name} ({size / (1024 * 1024):.2f} MB) -> r2://{R2_BUCKET}/{key}"
        )
        progress = ProgressCallback(path.name, size)
        s3.upload_file(str(path), R2_BUCKET, key, Callback=progress)
        print(f"Upload hoàn tất: {path.name}")

    print(f"\nTất cả các file đã được upload thành công lên prefix: r2://{R2_BUCKET}/{PREFIX}")


if __name__ == "__main__":
    main()
