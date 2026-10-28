"""Put a VirtualFdt on a TCP port or a pseudo-terminal, in real time.

TCP: any client that can open a socket (Python, Android tests, a browser bridge) connects to host:port and talks
the FDT protocol as if over the FTDI serial line. One client at a time, as one commanding host at a time is the
bench rule; a second connection waits. Pseudo-terminal (Linux and macOS): a path such as /tmp/fdt that pyserial,
MATLAB serialport and screen open like a USB serial device.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable

from .simulator import VirtualFdt

TICK_S = 0.001


async def _pump(fdt: VirtualFdt, write: Callable[[bytes], None], stop: asyncio.Event,
                on_tick: Callable[[float], None] | None = None) -> None:
    while not stop.is_set():
        now = time.monotonic()
        if on_tick is not None:
            on_tick(now)
        out = fdt.advance(now)
        if out:
            write(out)
        await asyncio.sleep(TICK_S)


async def serve_tcp(make_fdt: Callable[[], VirtualFdt], host: str = "127.0.0.1", port: int = 7800, *,
                    ready: Callable[[str, int], None] | None = None,
                    on_tick: Callable[[VirtualFdt, float], None] | None = None) -> None:
    """Serve forever. Each connection gets a fresh controller (as after a power cycle)."""
    busy = asyncio.Lock()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async with busy:
            fdt = make_fdt()
            stop = asyncio.Event()
            pump = asyncio.create_task(_pump(fdt, writer.write, stop, (lambda now: on_tick(fdt, now)) if on_tick else None))
            try:
                while data := await reader.read(4096):
                    fdt.feed(data, time.monotonic())
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            finally:
                stop.set()
                await pump
                writer.close()

    server = await asyncio.start_server(handle, host, port)
    bound = server.sockets[0].getsockname()
    if ready is not None:
        ready(bound[0], bound[1])
    async with server:
        await server.serve_forever()


async def serve_pty(make_fdt: Callable[[], VirtualFdt], link: str, *,
                    ready: Callable[[str], None] | None = None,
                    on_tick: Callable[[VirtualFdt, float], None] | None = None) -> None:
    """Create a pseudo-terminal, point the symlink link at it and serve forever (POSIX only)."""
    import tty

    master, slave = os.openpty()
    tty.setraw(slave)
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(os.ttyname(slave), link)
    os.set_blocking(master, False)
    fdt = make_fdt()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def readable() -> None:
        try:
            data = os.read(master, 4096)
        except BlockingIOError:
            return
        except OSError:
            return
        fdt.feed(data, time.monotonic())

    def write(data: bytes) -> None:
        view = memoryview(data)
        while view:
            try:
                view = view[os.write(master, view):]
            except BlockingIOError:
                time.sleep(0.0005)

    loop.add_reader(master, readable)
    if ready is not None:
        ready(link)
    try:
        await _pump(fdt, write, stop, (lambda now: on_tick(fdt, now)) if on_tick else None)
    finally:
        loop.remove_reader(master)
        os.close(master)
        os.close(slave)
        if os.path.islink(link):
            os.remove(link)
