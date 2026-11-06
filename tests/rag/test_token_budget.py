from types import SimpleNamespace

from eventrank.rag.token_budget import GemmaTokenCounter


def test_token_count_uses_vllm_text_block_format_without_mutating_messages():
    seen = []

    def apply(messages, **kwargs):
        seen.extend(messages)
        assert kwargs['enable_thinking'] is False
        assert kwargs['add_generation_prompt'] is True
        return [1, 2, 3]

    counter = object.__new__(GemmaTokenCounter)
    counter.tokenizer = SimpleNamespace(apply_chat_template=apply)
    messages = [{'role': 'system', 'content': 'System'}, {'role': 'user', 'content': 'Question'}]
    assert counter.count(messages) == 3
    assert seen[0]['content'] == [{'type': 'text', 'text': 'System'}]
    assert messages[0]['content'] == 'System'
