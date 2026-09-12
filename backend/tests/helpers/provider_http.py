"""Real loopback HTTP boundary for SDK tests; never forwards a request."""

import json
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Callable


@dataclass(frozen=True)
class ProviderRequest:
    path: str
    headers: dict[str, str]
    body: dict


@dataclass(frozen=True)
class ProviderReply:
    body: dict
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)


class ProviderHTTPServer:
    def __init__(self, respond: Callable[[ProviderRequest], ProviderReply]):
        self.respond = respond
        self.requests: list[ProviderRequest] = []
        self.errors: list[Exception] = []

    def __enter__(self):
        boundary = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                try:
                    payload = json.loads(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    )
                    request = ProviderRequest(
                        path=self.path,
                        headers={
                            key.lower(): value for key, value in self.headers.items()
                        },
                        body=payload,
                    )
                    boundary.requests.append(request)
                    reply = boundary.respond(request)
                except Exception as exc:
                    boundary.errors.append(exc)
                    reply = ProviderReply(
                        status=500,
                        body={
                            "type": "error",
                            "error": {
                                "type": "api_error",
                                "message": "Local test response handler failed",
                            },
                        },
                    )
                data = json.dumps(reply.body, ensure_ascii=False).encode("utf-8")
                self.send_response(reply.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                for key, value in reply.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.05), daemon=True
        )
        self.thread.start()
        return self

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def __exit__(self, exc_type, _exc, _traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        if exc_type is None:
            assert not self.thread.is_alive(), "Local provider server did not stop"
            assert not self.errors, f"Local provider handler failed: {self.errors!r}"


def anthropic_message(
    content: str | list[dict],
    *,
    model: str = "claude-local-test",
    input_tokens: int = 31,
    output_tokens: int = 17,
    stop_reason: str = "end_turn",
    usage_details: dict | None = None,
) -> dict:
    """Complete non-streaming Messages response with controlled, synthetic usage."""
    return {
        "id": "msg_local_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": content}]
        if isinstance(content, str)
        else content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            **(usage_details or {}),
        },
    }
