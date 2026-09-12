"""Small CONNECT-only dependency proxy on the internal installation network."""

import asyncio
import ipaddress
import socket

ALLOWED = {
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
    "registry.yarnpkg.com",
}


async def tunnel(reader, writer):
    """Allow TLS only to public addresses of explicitly permitted package registries."""
    upstream = None
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        method, target, _ = header.split(b"\r\n", 1)[0].decode("ascii").split()
        host, port = target.rsplit(":", 1)
        if method != "CONNECT" or host not in ALLOWED or port != "443":
            writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            await writer.drain()
            return
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, 443, type=socket.SOCK_STREAM
        )
        address = addresses[0][4][0]
        if not all(ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Non-public registry address")
        remote_reader, upstream = await asyncio.wait_for(
            asyncio.open_connection(address, 443), 20
        )
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()

        async def copy(source, destination):
            while data := await asyncio.wait_for(source.read(65536), 120):
                destination.write(data)
                await destination.drain()
            destination.close()

        await asyncio.gather(copy(reader, upstream), copy(remote_reader, writer))
    except (
        ValueError,
        OSError,
        TimeoutError,
        asyncio.IncompleteReadError,
        asyncio.LimitOverrunError,
    ):
        pass
    finally:
        writer.close()
        if upstream:
            upstream.close()


async def main():
    """Serve registry tunnels without exposing a host port."""
    server = await asyncio.start_server(tunnel, "0.0.0.0", 3128, limit=8192)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
