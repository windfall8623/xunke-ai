import json
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from rag_eval.metrics import score_sample
from rag_eval.store import EvalControlClient
from rag_eval.worker import ScoringWorker


@pytest.fixture
def control_server(two_group_case, retrieval_artifact):
    state = {
        "requests": [],
        "responses": {},
        "claim": {
            "result_id": "result-1",
            "lease_token": "lease-a",
            "attempt": 1,
            "sample": two_group_case,
            "artifact": retrieval_artifact,
            "config": {},
            "max_scoring_attempts": 3,
            "deadline_at": (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
        },
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}"
            )
            state["requests"].append(
                {
                    "path": self.path,
                    "body": body,
                    "authorization": self.headers.get("Authorization"),
                }
            )
            configured = state["responses"].get(self.path, 200)
            status = configured() if callable(configured) else configured
            payload = (
                state["claim"] if self.path.endswith("/claim") else {"accepted": True}
            )
            if (
                self.path.endswith("/claim")
                and state["claim"] is None
                and status == 200
            ):
                status = 204
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if status != 204:
                self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["base_url"] = f"http://127.0.0.1:{server.server_port}/api/v1"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def client(state, **kwargs):
    return EvalControlClient(
        state["base_url"], "local-test-service-token", "worker-test", **kwargs
    )


def test_worker_scores_claimed_artifact_and_fences_completion(control_server):
    result = ScoringWorker(client(control_server)).run_once()
    assert result["state"] == "completed"
    completion = next(
        item
        for item in control_server["requests"]
        if item["path"].endswith("/complete")
    )
    assert (
        completion["body"]["lease_token"] == "lease-a"
        and completion["body"]["attempt"] == 1
    )
    assert completion["body"]["metrics"]["evidence_group_recall@10"]["value"] == 0.5
    assert completion["authorization"] == "Bearer local-test-service-token"
    assert "sample" not in result and "artifact" not in result


def test_worker_idle_does_not_publish_result(control_server):
    control_server["claim"] = None
    result = ScoringWorker(client(control_server)).run_once()
    assert result["state"] == "idle"
    assert len(control_server["requests"]) == 1


def test_stale_lease_cannot_publish_scores(control_server):
    control_server["responses"]["/api/v1/internal/eval/scoring/result-1/complete"] = 409
    result = ScoringWorker(client(control_server)).run_once()
    assert result["state"] == "stale"
    assert not any(
        item["path"].endswith("/fail") for item in control_server["requests"]
    )


def test_expired_claim_fails_without_scoring(control_server):
    control_server["claim"]["deadline_at"] = "2001-01-01T00:00:00Z"
    result = ScoringWorker(client(control_server)).run_once()
    assert result["state"] == "failed"
    failure = next(
        item for item in control_server["requests"] if item["path"].endswith("/fail")
    )
    assert failure["body"]["error_code"] == "deadline_exceeded"
    assert not any(
        item["path"].endswith("/complete") for item in control_server["requests"]
    )


def test_slow_scoring_sends_heartbeat_and_stops_on_lost_lease(control_server):
    control_server["responses"]["/api/v1/internal/eval/scoring/result-1/heartbeat"] = (
        409
    )

    def slow(sample, artifact, config):
        time.sleep(0.08)
        return score_sample(sample, artifact, config)

    result = ScoringWorker(
        client(control_server), scorer=slow, heartbeat_interval_seconds=0.01
    ).run_once()
    assert result["state"] == "stale"
    assert any(
        item["path"].endswith("/heartbeat") for item in control_server["requests"]
    )
    assert not any(
        item["path"].endswith("/complete") for item in control_server["requests"]
    )


def test_journal_reservation_is_sent_before_settlement(control_server):
    control = client(control_server)
    claim = control.claim()
    control.journal_call(
        claim,
        {
            "call_id": "judge-1",
            "status": "reserved",
            "stage": "judge",
            "attempt": 1,
            "reserved_cost_cny": 0.1,
        },
    )
    control.journal_call(
        claim,
        {
            "call_id": "judge-1",
            "status": "completed",
            "stage": "judge",
            "attempt": 1,
            "cost_cny": 0.02,
            "cost_status": "estimated",
        },
    )
    events = [
        item["body"]["call"]
        for item in control_server["requests"]
        if item["path"].endswith("/calls")
    ]
    assert [event["status"] for event in events] == ["reserved", "completed"]
    assert all(
        item["body"]["lease_token"] == "lease-a"
        for item in control_server["requests"]
        if item["path"].endswith("/calls")
    )


def test_control_client_refuses_unlisted_remote_or_plaintext_service():
    with pytest.raises(ValueError, match="loopback|HTTPS|allow"):
        EvalControlClient("http://untrusted.invalid/api/v1", "token", "worker")
    with pytest.raises(ValueError, match="allow"):
        EvalControlClient("https://untrusted.invalid/api/v1", "token", "worker")


