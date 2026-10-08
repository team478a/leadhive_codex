"""Exact-target robots + HTML GET only, public pinned IP and shared deadline."""

import math
import ssl
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import certifi
import httpcore

from app.config import settings
from app.services import pinned_read_transport as transport
from app.services.scraper import FetchedPage, ScrapeError

USER_AGENT = "LeadHiveFormObserver"
GET_SLOTS = threading.BoundedSemaphore(4)


def tls_context() -> ssl.SSLContext:
    # Loading defaults would also consult SSL_CERT_FILE/SSL_CERT_DIR. Use only
    # the installed CA bundle here; environment settings cannot add trust roots.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=certifi.where())
    return context


class GetBlocked(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def remaining(deadline: float) -> float:
    budget = deadline - time.monotonic()
    if budget <= 0:
        raise GetBlocked("OBSERVATION_TIMEOUT")
    return budget


def fixed_target(url: str) -> tuple[str, str]:
    try:
        host = transport.target(url)
        parsed = urlsplit(url)
        if (
            len(url) > 2048
            or parsed.query
            or parsed.fragment
            or "%" in parsed.path
            or any(part in {".", ".."} for part in parsed.path.split("/"))
            or "//" in parsed.path
            or not parsed.path.startswith("/")
        ):
            raise ValueError
        robots = urlunsplit(("https", parsed.netloc, "/robots.txt", "", ""))
        return host, robots
    except ValueError:
        raise GetBlocked("OBSERVATION_TARGET_REJECTED") from None


def metadata(headers: list[tuple[bytes, bytes]], robots: bool) -> tuple[int | None, str]:
    if len(headers) > 64 or sum(len(k) + len(v) for k, v in headers) > 16384:
        raise GetBlocked("OBSERVATION_RESPONSE_INVALID")
    values: dict[bytes, list[bytes]] = {}
    for key, value in headers:
        values.setdefault(key.lower(), []).append(value)
    for key in (b"content-type", b"content-length", b"content-encoding", b"transfer-encoding"):
        if len(values.get(key, [])) > 1:
            raise GetBlocked("OBSERVATION_RESPONSE_INVALID")
    if values.get(b"content-encoding", [b"identity"])[0].lower() != b"identity":
        raise GetBlocked("OBSERVATION_RESPONSE_INVALID")
    transfer = values.get(b"transfer-encoding", [b""])[0].lower()
    if transfer not in {b"", b"chunked"} or (transfer and b"content-length" in values):
        raise GetBlocked("OBSERVATION_RESPONSE_INVALID")
    media = values.get(b"content-type", [b""])[0].lower().replace(b" ", b"")
    expected = b"text/plain" if robots else b"text/html"
    if media not in {expected, expected + b";charset=utf-8"}:
        raise GetBlocked("OBSERVATION_RESPONSE_INVALID")
    raw_length = values.get(b"content-length", [None])[0]
    length = None
    limit = 16384 if robots else 262144
    if raw_length is not None:
        if not raw_length.isdigit() or len(raw_length) > 6 or not 0 <= int(raw_length) <= limit:
            raise GetBlocked("OBSERVATION_RESPONSE_INVALID")
        length = int(raw_length)
    return length, media.decode("ascii")


def get_once(
    url: str,
    host: str,
    addresses: tuple[str, ...],
    deadline: float,
    context: ssl.SSLContext,
    *,
    robots: bool,
) -> bytes:
    # This internal primitive is fixed to the already-resolved same host and GET.
    if transport.target(url) != host:
        raise GetBlocked("OBSERVATION_TARGET_REJECTED")
    backend = transport.PinnedBackend(host, addresses, deadline)
    budget = remaining(deadline)
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
            extensions={"timeout": dict.fromkeys(("connect", "read", "write", "pool"), budget)},
        ) as response,
    ):
        remaining(deadline)
        if response.status != 200:
            raise GetBlocked("OBSERVATION_HTTP_REJECTED")
        length, _ = metadata(response.headers, robots)
        limit = 16384 if robots else 262144
        data = bytearray()
        for chunk in response.iter_stream():
            remaining(deadline)
            if len(data) + len(chunk) > limit or (
                length is not None and len(data) + len(chunk) > length
            ):
                raise GetBlocked("OBSERVATION_RESPONSE_INVALID")
            data.extend(chunk)
        if length is not None and len(data) != length:
            raise GetBlocked("OBSERVATION_RESPONSE_INVALID")
        remaining(deadline)
        return bytes(data)


