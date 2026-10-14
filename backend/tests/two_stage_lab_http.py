"""Anonymous two-stage multipart server and fixed loopback-only test transport."""

import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from app.services.form_execution_plan import FixtureResult, classify_fixture_result
from tests.fixture_plan_runner import unique_object


class TwoStageServer:
    def __init__(self, mode="success"):
        self.posts: list[str] = []
        self.tokens: dict[str, tuple[str, str, str, dict[str, str], datetime]] = {}
        self.accepted = 0
        self.lock = threading.Lock()
        self.response_held = threading.Event()
        self.response_release = threading.Event()
        lab = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, data, status=200):
                if mode == "hold_" + self.path.lstrip("/"):
                    lab.response_held.set()
                    if not lab.response_release.wait(timeout=30):
                        return
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Expected only when a test kills the waiting client.

            def do_GET(self):
                if self.path != "/contact":
                    self.send_error(404)
                    return
                self.reply(
                    {
                        "fingerprint": "a" * 64,
                        "confirm": "https://fixture.example/confirm",
                        "submit": "https://fixture.example/submit",
                    }
                )

            def do_POST(self):
                if self.path not in {"/confirm", "/submit"}:
                    self.send_error(404)
                    return
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 64000:
                    self.send_error(413)
                    return
                message = BytesParser(policy=policy.default).parsebytes(
                    ("Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n").encode()
                    + self.rfile.read(size)
                )
                values: dict[str, str] = {}
                for part in message.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    if (
                        not isinstance(name, str)
                        or not name
                        or name in values
                        or part.get_filename()
                    ):
                        self.send_error(422)
                        return
                    value = part.get_payload(decode=True)
                    if not isinstance(value, bytes):
                        self.send_error(422)
                        return
                    values[name] = value.decode("utf-8")
                attempt = self.headers["X-Lab-Attempt"]
                form = self.headers["X-Lab-Form"]
                payload_hash = self.headers["X-Lab-Payload"]
                with lab.lock:
                    lab.posts.append(self.path)
                    if self.path == "/confirm":
                        if attempt in lab.tokens:
                            self.send_error(409)
                            return
                        token = secrets.token_urlsafe(24)
                        expires = datetime.now(timezone.utc) + timedelta(minutes=5)
                        if mode == "expired_token":
                            expires = datetime.now(timezone.utc) - timedelta(seconds=1)
                        lab.tokens[attempt] = (
                            token,
                            form,
                            payload_hash,
                            values,
                            expires,
                        )
                        hidden = "".join(
                            f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">'
                            for k, v in values.items()
                        )
                        if mode == "changed_values":
                            hidden = hidden.replace("fixture@example.com", "other@example.com")
                        html = (
                            '<form method="post" enctype="multipart/form-data" '
                            'action="https://fixture.example/submit">'
                            + hidden
                            + f'<input type="hidden" name="fixture_token" value="{token}">'
                            + '<input type="submit" name="submitFinal" value="send"></form>'
                        )
                        self.reply(
                            {
                                "attempt_id": "wrong" if mode == "wrong_binding" else attempt,
                                "form_id": "wrong" if mode == "wrong_form" else form,
                                "payload_hash": "0" * 64 if mode == "wrong_hash" else payload_hash,
                                "expires_at": expires.isoformat(),
                                "token": token,
                                "html": html,
                            }
                        )
                        return
                    record = lab.tokens.pop(attempt, None)
                    token = values.pop("fixture_token", "")
                    final = values.pop("submitFinal", "")
                    if (
                        not record
                        or (token, form, payload_hash, values) != record[:4]
                        or final != "send"
                        or record[4] <= datetime.now(timezone.utc)
                    ):
                        self.send_error(409)
                        return
                    lab.accepted += 1
                    self.reply(
                        {
                            "form_id": form,
                            "attempt_id": attempt,
                            "stage": "final",
                            "status": "ambiguous" if mode == "ambiguous" else "fixture_accepted",
                        }
                    )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.response_release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class PinnedTwoStageTransport(httpx.BaseTransport):
    def __init__(self, port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Invalid lab port")
        self.port = port
        self.inner = httpx.HTTPTransport(retries=0)

    def handle_request(self, request):
        if (request.method, str(request.url)) not in {
            ("GET", "https://fixture.example/contact"),
            ("POST", "https://fixture.example/confirm"),
            ("POST", "https://fixture.example/submit"),
        }:
            raise ValueError("No unknown lab traffic")
        forwarded = httpx.Request(
            request.method,
            request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port),
            headers=request.headers,
            stream=request.stream,
            extensions=request.extensions,
        )
        return self.inner.handle_request(forwarded)

    def close(self):
        self.inner.close()


class TwoStageTransport:
    def __init__(self, port, after_confirm=None, before_post=None, timeout=0.5):
        self.port = port
        self.after_confirm = after_confirm
        self.before_post = before_post
        self.timeout = timeout

    def request(self, plan, attempt, stage, token=None):
        if self.before_post:
            self.before_post(stage)
        execution = plan.execution_plan
        values = [(item.name, (None, item.value)) for item in execution.field_values]
        if token is not None:
            values.extend([("fixture_token", (None, token)), ("submitFinal", (None, "send"))])
        with httpx.Client(
            transport=PinnedTwoStageTransport(self.port),
            trust_env=False,
            follow_redirects=False,
            timeout=self.timeout,
        ) as client:
            if stage == "confirm":
                observed = client.get(execution.form_url).json()
                if observed != {
                    "fingerprint": execution.field_fingerprint,
                    "confirm": execution.steps[0].url,
                    "submit": execution.steps[1].url,
                }:
                    return None
            with client.stream(
                "POST",
                execution.steps[0 if stage == "confirm" else 1].url,
                files=values,
                headers={
                    "X-Lab-Attempt": str(attempt),
                    "X-Lab-Form": execution.form_id,
                    "X-Lab-Payload": plan.approval_hash,
                },
            ) as response:
                if (
                    response.status_code != 200
                    or response.headers.get("Content-Type") != "application/json"
                ):
                    return None
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 64000:
                        return None
                return json.loads(raw, object_pairs_hook=unique_object)

    def confirm(self, plan, attempt):
        result = self.request(plan, attempt, "confirm")
        if self.after_confirm:
            self.after_confirm()
        return result

    def submit(self, plan, attempt, token):
        result = self.request(plan, attempt, "submit", token)
        if result is None:
            return False
        evidence = FixtureResult.model_validate_json(json.dumps(result))
        return (
            classify_fixture_result(
                evidence, form_id=plan.execution_plan.form_id, attempt_id=attempt
            )
            == "SUBMITTED"
        )
