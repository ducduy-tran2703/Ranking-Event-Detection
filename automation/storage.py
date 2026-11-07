"""Atomic metadata and article files. No user data is rewritten in place."""
import json
import os
from pathlib import Path
from uuid import uuid4


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    # Corrupt metadata is an error; never silently replace it with empty state.
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_text(path: Path, value: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class ProcessLock:
    """OS lock released even after a crash, including on Windows."""
    def __init__(self, path):
        self.path = path
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            self.stream = None
            raise RuntimeError("Another crawler instance owns this data directory") from exc

    def release(self):
        if self.stream:
            self.stream.close()
            self.stream = None
