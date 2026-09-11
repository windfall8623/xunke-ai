"""Lease-fenced scoring of approved JSON artifacts in an independent process."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import socket
import threading
import time
import uuid
from datetime import UTC, datetime

from .contracts import metric_config, uncertain
from .metric_registry import metric_applies
from .metrics import cost_metrics, score_sample
from .normalization import normalize_artifact
from .store import ControlError, EvalControlClient, StaleLease


class ClaimExpired(RuntimeError):
    pass


class ScoringWorker:
    def __init__(
        self,
        client: EvalControlClient,
        *,
        scorer=score_sample,
        heartbeat_interval_seconds: float | None = None,
        allow_external_judge: bool = False,
    ):
        self.client, self.scorer = client, scorer
        self.heartbeat_interval = heartbeat_interval_seconds or client.lease_seconds / 3
        if not 0 < self.heartbeat_interval < client.lease_seconds:
            raise ValueError(
                "heartbeat interval must be positive and less than the lease"
            )
        self.allow_external_judge = allow_external_judge

    def run_once(self) -> dict:
        claim = self.client.claim()
        if claim is None:
            return {"state": "idle"}
        summary = {"result_id": claim["result_id"], "attempt": claim["attempt"]}
        stop = threading.Event()
        heartbeat_errors = []
        judge_calls = []

        def ensure_active():
            if heartbeat_errors:
                raise heartbeat_errors[0]
            deadline = claim.get("deadline_at")
            if deadline:
                when = datetime.fromisoformat(deadline)
                if when.tzinfo is None:
                    raise ValueError("deadline requires timezone")
                if datetime.now(UTC) >= when:
                    raise ClaimExpired("deadline_exceeded")
            if claim["attempt"] > claim.get("max_scoring_attempts", 3):
                raise ClaimExpired("scoring_attempts_exhausted")

        def keep_lease():
            while not stop.wait(self.heartbeat_interval):
                try:
                    self.client.heartbeat(claim)
                except ControlError as exc:
                    heartbeat_errors.append(exc)
                    stop.set()

        heartbeat = threading.Thread(
            target=keep_lease, name="eval-scoring-heartbeat", daemon=True
        )
        try:
            ensure_active()
            heartbeat.start()
            config = metric_config(
                claim.get("config"), [claim["sample"].get("case_type")]
            )
            metrics = self.scorer(claim["sample"], claim["artifact"], config)
            judge_config = config.get("external_judge", {})
            if (
                judge_config.get("enabled")
                and claim["sample"].get("case_type") == "quiz"
            ):
                if not self.allow_external_judge:
                    metrics["ragas_faithfulness"] = uncertain(
                        0,
                        1,
                        1,
                        "external_judge_not_enabled_on_worker",
                        version=config["metric_version"],
                    )
                else:
                    from .judges.ragas_adapter import RagasAdapter

                    def journal(call):
                        if call.get("status") == "reserved":
                            ensure_active()
                        self.client.journal_call(
                            claim, {**call, "attempt": claim["attempt"]}
                        )

                    adapter = RagasAdapter(
                        judge_config, journal=journal, ensure_active=ensure_active
                    )
                    judge_result = asyncio.run(
                        adapter.score(claim["sample"], claim["artifact"])
                    )
                    metrics.update(judge_result["metrics"])
                    judge_calls = [
                        {**call, "attempt": claim["attempt"]}
                        for call in judge_result["calls"]
                    ]
            if judge_calls or claim.get("previous_judge_calls"):
                cost_artifact = normalize_artifact(claim["artifact"])
                usage = cost_artifact.setdefault("usage", {})
                usage["calls"] = [
                    *usage.get("calls", []),
                    *copy.deepcopy(claim.get("previous_judge_calls", [])),
                    *copy.deepcopy(judge_calls),
                ]
                confirmed = (
                    metrics.get("valid_question_yield", {})
                    .get("details", {})
                    .get("confirmed_valid")
                )
                metrics.update(
                    cost_metrics(
                        cost_artifact,
                        config,
                        confirmed,
                        validity=metrics.get("valid_question_yield"),
                    )
                )
            ensure_active()
            for name in metrics:
                if not metric_applies(name, claim["sample"]["case_type"]):
                    raise ValueError(
                        f"metric {name!r} does not apply to this case_type"
                    )
            self.client.complete(claim, metrics, judge_calls)
            return {"state": "completed", **summary}
        except StaleLease:
            return {"state": "stale", **summary}
        except (ClaimExpired, ValueError, ControlError) as exc:
            code = (
                str(exc)
                if isinstance(exc, ClaimExpired)
                else "scoring_input_invalid"
                if isinstance(exc, ValueError)
                else exc.code
            )
            try:
                self.client.fail(claim, code, judge_calls)
            except StaleLease:
                return {"state": "stale", **summary}
            return {"state": "failed", "error_code": code, **summary}
        except Exception:  # noqa: BLE001 -- journal a sanitized, bounded failure before the process continues
            try:
                self.client.fail(claim, "scoring_error", judge_calls)
            except StaleLease:
                return {"state": "stale", **summary}
            return {"state": "failed", "error_code": "scoring_error", **summary}
        finally:
            stop.set()
            if heartbeat.is_alive():
                heartbeat.join(timeout=2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Independent JSON scoring worker; never opens Chroma"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EVAL_CONTROL_URL", "http://127.0.0.1:8000/api/v1"),
        help="Internal API URL INCLUDING /api/v1",
    )
    parser.add_argument(
        "--worker-id", default=f"eval-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--allow-external-judge", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument(
        "--control-outage-seconds",
        type=float,
        default=os.environ.get("EVAL_CONTROL_OUTAGE_SECONDS", "60"),
        help="Exit nonzero after continuous control failures for this many seconds (default 60)",
    )
    args = parser.parse_args(argv)
    if not 0.1 <= args.poll_seconds <= 30:
        parser.error("poll interval must be between 0.1 and 30 seconds")
    if not 1 <= args.control_outage_seconds <= 3600:
        parser.error("control outage limit must be between 1 and 3600 seconds")
    try:
        client = EvalControlClient(
            args.base_url,
            os.environ.get("EVAL_WORKER_TOKEN", ""),
            args.worker_id,
            allowed_hosts=tuple(
                filter(None, os.environ.get("EVAL_WORKER_ALLOWED_HOSTS", "").split(","))
            ),
        )
    except ValueError as exc:
        parser.error(str(exc))
    worker = ScoringWorker(client, allow_external_judge=args.allow_external_judge)
    failure_since = None
    consecutive_failures = 0
    try:
        while True:
            try:
                state = worker.run_once()
                # A successful poll/lease response proves the control plane is
                # reachable again, including idle, stale and journaled failures.
                failure_since = None
                consecutive_failures = 0
                print(json.dumps(state, allow_nan=False), flush=True)
            except ControlError as exc:
                print(
                    json.dumps(
                        {
                            "state": "control_error",
                            "error_code": exc.code,
                            "http_status": exc.status_code,
                        }
                    ),
                    flush=True,
                )
                if args.once or exc.status_code in {401, 403}:
                    return 2
                consecutive_failures += 1
                failed_at = time.monotonic()
                if failure_since is None:
                    failure_since = failed_at
                outage_seconds = failed_at - failure_since
                if outage_seconds >= args.control_outage_seconds:
                    # Docker can retain an obsolete shared network namespace
                    # after the API restarts. Exiting lets the process supervisor
                    # reconnect the container without changing lease or cost data.
                    print(
                        json.dumps(
                            {
                                "state": "control_unavailable",
                                "error_code": "control_outage_limit",
                                "consecutive_failures": consecutive_failures,
                                "outage_seconds": round(outage_seconds, 3),
                            }
                        ),
                        flush=True,
                    )
                    return 2
            if args.once:
                return 0 if state["state"] in {"completed", "idle"} else 1
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
