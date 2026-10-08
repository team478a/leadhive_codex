"""Anonymous response server. Receives only local synthetic input."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FixtureServer:
    def __init__(self, mode="success", fingerprint="a" * 64):
        self.posts = []
        self.accepted = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        lab = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path != "/contact":
                    self.send_error(404)
                    return
                body = json.dumps(
                    {
                        "form_url": "https://fixture.example/contact",
                        "action_url": "https://fixture.example/submit",
                        "fingerprint": fingerprint,
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path != "/submit":
                    self.send_error(404)
                    return
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with lab.lock:
                    lab.posts.append(request)
                lab.accepted.set()
                if mode in {"timeout", "hold_accepted"}:
                    lab.release.wait(5)
                if mode == "disconnect":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                result = {
                    "form_id": request["form_id"],
                    "attempt_id": request["attempt_id"],
                    "stage": "final",
                    "status": "fixture_accepted",
                }
                if mode == "wrong_form":
                    result["form_id"] = "different"
                if mode == "wrong_attempt":
                    result["attempt_id"] = "00000000-0000-0000-0000-000000000099"
                if mode == "confirmation":
                    result["stage"] = "confirmation"
                if mode in {"ambiguous", "validation_error", "mail_sent"}:
                    result["status"] = mode
                body = json.dumps(result).encode()
                if mode == "duplicate_json":
                    body = body[:-1] + b',"status":"fixture_accepted"}'
                if mode == "malformed":
                    body = b"not-json"
                if mode == "oversized":
                    body = b" " * 65000 + body
                status = 307 if mode == "redirect" else 201 if mode == "wrong_http" else 200
                self.send_response(status)
                self.send_header(
                    "Content-Type", "text/html" if mode == "html" else "application/json"
                )
                self.send_header(
                    "Content-Length", str(len(body) + 100 if mode == "truncated" else len(body))
                )
                if mode == "redirect":
                    self.send_header("Location", "https://fixture.example/submit")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
