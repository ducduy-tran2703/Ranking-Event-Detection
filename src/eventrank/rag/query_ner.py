"""Query NER entity extraction and entity-aware soft boost for retrieval candidates."""
from __future__ import annotations

import unicodedata


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def boost_candidates_with_ner(
    candidates: list[dict],
    query_entities: list[dict],
    article_entities_by_id: dict[str, list[dict]],
    *,
    in_chunk_boost: float = 0.008,
    in_article_boost: float = 0.003,
    label_match_multiplier: float = 1.0,
    text_only_multiplier: float = 0.4,
) -> list[dict]:
    """Soft-boost RRF candidates whose chunk/article entities match query NER entities."""
    if not candidates or not query_entities:
        return [
            {
                **row,
                "ner_boost": 0.0,
                "final_score": row.get("rrf_score", 0.0),
                "matched_entities": [],
            }
            for row in candidates
        ]

    unique_q = list({(_norm(e["text"]), e["label"]): e for e in query_entities}.items())
    denom = len(unique_q)
    reranked = []

    for row in candidates:
        aid = row["article_id"]
        c_start = int(row.get("start_char", 0))
        c_end = int(row.get("end_char", 0))
        art_ents = article_entities_by_id.get(aid) or []

        total_boost = 0.0
        matched = []
        for (q_norm, q_label), _q_ent in unique_q:
            best_score = 0.0
            best_scope = None
            best_label_match = False
            for a_ent in art_ents:
                if _norm(a_ent.get("text", "")) != q_norm:
                    continue
                same_label = a_ent.get("label") == q_label
                mult = label_match_multiplier if same_label else text_only_multiplier
                in_chunk = (
                    c_start <= int(a_ent.get("start_char", -1))
                    and int(a_ent.get("end_char", -1)) <= c_end
                )
                base = in_chunk_boost if in_chunk else in_article_boost
                score = base * mult
                if score > best_score:
                    best_score = score
                    best_scope = "chunk" if in_chunk else "article"
                    best_label_match = same_label
            if best_score > 0.0:
                total_boost += best_score
                matched.append({
                    "text": _q_ent["text"],
                    "label": q_label,
                    "scope": best_scope,
                    "label_match": best_label_match,
                })

        ner_boost = round(total_boost / denom, 6)
        rrf = float(row.get("rrf_score", 0.0))
        reranked.append({
            **row,
            "rrf_rank": row.get("rank"),
            "ner_boost": ner_boost,
            "final_score": round(rrf + ner_boost, 6),
            "matched_entities": matched,
        })

    reranked.sort(key=lambda r: (-r["final_score"], -float(r.get("rrf_score", 0.0)), r["chunk_id"]))
    for rank, row in enumerate(reranked, 1):
        row["rank"] = rank
    return reranked


def fetch_article_entities(conn, article_ids: list[str]) -> dict[str, list[dict]]:
    """Fetch stored NER entities from Postgres for a list of article_ids."""
    if not article_ids or not hasattr(conn, "execute"):
        return {}
    unique_ids = list(dict.fromkeys(article_ids))
    rows = conn.execute(
        "SELECT article_id, entities FROM article_ner WHERE article_id = ANY(%s)",
        (unique_ids,),
    ).fetchall()
    return {row[0]: (row[1] or []) for row in rows}
