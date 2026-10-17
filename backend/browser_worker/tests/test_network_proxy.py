import asyncio

import pytest

from browser_worker.network_proxy import AllowlistProxy, BrowserNetworkPolicy


def test_job_network_policy_is_explicit_and_host_exact():
    policy = BrowserNetworkPolicy("www.company.test", ("forms.vendor.test",))

    assert policy.allows("company.test")
    assert policy.allows("www.company.test")
    assert policy.allows("forms.vendor.test")
    assert not policy.allows("sub.forms.vendor.test")
    assert not policy.allows("unlisted.vendor.test")
    assert not policy.allows("10.0.0.1")


async def _connect(proxy_url, authority):
    host_port = proxy_url.removeprefix("http://")
    host, port = host_port.rsplit(":", 1)
    reader, writer = await asyncio.open_connection(host, int(port))
    writer.write(
        f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode("ascii")
    )
    await writer.drain()
    response = await reader.readline()
    while await reader.readline() not in {b"\r\n", b"\n", b""}:
        pass
    return reader, writer, response


def test_allowlisted_https_tunnel_is_pinned_to_the_checked_address():
    async def scenario():
        connected_addresses = []

        async def local_echo(reader, writer):
            data = await reader.read(64)
            writer.write(data)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        echo_server = await asyncio.start_server(local_echo, "127.0.0.1", 0)
        echo_port = echo_server.sockets[0].getsockname()[1]

        async def test_dialer(address, port):
            connected_addresses.append((address, port))
            return await asyncio.open_connection("127.0.0.1", echo_port)

        proxy = AllowlistProxy(
            BrowserNetworkPolicy("www.example.test", ("forms.vendor.test",)),
            resolver=lambda _host: ("93.184.216.34",),
            dialer=test_dialer,
        )
        async with proxy:
            reader, writer, status = await _connect(proxy.proxy_url, "example.test:443")
            assert b"200 Connection Established" in status
            writer.write(b"synthetic tunnel")
            await writer.drain()
            assert await reader.readexactly(len(b"synthetic tunnel")) == b"synthetic tunnel"
            writer.close()
            await writer.wait_closed()
        echo_server.close()
        await echo_server.wait_closed()
        assert connected_addresses == [("93.184.216.34", 443)]

    asyncio.run(scenario())


@pytest.mark.parametrize("authority", ["not-allowed.test:443", "127.0.0.1:443"])
def test_proxy_blocks_unlisted_hosts_and_internal_ip_literals(authority):
    async def scenario():
        dial_calls = []
        proxy = AllowlistProxy(
            BrowserNetworkPolicy("example.test"),
            resolver=lambda _host: ("93.184.216.34",),
            dialer=lambda address, port: _recording_dial(dial_calls, address, port),
        )
        async with proxy:
            _reader, writer, status = await _connect(proxy.proxy_url, authority)
            writer.close()
            await writer.wait_closed()
        assert b"403 Forbidden" in status
        assert dial_calls == []

    asyncio.run(scenario())


async def _recording_dial(calls, address, port):
    calls.append((address, port))
    raise AssertionError("blocked proxy request must not dial")


def test_proxy_resolves_each_connection_and_blocks_dns_rebinding():
    async def scenario():
        answers = iter((("93.184.216.34",), ("127.0.0.1",)))
        resolver_calls = []
        dial_calls = []

        async def local_echo(reader, writer):
            await reader.read()
            writer.close()
            await writer.wait_closed()

        echo_server = await asyncio.start_server(local_echo, "127.0.0.1", 0)
        echo_port = echo_server.sockets[0].getsockname()[1]

        def resolver(host):
            resolver_calls.append(host)
            return next(answers)

        async def test_dialer(address, port):
            dial_calls.append((address, port))
            return await asyncio.open_connection("127.0.0.1", echo_port)

        proxy = AllowlistProxy(
            BrowserNetworkPolicy("example.test"), resolver=resolver, dialer=test_dialer
        )
        async with proxy:
            _reader, writer, first_status = await _connect(proxy.proxy_url, "example.test:443")
            writer.close()
            await writer.wait_closed()
            _reader, writer, second_status = await _connect(proxy.proxy_url, "example.test:443")
            writer.close()
            await writer.wait_closed()
        echo_server.close()
        await echo_server.wait_closed()
        assert b"200 Connection Established" in first_status
        assert b"403 Forbidden" in second_status
        assert resolver_calls == ["example.test", "example.test"]
        assert dial_calls == [("93.184.216.34", 443)]

    asyncio.run(scenario())
