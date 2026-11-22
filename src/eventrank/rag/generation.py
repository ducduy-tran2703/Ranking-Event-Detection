"""Validate structured model claims against selected evidence; assemble citations ourselves.

Quote matching supports provenance but does not establish semantic entailment. Claims whose
quotes all fail are dropped; an answer with no surviving claim is rejected. Unvalidated model
answers or URLs are never returned as accepted answers.
"""

import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eventrank.rag.context import normalized

NO_EVIDENCE = 'Chưa đủ bằng chứng trong kho dữ liệu để trả lời câu hỏi này.'
_CITATION = re.compile(r'\s*\[\s*(\d+)\s*\]')
# Punctuation between two digits is significant: 11,038 and 11.038 are different numbers.
_PUNCTUATION = re.compile(r'(?<!\d)[^\w\s]|[^\w\s](?!\d)')
_ELLIPSIS = re.compile(r'\.{3,}|…')
_MIN_ELLIPSIS_PART = 15


def _matchable(text):
    """Case and punctuation vary between model output and article text; words must still match."""
    return ' '.join(_PUNCTUATION.sub(' ', normalized(text).casefold()).split())


def _quote_in_text(quote, text):
    """An elided quote passes only if every long-enough part appears verbatim and in order."""
    parts = [part for part in map(_matchable, _ELLIPSIS.split(quote)) if part]
    if not parts or (len(parts) > 1 and any(len(part) < _MIN_ELLIPSIS_PART for part in parts)):
        return False
    body, position = _matchable(text), 0
    for part in parts:
        found = body.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return True


_MIN_SHARED_WORDS = 2


def _is_hollow(text, quotes):
    """Ý không chung nổi `_MIN_SHARED_WORDS` từ với BẤT KỲ quote nào nó dẫn = chỉ là lời chào/lời dẫn.

    Bằng chứng: E2E 22/11 lượt 4 (lần 4 và 5 giống hệt) Gemma trả một ý "Chị Lan ơi, vào ngày 10/9/2026, có các
    sự kiện nổi bật sau:" dẫn 5 quote đúng nguyên văn; ý đó chung 0 từ với mỗi quote. Ý trả lời thật
    ("VnExpress có 37 bài trong tháng 9" ↔ "có 37 bài báo của báo vnexpress") chung ≥ 3 từ.
    """
    words = set(_matchable(text).split())
    return bool(quotes) and all(len(words & set(_matchable(q).split())) < _MIN_SHARED_WORDS for q in quotes)


class CitationError(ValueError):
    pass


class _Ref(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: Annotated[int, Field(strict=True, ge=1)]
    quote: Annotated[str, Field(min_length=1, max_length=300)]


class _Claim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    evidence: Annotated[list[_Ref], Field(min_length=1, max_length=8)]


class _Output(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['answered', 'insufficient_evidence']
    claims: Annotated[list[_Claim], Field(max_length=12)]


def output_schema():
    return _Output.model_json_schema()


def validate_answer(content, evidence):
    if not isinstance(content, str):
        raise CitationError('non_text_generation')
    content = content.strip()
    if content.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', content, re.DOTALL)
        if not match:
            raise CitationError('invalid_json_fence')
        content = match[1]
    try:
        output = _Output.model_validate(json.loads(content))
    except (ValueError, TypeError, ValidationError):
        raise CitationError('invalid_generation_schema') from None
    if output.status == 'insufficient_evidence':
        if output.claims:
            raise CitationError('refusal_contains_claims')
        return {'status': 'insufficient_evidence', 'answer': NO_EVIDENCE, 'sources': [], 'dropped': []}
    if not output.claims:
        raise CitationError('answer_has_no_claims')
    lookup = {row['id']: row for row in evidence}
    used, statements, dropped = {}, [], []
    for index, claim in enumerate(output.claims):
        text = claim.text.strip()
        if re.search(r'https?://|www\.', text, re.IGNORECASE):
            raise CitationError('model_generated_url')
        refs = []
        for ref in claim.evidence:
            if ref.id not in lookup:
                raise CitationError('unknown_citation_id')
            quote = normalized(ref.quote)
            if not _quote_in_text(quote, lookup[ref.id]['text']):
                dropped.append({'claim': index, 'id': ref.id, 'quote': quote})
                continue
            quotes = used.setdefault(ref.id, [])
            if quote not in quotes:
                quotes.append(quote)
            if ref.id not in refs:
                refs.append(ref.id)
        declared = {ref.id for ref in claim.evidence}
        if any(int(cid) not in declared for cid in _CITATION.findall(text)):
            raise CitationError('undeclared_citation_in_claim')
        if not refs:
            continue
        text = _CITATION.sub('', text).strip()
        if not text:
            raise CitationError('empty_claim')
        kept = [(ref.id, normalized(ref.quote)) for ref in claim.evidence
                if ref.id in refs and normalized(ref.quote) in used.get(ref.id, [])]
        if _is_hollow(text, [q for _, q in kept]):
            # Ý chỉ là lời dẫn ("Chị Lan ơi, có các sự kiện sau:"): code liệt kê quote đã kiểm để câu trả lời
            # có nội dung. Không thêm chữ nào ngoài quote nguyên văn.
            lines, seen = [], set()
            for cid, quote in kept:
                if (cid, quote) not in seen:
                    seen.add((cid, quote))
                    lines.append(f'- {quote} [{cid}]')
            statements.append(text + '\n' + '\n'.join(lines))
            continue
        statements.append(text + ' ' + ''.join(f'[{cid}]' for cid in refs))
    if not statements:
        raise CitationError('quote_not_in_evidence')
    sources = []
    for cid in sorted(used):
        row = lookup[cid]
        if row.get('kind') == 'data':  # số liệu từ tool SQL: nguồn là kho dữ liệu, không có URL
            sources.append({'citation_id': cid, 'kind': 'data', 'tool': row['tool'], 'title': row['title'],
                            'text': row['text'], 'quotes': used[cid]})
            continue
        sources.append({'citation_id': cid, 'kind': 'chunk', **{key: row[key] for key in (
            'chunk_id', 'article_id', 'title', 'url', 'source', 'published_at',
            'start_char', 'end_char', 'chunking_version')}, 'quotes': used[cid]})
    return {'status': 'answered', 'answer': '\n\n'.join(statements), 'sources': sources, 'dropped': dropped}
