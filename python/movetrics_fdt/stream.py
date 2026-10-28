"""The 24-byte measurement frame (T_Frame, the firmware) and the device-side demultiplexer.

Wire layout (docs/05-measurement-stream.md, Table 2.1):
  BE EF pa 01 ts[4] forceX forceY forceZ momentX momentY momentZ crc_lo crc_hi 04 04
All multi-byte fields are little-endian. The CRC covers bytes 2 to 19.

The device sends stream frames and replies on one byte stream. A frame is found by its header, its
command byte and its length. It is accepted only when its end marker and CRC match. The 04 04 pair is
never used to cut the stream (doc 05 sections 9.1 and 9.2).
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass

from .errors import FrameError
from .frames import (
    ACK_CODE,
    ACK_LENGTH,
    DEVICE_HEADER,
    FIRMWARE_VERSION_LENGTH,
    NACK_CODE,
    NACK_LENGTH,
    AckReply,
    FirmwareVersionReply,
    NackReply,
    build_device_frame,
    check_envelope,
    decode_ack,
    decode_firmware_version,
    decode_nack,
    envelope_is_valid,
)
from .status import RECORD_LENGTH, RECORD_LENGTH_NO_SOC, STATUS_COMMAND, StatusRecord, decode_status_record

STREAM_COMMAND = 0x01  # CMD_START_STREAM, the firmware; the placeholders and the stream use it
# Sync event frames (FDT 1.2.8.24, docs/05 section 13): the 24-byte envelope with plate
# address 0xFD and code 0x0E. Sent only after a host sets EVENT_FRAMES (0x08) or SATURATION_EVENTS (0x20) with
# SET_SYNC_MODE, so firmware without sync modes never sends one. Vectors: vectors/sync_events.json ().
EVENT_ADDRESS = 0xFD
EVENT_COMMAND = 0x0E
STREAM_LENGTH = 24  # sizeof(T_Frame), the firmware
FIRMWARE_VERSION_COMMAND = 0x23  # CMD_GET_FW_VERSION, the firmware

_BODY = struct.Struct("<BBIhhhhhh")  # bytes 2 to 19: pa, commandCode, timeStamp, six int16 channels
assert _BODY.size == STREAM_LENGTH - 6


@dataclass(frozen=True)
class StreamFrame:
    """One decoded stream frame. The six integers are raw wire values; their unit is not defined."""

    platform_address: int
    commandCode: int
    timeStamp: int
    forceX: int
    forceY: int
    forceZ: int
    momentX: int
    momentY: int
    momentZ: int

    @property
    def is_placeholder(self) -> bool:
        """True for a zero stamp. Doc 05 section 6.4 treats every zero stamp as a placeholder."""
        return self.timeStamp == 0


_EVENT_BODY = struct.Struct("<BBIBBIhHBx")  # pa, code, stamp, type, source, counter, offset_us, detail, mode, 0
assert _EVENT_BODY.size == STREAM_LENGTH - 6

EVENT_NAMES: dict[int, str] = {  # contracts/vocabulary.v1.json "events"; docs/05 section 13
    1: "sync_in_rise",
    2: "sync_in_fall",
    3: "sync_out_rise",
    4: "sync_out_fall",
    5: "stream_armed",
    6: "stream_started_by_trigger",
    7: "saturation",
    8: "frames_dropped",
    9: "saturation_end",
    10: "arm_expired",
}


@dataclass(frozen=True)
class EventFrame:
    """A sync event from the controller: an edge or a state change. The edge lies offset_us after the start of tick
    timeStamp. source is the sync input or output (0), or the plate for saturation. detail: arm timeout in minutes
    for stream_armed and arm_expired, the channel mask for saturation (bits 0-5 fx..mz wrapped, bit 6 a pad
    channel clipped), the number of frames for frames_dropped. mode is the sync mode in force."""

    timeStamp: int
    event_type: int
    source: int
    count: int
    detail: int
    offset_us: int = 0
    mode: int = 0

    @property
    def name(self) -> str:
        return EVENT_NAMES.get(self.event_type, f"unknown_{self.event_type}")


def encode_event_frame(event: EventFrame) -> bytes:
    """Build the 24 wire bytes of an event frame. Used by the simulator and tests."""
    try:
        body = _EVENT_BODY.pack(EVENT_ADDRESS, EVENT_COMMAND, event.timeStamp, event.event_type, event.source,
                                event.count, event.offset_us, event.detail, event.mode)
    except struct.error as error:
        raise ValueError(f"event field out of range: {error}") from error
    return build_device_frame(body)


def decode_event_frame(data: bytes) -> EventFrame:
    """Decode exactly 24 bytes as an event frame."""
    raw = bytes(data)
    check_envelope(raw, STREAM_LENGTH)
    address, command, stamp, event_type, source, count, offset, detail, mode = _EVENT_BODY.unpack(raw[2:20])
    if address != EVENT_ADDRESS or command != EVENT_COMMAND:
        raise FrameError("bad_command", f"an event frame has address 0xFD and code 0x0E, got 0x{address:02X} 0x{command:02X}")
    return EventFrame(timeStamp=stamp, event_type=event_type, source=source, count=count, detail=detail,
                      offset_us=offset, mode=mode)


SYNC_MODE_COMMAND = 0x29
SYNC_MODE_LENGTH = 26
_SYNC_MODE_BODY = struct.Struct("<BBBHBBBBBIIH")


@dataclass(frozen=True)
class SyncModeReply:
    """GET_SYNC_MODE reply (docs/04 section 3.9). state bits: 0x01 armed, 0x02 restored after a
    reset, 0x04 backup write read back equal, 0x08 SYNC IN high, 0x10 SYNC OUT high, 0x20 streaming."""

    mode: int
    pulse_period_ms: int
    pulse_width_ms: int
    debounce_ticks: int
    arm_timeout_min: int
    state: int
    contract: int
    edges_in: int
    edges_out: int
    overflows: int


def encode_sync_mode_reply(reply: SyncModeReply, address: int = 0) -> bytes:
    return build_device_frame(_SYNC_MODE_BODY.pack(
        address, SYNC_MODE_COMMAND, reply.mode, reply.pulse_period_ms, reply.pulse_width_ms, reply.debounce_ticks,
        reply.arm_timeout_min, reply.state, reply.contract, reply.edges_in, reply.edges_out, reply.overflows))


def decode_sync_mode_reply(data: bytes) -> SyncModeReply:
    raw = bytes(data)
    check_envelope(raw, SYNC_MODE_LENGTH)
    fields = _SYNC_MODE_BODY.unpack(raw[2:22])
    if fields[1] != SYNC_MODE_COMMAND:
        raise FrameError("bad_command")
    return SyncModeReply(*fields[2:])


def encode_stream_frame(frame: StreamFrame) -> bytes:
    """Build the 24 wire bytes of a stream frame from its fields. Used to produce test replies."""
    try:
        body = _BODY.pack(
            frame.platform_address,
            frame.commandCode,
            frame.timeStamp,
            frame.forceX,
            frame.forceY,
            frame.forceZ,
            frame.momentX,
            frame.momentY,
            frame.momentZ,
        )
    except struct.error as error:
        raise ValueError(f"stream field out of range: {error}") from error
    return build_device_frame(body)


def decode_stream_frame(data: bytes) -> StreamFrame:
    """Decode exactly 24 bytes as a stream frame.

    Raises FrameError with reason bad_length, bad_header, bad_end_marker, crc_mismatch or bad_command.
    """
    raw = bytes(data)
    check_envelope(raw, STREAM_LENGTH)
    platform_address, command, stamp, force_x, force_y, force_z, moment_x, moment_y, moment_z = (
        _BODY.unpack(raw[2:20])
    )
    if command != STREAM_COMMAND:
        raise FrameError("bad_command", f"a stream frame has command 0x01, got 0x{command:02X}")
    return StreamFrame(
        platform_address=platform_address,
        commandCode=command,
        timeStamp=stamp,
        forceX=force_x,
        forceY=force_y,
        forceZ=force_z,
        momentX=moment_x,
        momentY=moment_y,
        momentZ=moment_z,
    )


DeviceReply = AckReply | NackReply | FirmwareVersionReply | StatusRecord | EventFrame | SyncModeReply

_REPLY_LENGTHS: dict[int, tuple[int, ...]] = {
    STREAM_COMMAND: (STREAM_LENGTH,),
    EVENT_COMMAND: (STREAM_LENGTH,),
    SYNC_MODE_COMMAND: (SYNC_MODE_LENGTH,),
    STATUS_COMMAND: (RECORD_LENGTH, RECORD_LENGTH_NO_SOC),
    FIRMWARE_VERSION_COMMAND: (FIRMWARE_VERSION_LENGTH,),
}


def _typed(frame: bytes, command: int, length: int) -> DeviceReply | None:
    """Decode a candidate that already passed its envelope check, or return None if it is not that kind."""
    try:
        if length == ACK_LENGTH and frame[4] == ACK_CODE:
            return decode_ack(frame)
        if length == NACK_LENGTH and frame[4] == NACK_CODE:
            return decode_nack(frame)
        if command == STREAM_COMMAND and length == STREAM_LENGTH:
            return decode_stream_frame(frame)
        if command == EVENT_COMMAND and length == STREAM_LENGTH and frame[2] == EVENT_ADDRESS:
            return decode_event_frame(frame)
        if command == SYNC_MODE_COMMAND and length == SYNC_MODE_LENGTH:
            return decode_sync_mode_reply(frame)
        if command == STATUS_COMMAND and length in (RECORD_LENGTH, RECORD_LENGTH_NO_SOC):
            return decode_status_record(frame)
        if command == FIRMWARE_VERSION_COMMAND and length == FIRMWARE_VERSION_LENGTH:
            return decode_firmware_version(frame)
    except FrameError:
        return None
    return None


class StreamDecoder:
    """Splits device output into stream frames and other replies.

    push() returns the stream frames completed by the bytes it was given. Every other reply
    (ACK, NACK, GET_STATUS records, GET_FW_VERSION, event frames) goes to on_reply when one is set. Partial frames
    are kept for the next push. Bytes that start no valid frame are discarded one at a time.
    """

    def __init__(self, on_reply: Callable[[DeviceReply], None] | None = None) -> None:
        self._buffer = bytearray()
        self._on_reply = on_reply
        self.discarded_bytes = 0

    def push(self, data: bytes) -> list[StreamFrame]:
        """Feed device bytes. Return the stream frames they complete, in order."""
        self._buffer.extend(data)
        frames: list[StreamFrame] = []
        while True:
            head = self._buffer.find(DEVICE_HEADER)
            if head < 0:
                keep = 1 if self._buffer[-1:] == b"\xbe" else 0
                dropped = len(self._buffer) - keep
                del self._buffer[:dropped]
                self.discarded_bytes += dropped
                break
            if head:
                del self._buffer[:head]
                self.discarded_bytes += head
            state, length, item = self._match()
            if state == "need":
                break
            if state == "discard":
                del self._buffer[:1]
                self.discarded_bytes += 1
                continue
            del self._buffer[:length]
            if isinstance(item, StreamFrame):
                frames.append(item)
            elif item is not None and self._on_reply is not None:
                self._on_reply(item)
        return frames

    def _match(self) -> tuple[str, int, StreamFrame | DeviceReply | None]:
        """Classify the frame at the head of the buffer, which starts with BE EF."""
        buffer = self._buffer
        if len(buffer) < 4:
            return "need", 0, None
        command = buffer[3]
        undecided = False
        for length in _REPLY_LENGTHS.get(command, ()) + (ACK_LENGTH, NACK_LENGTH):
            if len(buffer) < length:
                undecided = True
                continue
            candidate = bytes(buffer[:length])
            if not envelope_is_valid(candidate):
                continue
            item = _typed(candidate, command, length)
            if item is not None:
                return "frame", length, item
        return ("need" if undecided else "discard"), 0, None
