"""Unregistered transport prototype. Never imported by the application/worker.

Opt-in is not send authorization. Callers must supply an already-approved URL;
approval, suppression, payload binding and UNKNOWN persistence are separate gates.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import ssl
import time
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpcore


class TransportBlocked(ValueError):
    pass


def target(url: str) -> str:
    if (
        not isinstance(url, str)
        or not url.isascii()
        or re.search(r"[\x00-\x20\x7f\\]", url)
    ):
        raise TransportBlocked("Invalid URL")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise TransportBlocked("Invalid URL") from None
    if (
        parts.scheme != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.fragment
        or host.endswith(".")
        or not re.fullmatch(r"[a-z0-9.-]+", host)
        or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in host.split(".")
        )
        or len(host) > 253
    ):
        raise TransportBlocked("Unsupported HTTPS target")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise TransportBlocked("Hostname required for TLS")
    return host


def resolve(host: str) -> tuple[str, ...]:
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise TransportBlocked("DNS resolution failed") from None
    addresses: list[str] = []
    for answer in answers:
        address = answer[4][0]
        if not isinstance(address, str):
            raise TransportBlocked("Invalid DNS result")
        addresses.append(address)
    return tuple(dict.fromkeys(addresses))


def public_addresses(answers: tuple[str, ...]) -> tuple[str, ...]:
    if not answers:
        raise TransportBlocked("Empty DNS result")
    for answer in answers:
        try:
            address = ipaddress.ip_address(answer)
        except ValueError:
            raise TransportBlocked("Invalid DNS address") from None
        if (
            not address.is_global
            or address.is_multicast
            or getattr(address, "ipv4_mapped", None) is not None
            or getattr(address, "sixtofour", None) is not None
            or getattr(address, "teredo", None) is not None
            or (
                address.version == 6
                and any(
                    address in ipaddress.ip_network(prefix)
                    for prefix in ("64:ff9b::/96", "64:ff9b:1::/48")
                )
            )
        ):
            raise TransportBlocked("Unsafe DNS address")
    return answers


def dial(address: str, timeout: float) -> socket.socket:
    """Numeric socket.connect: no hostname lookup, proxy or address fallback."""
    family = (
        socket.AF_INET6
        if ipaddress.ip_address(address).version == 6
        else socket.AF_INET
    )
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect((address, 443))
        return sock
    except OSError:
        sock.close()
        raise httpcore.ConnectError("Pinned connection failed") from None


class Stream(httpcore.NetworkStream):
    def __init__(self, sock: socket.socket, host: str, deadline: float) -> None:
        self.sock, self.host, self.deadline = sock, host, deadline

    def budget(self, timeout: float | None) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise httpcore.ReadTimeout("Transport deadline exceeded")
        return min(remaining, timeout if timeout is not None else remaining)

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        self.sock.settimeout(self.budget(timeout))
        try:
            return self.sock.recv(max_bytes)
        except TimeoutError:
            raise httpcore.ReadTimeout("Response timeout") from None
        except OSError:
            raise httpcore.ReadError("Response read failed") from None

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.sock.settimeout(self.budget(timeout))
        try:
            self.sock.sendall(buffer)
        except TimeoutError:
            raise httpcore.WriteTimeout("Request timeout") from None
        except OSError:
            raise httpcore.WriteError("Request write failed") from None

    def close(self) -> None:
        self.sock.close()

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> Stream:
        if (
            server_hostname != self.host
            or not ssl_context.check_hostname
            or ssl_context.verify_mode != ssl.CERT_REQUIRED
        ):
            self.close()
            raise TransportBlocked("TLS identity guard failed")
        self.sock.settimeout(self.budget(timeout))
        try:
            self.sock = ssl_context.wrap_socket(self.sock, server_hostname=self.host)
        except OSError:
            self.close()
            raise httpcore.ConnectError("TLS verification failed") from None
        return self

    def get_extra_info(self, info: str) -> ssl.SSLSocket | None:
        if info == "ssl_object" and isinstance(self.sock, ssl.SSLSocket):
            return self.sock
        return None


class PinnedBackend(httpcore.NetworkBackend):
    def __init__(self, host: str, addresses: tuple[str, ...], deadline: float) -> None:
        self.host, self.addresses, self.deadline = host, addresses, deadline
        self.used = False

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> Stream:
        if (
            host != self.host
            or port != 443
            or self.used
            or local_address
            or socket_options
        ):
            raise TransportBlocked("Unexpected connection")
        self.used = True
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise httpcore.ConnectTimeout("Connection deadline exceeded")
        sock = dial(self.addresses[0], min(remaining, timeout or remaining))
        return Stream(sock, self.host, self.deadline)


@dataclass(frozen=True)
class Result:
    status: int
    body: bytes
    pinned_ip: str


def exchange(
    url: str,
    *,
    method: str = "GET",
    body: bytes = b"",
    content_type: str = "application/octet-stream",
    context: ssl.SSLContext | None = None,
    timeout: float = 5,
    limit: int = 65536,
) -> Result:
    if os.environ.get("PINNED_TLS_LAB") != "1":
        raise TransportBlocked("Transport lab is disabled")
    if method not in ("GET", "POST") or (method == "GET" and body):
        raise TransportBlocked("Unsupported request")
    if not 0 < timeout <= 30 or not 0 < limit <= 65536 or len(body) > 65536:
        raise TransportBlocked("Invalid bounds")
    if not re.fullmatch(r"[a-zA-Z0-9/+;= ._-]{1,128}", content_type):
        raise TransportBlocked("Invalid content type")
    host = target(url)
    # Explicit certifi trust: SSL_CERT_FILE/SSL_CERT_DIR cannot replace trust roots.
    context = context if context is not None else httpcore.default_ssl_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise TransportBlocked("TLS verification required")
    deadline = time.monotonic() + timeout
    addresses = public_addresses(resolve(host))
    backend = PinnedBackend(host, addresses, deadline)
    headers = [
        (b"Host", host.encode()),
        (b"Accept-Encoding", b"identity"),
        (b"Connection", b"close"),
        (b"Content-Type", content_type.encode()),
    ]
    with (
        httpcore.ConnectionPool(
            ssl_context=context,
            network_backend=backend,
            retries=0,
            max_connections=1,
            max_keepalive_connections=0,
            http2=False,
        ) as pool,
        pool.stream(
            method,
            url,
            headers=headers,
            content=body,
            extensions={
                "timeout": dict.fromkeys(("connect", "read", "write", "pool"), timeout)
            },
        ) as response,
    ):
        if 300 <= response.status < 400:
            raise TransportBlocked("Redirect requires new approval")
        if any(
            k.lower() == b"content-encoding" and v.lower() != b"identity"
            for k, v in response.headers
        ):
            raise TransportBlocked("Compressed response is unsupported")
        data = bytearray()
        for chunk in response.iter_stream():
            if len(data) + len(chunk) > limit:
                raise TransportBlocked("Response too large")
            data.extend(chunk)
        return Result(response.status, bytes(data), addresses[0])
