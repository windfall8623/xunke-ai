"""Read final model text without treating reasoning or tool blocks as an answer."""


def response_text(message) -> str:
    metadata = getattr(message, "response_metadata", None) or {}
    if isinstance(metadata, dict) and (
        metadata.get("stop_reason")
        in {"max_tokens", "refusal", "tool_use", "pause_turn"}
        or metadata.get("finish_reason") in {"length", "content_filter", "tool_calls"}
    ):
        raise ValueError("Model did not finish a complete text answer")
    tool_calls = getattr(message, "tool_calls", None)
    invalid_tool_calls = getattr(message, "invalid_tool_calls", None)
    if (isinstance(tool_calls, list) and tool_calls) or (
        isinstance(invalid_tool_calls, list) and invalid_tool_calls
    ):
        raise ValueError("Model requested tools instead of returning final text")
    content = message.content
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                if not isinstance(block.get("text"), str):
                    raise ValueError("Invalid model text block")
                parts.append(block["text"])
            elif isinstance(block, dict) and block.get("type") in {
                "thinking",
                "redacted_thinking",
                "reasoning",
            }:
                continue
            else:
                raise ValueError("Model returned an unsupported final content block")
        text = "".join(parts)
    else:
        raise ValueError("Model returned no text")
    if not text.strip():
        raise ValueError("Model returned no text")
    return text
