"""Chunk theo đơn vị ngăn bằng whitespace (KHÔNG phải model token), giữ nguyên offset.

Mục tiêu 320 units, overlap 48; ưu tiên đoạn/câu trong 40% cuối cửa sổ. Entity dài hơn
cửa sổ được giữ nguyên và báo oversized, không cắt mất thực thể. Chưa tune trên tập đo.
"""
import bisect
import json
import re
import uuid

from eventrank.rag.text import text_hash, validate_entities

_BOUNDARY = re.compile(r"\n\s*\n|(?<=[.!?…])\s+")


def chunking_version(max_units: int, overlap_units: int) -> str:
    if (type(max_units) is not int or type(overlap_units) is not int
            or max_units < 2 or not 0 <= overlap_units < max_units):
        raise ValueError("Cần max_units >= 2 và 0 <= overlap_units < max_units")
    params = {"algorithm": "paragraph_sentence_units_v1", "max_units": max_units,
              "overlap_units": overlap_units, "boundary_min_ratio": 0.6}
    return "c1-" + text_hash(json.dumps(params, sort_keys=True))[:12]


def make_chunks(article_id, text, entities, *, max_units=320, overlap_units=48):
    version = chunking_version(max_units, overlap_units)
    entities = validate_entities(text, entities)
    units = list(re.finditer(r"\S+", text))
    if not units:
        return []
    # Gộp span chồng lấn để không tạo boundary nằm trong bất kỳ entity nào.
    spans = []
    for e in entities:
        lo, hi = e["start_char"], e["end_char"]
        if spans and lo < spans[-1][1]:
            spans[-1] = (spans[-1][0], max(hi, spans[-1][1]))
        else:
            spans.append((lo, hi))

    span_starts = [lo for lo, _ in spans]

    def inside(pos):
        i = bisect.bisect_left(span_starts, pos) - 1
        return i >= 0 and spans[i][0] < pos < spans[i][1]

    starts = [u.start() for u in units]
    safe_ends = [u.end() for u in units if not inside(u.end())]
    if not safe_ends or safe_ends[-1] != len(text):
        safe_ends.append(len(text))
    safe_starts = sorted(set([u.start() for u in units if not inside(u.start())]
                             + span_starts))
    boundaries = [m.start() for m in _BOUNDARY.finditer(text)]
    digest, chunks, start = text_hash(text), [], safe_starts[0]
    while start < units[-1].end():
        first = bisect.bisect_left(starts, start)
        last = min(first + max_units, len(units))
        end = units[last - 1].end()
        if last < len(units):
            lower = units[min(first + int(max_units * 0.6), last - 1)].start()
            candidates = boundaries[bisect.bisect_left(boundaries, lower):
                                    bisect.bisect_right(boundaries, end)]
            if candidates:
                end = candidates[-1]
        # Chỉ kết thúc ở cuối unit an toàn, không bỏ phần dấu câu/đuôi unit sát entity.
        previous = bisect.bisect_right(safe_ends, end) - 1
        if previous >= 0 and safe_ends[previous] > start:
            end = safe_ends[previous]
        else:
            end = safe_ends[bisect.bisect_right(safe_ends, start)]
        chunks.append({
            "chunk_id": uuid.uuid5(uuid.NAMESPACE_URL,
                                   f"eventrank:rag:{article_id}:{digest}:{version}:{start}:{end}"),
            "article_id": article_id, "chunk_index": len(chunks), "text": text[start:end],
            "start_char": start, "end_char": end, "chunking_version": version,
        })
        if end >= units[-1].end():
            break
        next_unit = bisect.bisect_left(starts, end)
        index = max(first + 1, next_unit - overlap_units)
        index = min(index, len(starts) - 1)
        candidate = bisect.bisect_right(safe_starts, starts[index]) - 1
        if candidate >= 0 and safe_starts[candidate] > start:
            start = safe_starts[candidate]
        else:
            start = safe_starts[bisect.bisect_left(safe_starts, end)]
    return chunks