def test_schema_failure_is_sanitized_in_worker_error(control_server):
    control_server["claim"]["artifact"]["case_type"] = "private-secret-do-not-log"
    result = ScoringWorker(client(control_server)).run_once()
    failure = next(
        item for item in control_server["requests"] if item["path"].endswith("/fail")
    )
    assert result["state"] == "failed"
    assert "private-secret" not in json.dumps(failure)


def test_worker_cost_metrics_include_judge_and_prediction_calls(
    control_server, quiz_case, quiz_artifact, monkeypatch
):
    from rag_eval.judges.ragas_adapter import RagasAdapter

    control_server["claim"].update(
        {
            "sample": quiz_case,
            "artifact": quiz_artifact,
            "config": {"external_judge": {"enabled": True}},
        }
    )
    quiz_artifact["usage"]["calls"] = [
        {
            "call_id": "generation-1",
            "stage": "generation",
            "attempt": 1,
            "cost_status": "estimated",
            "cost_cny": 0.2,
            "status": "completed",
            "input_tokens": 20,
            "output_tokens": 10,
        }
    ]

    def initialize(self, config, **kwargs):
        pass

    async def score(self, sample, artifact):
        return {
            "metrics": {},
            "calls": [
                {
                    "call_id": "judge-1",
                    "stage": "judge",
                    "attempt": 1,
                    "cost_status": "estimated",
                    "cost_cny": 0.3,
                    "status": "completed",
                    "input_tokens": 30,
                    "output_tokens": 5,
                }
            ],
        }

    monkeypatch.setattr(RagasAdapter, "__init__", initialize)
    monkeypatch.setattr(RagasAdapter, "score", score)
    assert (
        ScoringWorker(client(control_server), allow_external_judge=True).run_once()[
            "state"
        ]
        == "completed"
    )
    completion = next(
        item
        for item in control_server["requests"]
        if item["path"].endswith("/complete")
    )["body"]
    assert completion["metrics"]["total_cost_cny"]["value"] == 0.5
    assert completion["metrics"]["judge_cost_cny"]["value"] == 0.3
    assert completion["metrics"]["cost_per_valid_question_cny"][
        "value"
    ] == pytest.approx(0.5 / 3)


def test_retry_scoring_costs_keep_prior_failed_judge_attempts(control_server):
    control_server["claim"]["attempt"] = 2
    control_server["claim"]["previous_judge_calls"] = [
        {
            "call_id": "old-judge-call",
            "attempt": 1,
            "stage": "judge",
            "status": "timeout",
            "cost_status": "unknown",
            "cost_cny": None,
            "reserved_cost_cny": 0.2,
            "input_tokens": None,
            "output_tokens": None,
        }
    ]
    assert ScoringWorker(client(control_server)).run_once()["state"] == "completed"
    completion = next(
        item
        for item in control_server["requests"]
        if item["path"].endswith("/complete")
    )["body"]
    assert completion["metrics"]["total_cost_cny"]["status"] == "error"
    assert completion["metrics"]["judge_cost_cny"]["unknown_count"] == 1


def test_inflight_judge_receipt_is_returned_even_after_heartbeat_loses_lease(
    control_server, quiz_case, quiz_artifact, monkeypatch
):
    import asyncio

    from rag_eval.judges.ragas_adapter import RagasAdapter

    control_server["claim"].update(
        {
            "sample": quiz_case,
            "artifact": quiz_artifact,
            "config": {"external_judge": {"enabled": True}},
        }
    )
    control_server["responses"]["/api/v1/internal/eval/scoring/result-1/heartbeat"] = (
        409
    )

    def initialize(self, config, **kwargs):
        self.journal = kwargs["journal"]

    async def score(self, sample, artifact):
        call = {
            "call_id": "inflight",
            "stage": "judge",
            "status": "reserved",
            "reserved_cost_cny": 0.5,
        }
        self.journal(call)
        await asyncio.sleep(0.08)
        self.journal(
            {**call, "status": "completed", "cost_status": "estimated", "cost_cny": 0.2}
        )
        return {"metrics": {}, "calls": []}

    monkeypatch.setattr(RagasAdapter, "__init__", initialize)
    monkeypatch.setattr(RagasAdapter, "score", score)
    worker = ScoringWorker(
        client(control_server),
        heartbeat_interval_seconds=0.01,
        allow_external_judge=True,
    )
    assert worker.run_once()["state"] == "stale"
    calls = [
        request["body"]["call"]
        for request in control_server["requests"]
        if request["path"].endswith("/calls")
    ]
    assert [call["status"] for call in calls] == ["reserved", "completed"]


class PollingClock:
    """Advance only the worker's polling clock, leaving real HTTP timing alone."""

    def __init__(self, maximum_seconds=64):
        self.elapsed = 0.0
        self.maximum = maximum_seconds

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds
        if self.elapsed > self.maximum:
            raise AssertionError("worker kept retrying after its control outage budget")


