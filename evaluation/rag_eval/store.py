"""Internal HTTP control plane; no database or vector-store access.

base_url includes /api/v1, for example http://127.0.0.1:8000/api/v1.
Redirects and ambient proxies are disabled so service credentials cannot be
forwarded to a different origin. Only idempotently fenced updates are retried.
"""

from __future__ import annotations

import ipaddress
import time
import uuid
from urllib.parse import quote, urlsplit

import httpx


class ControlError(RuntimeError):
    def __init__(self, code: str, status_code: int | None = None):
        super().__init__(code)
        self.code, self.status_code = code, status_code


class StaleLease(ControlError):
    pass


class EvalControlClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        worker_id: str,
        *,
        lease_seconds: int = 120,
        timeout_seconds: float = 10,
        max_http_attempts: int = 3,
        allowed_hosts: tuple[str, ...] | list[str] = (),
        max_payload_bytes: int = 64 * 1024 * 1024,
    ):
        parsed = urlsplit(base_url)
        hostname = (parsed.hostname or "").lower()
        try:
            loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            loopback = hostname == "localhost"
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not hostname
        ):
            raise ValueError("control URL must have a clean allowed origin")
        if not loopback and (parsed.scheme != "https" or hostname not in allowed_hosts):
            raise ValueError(
                "control server requires loopback or an explicitly allowed HTTPS host"
            )
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("control URL requires HTTP loopback or HTTPS")
        if not token or not worker_id:
            raise ValueError("worker service token and worker_id are required")
        if (
            not 5 <= lease_seconds <= 3600
            or not 0 < timeout_seconds <= 60
            or not 1 <= max_http_attempts <= 5
        ):
            raise ValueError(
                "control lease, timeout, and retry budgets must be bounded"
            )
        self.base_url = base_url.rstrip("/")
        self.worker_id, self.lease_seconds = worker_id, lease_seconds
        self.max_http_attempts, self.max_payload_bytes = (
            max_http_attempts,
            max_payload_bytes,
        )
        self.client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    def close(self):
        self.client.close()

    def _post(self, path: str, payload: dict, *, retry: bool = True):
        attempts = self.max_http_attempts if retry else 1
        request_id = str(uuid.uuid4())
        for attempt in range(attempts):
            try:
                response = self.client.post(
                    f"{self.base_url}/internal/eval/scoring{path}",
                    json=payload,
                    headers={"X-Worker-Request-ID": request_id},
                )
                if response.status_code == 204:
                    return None
                if response.status_code == 409:
                    raise StaleLease("stale_scoring_lease", 409)
                if (
                    response.status_code in {429, 502, 503, 504}
                    and attempt + 1 < attempts
                ):
                    time.sleep(min(0.25 * 2**attempt, 2))
                    continue
                if not 200 <= response.status_code < 300:
                    raise ControlError("control_request_rejected", response.status_code)
                if len(response.content) > self.max_payload_bytes:
                    raise ControlError("control_payload_too_large")
                value = response.json()
                if (
                    isinstance(value, dict)
                    and "data" in value
                    and "result_id" not in value
                ):
                    value = value["data"]
                return value
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt + 1 >= attempts:
                    raise ControlError("control_transport_error") from None
                time.sleep(min(0.25 * 2**attempt, 2))
            except ValueError:
                raise ControlError("invalid_control_json") from None
        raise ControlError("control_retry_exhausted")

    @staticmethod
    def fence(claim: dict) -> dict:
        return {"lease_token": claim["lease_token"], "attempt": claim["attempt"]}

    @staticmethod
    def result_path(claim: dict, action: str) -> str:
        return f"/{quote(str(claim['result_id']), safe='')}/{action}"

    def claim(self) -> dict | None:
        # Claim has no result lease yet; blindly retrying a lost response could
        # acquire a second job. The server expires the first lease if necessary.
        result = self._post(
            "/claim",
            {"worker_id": self.worker_id, "lease_seconds": self.lease_seconds},
            retry=False,
        )
        if result is None:
            return None
        if not isinstance(result, dict) or not all(
            key in result
            for key in ("result_id", "lease_token", "attempt", "sample", "artifact")
        ):
            raise ControlError("invalid_scoring_claim")
        return result

    def heartbeat(self, claim: dict):
        return self._post(
            self.result_path(claim, "heartbeat"),
            {**self.fence(claim), "lease_seconds": self.lease_seconds},
        )

    def complete(
        self, claim: dict, metrics: dict, judge_calls: list[dict] | None = None
    ):
        return self._post(
            self.result_path(claim, "complete"),
            {
                **self.fence(claim),
                "metrics": metrics,
                "judge_calls": judge_calls or [],
                "status": "completed",
            },
        )

    def fail(self, claim: dict, code: str, judge_calls: list[dict] | None = None):
        return self._post(
            self.result_path(claim, "fail"),
            {
                **self.fence(claim),
                "error_code": code,
                "error_message": "Scoring did not complete; inspect controlled worker diagnostics by result ID.",
                "judge_calls": judge_calls or [],
            },
        )

    def journal_call(self, claim: dict, call: dict):
        return self._post(
            self.result_path(claim, "calls"), {**self.fence(claim), "call": call}
        )
