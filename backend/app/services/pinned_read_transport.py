"""GET acquisition primitives promoted from the owned TLS lab; no POST interface."""

from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import time
from collections.abc import Iterable
from urllib.parse import urlsplit

import httpcore

from app.services.pinned_dns import (
    ResolutionCleanupFailure,
    ResolutionFailure,
    ResolutionTimeout,
    isolated_resolve,
)


class TransportBlocked(ValueError):
    pass


def target(url: str) -> str:
    if not isinstance(url, str) or not url.isascii() or re.search(r"[\x00-\x20\x7f\\]", url):
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


def resolve(host: str, timeout: float = 5) -> tuple[str, ...]:
    try:
        return isolated_resolve(host, timeout)
    except ResolutionTimeout:
        raise httpcore.ConnectTimeout("DNS deadline exceeded") from None
    except ResolutionCleanupFailure:
        raise TransportBlocked("DNS termination unconfirmed; resolver blocked") from None
    except ResolutionFailure:
        raise TransportBlocked("DNS resolution failed") from None


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
    family = socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET
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
        if host != self.host or port != 443 or self.used or local_address or socket_options:
            raise TransportBlocked("Unexpected connection")
        self.used = True
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise httpcore.ConnectTimeout("Connection deadline exceeded")
        sock = dial(self.addresses[0], min(remaining, timeout or remaining))
        return Stream(sock, self.host, self.deadline)
