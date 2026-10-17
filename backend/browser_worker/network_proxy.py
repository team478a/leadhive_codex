"""Fail-closed HTTPS CONNECT proxy for isolated browser jobs."""

from __future__ import annotations

import asyncio
import ipaddress
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.services.pinned_read_transport import public_addresses, resolve

Resolver = Callable[[str], tuple[str, ...]]
Dialer = Callable[[str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


class ProxyBlocked(ConnectionError):
    pass


def _valid_hostname(host: str) -> bool:
    return (
        len(host) <= 253
        and bool(re.fullmatch(r"[a-z0-9.-]+", host))
        and all(
            label and len(label) <= 63 and not label.startswith("-") and not label.endswith("-")
            for label in host.split(".")
        )
    )


def _normalized_host(host: str) -> str:
    normalized = host.lower()
    if normalized.endswith(".") or not _valid_hostname(normalized):
        raise ProxyBlocked("Invalid CONNECT hostname")
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        return normalized
    raise ProxyBlocked("IP literals are not allowed")


@dataclass(frozen=True)
class BrowserNetworkPolicy:
    site_host: str | None = None
    external_form_domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.site_host is not None:
            object.__setattr__(self, "site_host", _normalized_host(self.site_host))
        object.__setattr__(
            self,
            "external_form_domains",
            tuple(_normalized_host(domain) for domain in self.external_form_domains),
        )

    def allows(self, host: str) -> bool:
        try:
            normalized = _normalized_host(host)
        except ProxyBlocked:
            return False
        if self.site_host is not None:
            site = self.site_host.removeprefix("www.")
            if normalized.removeprefix("www.") == site:
                return True
        return normalized in self.external_form_domains


async def _numeric_dial(
    address: str, port: int
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.open_connection(host=address, port=port)


class AllowlistProxy:
    def __init__(
        self,
        policy: BrowserNetworkPolicy,
        *,
        resolver: Resolver = resolve,
        dialer: Dialer = _numeric_dial,
        connect_timeout: float = 5,
    ) -> None:
        self.policy = policy
        self.resolver = resolver
        self.dialer = dialer
        self.connect_timeout = connect_timeout
        self._server: asyncio.AbstractServer | None = None

    @property
    def proxy_url(self) -> str:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("Proxy has not started")
        address, port = self._server.sockets[0].getsockname()[:2]
        return f"http://{address}:{port}"

    async def start(self) -> AllowlistProxy:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def __aenter__(self) -> AllowlistProxy:
        return await self.start()

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def _handle(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        upstream_writer: asyncio.StreamWriter | None = None
        tunnel_established = False
        try:
            request_line = await asyncio.wait_for(client_reader.readline(), self.connect_timeout)
            if len(request_line) > 4096:
                raise ProxyBlocked("CONNECT request is too large")
            parts = request_line.decode("ascii", errors="strict").strip().split()
            if len(parts) != 3 or parts[0] != "CONNECT" or parts[2] not in {
                "HTTP/1.0",
                "HTTP/1.1",
            }:
                raise ProxyBlocked("Only HTTPS CONNECT is supported")
            for _ in range(64):
                header = await asyncio.wait_for(client_reader.readline(), self.connect_timeout)
                if not header or len(header) > 8192:
                    raise ProxyBlocked("Invalid CONNECT headers")
                if header in {b"\r\n", b"\n"}:
                    break
            else:
                raise ProxyBlocked("Too many CONNECT headers")

            authority = parts[1]
            host, separator, port_text = authority.rpartition(":")
            if not separator or port_text != "443":
                raise ProxyBlocked("Only port 443 is supported")
            host = _normalized_host(host)
            if not self.policy.allows(host):
                raise ProxyBlocked("CONNECT host is not allowlisted")

            answers = await asyncio.wait_for(
                asyncio.to_thread(self.resolver, host), self.connect_timeout
            )
            pinned = public_addresses(tuple(answers))[0]
            upstream_reader, upstream_writer = await asyncio.wait_for(
                self.dialer(pinned, 443), self.connect_timeout
            )
            client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_writer.drain()
            tunnel_established = True
            await self._tunnel(client_reader, client_writer, upstream_reader, upstream_writer)
        except Exception:
            if not tunnel_established and not client_writer.is_closing():
                client_writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                try:
                    await client_writer.drain()
                except OSError:
                    pass
        finally:
            if upstream_writer is not None:
                upstream_writer.close()
                try:
                    await upstream_writer.wait_closed()
                except OSError:
                    pass
            client_writer.close()
            try:
                await client_writer.wait_closed()
            except OSError:
                pass

    @staticmethod
    async def _tunnel(
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        upstream_reader: asyncio.StreamReader,
        upstream_writer: asyncio.StreamWriter,
    ) -> None:
        async def relay(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()

        tasks = {
            asyncio.create_task(relay(client_reader, upstream_writer)),
            asyncio.create_task(relay(upstream_reader, client_writer)),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
