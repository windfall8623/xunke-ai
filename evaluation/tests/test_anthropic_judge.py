"""Native SDK and real Ragas scoring against an isolated loopback HTTP server."""

import asyncio
import copy
import importlib.util
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from rag_eval.judges.ragas_adapter import RagasAdapter, ragas_runtime_info

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ragas") is None
    or importlib.util.find_spec("anthropic") is None,
    reason="install the isolated requirements-ragas.lock for native judge checks",
)


@contextmanager
def native_server(reply):
    requests = []
    failures = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                request = {
                    "path": self.path,
                    "headers": {
                        key.lower(): value for key, value in self.headers.items()
                    },
                    "body": body,
                }
                requests.append(request)
                if self.path == "/v1/messages":
                    status, payload = reply(request)
                else:
                    status, payload = (
                        404,
                        {
                            "type": "error",
                            "error": {
                                "type": "not_found_error",
                                "message": "Native API only",
                            },
                        },
                    )
            except Exception as exc:
                failures.append(exc)
                status, payload = 500, {"error": "local fixture failure"}
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Retry-After", "0")
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not failures, failures


def native_config(base_url):
    return {
        "enabled": True,
        "provider": "anthropic",
        "model": "claude-opus-5-max",
        "base_url": base_url,
        "api_key_env": "EVAL_JUDGE_API_KEY",
        "ragas_version": "0.4.3",
        "prompt_version": "quiz-facts-v1",
        "prompt_hash": ragas_runtime_info()["prompt_hash"],
        "max_llm_calls": 4,
        "max_cost_cny": 5,
        "call_cost_ceiling_cny": 1,
        "max_input_tokens": 20000,
        "max_output_tokens": 1024,
        "timeout_seconds": 5,
        "total_timeout_seconds": 30,
        "price_table": {
            "effective_date": "2026-09-08",
            "input_cny_per_million": 35,
            "output_cny_per_million": 175,
            "cache_read_cny_per_million": 3.5,
            "cache_write_cny_per_million": 3.5,
        },
        "calibrated": False,
    }


def native_reply(request, *, usage=None, stop_reason="tool_use"):
    tool_name = request["body"]["tools"][0]["name"]
    if tool_name == "StatementGeneratorOutput":
        parsed = {"statements": ["Supported statement.", "Unsupported statement."]}
    else:
        parsed = {
            "statements": [
                {
                    "statement": "Supported statement.",
                    "reason": "Supported",
                    "verdict": 1,
                },
                {
                    "statement": "Unsupported statement.",
                    "reason": "Unsupported",
                    "verdict": 0,
                },
            ]
        }
    body = {
        "id": "msg_judge_fixture",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_judge",
                "name": tool_name,
                "input": parsed,
            }
        ],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage
        if usage is not None
        else {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 20,
        },
    }
    return 200, body


def score_one(config, sample, artifact, events):
    artifact = copy.deepcopy(artifact)
    artifact["questions"] = artifact["questions"][:1]
    return asyncio.run(
        RagasAdapter(
            config, journal=lambda call: events.append(copy.deepcopy(call))
        ).score(sample, artifact)
    )


@pytest.mark.parametrize("base_suffix", ["", "/v1/"])
def test_native_judge_scores_real_ragas_with_both_calls_and_cache_prices(
    monkeypatch, quiz_case, quiz_artifact, base_suffix
):
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "local-judge-fixture-key")
    events = []

    def reply(request):
        assert events[-1]["status"] == "reserved"
        return native_reply(request)

    with native_server(reply) as (base_url, requests):
        result = score_one(
            native_config(base_url + base_suffix), quiz_case, quiz_artifact, events
        )
    assert result["metrics"]["ragas_faithfulness"]["value"] == 0.5
    assert len(requests) == len(result["calls"]) == 2
    assert [event["status"] for event in events] == [
        "reserved",
        "completed",
        "reserved",
        "completed",
    ]
    for request in requests:
        assert request["path"] == "/v1/messages"
        assert request["headers"]["x-api-key"] == "local-judge-fixture-key"
        assert "anthropic-version" in request["headers"]
        assert request["body"]["model"] == "claude-opus-5-max"
        assert request["body"]["max_tokens"] == 1024
        assert request["body"]["tool_choice"] == {
            "type": "tool",
            "name": request["body"]["tools"][0]["name"],
        }
    for call in result["calls"]:
        assert call["provider"] == "anthropic"
        assert call["model"] == "claude-opus-5-max"
        assert call["provider_model"] == "claude-opus-5"
        assert call["input_tokens"] == 200
        assert call["output_tokens"] == 20
        assert call["input_token_details"] == {"cache_read": 80, "cache_creation": 20}
        assert call["cost_cny"] == pytest.approx(0.00735)
        assert call["cost_status"] == "estimated"
    assert result["metadata"]["provider"] == "anthropic"
    assert result["metadata"]["calibrated"] is False
    assert result["metadata"]["sdk_retries"] == 0
    assert result["metadata"]["instructor_retries"] == 0
    assert "local-judge-fixture-key" not in json.dumps(result)
    assert "Supported statement." not in json.dumps(events)


