"""Exact Gemma chat-template token counting; tokenizer files only, no model weights."""

import argparse
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from eventrank.rag.models import load_model_config

DEFAULT_CACHE = Path(__file__).resolve().parents[3] / 'data/rag/tokenizers'


@lru_cache(maxsize=2)
def _load(model, revision, cache, local_only):
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(model, revision=revision, cache_dir=cache,
                                         local_files_only=local_only, trust_remote_code=False)


class GemmaTokenCounter:
    def __init__(self, spec=None, *, allow_download=False, cache_dir=DEFAULT_CACHE):
        self.spec = spec or load_model_config()['llm']
        self.tokenizer = _load(self.spec['model'], self.spec['revision'], str(cache_dir), not allow_download)
        template = self.tokenizer.chat_template
        if not isinstance(template, str) or not template:
            raise ValueError('Gemma tokenizer has no supported chat template')
        self.version = {'model': self.spec['model'], 'revision': self.spec['revision'],
                        'content_format': 'openai_text_blocks',
                        'chat_template_sha256': hashlib.sha256(template.encode()).hexdigest()}

    def count(self, messages):
        # Gemma's vLLM multimodal renderer uses typed text blocks, including for
        # text-only requests. Its template adds a space after system text in this
        # format. Verified against returned prompt_text/prompt_token_ids.
        rendered = [{**message, 'content': [{'type': 'text', 'text': message['content']}]}
                    if isinstance(message['content'], str) else message for message in messages]
        ids = self.tokenizer.apply_chat_template(rendered, tokenize=True, add_generation_prompt=True,
                                                 return_dict=False, enable_thinking=False)
        return len(ids)


def main():
    from dotenv import load_dotenv

    load_dotenv('.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare'])
    parser.parse_args()
    counter = GemmaTokenCounter(allow_download=True)
    print(json.dumps({'prepared': True, 'tokenizer': counter.version,
                       'sample_chat_tokens': counter.count([{'role': 'user', 'content': 'Xin chào'}])}),
          flush=True)


if __name__ == '__main__':
    main()
