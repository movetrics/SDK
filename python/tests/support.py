"""Shared test helpers: vector loading, a fake transport, a fake controller and a controller model.

Nothing here opens a port or touches hardware.

The controller model (controller_response) is a separate port of the controller's host parser and NACK rules
(the firmware). It is written apart from movetrics_fdt.frames so the
two can disagree, and the vectors decide which one is right.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any, Final

from movetrics_fdt.commands import GET_FW_VERSION, GET_STATUS, KEEP_ALIVE, SET_FILTER, START_STREAM, STOP_STREAM
from movetrics_fdt.crc import crc16_ccitt_false
from movetrics_fdt.frames import build_device_frame, parse_host_message
from movetrics_fdt.transport import Transport

TESTS_DIR: Final = Path(__file__).resolve().parent
VECTOR_DIR: Final = TESTS_DIR.parents[1] / "vectors"  # tests -> sdk/python -> sdk/vectors
# The public repository (movetrics/sdk) ships the host-link vectors only: no pad-bus or pad-bootloader files, and
# ota_frames.json without its firmware-update cases. SOURCES.md, which pins the private sources, exists only in
# the private tree, so its absence marks the public copy.
PUBLIC_REPOSITORY: Final = not (TESTS_DIR.parents[1] / "SOURCES.md").exists()
FIRMWARE_UPDATE_CASES: Final = frozenset(
    {
        "ota-derived-request-status-s",
        "ota-derived-request-data-salted",
        "ota-derived-reply-ok",
        "ota-derived-reply-param-error",
    }
)
VECTOR_FILES: Final = tuple(
    name
    for name in (
        "crc16.json",
        "host_frames.json",
        "stream_frames.json",
        "status.json",
        "pad_bus.json",
        "boot_frames.json",
        "ota_frames.json",
    )
    if not (PUBLIC_REPOSITORY and name in ("pad_bus.json", "boot_frames.json"))
)

# Command codes that the firmware parses but has no case for (central.cpp answers NACK 7). The codes come
# from docs/04-host-commands.md section 3.7; commands.py lists them as NOT_DISPATCHED.
UNDISPATCHED_CODES: Final = frozenset({0x02, 0x03, 0x04, 0x17, 0x32, 0x50, 0x51, 0x54, 0x55})

_END: Final = object()


def load_vector_file(name: str) -> dict[str, Any]:
    """Load one vector file from sdk/vectors, failing loudly if it is missing."""
    with (VECTOR_DIR / name).open(encoding="ascii") as handle:
        document: dict[str, Any] = json.load(handle)
    return document


def find_case(file_name: str, case_id: str) -> dict[str, Any]:
    """Return one case by id from a vector file."""
    for case in load_vector_file(file_name)["cases"]:
        if case["id"] == case_id:
            found: dict[str, Any] = case
            return found
    raise KeyError(f"{case_id} is not a case in {file_name}")


class FakeTransport(Transport):
    """An in-memory link.

    Writes are recorded in written and passed to responder, whose replies arrive as if from the controller.
    feed() delivers bytes by hand. chunk_size, when set, splits every delivery into pieces of that size, which
    checks that the client does not depend on chunk boundaries. end() closes the receive side normally, and
    fail() makes the receive side raise.
    """

    def __init__(
        self,
        responder: Callable[[bytes], Sequence[bytes]] | None = None,
        *,
        chunk_size: int | None = None,
    ) -> None:
        self.written: list[bytes] = []
        self.opened = False
        self.closed = False
        self._responder = responder
        self._chunk_size = chunk_size
        self._queue: asyncio.Queue[object] = asyncio.Queue()

    async def open(self) -> None:
        self.opened = True

    async def write(self, data: bytes) -> None:
        payload = bytes(data)
        self.written.append(payload)
        if self._responder is not None:
            for reply in self._responder(payload):
                self.feed(reply)

    def feed(self, data: bytes) -> None:
        """Deliver bytes from the controller, in pieces of chunk_size when that is set."""
        payload = bytes(data)
        if self._chunk_size is None:
            self._queue.put_nowait(payload)
            return
        for offset in range(0, len(payload), self._chunk_size):
            self._queue.put_nowait(payload[offset : offset + self._chunk_size])

    def end(self) -> None:
        """Close the receive side normally: the receive iterator ends."""
        self._queue.put_nowait(_END)

    def fail(self, error: BaseException) -> None:
        """Make the receive side raise error, as a dropped link would."""
        self._queue.put_nowait(error)

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._chunks()

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(_END)

    async def _chunks(self) -> AsyncIterator[bytes]:
        while True:
            item = await self._queue.get()
            if item is _END:
                self._queue.put_nowait(_END)
                return
            if isinstance(item, BaseException):
                raise item
            assert isinstance(item, bytes)
            yield item


class FakeController:
    """Answers the five implemented commands the way the controller does, and nothing else.

    status_reply: the bytes sent for GET_STATUS (one record, or one per detected platform).
    fw_version_reply: the bytes sent for GET_FW_VERSION; no reply when empty.
    stream: the frames sent right after START. START gets no ACK.
    refuse_start: answer START with NACK 3 (ERR_INVALID_PARAMETER) instead of streaming.
    silent_stop: give STOP no ACK.
    silent: give GET_STATUS no reply.
    SET_FILTER gets an ACK, or NACK 3 when the cutoff is at or above half the rate (the firmware).
    KEEP_ALIVE gets no reply.
    """

    def __init__(
        self,
        *,
        status_reply: bytes = b"",
        fw_version_reply: bytes = b"",
        stream: Sequence[bytes] = (),
        refuse_start: bool = False,
        silent_stop: bool = False,
        silent: bool = False,
    ) -> None:
        self.status_reply = status_reply
        self.fw_version_reply = fw_version_reply
        self.stream = tuple(stream)
        self.refuse_start = refuse_start
        self.silent_stop = silent_stop
        self.silent = silent

    def __call__(self, frame: bytes) -> list[bytes]:
        command = parse_host_message(frame).command
        if command == GET_STATUS.code:
            return [] if self.silent else [self.status_reply]
        if command == GET_FW_VERSION.code:
            return [self.fw_version_reply] if self.fw_version_reply else []
        if command == START_STREAM.code:
            if self.refuse_start:
                return [build_device_frame(bytes((0xFF, START_STREAM.code, 0x15, 0x03, 0x00)))]
            return list(self.stream)
        if command == STOP_STREAM.code:
            if self.silent_stop:
                return []
            return [build_device_frame(bytes((0xFF, STOP_STREAM.code, 0x06)))]
        if command == SET_FILTER.code:
            payload = parse_host_message(frame).payload
            cutoff, sps = payload[0], payload[1] | (payload[2] << 8)
            if cutoff and cutoff >= sps / 2:
                return [build_device_frame(bytes((0x00, SET_FILTER.code, 0x15, 0x03, 0x00)))]
            return [build_device_frame(bytes((0x00, SET_FILTER.code, 0x06)))]
        if command == KEEP_ALIVE.code:
            return []
        raise AssertionError(f"FakeController was sent command 0x{command:02X}, which the client must not send")


def controller_response(message: bytes) -> tuple[dict[str, Any], bool]:
    """The controller's answer to one RX message, and whether it dispatched the command.

    The first value uses the device_reply shape of host_frames.json: {"reply": "command_reply"},
    {"nack_code": n} or {"reply": "none", "reason": ...}. Rules: resync at the first FE ED that has nine bytes
    (hp.cpp:233-234), fewer than nine bytes is silent (hp.cpp:241), a bad header is silent (hp.cpp:245), a CRC
    mismatch is NACK 9 (hp.cpp:288), an EOT other than 04 04 is NACK 7 (hp.cpp:281), a payload below the
    command's minimum is NACK 3 (hp.cpp:264-272), and a code in UNDISPATCHED_CODES is NACK 7 from central.cpp.

    Not modelled: the platform and pad index checks for 0x14, 0x15, 0x52 and 0x53, which need PLATFORMS_MAX and
    PADS_IN_PLATFORM_MAX. No vector uses them.
    """
    buffer = bytes(message)
    if len(buffer) >= 9 and buffer[0:2] != b"\xfe\xed":
        for index in range(1, len(buffer)):
            if index + 9 > len(buffer):
                break
            if buffer[index : index + 2] == b"\xfe\xed":
                buffer = buffer[index:]
                break
    if len(buffer) < 9:
        return {"reply": "none", "reason": "shorter_than_9_bytes"}, False
    if buffer[0:2] != b"\xfe\xed":
        return {"reply": "none", "reason": "bad_header"}, False
    size = len(buffer)
    command = buffer[4]
    received_crc = buffer[size - 4] | (buffer[size - 3] << 8)
    if received_crc != crc16_ccitt_false(buffer[2 : size - 4]):
        return {"nack_code": 9}, False
    if buffer[size - 2 : size] != b"\x04\x04":
        return {"nack_code": 7}, False
    too_short = (
        (command == 0x1C and size < 12)
        or (command in (0x07, 0x26, 0x53) and size < 11)
        or (command in (0x12, 0x14, 0x15, 0x31, 0x34) and size < 10)
    )
    if too_short:
        return {"nack_code": 3}, False
    if command in UNDISPATCHED_CODES:
        return {"nack_code": 7}, False
    if command == 0x23:
        return {"reply": "command_reply"}, True
    return {"reply": "not_modelled"}, True
