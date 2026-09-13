"""Decode only permitted model text and complete JSON fields for private previews."""

import inspect
import json
import logging

logger = logging.getLogger(__name__)
MAX_BUFFER_BYTES = 262_144


def chunk_text(chunk) -> str:
    """Reasoning, tool arguments and provider control fields never enter previews."""
    if getattr(chunk, "tool_calls", None) or getattr(chunk, "tool_call_chunks", None):
        return ""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        item["text"] for item in content
        if isinstance(item, dict) and item.get("type") in {"text", "text_delta"}
        and isinstance(item.get("text"), str)
    )


def _merge_counters(previous, current):
    """SDK usage frames are cumulative snapshots, not independently billed calls."""
    merged = dict(previous or {})
    for key, value in (current or {}).items():
        if isinstance(value, dict):
            merged[key] = _merge_counters(merged.get(key) if isinstance(merged.get(key), dict) else {}, value)
        elif type(value) is int and value >= 0:
            merged[key] = max(merged.get(key, 0) or 0, value)
        else:
            merged[key] = value  # preserve invalid counters so metering marks them unknown
    if all(type(merged.get(key)) is int and merged[key] >= 0 for key in ("input_tokens", "output_tokens")) and "total_tokens" in merged:
        merged["total_tokens"] = merged["input_tokens"] + merged["output_tokens"]
    return merged


async def collect_stream(client, messages, on_chunk):
    """One SDK stream; aggregate its message and final usage without a second call."""
    aggregate, usage, metadata = None, {}, {}
    callback = on_chunk
    async for chunk in client.astream(messages):
        aggregate = chunk if aggregate is None else aggregate + chunk
        reported = getattr(chunk, "usage_metadata", None)
        if isinstance(reported, dict):
            usage = _merge_counters(usage, reported)
        raw_meta = getattr(chunk, "response_metadata", None)
        if isinstance(raw_meta, dict):
            for key, value in raw_meta.items():
                if key in {"usage", "token_usage"} and isinstance(value, dict):
                    metadata[key] = _merge_counters(metadata.get(key), value)
                else:
                    metadata[key] = value
        if callback is not None:
            try:
                result = callback(chunk)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                from app.core.errors import AppError
                from app.rag.errors import RagError

                if isinstance(exc, (AppError, RagError)):
                    raise  # lease, authorization, cancellation and budget still fence work
                logger.warning("content_preview_callback_disabled", extra={"reason": type(exc).__name__})
                callback = None
    if aggregate is None:
        raise ValueError("Provider stream returned no message")
    # LangChain message addition sums usage; replace it with observed snapshots.
    aggregate.usage_metadata = usage or None
    aggregate.response_metadata = metadata
    return aggregate


def _decoded_string_prefix(raw):
    """Decode a JSON string prefix without leaking half an escape/surrogate pair."""
    if not raw.startswith('"'):
        return ""
    out, index = [], 1
    escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    while index < len(raw):
        char = raw[index]
        if char == '"':
            break
        if char == "\\":
            if index + 1 >= len(raw):
                break
            escape = raw[index + 1]
            if escape in escapes:
                out.append(escapes[escape])
                index += 2
                continue
            if escape != "u" or index + 6 > len(raw):
                break
            try:
                point = int(raw[index + 2:index + 6], 16)
            except ValueError:
                break
            if 0xD800 <= point <= 0xDBFF:
                if index + 12 > len(raw) or raw[index + 6:index + 8] != "\\u":
                    break
                try:
                    low = int(raw[index + 8:index + 12], 16)
                except ValueError:
                    break
                if not 0xDC00 <= low <= 0xDFFF:
                    break
                out.append(chr(0x10000 + ((point - 0xD800) << 10) + low - 0xDC00))
                index += 12
            elif 0xDC00 <= point <= 0xDFFF:
                break
            else:
                out.append(chr(point))
                index += 6
            continue
        if ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF:
            break
        out.append(char)
        index += 1
    return "".join(out)


class JsonContentDecoder:
    """Only top-level answer/blocks, never regex matches inside model strings."""

    def __init__(self):
        self.buffer = ""
        self.bytes = 0
        self.disabled = False
        self._answer = ""
        self._blocks = 0

    def feed(self, chunk) -> None:
        text = chunk_text(chunk)
        self.bytes += len(text.encode("utf-8", errors="replace"))
        if self.bytes > MAX_BUFFER_BYTES:
            self.disabled = True
            self.buffer = ""
        if not self.disabled:
            self.buffer += text

    def _value(self, field, *, container=None):
        raw = (self._value(container) or "") if container else self.buffer.lstrip()
        if raw.startswith("```"):
            newline = raw.find("\n")
            if newline < 0 or raw[:newline].strip() not in {"```", "```json"}:
                return None
            raw = raw[newline + 1:].lstrip()
        if not raw.startswith("{"):
            return None
        decoder, index = json.JSONDecoder(), 1
        try:
            while index < len(raw):
                while index < len(raw) and raw[index].isspace():
                    index += 1
                key, index = decoder.raw_decode(raw, index)
                if not isinstance(key, str):
                    return None
                while index < len(raw) and raw[index].isspace():
                    index += 1
                if raw[index:index + 1] != ":":
                    return None
                index += 1
                while index < len(raw) and raw[index].isspace():
                    index += 1
                if key == field:
                    return raw[index:]
                _, index = decoder.raw_decode(raw, index)
                while index < len(raw) and raw[index].isspace():
                    index += 1
                if raw[index:index + 1] != ",":
                    return None
                index += 1
        except (ValueError, IndexError):
            return None
        return None

    def answer_delta(self) -> str:
        current = _decoded_string_prefix(self._value("answer") or "")
        if not current.startswith(self._answer):
            self.disabled = True
            return ""
        delta, self._answer = current[len(self._answer):], current
        return delta

    def complete_blocks(self, *, container=None) -> list[dict]:
        raw = self._value("blocks", container=container) or ""
        if not raw.startswith("["):
            return []
        decoder, index, values = json.JSONDecoder(), 1, []
        try:
            while index < len(raw):
                while index < len(raw) and raw[index].isspace():
                    index += 1
                value, index = decoder.raw_decode(raw, index)
                if not isinstance(value, dict):
                    break
                values.append(value)
                while index < len(raw) and raw[index].isspace():
                    index += 1
                if raw[index:index + 1] != ",":
                    break
                index += 1
        except (ValueError, IndexError):
            pass
        new, self._blocks = values[self._blocks:], len(values)
        return new
