"""Hợp đồng canonical của NER_Detect. Không gộp khoảng trắng sau khi dựng text."""
import hashlib
import unicodedata

LABELS = {"PER", "ORG", "LOC", "EVENT", "DOC", "PRODUCT"}


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_full_text(article: dict) -> str:
    """Giống ner_common.build_full_text của bộ NER: strip từng trường, ghép rồi NFC."""
    parts = []
    for field, prefix in (("title", "Tiêu đề: "), ("sapo", "Sapo: "),
                          ("content_text", "Nội dung:\n")):
        value = (article.get(field) or "").strip()
        if value:
            parts.append(prefix + value)
    return unicodedata.normalize("NFC", "\n\n".join(parts))


def validate_entities(text: str, entities: list) -> list[dict]:
    if not isinstance(entities, list):
        raise TypeError("entities phải là array")
    out = []
    for i, e in enumerate(entities):
        if not isinstance(e, dict):
            raise TypeError(f"entity {i}: phải là object")
        start, end = e.get("start_char"), e.get("end_char")
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text)):
            raise ValueError(f"entity {i}: offset không hợp lệ")
        if e.get("label") not in LABELS or text[start:end] != e.get("text"):
            raise ValueError(f"entity {i}: nhãn hoặc slice không khớp")
        out.append({k: e[k] for k in ("text", "label", "start_char", "end_char")})
    return sorted(out, key=lambda e: (e["start_char"], e["end_char"], e["label"]))
