"""Local relay: an FDT stream that a web page sends over a WebSocket on this computer goes out on Lab Streaming Layer.

A page that reads the FDT in the browser (WebSerialTransport, WebBluetoothTransport) cannot publish LSL itself:
browsers cannot open the sockets LSL uses. The page sends what FdtClient.samples() yields to this relay (LslRelay in
the TypeScript client), and the relay feeds LslBridge: the same streams, names, units and clock mapping as a Python
program that reads the FDT itself (docs/22). Only one program can own an FDT's stream, so this is also how a browser
recorder and LabRecorder can both have the data.

    movetrics-fdt lsl-relay                                   # ws://127.0.0.1:7812, pages served from this computer
    movetrics-fdt lsl-relay --allow-origin https://lab.example.org --device B

Protocol, JSON text messages. The page sends hello first:

    {"type": "hello", "version": 1, "rate_hz": 2000, "plates": [1, 2], "firmware": "1.2.8.20", "device": null}

and the relay answers {"type": "ready", "streams": [...stream names...]}. Then batches, as they come off the FDT:

    {"type": "items", "items": [{"kind": "sample", "t": 1.0005, "plate": 1, "fx": 1.2, "fy": -0.4, "fz": 702.5,
                                 "mx": 3.1, "my": -4.0, "mz": 0.5, "cop_x": 0.0057, "cop_y": null, "stamp": 10005},
                                {"kind": "event", "t": 1.25, "name": "sync_in_rise", "type": 1},
                                {"kind": "gap", "plate": 1, "start_t": 2.0, "end_t": 2.01, "missing": 9}]}

cop_x and cop_y are null where the vocabulary has NaN (below 50 N); every other number must be finite. A free-text
marker is {"type": "mark", "text": "jump 3"}. The clock mapping sees when each message arrives on the LSL clock, so
send items as they come rather than holding them back. Anything the relay cannot accept closes the connection with
a code (1007 bad data, 1008 refused, 1013 busy) and a reason the page can show.

The relay listens on 127.0.0.1 only. A browser page is accepted when its origin is on this computer (localhost,
127.0.0.1) or named with allow_origins; a client that sends no Origin header is a program on this computer, which
could publish to LSL itself, and is accepted.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from .lsl import _DEVICE_LABEL, LslBridge, _import_pylsl
from .vocabulary import Event, Gap, Sample

DEFAULT_PORT = 7812
PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1 << 20
MAX_ITEMS = 20_000
HELLO_TIMEOUT_S = 10.0
LOCAL_ORIGIN = re.compile(r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d{1,5})?")

CLOSE_BAD_DATA = 1007
CLOSE_REFUSED = 1008
CLOSE_BUSY = 1013

_SAMPLE_NUMBERS = ("t", "fx", "fy", "fz", "mx", "my", "mz")
_EVENT_INTS = ("type", "source", "count", "detail", "stamp", "offset_us")


class RelayError(ValueError):
    """A message the relay refuses. code is the WebSocket close code sent to the page."""

    def __init__(self, message: str, code: int = CLOSE_BAD_DATA) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Hello:
    rate_hz: float
    plates: tuple[int, ...]
    firmware: str
    device: str | None


def origin_allowed(origin: str | None, allow_origins: Sequence[str] = ()) -> bool:
    """A page served from this computer, a named origin, or no Origin header (a program, not a browser)."""
    return origin is None or bool(LOCAL_ORIGIN.fullmatch(origin)) or origin in allow_origins


def decode(text: str | bytes) -> dict[str, Any]:
    if not isinstance(text, str):
        raise RelayError("send JSON text messages, not binary")
    try:
        message = json.loads(text)
    except ValueError as error:
        raise RelayError(f"not JSON: {error.msg}") from None
    if not isinstance(message, dict):
        raise RelayError("a message is a JSON object")
    return message


def parse_hello(message: dict[str, Any]) -> Hello:
    if message.get("type") != "hello":
        raise RelayError("the first message must be hello", CLOSE_REFUSED)
    if message.get("version") != PROTOCOL_VERSION:
        raise RelayError(f"protocol version {message.get('version')!r} is not {PROTOCOL_VERSION}", CLOSE_REFUSED)
    rate = _number(message, "rate_hz")
    if not 0 < rate <= 100_000:
        raise RelayError("rate_hz must be above 0 and at most 100000")
    plates = message.get("plates", [1, 2])
    if (not isinstance(plates, list) or not plates or len(set(plates)) != len(plates)
            or not all(_is_int(p) and 1 <= p <= 4 for p in plates)):
        raise RelayError("plates must be distinct plate numbers from 1 to 4")
    firmware = message.get("firmware", "unknown")
    if not isinstance(firmware, str) or not 0 < len(firmware) <= 64:
        raise RelayError("firmware must be a string of 1 to 64 characters")
    device = message.get("device")
    if device is not None and (not isinstance(device, str) or not _DEVICE_LABEL.fullmatch(device)):
        raise RelayError("device must be letters, digits, '-' or '_'")
    return Hello(float(rate), tuple(int(p) for p in plates), firmware, device)


def parse_items(message: dict[str, Any], plates: Sequence[int]) -> list[Sample | Event | Gap]:
    items = message.get("items")
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise RelayError(f"items must be a list of at most {MAX_ITEMS}")
    out: list[Sample | Event | Gap] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise RelayError(f"item {index} is not an object")
        try:
            out.append(_item(item, plates))
        except RelayError as error:
            raise RelayError(f"item {index}: {error}") from None
    return out


def _item(item: dict[str, Any], plates: Sequence[int]) -> Sample | Event | Gap:
    kind = item.get("kind")
    if kind == "sample":
        plate = _plate(item, plates)
        t, fx, fy, fz, mx, my, mz = (_number(item, name) for name in _SAMPLE_NUMBERS)
        stamp = item.get("stamp")
        if not _is_int(stamp) or stamp < 0:
            raise RelayError("stamp must be a whole number of FDT ticks")
        return Sample(t, plate, fx, fy, fz, mx, my, mz, _cop(item, "cop_x"), _cop(item, "cop_y"), stamp, ())
    if kind == "event":
        name = item.get("name")
        if not isinstance(name, str) or not 0 < len(name) <= 64:
            raise RelayError("an event needs a name of 1 to 64 characters")
        ints = {key: item.get(key, 0) for key in _EVENT_INTS}
        if not all(_is_int(value) for value in ints.values()):
            raise RelayError("event type, source, count, detail, stamp and offset_us must be whole numbers")
        return Event(_number(item, "t"), ints["type"], name, ints["source"], ints["count"], ints["detail"],
                     ints["stamp"], ints["offset_us"])
    if kind == "gap":
        plate = _plate(item, plates)
        missing = item.get("missing")
        if not _is_int(missing) or missing < 0:
            raise RelayError("missing must be a whole number")
        return Gap(plate, _number(item, "start_t"), _number(item, "end_t"), missing)
    raise RelayError(f"unknown item kind {kind!r}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(item: dict[str, Any], name: str) -> float:
    value = item.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RelayError(f"{name} must be a finite number")
    return float(value)


def _cop(item: dict[str, Any], name: str) -> float:
    return math.nan if item.get(name) is None else _number(item, name)


def _plate(item: dict[str, Any], plates: Sequence[int]) -> int:
    plate = item.get("plate")
    if not _is_int(plate) or plate not in plates:
        raise RelayError(f"plate {plate!r} was not announced in hello")
    return int(plate)


def stream_names(bridge: LslBridge) -> list[str]:
    return [outlet.get_info().name() for outlet in (*bridge.outlets.values(), bridge.markers)]


async def serve_relay(*, port: int = DEFAULT_PORT, allow_origins: Sequence[str] = (), device: str | None = None,
                      latency_s: float = 0.0, ready: Callable[[str], None] | None = None,
                      log: Callable[[str], None] | None = None) -> None:
    """Run the relay until cancelled. ready(url) is called once it listens (port 0 picks a free port).

    device, when given, names the FDT in the stream names and source ids and wins over the page's own label.
    """
    try:
        from websockets.asyncio.server import serve
        from websockets.exceptions import ConnectionClosed
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise ImportError("The relay needs websockets and pylsl: pip install 'movetrics-fdt[relay]'") from error
    if device is not None and not _DEVICE_LABEL.fullmatch(device):
        raise ValueError("device must be letters, digits, '-' or '_'")
    pylsl = _import_pylsl()
    say = log or (lambda text: None)
    busy = False

    def check_origin(connection: Any, request: Any) -> Any:
        origin = request.headers.get("Origin")
        if origin_allowed(origin, allow_origins):
            return None
        say(f"refused a page from {origin}: start the relay with --allow-origin {origin} to accept it")
        return connection.respond(HTTPStatus.FORBIDDEN, f"Origin {origin} is not allowed by this relay.\n")

    async def handle(connection: Any) -> None:
        nonlocal busy
        if busy:
            await connection.close(CLOSE_BUSY, "another page is already streaming to this relay")
            return
        busy = True
        bridge: LslBridge | None = None
        origin = connection.request.headers.get("Origin") or "a program on this computer"
        try:
            try:
                hello = parse_hello(decode(await asyncio.wait_for(connection.recv(), HELLO_TIMEOUT_S)))
            except asyncio.TimeoutError:
                raise RelayError(f"no hello within {HELLO_TIMEOUT_S:.0f} s", CLOSE_REFUSED) from None
            bridge = LslBridge(hello.rate_hz, hello.plates, device=device or hello.device, firmware=hello.firmware,
                               latency_s=latency_s)
            names = stream_names(bridge)
            await connection.send(json.dumps({"type": "ready", "streams": names}))
            say(f"{origin} streams FDT {hello.firmware} at {hello.rate_hz:g} frames/s per plate as {', '.join(names)}")
            async for text in connection:
                arrival = pylsl.local_clock()
                message = decode(text)
                if message.get("type") == "items":
                    for item in parse_items(message, hello.plates):
                        bridge.push(item, arrival)
                    bridge.flush()
                elif message.get("type") == "mark":
                    note = message.get("text")
                    if not isinstance(note, str) or not 0 < len(note) <= 256:
                        raise RelayError("a mark needs text of 1 to 256 characters")
                    bridge.mark(note)
                else:
                    raise RelayError(f"unknown message type {message.get('type')!r}")
            say(f"{origin} closed the connection; {bridge.stats()}")
        except RelayError as error:
            say(f"refused {origin}: {error}")
            await connection.close(error.code, str(error)[:120])
        except ConnectionClosed:
            say(f"{origin} went away")
        finally:
            if bridge is not None:
                bridge.close()
            busy = False

    async with serve(handle, "127.0.0.1", port, process_request=check_origin, max_size=MAX_MESSAGE_BYTES) as server:
        bound = server.sockets[0].getsockname()[1]
        if ready is not None:
            ready(f"ws://127.0.0.1:{bound}")
        await asyncio.get_running_loop().create_future()
