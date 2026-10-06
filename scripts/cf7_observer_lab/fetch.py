"""Owned-host GET integration experiment; never imported by app or worker."""

from __future__ import annotations

import hashlib
import math
import os
import ssl
import time
from dataclasses import dataclass, field
from threading import Event

import httpcore
import observer
import transport

PAGE = "https://managed.example/contact/"
ROBOTS = "https://managed.example/robots.txt"
USER_AGENT = "LeadHiveObserverLab"


@dataclass(frozen=True)
class FetchResult:
    observation: observer.Observation = field(repr=False)
    robots_sha256: str
    pinned_ips: tuple[str, str]
    body: bytes = field(repr=False)
    robots: bytes = field(repr=False)
    media_type: str


def checkpoint(deadline: float, cancelled: Event) -> float:
    if cancelled.is_set():
        raise transport.TransportBlocked("Observation cancelled")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise transport.TransportBlocked("Observation deadline exceeded")
    return remaining


def metadata(headers: list[tuple[bytes, bytes]], *, robots: bool) -> tuple[str, int]:
    # Checked before reading the body. httpcore/h11 has its own header parse cap;
    # this smaller acceptance cap is not an OS allocation/sandbox guarantee.
    if len(headers) > 32 or sum(len(k) + len(v) for k, v in headers) > 8192:
        raise transport.TransportBlocked("Response headers too large")
    values: dict[bytes, list[bytes]] = {}
    for key, value in headers:
        values.setdefault(key.lower(), []).append(value)
    for key in (b"content-type", b"content-length", b"content-encoding"):
        if len(values.get(key, [])) > 1:
            raise transport.TransportBlocked("Ambiguous response metadata")
    if b"transfer-encoding" in values:
        raise transport.TransportBlocked("Transfer encoding unsupported")
    if values.get(b"content-encoding", [b"identity"])[0].lower() != b"identity":
        raise transport.TransportBlocked("Compression unsupported")
    content_type = values.get(b"content-type", [b""])[0].lower()
    expected = b"text/plain" if robots else b"text/html"
    if content_type not in (expected, expected + b"; charset=utf-8"):
        raise transport.TransportBlocked("Unsupported response type")
    length = values.get(b"content-length", [b""])[0]
    limit = 16384 if robots else 65536
    if not length.isdigit() or len(length) > 6 or not 0 < int(length) <= limit:
        raise transport.TransportBlocked("Invalid response length")
    return content_type.decode("ascii"), int(length)


def get(
    url: str,
    context: ssl.SSLContext,
    deadline: float,
    cancelled: Event,
    *,
    robots: bool,
) -> tuple[bytes, str, str]:
    if os.environ.get("CF7_OBSERVER_GET_LAB") != "1" or url != (
        ROBOTS if robots else PAGE
    ):
        raise transport.TransportBlocked("Only owned lab GET supported")
    remaining = checkpoint(deadline, cancelled)
    host = transport.target(url)
    addresses = transport.public_addresses(transport.resolve(host, remaining))
    remaining = checkpoint(deadline, cancelled)
    backend = transport.PinnedBackend(host, addresses, deadline)
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
            "GET",
            url,
            headers=[
                (b"Host", host.encode()),
                (b"User-Agent", USER_AGENT.encode()),
                (b"Accept-Encoding", b"identity"),
                (b"Connection", b"close"),
            ],
            extensions={
                "timeout": dict.fromkeys(
                    ("connect", "read", "write", "pool"), remaining
                )
            },
        ) as response,
    ):
        checkpoint(deadline, cancelled)
        if response.status != 200:
            raise transport.TransportBlocked("Response status unsupported")
        media_type, length = metadata(response.headers, robots=robots)
        data = bytearray()
        for chunk in response.iter_stream():
            checkpoint(deadline, cancelled)
            if len(data) + len(chunk) > length:
                raise transport.TransportBlocked("Response length exceeded")
            data.extend(chunk)
        if len(data) != length:
            raise transport.TransportBlocked("Response length mismatch")
        checkpoint(deadline, cancelled)
        return bytes(data), media_type, addresses[0]


def robots_allowed(body: bytes) -> bool:
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise transport.TransportBlocked("Invalid robots encoding") from None
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise transport.TransportBlocked("Invalid robots text")
    # Conservative subset: unsupported directives (including crawl-delay) and
    # malformed policies stop, rather than being silently interpreted as allow.
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            if agents:
                groups.append((agents, rules))
                agents, rules = [], []
            continue
        key, separator, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not separator or key not in ("user-agent", "allow", "disallow"):
            raise transport.TransportBlocked("Unsupported robots policy")
        if key == "user-agent":
            if not value or any(c.isspace() for c in value):
                raise transport.TransportBlocked("Invalid robots agent")
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif (
            not agents
            or (value and not value.startswith("/"))
            or any(c in value for c in "*$%")
        ):
            raise transport.TransportBlocked("Invalid robots rule")
        else:
            rules.append((key, value))
    if agents:
        groups.append((agents, rules))
    applicable = [
        rules
        for agents, rules in groups
        if any(agent == "*" or agent in USER_AGENT.lower() for agent in agents)
    ]
    if not applicable:
        raise transport.TransportBlocked("Missing applicable robots policy")
    # Deliberately stricter than RFC longest-match precedence: a matching
    # disallow in ANY applicable group wins. Never weaken a prohibition via allow.
    return not any(
        key == "disallow" and value and "/contact/".startswith(value)
        for rules in applicable
        for key, value in rules
    )


def observe_owned_page(
    url: str = PAGE,
    *,
    context: ssl.SSLContext | None = None,
    timeout: float = 5,
    cancelled: Event | None = None,
) -> FetchResult:
    """Fixed lab destination. No method/body/header/credential override accepted.

    Cancellation is cooperative at stage/chunk boundaries; a blocked socket can
    wait until the shared deadline. Parsing has no process-level CPU deadline.
    """
    if os.environ.get("CF7_OBSERVER_GET_LAB") != "1":
        raise transport.TransportBlocked("Observer GET lab disabled")
    if url != PAGE:
        raise transport.TransportBlocked("Only owned lab contact page supported")
    if not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise transport.TransportBlocked("Invalid observation budget")
    context = context if context is not None else httpcore.default_ssl_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise transport.TransportBlocked("TLS verification required")
    cancelled = cancelled if cancelled is not None else Event()
    deadline = time.monotonic() + timeout
    try:
        robots, _, robots_ip = get(ROBOTS, context, deadline, cancelled, robots=True)
        if not robots_allowed(robots):
            raise transport.TransportBlocked("Robots disallows contact observation")
        body, media_type, page_ip = get(
            PAGE, context, deadline, cancelled, robots=False
        )
    except httpcore.NetworkError:
        raise transport.TransportBlocked("Observation network failure") from None
    except httpcore.TimeoutException:
        raise transport.TransportBlocked(
            "Observation network deadline exceeded"
        ) from None
    except httpcore.ProtocolError:
        raise transport.TransportBlocked("Observation protocol failure") from None
    checkpoint(deadline, cancelled)
    observation = observer.analyze(PAGE, body, status=200, media_type=media_type)
    checkpoint(deadline, cancelled)
    return FetchResult(
        observation,
        hashlib.sha256(robots).hexdigest(),
        (robots_ip, page_ip),
        body,
        robots,
        media_type,
    )
