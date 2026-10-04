"""Nạp lớp Gold (NER) + Silver (văn bản), join theo `article_id`, tính df/idf của thực thể."""
from __future__ import annotations

import glob
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from eventrank.weak_labels.entities import ArticleEntity, EntityNormalizer, article_entities, nfc

_SPACE = re.compile(r"\s+")


@dataclass
class Article:
    idx: int
    article_id: str
    source: str
    category: str
    published_at: datetime
    title: str
    sapo: str
    lead: str                                   # ~600 ký tự đầu nội dung
    entities: dict[str, ArticleEntity]
    dup_group: int = -1                         # nhóm bài đăng lại (cùng tiêu đề + sapo)
    weights: dict[str, float] = field(default_factory=dict)   # text_norm → salience × idf

    @property
    def ts(self) -> float:
        return self.published_at.timestamp()

    def head_text(self) -> str:
        """Văn bản đưa vào mô hình embedding: tiêu đề + sapo."""
        return f"{self.title}. {self.sapo}".strip(" .") if self.sapo else self.title


def _read_jsonl(paths: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    d = json.loads(line)
                    out[d["article_id"]] = d
    return out


def _clean(s: str | None) -> str:
    return _SPACE.sub(" ", nfc(s or "")).strip()


def load_corpus(gold_path: str | Path, silver_glob: str, normalizer: EntityNormalizer,
                max_df_ratio: float = 0.02) -> tuple[list[Article], dict[str, float], Counter]:
    """Trả về (bài, idf theo text_norm, df). Thực thể có df > max_df_ratio coi là từ dừng (idf=0)."""
    silver = _read_jsonl(sorted(glob.glob(silver_glob)))
    if not silver:
        raise FileNotFoundError(f"Không thấy Silver ở {silver_glob}")
    arts: list[Article] = []
    with open(gold_path, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            s = silver.get(g["article_id"])
            if s is None or not g.get("published_at"):
                continue
            # Offset của Gold tính trên văn bản Silver gốc → dùng title/sapo GỐC để xác định vùng
            rec = {"source": g["source"], "title": s.get("title") or "", "sapo": s.get("sapo") or "",
                   "content_text": s.get("content_text") or "", "entities": g["entities"]}
            content = _clean(s.get("content_text"))
            arts.append(Article(
                idx=len(arts), article_id=g["article_id"], source=g["source"].lower(),
                category=g.get("standardized_category") or g.get("category") or "",
                published_at=datetime.fromisoformat(g["published_at"]),
                title=_clean(s.get("title")), sapo=_clean(s.get("sapo")),
                lead=content[:600], entities=article_entities(rec, normalizer)))
    n = len(arts)
    df = Counter(k for a in arts for k in a.entities)
    max_df = max_df_ratio * n
    idf = {k: (math.log(n / c) if 1 < c <= max_df else 0.0) for k, c in df.items()}
    for a in arts:
        a.weights = {k: e.salience * idf[k] for k, e in a.entities.items() if idf[k] > 0}
    _mark_reposts(arts)
    return arts, idf, df


def _mark_reposts(arts: list[Article]) -> None:
    """Bài đăng lại: cùng tiêu đề, hoặc cùng sapo dài (≥ 80 ký tự). Đánh dấu, không xoá."""
    groups: dict[str, int] = {}
    for a in arts:
        keys = [("t", a.title.lower())]
        if len(a.sapo) >= 80:
            keys.append(("s", a.sapo.lower()))
        for k in keys:
            gid = groups.get(str(k))
            if gid is not None:
                a.dup_group = gid
                break
        if a.dup_group < 0:
            a.dup_group = a.idx
        for k in keys:
            groups.setdefault(str(k), a.dup_group)
