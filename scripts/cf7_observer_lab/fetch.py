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
from failures import ObservationFailure, caused_by

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
        raise ObservationFailure("CANCELLED")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ObservationFailure("OBSERVATION_TIMEOUT")
    return remaining


def metadata(headers: list[tuple[bytes, bytes]], *, robots: bool) -> tuple[str, int]:
    # Checked before reading the body. httpcore/h11 has its own header parse cap;
    # this smaller acceptance cap is not an OS allocation/sandbox guarantee.
    if len(headers) > 32 or sum(len(k) + len(v) for k, v in headers) > 8192:
        raise ObservationFailure("OBSERVATION_RESPONSE_INVALID")
    values: dict[bytes, list[bytes]] = {}
    for key, value in headers:
        values.setdefault(key.lower(), []).append(value)
    for key in (b"content-type", b"content-length", b"content-encoding"):
        if len(values.get(key, [])) > 1:
            raise ObservationFailure("OBSERVATION_RESPONSE_INVALID")
    if b"transfer-encoding" in values:
        raise ObservationFailure("OBSERVATION_RESPONSE_INVALID")
    if values.get(b"content-encoding", [b"identity"])[0].lower() != b"identity":
        raise ObservationFailure("OBSERVATION_RESPONSE_INVALID")
    content_type = values.get(b"content-type", [b""])[0].lower()
    expected = b"text/plain" if robots else b"text/html"
    if content_type not in (expected, expected + b"; charset=utf-8"):
        raise ObservationFailure("OBSERVATION_RESPONSE_INVALID")
    length = values.get(b"content-length", [b""])[0]
    limit = 16384 if robots else 65536
    if not length.isdigit() or len(length) > 6 or not 0 < int(length) <= limit:
        raise ObservationFailure("OBSERVATION_RESPONSE_INVALID")
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
        raise ObservationFailure("LAB_DISABLED")
    remaining = checkpoint(deadline, cancelled)
    host = transport.target(url)
    try:
        answers = transport.resolve(host, remaining)
    except httpcore.TimeoutException:
        raise ObservationFailure("OBSERVATION_TIMEOUT") from None
    except transport.TransportBlocked:
        raise ObservationFailure("OBSERVATION_DNS_FAILED") from None
    try:
        addresses = transport.public_addresses(answers)
    except transport.TransportBlocked:
        raise ObservationFailure("OBSERVATION_UNSAFE_DNS") from None
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
            raise ObservationFailure("OBSERVATION_HTTP_REJECTED")
        media_type, length = metadata(response.headers, robots=robots)
        data = bytearray()
        for chunk in response.iter_stream():
            checkpoint(deadline, cancelled)
            if len(data) + len(chunk) > length:
                raise ObservationFailure("OBSERVATION_RESPONSE_INVALID")
            data.extend(chunk)
        if len(data) != length:
            raise ObservationFailure("OBSERVATION_RESPONSE_INVALID")
        checkpoint(deadline, cancelled)
        return bytes(data), media_type, addresses[0]


def robots_allowed(body: bytes) -> bool:
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ObservationFailure("OBSERVATION_ROBOTS_INVALID") from None
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise ObservationFailure("OBSERVATION_ROBOTS_INVALID")
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
            raise ObservationFailure("OBSERVATION_ROBOTS_INVALID")
        if key == "user-agent":
            if not value or any(c.isspace() for c in value):
                raise ObservationFailure("OBSERVATION_ROBOTS_INVALID")
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif (
            not agents
            or (value and not value.startswith("/"))
            or any(c in value for c in "*$%")
        ):
            raise ObservationFailure("OBSERVATION_ROBOTS_INVALID")
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
        raise ObservationFailure("OBSERVATION_ROBOTS_INVALID")
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
        raise ObservationFailure("LAB_DISABLED")
    if url != PAGE:
        raise ObservationFailure("LAB_DISABLED")
    if not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ObservationFailure("LAB_DISABLED")
    context = context if context is not None else httpcore.default_ssl_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise ObservationFailure("OBSERVATION_TLS_FAILED")
    cancelled = cancelled if cancelled is not None else Event()
    deadline = time.monotonic() + timeout
    try:
        robots, _, robots_ip = get(ROBOTS, context, deadline, cancelled, robots=True)
        if not robots_allowed(robots):
            raise ObservationFailure("OBSERVATION_ROBOTS_DENIED")
        body, media_type, page_ip = get(
            PAGE, context, deadline, cancelled, robots=False
        )
    except httpcore.NetworkError as error:
        code = (
            "OBSERVATION_TLS_FAILED"
            if caused_by(error, ssl.SSLError)
            else "OBSERVATION_TIMEOUT"
            if caused_by(error, TimeoutError)
            else "OBSERVATION_NETWORK_FAILED"
        )
        raise ObservationFailure(code) from None
    except httpcore.TimeoutException:
        raise ObservationFailure("OBSERVATION_TIMEOUT") from None
    except httpcore.ProtocolError:
        raise ObservationFailure("OBSERVATION_RESPONSE_INVALID") from None
    checkpoint(deadline, cancelled)
    try:
        observation = observer.analyze(PAGE, body, status=200, media_type=media_type)
    except ValueError:
        raise ObservationFailure("OBSERVATION_PARSE_FAILED") from None
    checkpoint(deadline, cancelled)
    return FetchResult(
        observation,
        hashlib.sha256(robots).hexdigest(),
        (robots_ip, page_ip),
        body,
        robots,
        media_type,
    )
