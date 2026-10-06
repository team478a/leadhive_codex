"""Tests-only subprocess fixture: replaces DNS before calling the real worker codec."""

import importlib.util
import os
import socket
import sys
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "dns_worker", Path(__file__).with_name("dns_worker.py")
)
assert spec is not None and spec.loader is not None
dns_worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dns_worker)


def answer(*args, **kwargs):
    if sys.argv[1] == "hang.example":
        Path(sys.argv[2]).write_text("ready", encoding="ascii")
        time.sleep(60)
        Path(sys.argv[2]).write_text("unexpected late result", encoding="ascii")
    if sys.argv[1] == "crash.example":
        raise socket.gaierror("fake secret diagnostic")
    if sys.argv[1] == "env.example":
        allowed = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "LC_CTYPE"}
        if any(key.upper() not in allowed for key in os.environ):
            raise ValueError("Environment inherited")
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (
            socket.AF_INET6,
            socket.SOCK_STREAM,
            6,
            "",
            ("2606:4700:4700::1111", 443, 0, 0),
        ),
    ]


if __name__ == "__main__":
    socket.getaddrinfo = answer
    if sys.argv[1] == "invalid.example":
        print('{"version":true,"addresses":["8.8.8.8"]}')
    else:
        try:
            sys.stdout.buffer.write(dns_worker.lookup(sys.argv[1]))
        except (ValueError, OSError):
            sys.exit(2)
