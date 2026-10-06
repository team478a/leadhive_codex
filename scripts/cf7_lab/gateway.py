"""Loopback test gateway via Docker stdin; containers publish NO ports."""

import http.client
import io
import re
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class BytesSocket:
    def __init__(self, data):
        self.data = data

    def makefile(self, *args):
        return io.BytesIO(self.data)


def permitted_target(method, path):
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or not path.startswith("/"):
        return False
    if "\r" in path or "\n" in path:
        return False
    if method == "GET":
        return True
    return method == "POST" and bool(
        re.fullmatch(
            r"(?:/wp-json/|/(?:index\.php)?\?rest_route=/)"
            r"contact-form-7/v1/contact-forms/\d+/feedback",
            path,
        )
    )


@contextmanager
def gateway(container):
    if not re.fullmatch(r"leadhive-cf7-lab-[a-f0-9]{12}-wp", container):
        raise ValueError("Only this lab's WordPress container can be relayed")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log wire input, cookies, or response text.

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def forward(self):
            if not permitted_target(self.command, self.path):
                self.send_error(403)
                return
            length = self.headers.get("Content-Length", "0")
            if not length.isdigit() or int(length) > 64000:
                self.send_error(413)
                return
            if self.headers.get("Transfer-Encoding"):
                self.send_error(400)
                return
            body = self.rfile.read(int(length))
            port = self.server.server_address[1]
            # Only selected protocol headers; Host is the known loopback origin.
            headers = [
                f"{self.command} {self.path} HTTP/1.1",
                f"Host: 127.0.0.1:{port}",
                "Connection: close",
                f"Content-Length: {len(body)}",
            ]
            for name in (
                "Content-Type",
                "Accept",
                "Accept-Encoding",
                "User-Agent",
                "Referer",
            ):
                value = self.headers.get(name)
                if value:
                    if "\r" in value or "\n" in value:
                        self.send_error(400)
                        return
                    headers.append(name + ": " + value)
            raw = ("\r\n".join(headers) + "\r\n\r\n").encode("latin-1") + body
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        container,
                        "php",
                        "/opt/cf7-lab/relay.php",
                    ],
                    input=raw,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                if result.returncode:
                    raise OSError("Lab relay failed")
                response = http.client.HTTPResponse(
                    BytesSocket(result.stdout), method=self.command
                )
                response.begin()
                content = response.read(2_000_001)
                if len(content) > 2_000_000:
                    raise OSError("Lab relay oversized")
                self.send_response(response.status)
                for name, value in response.getheaders():
                    if name.lower() not in {
                        "connection",
                        "transfer-encoding",
                        "content-length",
                        "server",
                        "date",
                        "set-cookie",
                    }:
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except (OSError, subprocess.SubprocessError, http.client.HTTPException):
                try:
                    self.send_error(502, "Local lab relay failed")
                except OSError:
                    pass  # Browser closed a static-resource connection; never retry.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
