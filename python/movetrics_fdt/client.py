"""FdtClient: the host side of the controller protocol for the five implemented commands.

Implemented: START_STREAM (FF/FF), STOP_STREAM (FF/00), SET_FILTER (00/00, Movetrics firmware 1.2.8+ only),
GET_STATUS (00/00), GET_FW_VERSION (00/00) and KEEP_ALIVE (00/00).
Every other command is listed in commands.NOT_IMPLEMENTED and is never built or sent.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import re
import struct
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Final

import enum

from .commands import (
    GET_FW_VERSION, GET_STATUS, GET_SYNC_MODE, KEEP_ALIVE, SET_FILTER, SET_SYNC_MODE, START_STREAM, STOP_STREAM,
)
from .errors import FdtError, NackError, ReplyTimeoutError, TransportError
from .frames import BROADCAST_ADDRESS, AckReply, FirmwareVersionReply, NackReply, encode_host_frame
from .status import Status, StatusRecord, parse_status
from .stream import DeviceReply, EventFrame, StreamDecoder, StreamFrame, SyncModeReply
from .transport import Transport
from .vocabulary import Event, Gap, Sample, SampleConverter

DEFAULT_TIMEOUT_S: Final = 2.0
DEFAULT_RECORD_GAP_S: Final = 0.2
DEFAULT_START_CHECK_S: Final = 0.25
DEFAULT_FRAME_QUEUE_SIZE: Final = 65536
DEFAULT_KEEP_ALIVE_S: Final = 600  # KEEP_ALIVE_INTERVAL, the firmware
# The stream rate is clamped to 50..2000 frames per second per plate (the firmware). 2,000 is clean
# over USB on 1.2.8.1+ (bench, 10 Oct 2026); the default after every reset is 500 (1,000 from firmware 1.2.8.8) with a 50 Hz low-pass.
MIN_RATE_HZ: Final = 50
MAX_RATE_HZ: Final = 2000
DEFAULT_CUTOFF_HZ: Final = 50
# The bench tools leave 100 ms between SET_FILTER and START (stream_check.py); the filter state is rebuilt then.
SET_RATE_SETTLE_S: Final = 0.1
# SET_FILTER means cutoff + rate only on Movetrics firmware from 1.2.8.0 (doc 17, SET_FILTER section).
MIN_SET_FILTER_FIRMWARE: Final = (1, 2, 8, 0)
_VERSION_RE: Final = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)")


class SyncMode(enum.IntFlag):
    """Bits of SET_SYNC_MODE (docs/04 section 3.9). 0 is the behaviour of firmware without sync modes.
    MASTER_OUT and PULSE_TRAIN exclude each other."""

    OFF = 0
    START_ON_RISE = 0x01  # arm: START waits for a rising edge on SYNC IN
    STOP_ON_FALL = 0x02  # stop the stream on a falling edge on SYNC IN (with START_ON_RISE: a gate)
    MASTER_OUT = 0x04  # SYNC OUT high while streaming
    EVENT_FRAMES = 0x08  # send an event frame (address 0xFD, code 0x0E) for every edge
    PULSE_TRAIN = 0x10  # SYNC OUT rises at stream ticks 1, 1 + P, 1 + 2P ... while streaming
    SATURATION_EVENTS = 0x20  # events 7 and 9 at the start and end of each int16 wrap or pad clip episode


NACK_INVALID_PARAMETER: Final = 3
NACK_UNKNOWN_COMMAND: Final = 7
NACK_NOT_NOW: Final = 8


class FdtClient:
    """Talks to one controller over a Transport. Use it as an async context manager.

        async with FdtClient(transport) as fdt:
            await fdt.start_stream()
            async for frame in fdt.frames():
                ...

    The client runs one reader task. Stream frames go to frames(). Replies go to the command that waits for
    them, and commands are serialised, so only one is in flight at a time. A client opens once. On exit, a
    stream that this client started is stopped first (best effort), then the transport is closed.

    timeout is the wait for a reply to get_status() or stop_stream(), in seconds.
    record_gap is how long get_status() waits for another record after the first one.
    start_check is how long start_stream() watches for a NACK, because START sends no ACK.
    frame_queue_size bounds the frames held for frames(). When it is full the oldest frame is dropped and
    counted in dropped_frames.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        record_gap: float = DEFAULT_RECORD_GAP_S,
        start_check: float = DEFAULT_START_CHECK_S,
        frame_queue_size: int = DEFAULT_FRAME_QUEUE_SIZE,
    ) -> None:
        if timeout <= 0 or record_gap <= 0 or start_check < 0:
            raise ValueError("timeout and record_gap must be positive, and start_check must not be negative")
        if frame_queue_size < 1:
            raise ValueError("frame_queue_size must be at least 1")
        self._transport = transport
        self._timeout = timeout
        self._record_gap = record_gap
        self._start_check = start_check
        self._frame_queue_size = frame_queue_size
        self._opened = False
        self._reader: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._frame_buffer: collections.deque[StreamFrame | EventFrame] = collections.deque()
        self._rate_hz: int | None = None
        self._frame_ready = asyncio.Event()
        self._reply_buffer: collections.deque[DeviceReply] = collections.deque()
        self._reply_ready = asyncio.Event()
        self._streaming = False
        self._link_closed = False
        self._link_reason = ""
        self._dropped_frames = 0

    @property
    def streaming(self) -> bool:
        """True from a successful start_stream() until stop_stream() is acknowledged."""
        return self._streaming

    @property
    def dropped_frames(self) -> int:
        """Stream frames discarded because frames() did not keep up with frame_queue_size."""
        return self._dropped_frames

    async def __aenter__(self) -> FdtClient:
        if self._opened:
            raise FdtError("this FdtClient has already been opened; create a new one to connect again")
        self._opened = True
        await self._transport.open()
        self._reader = asyncio.create_task(self._read_loop(), name="movetrics-fdt-reader")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if self._streaming and not self._link_closed:
                try:
                    await self.stop_stream()
                except FdtError:
                    # Raised only when the block finished normally, so an error that ended the block is not hidden.
                    if exc_type is None:
                        raise
        finally:
            await self._shutdown()

    async def get_status(self) -> Status:
        """Send GET_STATUS to 00/00 and return the parsed reply.

        Waits up to timeout seconds for the first record. Then it collects the other records (one per address:
        the general record, then one per detected platform) until none has arrived for record_gap seconds. A
        reply is 1 to 3 records, all 85 bytes long or all 86 bytes long (docs/03-host-link-framing.md section
        3.6; the firmware). Records are kept in arrival order and are not sorted. A reply must start with
        the general record (address 0), and its platforms must follow in increasing order (see parse_status).

        Raises NackError on a refusal, ReplyTimeoutError when no record arrives, TransportError when the link
        fails, and FrameError when the collected bytes are not a valid reply, for example a mix of lengths or
        platform records out of order (reason bad_platform_order).
        """
        lock = self._require_open()
        frame = encode_host_frame(GET_STATUS.code, 0x00, 0x00)
        async with lock:
            self._reply_buffer.clear()
            await self._write(frame)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._timeout
            records: list[StatusRecord] = []
            while not records:
                item = await self._next_reply(deadline)
                if item is None:
                    raise ReplyTimeoutError(f"no GET_STATUS reply within {self._timeout} s")
                if isinstance(item, StatusRecord):
                    records.append(item)
                elif isinstance(item, NackReply) and item.command == GET_STATUS.code:
                    raise self._nack(item)
            while True:
                item = await self._next_reply(loop.time() + self._record_gap)
                if item is None:
                    break
                if isinstance(item, StatusRecord):
                    records.append(item)
        return parse_status(b"".join(record.raw for record in records))

    async def get_firmware_version(self) -> FirmwareVersionReply:
        """Send GET_FW_VERSION to 00/00 and return the STM32 and ESP32 firmware version strings.

        Reply: BE EF pa 23 ... with 38 bytes (the firmware). Raises NackError on a refusal,
        ReplyTimeoutError when no reply arrives within timeout seconds, and TransportError when the link fails.
        """
        lock = self._require_open()
        frame = encode_host_frame(GET_FW_VERSION.code, 0x00, 0x00)
        async with lock:
            self._reply_buffer.clear()
            await self._write(frame)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._timeout
            while True:
                item = await self._next_reply(deadline)
                if item is None:
                    raise ReplyTimeoutError(f"no GET_FW_VERSION reply within {self._timeout} s")
                if isinstance(item, FirmwareVersionReply):
                    return item
                if isinstance(item, NackReply) and item.command == GET_FW_VERSION.code:
                    raise self._nack(item)

    async def start_stream(self) -> None:
        """Send START_STREAM to FF/FF and start the stream.

        The controller sends no ACK, so this returns after the bytes are written and start_check seconds have
        passed without a NACK. Raises NackError if the controller refuses (for example during a firmware
        update). The first two frames have timeStamp 0 and are placeholders (docs/04-host-commands.md F2;
        docs/05-measurement-stream.md section 6). Read the stream with frames(). Raises FdtError if this
        client has already started the stream.
        """
        lock = self._require_open()
        frame = encode_host_frame(START_STREAM.code, BROADCAST_ADDRESS, BROADCAST_ADDRESS)
        async with lock:
            if self._streaming:
                raise FdtError("the stream is already started by this client; call stop_stream() first")
            self._reply_buffer.clear()
            await self._write(frame)
            self._streaming = True
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._start_check
            while True:
                item = await self._next_reply(deadline)
                if item is None:
                    break
                if isinstance(item, NackReply) and item.command == START_STREAM.code:
                    self._streaming = False
                    raise self._nack(item)

    async def stop_stream(self) -> None:
        """Send STOP_STREAM to FF/00 and wait up to timeout seconds for its ACK.

        Reply: BE EF pa 05 06 crc crc 04 04 (docs/03-host-link-framing.md section 3.6). The controller sends
        the ACK before it clears the stream, so frames that arrived earlier are still delivered to frames().
        Raises NackError on a refusal and ReplyTimeoutError when no ACK arrives. After a timeout the client still
        counts the stream as running.
        """
        lock = self._require_open()
        frame = encode_host_frame(STOP_STREAM.code, BROADCAST_ADDRESS, 0x00)
        async with lock:
            self._reply_buffer.clear()
            await self._write(frame)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._timeout
            while True:
                item = await self._next_reply(deadline)
                if item is None:
                    raise ReplyTimeoutError(f"no ACK for STOP_STREAM within {self._timeout} s")
                if isinstance(item, AckReply) and item.command == STOP_STREAM.code:
                    break
                if isinstance(item, NackReply) and item.command == STOP_STREAM.code:
                    raise self._nack(item)
            self._streaming = False

    async def keep_alive(self, interval_s: int = DEFAULT_KEEP_ALIVE_S) -> None:
        """Send KEEP_ALIVE to 00/00 with the sleep interval in seconds, as a uint16 little-endian payload.

        The controller sends no reply, so this returns once the bytes are written. Any accepted command resets
        its sleep counter. An interval of 0 would turn the sleep off and drain the battery, so it is refused, as in
        the TypeScript client (docs/15 section 5). The interval is a RAM variable
        (the firmware), so a reset restores the default 600 s (docs/03-host-link-framing.md
        section 3.9). Raises FrameError for an interval whose frame the controller would split, for example
        1028, whose bytes are 04 04.
        """
        if not 1 <= interval_s <= 0xFFFF:
            raise ValueError(f"interval_s must be 1..65535 seconds, got {interval_s}")
        frame = encode_host_frame(KEEP_ALIVE.code, 0x00, 0x00, struct.pack("<H", interval_s))
        lock = self._require_open()
        async with lock:
            await self._write(frame)

    async def set_rate(self, frames_per_second: int, cutoff_hz: int = DEFAULT_CUTOFF_HZ) -> None:
        """Set the stream rate per plate and the controller's low-pass cutoff (SET_FILTER 0x1C to 00/00).

        frames_per_second: 50 to 2000. cutoff_hz: 1 to 255 and below half the rate, or 0 for no low-pass (raw,
        tare-corrected data). The controller keeps the setting in RAM only: a reset restores 500 frames per second
        and 50 Hz, so set it after every connect. Call it with the stream stopped; it returns 100 ms after the ACK,
        so start_stream() may follow at once.

        It first asks GET_FW_VERSION and refuses (FdtError, nothing sent) unless the controller runs Movetrics
        firmware 1.2.8.0 or later, because older and vendor firmware read 0x1C differently. Raises NackError when
        the controller refuses the values, ReplyTimeoutError when no ACK arrives, and FrameError for a rate whose
        bytes form 04 04 (1028), which the controller would split.
        """
        if not MIN_RATE_HZ <= frames_per_second <= MAX_RATE_HZ:
            raise ValueError(f"frames_per_second must be {MIN_RATE_HZ}..{MAX_RATE_HZ}, got {frames_per_second}")
        if not 0 <= cutoff_hz <= 255 or (cutoff_hz and cutoff_hz * 2 >= frames_per_second):
            raise ValueError(f"cutoff_hz must be 0 (off) or 1..255 and below half the rate, got {cutoff_hz}")
        if self._streaming:
            raise FdtError("stop the stream before set_rate(); the controller rebuilds its filter between streams")
        frame = encode_host_frame(SET_FILTER.code, 0x00, 0x00, bytes((cutoff_hz,)) + struct.pack("<H", frames_per_second))
        version = await self.get_firmware_version()
        match = _VERSION_RE.match(version.stm32FW)
        if match is None or tuple(int(part) for part in match.groups()) < MIN_SET_FILTER_FIRMWARE:
            raise FdtError(f"set_rate needs Movetrics firmware 1.2.8.0 or later; the controller reports {version.stm32FW!r}")
        lock = self._require_open()
        async with lock:
            self._reply_buffer.clear()
            await self._write(frame)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._timeout
            while True:
                item = await self._next_reply(deadline)
                if item is None:
                    raise ReplyTimeoutError(f"no ACK for SET_FILTER within {self._timeout} s")
                if isinstance(item, AckReply) and item.command == SET_FILTER.code:
                    break
                if isinstance(item, NackReply) and item.command == SET_FILTER.code:
                    raise self._nack(item)
            self._rate_hz = frames_per_second
            await asyncio.sleep(SET_RATE_SETTLE_S)

    async def set_sync_mode(self, mode: SyncMode | int, pulse_period_ms: int = 0, pulse_width_ms: int = 0,
                            debounce_ticks: int = 0, arm_timeout_min: int = 0) -> None:
        """SET_SYNC_MODE (0x28): mode bits, and optionally the pulse period (10 to 60,000 ms), pulse width (ms, below
        the period), SYNC IN debounce (0.1 ms units) and arm timeout (minutes). 0 keeps the firmware default
        (1,000 ms, 5 ms, 0.5 ms, 30 min). Waits for the ACK.

        Needs FDT 1.2.8.24 or later with the sync jack; older firmware and the digital variant answer NACK 7 and
        this raises FdtError saying so (probe first with get_sync_mode()). Call it with the stream stopped and not
        armed. The mode survives CONTROLLER_RESET (Studio's tare) but not a power cycle.
        """
        values = (int(mode), pulse_period_ms, pulse_width_ms, debounce_ticks, arm_timeout_min)
        limits = (0xFF, 0xFFFF, 0xFF, 0xFF, 0xFF)
        if any(not 0 <= value <= limit for value, limit in zip(values, limits)):
            raise ValueError(f"sync mode values out of range: {values}")
        if mode & SyncMode.MASTER_OUT and mode & SyncMode.PULSE_TRAIN:
            raise ValueError("MASTER_OUT and PULSE_TRAIN exclude each other (the firmware answers NACK 3)")
        if self._streaming:
            raise FdtError("stop the stream before set_sync_mode()")
        payload = struct.pack("<BHBBB", *values)
        frame = encode_host_frame(SET_SYNC_MODE.code, 0x00, 0x00, payload)
        lock = self._require_open()
        async with lock:
            self._reply_buffer.clear()
            await self._write(frame)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._timeout
            while True:
                item = await self._next_reply(deadline)
                if item is None:
                    raise ReplyTimeoutError(f"no ACK for SET_SYNC_MODE within {self._timeout} s")
                if isinstance(item, AckReply) and item.command == SET_SYNC_MODE.code:
                    return
                if isinstance(item, NackReply) and item.command == SET_SYNC_MODE.code:
                    if item.error_code == NACK_UNKNOWN_COMMAND:
                        raise FdtError("this FDT has no sync modes (it answered 'unknown command'): they need firmware "
                                       "1.2.8.24 or later on an FDT with the sync jack")
                    if item.error_code == NACK_NOT_NOW:
                        raise FdtError("the FDT refused the sync mode while a stream runs or waits for its trigger; "
                                       "stop it first")
                    raise self._nack(item)

    async def get_sync_mode(self) -> SyncModeReply | None:
        """GET_SYNC_MODE (0x29): the sync settings, state bits and edge counters, or None when this FDT has no sync
        modes (NACK 7: firmware before 1.2.8.24 or the digital variant). Use it as the capability probe."""
        frame = encode_host_frame(GET_SYNC_MODE.code, 0x00, 0x00)
        lock = self._require_open()
        async with lock:
            self._reply_buffer.clear()
            await self._write(frame)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._timeout
            while True:
                item = await self._next_reply(deadline)
                if item is None:
                    raise ReplyTimeoutError(f"no GET_SYNC_MODE reply within {self._timeout} s")
                if isinstance(item, SyncModeReply):
                    return item
                if isinstance(item, NackReply) and item.command == GET_SYNC_MODE.code:
                    if item.error_code == NACK_UNKNOWN_COMMAND:
                        return None
                    raise self._nack(item)

    async def frames(self) -> AsyncIterator[StreamFrame]:
        """Yield stream frames in arrival order, until the link closes.

        The iterator does not end on its own while the link is open. Stop it with a break or with
        asyncio.wait_for. Frames are yielded as they arrive, including placeholders with timeStamp 0. After
        the link closes, the frames still queued are yielded and then the iterator ends. Event frames are
        skipped here; records() and samples() deliver them.
        """
        async for item in self.records():
            if isinstance(item, StreamFrame):
                yield item

    async def samples(self, rate_hz: float | None = None) -> AsyncIterator[Sample | Event | Gap]:
        """Yield the stream in the shared vocabulary (docs/19): Samples in SI units and the plate frame,
        sync Events, and a Gap before the first sample after any hole. Placeholders are dropped.

        rate_hz defaults to the rate this client set with set_rate(); without it the period is learnt from
        the stream. Start a new samples() iterator after each START, because the stamp restarts at 0.
        """
        converter = SampleConverter(rate_hz or self._rate_hz)
        async for item in self.records():
            for out in converter.push(item):
                yield out

    async def records(self) -> AsyncIterator[StreamFrame | EventFrame]:
        """Yield stream frames and event frames in arrival order (wire values), until the link closes."""
        if not self._opened:
            raise FdtError("open the client with 'async with FdtClient(transport) as fdt:' first")
        while True:
            if self._frame_buffer:
                yield self._frame_buffer.popleft()
                continue
            if self._link_closed:
                return
            self._frame_ready.clear()
            await self._frame_ready.wait()

    def _require_open(self) -> asyncio.Lock:
        if self._reader is None:
            raise FdtError("the client is not open; use 'async with FdtClient(transport) as fdt:'")
        return self._lock

    async def _write(self, frame: bytes) -> None:
        if self._link_closed:
            raise TransportError(self._link_reason)
        await self._transport.write(frame)

    async def _next_reply(self, deadline: float) -> DeviceReply | None:
        """Return the next reply, or None when the deadline passes first. Raises TransportError when the link is down."""
        loop = asyncio.get_running_loop()
        while True:
            if self._reply_buffer:
                return self._reply_buffer.popleft()
            if self._link_closed:
                raise TransportError(self._link_reason)
            if loop.time() >= deadline:
                return None
            self._reply_ready.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._reply_ready.wait(), deadline - loop.time())

    def _nack(self, reply: NackReply) -> NackError:
        return NackError(reply.command, reply.error_code, reply.error_name)

    async def _read_loop(self) -> None:
        decoder = StreamDecoder(on_reply=self._queue_reply)
        reason = "the link was closed"
        try:
            async for chunk in self._transport:
                for frame in decoder.push(chunk):
                    self._queue_frame(frame)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            reason = f"the link failed: {error}"
        self._mark_link_down(reason)

    def _queue_frame(self, frame: StreamFrame | EventFrame) -> None:
        if len(self._frame_buffer) >= self._frame_queue_size:
            self._frame_buffer.popleft()
            self._dropped_frames += 1
        self._frame_buffer.append(frame)
        self._frame_ready.set()

    def _queue_reply(self, reply: DeviceReply) -> None:
        if isinstance(reply, EventFrame):
            # Events belong to the stream: keep them in order with the frames around them.
            self._queue_frame(reply)
            return
        self._reply_buffer.append(reply)
        self._reply_ready.set()

    def _mark_link_down(self, reason: str) -> None:
        if self._link_closed:
            return
        self._link_closed = True
        self._link_reason = reason
        self._frame_ready.set()
        self._reply_ready.set()

    async def _shutdown(self) -> None:
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
        self._mark_link_down("the client was closed")
        await self._transport.close()
