"""Validate structured model claims against selected evidence; assemble citations ourselves.

Exact quote matching supports provenance but does not establish semantic entailment.
Unvalidated model answers or URLs are never returned as accepted answers.
"""

import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eventrank.rag.context import normalized

NO_EVIDENCE = 'Chưa đủ bằng chứng trong kho dữ liệu để trả lời câu hỏi này.'
_CITATION = re.compile(r'\[\s*(\d+)\s*\]')


class CitationError(ValueError):
    pass


class _Ref(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: Annotated[int, Field(strict=True, ge=1)]
    quote: Annotated[str, Field(min_length=1, max_length=8000)]


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
        return {'status': 'insufficient_evidence', 'answer': NO_EVIDENCE, 'sources': []}
    if not output.claims:
        raise CitationError('answer_has_no_claims')
    lookup = {row['id']: row for row in evidence}
    used, statements = {}, []
    for claim in output.claims:
        text = claim.text.strip()
        if re.search(r'https?://|www\.', text, re.IGNORECASE):
            raise CitationError('model_generated_url')
        refs = []
        for ref in claim.evidence:
            if ref.id not in lookup:
                raise CitationError('unknown_citation_id')
            quote = normalized(ref.quote)
            if not quote or quote not in normalized(lookup[ref.id]['text']):
                raise CitationError('quote_not_in_evidence')
            quotes = used.setdefault(ref.id, [])
            if quote not in quotes:
                quotes.append(quote)
            if ref.id not in refs:
                refs.append(ref.id)
        if any(int(cid) not in refs for cid in _CITATION.findall(text)):
            raise CitationError('undeclared_citation_in_claim')
        text = _CITATION.sub('', text).strip()
        if not text:
            raise CitationError('empty_claim')
        statements.append(text + ' ' + ''.join(f'[{cid}]' for cid in refs))
    sources = []
    for cid in sorted(used):
        row = lookup[cid]
        sources.append({'citation_id': cid, **{key: row[key] for key in (
            'chunk_id', 'article_id', 'title', 'url', 'source', 'published_at',
            'start_char', 'end_char', 'chunking_version')}, 'quotes': used[cid]})
    return {'status': 'answered', 'answer': '\n\n'.join(statements), 'sources': sources}
