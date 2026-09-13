from types import SimpleNamespace

from app.llm.streaming import JsonContentDecoder, chunk_text


def test_string_escape_unicode_and_hidden_content_are_not_leaked():
    decoder = JsonContentDecoder()
    result = []
    for text in ['{"answer":"第一', '段\\n第二\\uD83D', '\\uDE00段","source_refs":[]}']:
        decoder.feed(SimpleNamespace(content=text))
        result.append(decoder.answer_delta())
    assert result == ["第一", "段\n第二", "😀段"]
    assert chunk_text(SimpleNamespace(content=[{"type": "thinking", "thinking": "private"},
                                               {"type": "tool_use", "input": {"answer": "secret"}},
                                               {"type": "text", "text": "safe"}])) == "safe"


def test_only_complete_top_level_or_payload_blocks_are_emitted():
    decoder = JsonContentDecoder()
    decoder.feed(SimpleNamespace(content='{"secret":{"blocks":[{"text":"hidden"}]},"payload":{"blocks":[{"block_ref":"b1","text":"one"},'))
    assert decoder.complete_blocks() == []
    assert decoder.complete_blocks(container="payload") == [{"block_ref": "b1", "text": "one"}]
    decoder.feed(SimpleNamespace(content='{"block_ref":"b2","text":"two"}]}}'))
    assert decoder.complete_blocks(container="payload") == [{"block_ref": "b2", "text": "two"}]


def test_answer_key_in_model_string_cannot_become_a_preview():
    decoder = JsonContentDecoder()
    decoder.feed(SimpleNamespace(content='{"meta":"\\\"answer\\\":\\\"private\\\"","answer":"public"}'))
    assert decoder.answer_delta() == "public"