def permits(robots: bytes, url: str) -> bool:
    try:
        policy = robots.decode("utf-8", errors="strict")
    except UnicodeError:
        raise GetBlocked("OBSERVATION_ROBOTS_INVALID") from None
    if not policy.strip() or any(ord(c) < 32 and c not in "\r\n\t" for c in policy):
        raise GetBlocked("OBSERVATION_ROBOTS_INVALID")
    # Reject unsupported/malformed directives instead of assuming they allow us.
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    for line in policy.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            if agents:
                groups.append((agents, rules))
                agents, rules = [], []
            continue
        key, separator, value = line.partition(":")
        key, value = key.lower().strip(), value.strip()
        if not separator or key not in {"user-agent", "allow", "disallow", "sitemap"}:
            raise GetBlocked("OBSERVATION_ROBOTS_INVALID")
        if key == "user-agent":
            if not value or any(c.isspace() for c in value):
                raise GetBlocked("OBSERVATION_ROBOTS_INVALID")
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        if key in {"allow", "disallow"} and value and not value.startswith("/"):
            raise GetBlocked("OBSERVATION_ROBOTS_INVALID")
        if key in {"allow", "disallow"} and any(c in value for c in "*$%"):
            raise GetBlocked("OBSERVATION_ROBOTS_INVALID")
        if key in {"allow", "disallow"}:
            if not agents:
                raise GetBlocked("OBSERVATION_ROBOTS_INVALID")
            rules.append((key, value))
    if agents:
        groups.append((agents, rules))
    applicable = [
        rules
        for agents, rules in groups
        if any(agent == "*" or agent in USER_AGENT.lower() for agent in agents)
    ]
    if not applicable:
        raise GetBlocked("OBSERVATION_ROBOTS_INVALID")
    path = urlsplit(url).path
    # Preserve any applicable prohibition; do not resolve ambiguity to allow.
    return not any(
        key == "disallow" and value and path.startswith(value)
        for rules in applicable
        for key, value in rules
    )


class TargetFetcher:
    def close(self) -> None:
        # Each GET owns and closes its pool/socket. No session/cookie jar.
        pass

    def fetch_html(self, url: str) -> FetchedPage:
        acquired = False
        try:
            host, robots_url = fixed_target(url)
            timeout = settings.scraper_timeout_seconds
            if not math.isfinite(timeout) or not 0 < timeout <= 30:
                raise GetBlocked("OBSERVATION_TIMEOUT")
            deadline = time.monotonic() + timeout
            acquired = GET_SLOTS.acquire(timeout=remaining(deadline))
            if not acquired:
                raise GetBlocked("OBSERVATION_TIMEOUT")
            addresses = transport.public_addresses(transport.resolve(host, remaining(deadline)))
            context = tls_context()
            robots = get_once(robots_url, host, addresses, deadline, context, robots=True)
            if not permits(robots, url):
                raise GetBlocked("OBSERVATION_ROBOTS_DENIED")
            body = get_once(url, host, addresses, deadline, context, robots=False)
            try:
                html = body.decode("utf-8", errors="strict")
            except UnicodeError:
                raise GetBlocked("OBSERVATION_RESPONSE_INVALID") from None
            remaining(deadline)
            return FetchedPage(url, html)
        except GetBlocked as error:
            raise ScrapeError(f"限定GETを停止しました（{error.code}）。") from None
        except httpcore.TimeoutException:
            raise ScrapeError("限定GETを停止しました（OBSERVATION_TIMEOUT）。") from None
        except (transport.TransportBlocked, httpcore.NetworkError, httpcore.ProtocolError, OSError):
            raise ScrapeError(
                "限定GETを停止しました（OBSERVATION_CONNECTION_REJECTED）。"
            ) from None
        finally:
            if acquired:
                GET_SLOTS.release()