@pytest.mark.parametrize(
    "usage,missing",
    [
        ({}, "input_tokens"),
        ({"input_tokens": 100}, "output_tokens"),
        ({"output_tokens": 20}, "input_tokens"),
        ({"input_tokens": True, "output_tokens": 20}, "input_tokens"),
        ({"input_tokens": 100, "output_tokens": "20"}, "output_tokens"),
    ],
)
def test_native_judge_missing_or_invalid_raw_usage_keeps_unknown_reservations(
    monkeypatch, quiz_case, quiz_artifact, usage, missing
):
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "local-judge-fixture-key")
    events = []
    with native_server(lambda request: native_reply(request, usage=usage)) as (
        base_url,
        requests,
    ):
        result = score_one(native_config(base_url), quiz_case, quiz_artifact, events)
    assert result["metrics"]["ragas_faithfulness"]["value"] == 0.5
    assert len(requests) == 2
    for call in result["calls"]:
        assert call[missing] is None
        assert call["cost_cny"] is None
        assert call["cost_status"] == "unknown"
        assert call["reserved_cost_cny"] == 1


def test_native_cached_judge_without_cache_prices_does_not_bill_ordinary_input(
    monkeypatch, quiz_case, quiz_artifact
):
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "local-judge-fixture-key")
    with native_server(native_reply) as (base_url, requests):
        config = native_config(base_url)
        config["price_table"].pop("cache_read_cny_per_million")
        config["price_table"].pop("cache_write_cny_per_million")
        result = score_one(config, quiz_case, quiz_artifact, [])
    assert result["metrics"]["ragas_faithfulness"]["value"] == 0.5
    assert len(requests) == 2
    assert all(call["input_tokens"] == 200 for call in result["calls"])
    assert all(call["cost_cny"] is None for call in result["calls"])


@pytest.mark.parametrize("status", [401, 429])
def test_native_judge_sdk_errors_do_not_retry_or_release_the_call_reservation(
    monkeypatch, quiz_case, quiz_artifact, status
):
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "local-judge-fixture-key")
    reply = {
        "type": "error",
        "error": {
            "type": "authentication_error" if status == 401 else "rate_limit_error",
            "message": "Local fixture failure",
        },
    }
    with native_server(lambda request: (status, reply)) as (base_url, requests):
        result = score_one(native_config(base_url), quiz_case, quiz_artifact, [])
    assert result["metrics"]["ragas_faithfulness"]["reason"] == "judge_error"
    assert len(requests) == len(result["calls"]) == 1
    assert result["calls"][0]["cost_cny"] is None
    assert result["calls"][0]["reserved_cost_cny"] == 1


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal", "end_turn"])
def test_native_judge_rejects_incomplete_or_wrong_response_protocol_after_metering(
    monkeypatch, quiz_case, quiz_artifact, stop_reason
):
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "local-judge-fixture-key")
    with native_server(
        lambda request: native_reply(request, stop_reason=stop_reason)
    ) as (base_url, requests):
        result = score_one(native_config(base_url), quiz_case, quiz_artifact, [])
    assert result["metrics"]["ragas_faithfulness"]["reason"] == "judge_error"
    assert len(requests) == len(result["calls"]) == 1
    assert result["calls"][0]["cost_cny"] == pytest.approx(0.00735)


def test_disabled_native_judge_does_not_dispatch_even_with_a_worker_key(
    monkeypatch, quiz_case, quiz_artifact
):
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "local-judge-fixture-key")
    with native_server(native_reply) as (base_url, requests):
        config = native_config(base_url)
        config["enabled"] = False
        events = []
        result = score_one(config, quiz_case, quiz_artifact, events)
    assert result["metrics"]["ragas_faithfulness"]["reason"] == "judge_profile_invalid"
    assert requests == events == []