def test_main_exits_nonzero_after_bounded_continuous_connection_refusal(
    monkeypatch, capsys
):
    from rag_eval import worker

    clock = PollingClock()
    monkeypatch.setattr(worker, "time", clock)
    monkeypatch.setenv("EVAL_WORKER_TOKEN", "test-control-token-not-for-logs")
    monkeypatch.delenv("EVAL_CONTROL_OUTAGE_SECONDS", raising=False)
    # Reserve a real loopback port without listening: every request receives
    # connection refusal, as in a scorer stuck in the API's old network namespace.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{reserved.getsockname()[1]}/api/v1"
        result = worker.main(["--base-url", base, "--poll-seconds", "30"])
    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines()]
    assert result == 2 and 60 <= clock.elapsed <= 62
    assert events[-1]["state"] == "control_unavailable"
    assert events[-1]["error_code"] == "control_outage_limit"
    assert events[-1]["consecutive_failures"] >= 2
    assert "test-control-token-not-for-logs" not in output and base not in output


def test_main_resets_failure_window_after_each_successful_idle_poll(
    control_server, monkeypatch, capsys
):
    from rag_eval import worker

    statuses = iter([503, 503, 200, 503, 503, 200, 401])
    control_server["claim"] = None
    control_server["responses"]["/api/v1/internal/eval/scoring/claim"] = lambda: next(
        statuses
    )
    clock = PollingClock(maximum_seconds=20)
    monkeypatch.setattr(worker, "time", clock)
    monkeypatch.setenv("EVAL_WORKER_TOKEN", "test-control-token")
    monkeypatch.setenv("EVAL_CONTROL_OUTAGE_SECONDS", "4")
    result = worker.main(["--base-url", control_server["base_url"]])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert result == 2
    assert [item["state"] for item in events].count("idle") == 2
    assert events[-1]["http_status"] == 401
    assert not any(item["state"] == "control_unavailable" for item in events)
    assert len(control_server["requests"]) == 7


@pytest.mark.parametrize("status", [401, 403])
def test_main_exits_immediately_on_auth_failure(
    control_server, monkeypatch, capsys, status
):
    from rag_eval import worker

    control_server["responses"]["/api/v1/internal/eval/scoring/claim"] = status
    clock = PollingClock(maximum_seconds=0)
    monkeypatch.setattr(worker, "time", clock)
    monkeypatch.setenv("EVAL_WORKER_TOKEN", "test-control-token")
    assert worker.main(["--base-url", control_server["base_url"]]) == 2
    assert len(control_server["requests"]) == 1
    assert json.loads(capsys.readouterr().out)["http_status"] == status


def test_main_once_preserves_failure_exit_without_waiting(control_server, monkeypatch):
    from rag_eval import worker

    control_server["responses"]["/api/v1/internal/eval/scoring/claim"] = 503
    clock = PollingClock(maximum_seconds=0)
    monkeypatch.setattr(worker, "time", clock)
    monkeypatch.setenv("EVAL_WORKER_TOKEN", "test-control-token")
    assert worker.main(["--base-url", control_server["base_url"], "--once"]) == 2
    assert len(control_server["requests"]) == 1


@pytest.mark.parametrize("configured_via", ["environment", "command_line"])
def test_main_applies_configured_control_outage_limit(
    control_server, monkeypatch, capsys, configured_via
):
    from rag_eval import worker

    control_server["responses"]["/api/v1/internal/eval/scoring/claim"] = 503
    clock = PollingClock(maximum_seconds=6)
    monkeypatch.setattr(worker, "time", clock)
    monkeypatch.setenv("EVAL_WORKER_TOKEN", "test-control-token")
    args = ["--base-url", control_server["base_url"]]
    if configured_via == "environment":
        monkeypatch.setenv("EVAL_CONTROL_OUTAGE_SECONDS", "4")
    else:
        monkeypatch.setenv("EVAL_CONTROL_OUTAGE_SECONDS", "20")
        args.extend(["--control-outage-seconds", "4"])
    assert worker.main(args) == 2
    assert clock.elapsed == 4
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["error_code"] == "control_outage_limit"
    assert events[-1]["consecutive_failures"] == 3
    assert len(control_server["requests"]) == 3


@pytest.mark.parametrize("limit", ["0", "3601", "nan", "inf"])
def test_main_rejects_unbounded_or_nonpositive_outage_setting(
    control_server, monkeypatch, limit
):
    from rag_eval import worker

    monkeypatch.setenv("EVAL_WORKER_TOKEN", "test-control-token")
    with pytest.raises(SystemExit) as error:
        worker.main(
            [
                "--base-url",
                control_server["base_url"],
                "--control-outage-seconds",
                limit,
            ]
        )
    assert error.value.code == 2
    assert control_server["requests"] == []
