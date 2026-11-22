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


def test_dem_token_tinh_ca_tools_va_luot_tool_call():
    seen = {}

    def apply(messages, **kwargs):
        seen['messages'], seen['tools'] = messages, kwargs.get('tools')
        return [1] * 7

    counter = object.__new__(GemmaTokenCounter)
    counter.tokenizer = SimpleNamespace(apply_chat_template=apply)
    tools = [{'type': 'function', 'function': {'name': 'corpus_info', 'parameters': {'type': 'object'}}}]
    messages = [{'role': 'user', 'content': 'Q'},
                {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': 'c1', 'type': 'function', 'function': {'name': 'corpus_info', 'arguments': '{}'}}]},
                {'role': 'tool', 'tool_call_id': 'c1', 'content': '{"articles": 3}'}]
    assert counter.count(messages, tools=tools) == 7
    assert seen['tools'] == tools
    # Lượt assistant chỉ gọi tool: content None giữ nguyên (không bọc thành text block rỗng).
    assert seen['messages'][1]['content'] is None
    assert seen['messages'][1]['tool_calls'][0]['function']['arguments'] == {}
    assert seen['messages'][2]['content'] == [{'type': 'text', 'text': '{"articles": 3}'}]


def test_dem_token_khong_tools_khong_truyen_tham_so_tools():
    seen = {}

    def apply(messages, **kwargs):
        seen.update(kwargs)
        return [1]

    counter = object.__new__(GemmaTokenCounter)
    counter.tokenizer = SimpleNamespace(apply_chat_template=apply)
    counter.count([{'role': 'user', 'content': 'Q'}])
    assert 'tools' not in seen


def test_dem_token_parse_arguments_chuoi_json_thanh_object_nhu_vllm():
    seen = {}

    def apply(messages, **kwargs):
        seen['messages'] = messages
        return [1]

    counter = object.__new__(GemmaTokenCounter)
    counter.tokenizer = SimpleNamespace(apply_chat_template=apply)
    call = {'id': 'c1', 'type': 'function', 'function': {'name': 'f', 'arguments': '{"a": 1}'}}
    original = [{'role': 'assistant', 'content': None, 'tool_calls': [call]}]
    counter.count(original)
    assert seen['messages'][0]['tool_calls'][0]['function']['arguments'] == {'a': 1}
    assert call['function']['arguments'] == '{"a": 1}'  # không sửa message gốc
