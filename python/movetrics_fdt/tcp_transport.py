"""TCP transport: the FDT byte stream over a socket. Connects to the simulator (movetrics-fdt simulate --tcp) and
to anything that bridges a controller's serial line to TCP (ser2net, the FDT repo's TCP streamer)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from .errors import TransportError
from .transport import Transport


class TcpTransport(Transport):
    def __init__(self, host: str = "127.0.0.1", port: int = 7800, *, connect_timeout_s: float = 5.0) -> None:
        self._host, self._port, self._timeout = host, port, connect_timeout_s
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def open(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), self._timeout)
        except (OSError, asyncio.TimeoutError) as error:
            raise TransportError(f"cannot connect to {self._host}:{self._port}: {error}") from error

    async def write(self, data: bytes) -> None:
        if self._writer is None:
            raise TransportError(f"{self._host}:{self._port} is not open; call open() first")
        try:
            self._writer.write(bytes(data))
            await self._writer.drain()
        except OSError as error:
            raise TransportError(f"write to {self._host}:{self._port} failed: {error}") from error

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._chunks()

    async def _chunks(self) -> AsyncIterator[bytes]:
        reader = self._reader
        if reader is None:
            return
        while True:
            try:
                data = await reader.read(65536)
            except OSError:
                return
            if not data:
                return
            yield data

    async def close(self) -> None:
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
