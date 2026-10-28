"""Host request frames and device reply envelopes, as docs/03-host-link-framing.md defines them.

Host request:  FE ED pa da cmd [payload] crc_lo crc_hi 04 04
Device reply:  BE EF pa cmd ...         crc_lo crc_hi 04 04
The CRC is CRC-16/CCITT-FALSE over bytes 2 to n-5 and is stored low byte first. Nothing here
opens a port or sends bytes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .commands import IMPLEMENTED_CODES, not_implemented_reason
from .crc import crc16_ccitt_false
from .errors import FrameError, UnsupportedCommandError

HOST_HEADER = b"\xfe\xed"  # CMD_HEADER_MARKER 0xFEED, the firmware
DEVICE_HEADER = b"\xbe\xef"  # RSP_HEADER_MARKER 0xEFBE, the firmware
END_MARKER = b"\x04\x04"  # HP_EOT, the firmware
ACK_CODE = 0x06  # HP_ACK, the firmware
NACK_CODE = 0x15  # HP_NACK, the firmware
BROADCAST_ADDRESS = 0xFF  # the firmware
MAX_MESSAGE_LENGTH = 320  # MSG_BUILDER_SIZE 256 + 64, the firmware; doc 03 section 3.4
MIN_REQUEST_LENGTH = 9  # the firmware

ACK_LENGTH = 9  # the firmware
NACK_LENGTH = 11  # the firmware
FIRMWARE_VERSION_LENGTH = 38  # the firmware

NACK_ERROR_NAMES: dict[int, str] = {  # the firmware
    1: "ERR_PLATFORM_NOT_EXIST",
    2: "ERR_PLATFORM_NO_RESPONSE",
    3: "ERR_INVALID_PARAMETER",
    4: "ERR_SELF_TEST_FAILED",
    5: "ERR_WIFI_CONNECTION_FAILED",
    6: "ERR_WIFI_AP_START_FAILED",
    7: "ERR_UNKNOWN_COMMAND",
    8: "ERR_UNEFFECTIVE_COMMAND",
    9: "ERR_CRC",
}


def _check_byte(name: str, value: int) -> None:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be 0..255, got {value}")


def _crc_bytes(crc: int) -> bytes:
    return bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def encode_host_frame(command: int, address: int, destination: int, payload: bytes = b"") -> bytes:
    """Build a host request frame.

    Refuses every command the client does not implement (UnsupportedCommandError), and any frame in
    which 04 04 would close the controller's message early (FrameError, reason early_04_04_delimiter,
    with the frame in .would_be). Doc 03 section 3.3.
    """
    _check_byte("command", command)
    _check_byte("address", address)
    _check_byte("destination", destination)
    if command not in IMPLEMENTED_CODES:
        reason = not_implemented_reason(command) or "not a known command code"
        raise UnsupportedCommandError(command, reason)
    body = bytes(payload)
    head = HOST_HEADER + bytes((address, destination, command)) + body
    frame = head + _crc_bytes(crc16_ccitt_false(head[2:]))
    frame += END_MARKER
    if len(frame) > MAX_MESSAGE_LENGTH:
        raise FrameError("too_long", f"host frame of {len(frame)} bytes exceeds {MAX_MESSAGE_LENGTH}")
    # The controller closes a message at the first 04 04, so no pair may end before the last byte.
    if frame.find(END_MARKER, 0, len(frame) - 1) != -1:
        raise FrameError(
            "early_04_04_delimiter",
            "the frame contains 04 04 before its end marker, so the controller would split it",
            would_be=frame,
        )
    return frame


@dataclass(frozen=True)
class HostFrame:
    """A host request as the controller parses it."""

    address: int
    destination: int
    command: int
    payload: bytes
    raw: bytes = field(repr=False, compare=False)


def parse_host_message(message: bytes) -> HostFrame:
    """Parse one message the way the controller does (the firmware), without replying.

    Resynchronises at the first FE ED that has nine bytes from its position onward. Raises
    FrameError with reason shorter_than_9_bytes, bad_header, crc_mismatch or bad_end_marker.
    """
    buf = bytes(message)
    if len(buf) >= MIN_REQUEST_LENGTH and buf[:2] != HOST_HEADER:
        for index in range(1, len(buf) - MIN_REQUEST_LENGTH + 1):
            if buf[index : index + 2] == HOST_HEADER:
                buf = buf[index:]
                break
    if len(buf) < MIN_REQUEST_LENGTH:
        raise FrameError("shorter_than_9_bytes")
    if buf[:2] != HOST_HEADER:
        raise FrameError("bad_header")
    received_crc = buf[-4] | (buf[-3] << 8)
    if crc16_ccitt_false(buf[2:-4]) != received_crc:
        raise FrameError("crc_mismatch")
    if buf[-2:] != END_MARKER:
        raise FrameError("bad_end_marker")
    return HostFrame(
        address=buf[2],
        destination=buf[3],
        command=buf[4],
        payload=buf[5:-4],
        raw=buf,
    )


class HostRxSplitter:
    """Cuts a byte stream into messages at the first pair of 04 bytes, as the firmware does.

    A message longer than MAX_MESSAGE_LENGTH is dropped, as the controller drops it.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._previous = 0
        self._overflow = False

    def feed(self, data: bytes) -> list[bytes]:
        """Return the messages completed by data, in order. A trailing partial message is kept."""
        messages: list[bytes] = []
        for byte in data:
            if len(self._buffer) < MAX_MESSAGE_LENGTH:
                self._buffer.append(byte)
            else:
                self._overflow = True
            if self._previous == 0x04 and byte == 0x04:
                if not self._overflow:
                    messages.append(bytes(self._buffer))
                self._buffer.clear()
                self._overflow = False
                self._previous = 0
            else:
                self._previous = byte
        return messages


