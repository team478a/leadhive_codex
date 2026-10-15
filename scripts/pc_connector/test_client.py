import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from uuid import uuid4

import client
import pytest


def record(project):
    snapshot = {"subject": "private", "sender": {"email": "private@example.com"}}
    digest = hashlib.sha256(
        json.dumps(
            snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return {
        "id": str(uuid4()),
        "project_id": str(project),
        "channel": "form",
        "delivery_method": "form_codex",
        "status": "APPROVED",
        "canonicalization_version": "json-v1",
        "payload_snapshot": snapshot,
        "payload_hash": digest,
        "payload_version": 1,
        "approved_payload_hash": digest,
        "approved_payload_version": 1,
        "approved_by_user_id": str(uuid4()),
        "approved_at": "2026-10-10T00:00:00Z",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }


def test_manifest_never_exports_message_sender_or_execution_authority():
    project = uuid4()
    result = client.review_manifest([record(project)], project)
    serialized = json.dumps(result)
    assert "private" not in serialized
    assert result["execution_allowed"] is False
    assert result["items"][0]["execution_allowed"] is False
    assert result["items"][0]["status_at_read"] == "APPROVED"


@pytest.mark.parametrize(
    "change",
    [
        {"project_id": str(uuid4())},
        {"payload_hash": "x" * 64},
        {"payload_version": True},
        {"approved_payload_version": 2},
        {"approved_by_user_id": None},
        {"expires_at": "2026-10-10"},
        {"canonicalization_version": "other"},
        {"status": "SENT"},
    ],
)
def test_invalid_binding_fails_closed(change):
    project = uuid4()
    with pytest.raises(client.ConnectorError):
        client.review_manifest([record(project) | change], project)


def test_expired_pending_and_approved_are_not_current():
    project = uuid4()
    row = record(project) | {"expires_at": "2020-01-01T00:00:00Z"}
    assert (
        client.review_manifest([row], project)["items"][0]["status_at_read"]
        == "EXPIRED"
    )


def test_duplicate_records_fail_and_non_codex_are_not_tasks():
    project = uuid4()
    row = record(project)
    with pytest.raises(client.ConnectorError):
        client.review_manifest([row, row], project)
    assert not client.review_manifest(
        [row | {"delivery_method": "form_direct"}], project
    )["items"]


@pytest.mark.parametrize(
    "server",
    [
        "http://cloud.example",
        "https://user:secret@cloud.example",
        "https://cloud.example/path",
        "https://cloud.example?token=secret",
        "https://cloud.example/#fragment",
        "https://cloud.example:8000",
        "https://cloud.example\n",
        "http://localhost:8000",
    ],
)
def test_origin_rejects_untrusted_transport_or_embedded_secrets(server):
    with pytest.raises(client.ConnectorError):
        client.origin(server, local=True)


def test_loopback_requires_explicit_option():
    with pytest.raises(client.ConnectorError):
        client.origin("http://127.0.0.1:8000")
    assert client.origin("http://127.0.0.1:8000", local=True) == "http://127.0.0.1:8000"


def test_redirect_is_never_followed():
    with pytest.raises(client.ConnectorError):
        client.NoRedirect().redirect_request(
            None, None, 302, "", {}, "https://evil.example"
        )


class Response(BytesIO):
    status = 200
    headers = Message()
    headers["Content-Type"] = "application/json"


def test_bounded_transport_has_only_get_and_no_cookie(monkeypatch):
    project = uuid4()
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            assert timeout == 15
            return Response(json.dumps([record(project) for _ in range(50)]).encode())

    monkeypatch.setattr(client, "build_opener", lambda *args: Opener())
    result = client.collect("https://cloud.example", project, "lh_agent_test", pages=3)
    assert result["request_count"] == 3
    assert result["raw_records_read"] == 150
    assert result["possibly_truncated"] is True
    assert all(
        r.method == "GET" and not r.has_header("Cookie") and r.data is None
        for r in requests
    )
    assert "offset=100" in requests[-1].full_url


@pytest.mark.parametrize(
    "content",
    [b"invalid", b"{}", b"[1]", b"x" * (client.MAX_BYTES + 1)],
    ids=["invalid-json", "wrong-shape", "wrong-item", "over-size"],
)
def test_bad_or_large_responses_are_rejected(content):
    class Opener:
        def open(self, *args, **kwargs):
            return Response(content)

    with pytest.raises(client.ConnectorError):
        client.read_page(Opener(), "https://cloud.example", uuid4(), "lh_agent_test", 0)


def test_missing_token_does_not_attempt_network(monkeypatch):
    monkeypatch.setattr(
        client, "build_opener", lambda *args: pytest.fail("network created")
    )
    with pytest.raises(client.ConnectorError):
        client.collect("https://cloud.example", uuid4(), "")


def test_output_never_overwrites_and_errors_do_not_leak(monkeypatch, tmp_path, capsys):
    path = tmp_path / "private.json"
    path.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(client, "collect", lambda *args: {})
    monkeypatch.setattr(
        "sys.argv",
        [
            "client",
            "--server",
            "https://cloud.example",
            "--project",
            str(uuid4()),
            "--output",
            str(path),
        ],
    )
    assert client.main() == 1
    assert path.read_text() == "existing"
    assert str(path) not in capsys.readouterr().err


@pytest.mark.parametrize("redirect", [False, True], ids=["read", "redirect-refused"])
def test_real_loopback_http_transport_without_external_requests(redirect):
    project = uuid4()
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            received.append((self.path, dict(self.headers)))
            if redirect:
                self.send_response(302)
                self.send_header("Location", "https://must-not-be-contacted.example/")
                self.end_headers()
                return
            payload = json.dumps([record(project)]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        args = (f"http://127.0.0.1:{server.server_port}", project, "lh_agent_test")
        if redirect:
            with pytest.raises(client.ConnectorError):
                client.collect(*args, local=True)
        else:
            result = client.collect(*args, local=True)
            assert len(result["items"]) == 1
            assert result["execution_allowed"] is False
        assert len(received) == 1
        assert received[0][1]["Authorization"] == "Bearer lh_agent_test"
        assert "Cookie" not in received[0][1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