class HostFrameReader:
    """Reads host frames from a byte stream: the RX splitter followed by parse_host_message."""

    def __init__(self) -> None:
        self._splitter = HostRxSplitter()
        self.rejected: list[tuple[bytes, str]] = []

    def feed(self, data: bytes) -> list[HostFrame]:
        """Return the valid host frames completed by data. Rejected messages go to self.rejected."""
        frames: list[HostFrame] = []
        for message in self._splitter.feed(data):
            try:
                frames.append(parse_host_message(message))
            except FrameError as error:
                self.rejected.append((message, error.reason))
        return frames


def envelope_is_valid(frame: bytes) -> bool:
    """True when a device frame has the BE EF header, the 04 04 end and a matching CRC."""
    if len(frame) < ACK_LENGTH or frame[:2] != DEVICE_HEADER or frame[-2:] != END_MARKER:
        return False
    return crc16_ccitt_false(frame[2:-4]) == (frame[-4] | (frame[-3] << 8))


def check_envelope(frame: bytes, length: int) -> None:
    """Raise FrameError unless frame is exactly length bytes with a valid envelope."""
    if len(frame) != length:
        raise FrameError("bad_length", f"expected {length} bytes, got {len(frame)}")
    if frame[:2] != DEVICE_HEADER:
        raise FrameError("bad_header")
    if frame[-2:] != END_MARKER:
        raise FrameError("bad_end_marker")
    if not envelope_is_valid(frame):
        raise FrameError("crc_mismatch")


@dataclass(frozen=True)
class AckReply:
    """ACK reply: BE EF pa cmd 06 crc crc 04 04 (the firmware)."""

    platform_address: int
    command: int
    raw: bytes = field(repr=False, compare=False)


@dataclass(frozen=True)
class NackReply:
    """NACK reply: BE EF pa cmd 15 err_lo err_hi crc crc 04 04 (the firmware)."""

    platform_address: int
    command: int
    nack_code: int
    error_code: int
    raw: bytes = field(repr=False, compare=False)

    @property
    def error_name(self) -> str:
        """The firmware name of the error code, or UNKNOWN."""
        return NACK_ERROR_NAMES.get(self.error_code, "UNKNOWN")


@dataclass(frozen=True)
class FirmwareVersionReply:
    """GET_FW_VERSION reply, 38 bytes (the firmware)."""

    platform_address: int
    command: int
    stm32FW: str
    esp32FW: str
    raw: bytes = field(repr=False, compare=False)


def _text(field_bytes: bytes) -> str:
    return field_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def decode_ack(frame: bytes) -> AckReply:
    """Decode a 9-byte ACK reply."""
    check_envelope(frame, ACK_LENGTH)
    if frame[4] != ACK_CODE:
        raise FrameError("bad_ack_code")
    return AckReply(platform_address=frame[2], command=frame[3], raw=bytes(frame))


def decode_nack(frame: bytes) -> NackReply:
    """Decode an 11-byte NACK reply."""
    check_envelope(frame, NACK_LENGTH)
    if frame[4] != NACK_CODE:
        raise FrameError("bad_nack_code")
    return NackReply(
        platform_address=frame[2],
        command=frame[3],
        nack_code=frame[4],
        error_code=frame[5] | (frame[6] << 8),
        raw=bytes(frame),
    )


def decode_firmware_version(frame: bytes) -> FirmwareVersionReply:
    """Decode a 38-byte GET_FW_VERSION reply (the firmware; the CRC covers bytes 2 to 33)."""
    check_envelope(frame, FIRMWARE_VERSION_LENGTH)
    if frame[3] != 0x23:
        raise FrameError("bad_command")
    return FirmwareVersionReply(
        platform_address=frame[2],
        command=frame[3],
        stm32FW=_text(frame[4:19]),
        esp32FW=_text(frame[19:34]),
        raw=bytes(frame),
    )


def build_device_frame(body: Iterable[int]) -> bytes:
    """Wrap pa, cmd and the rest of a device reply body in BE EF, its CRC and 04 04.

    Used by tests and fake transports to produce replies from their layouts.
    """
    head = DEVICE_HEADER + bytes(body)
    return head + _crc_bytes(crc16_ccitt_false(head[2:])) + END_MARKER
