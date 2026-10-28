"""GET_STATUS (0x22) records.

Layout: the firmware (T_StatusResponse, 86 bytes, batterySOC at offset 81). The 85-byte class is
the same layout without batterySOC (vectors/status.json; vectors/README.md, conflict 1).
The layout is chosen by the byte count and the CRC only. A version string never selects it.

A reply is one record for address 0, then one record per detected platform (the firmware).
So a reply is 1 to STATUS_MAX_RECORDS records, all of one length: 85 bytes each, or 86 bytes each. A reply
that mixes the two lengths is refused. Every reply starts with the general record (address 0), even one that
holds a single record, and its platforms follow in strictly increasing order, with addresses 1 and 2
(ts/src/status.ts). decode_status_record accepts a platform record on its own; parse_status refuses it as a
reply (see _check_platform_order).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .errors import FrameError
from .frames import check_envelope

STATUS_COMMAND = 0x22
RECORD_LENGTH = 86
RECORD_LENGTH_NO_SOC = 85
# One general record and up to two platforms: PLATFORMS_MAX is 2 + 1 (the firmware).
STATUS_MAX_RECORDS = 3
# The general record is address 0, so the platforms are addresses 1 up to STATUS_MAX_RECORDS - 1.
_HIGHEST_PLATFORM_ADDRESS = STATUS_MAX_RECORDS - 1

# Little-endian. Fields: header, platform_address, commandCode, errorFlags, temperature (int8),
# serialParams[20], wifiSSID[30], wifiIP[4], wifiMask[4], wifiGW[4], cacheFrames, calibrationFactorX/Y/Z,
# then batterySOC (86-byte class only), crc, eot1 and eot2.
_RECORD_86 = struct.Struct("<HBBIb20s30s4s4s4sIHHHBH2s")
_RECORD_85 = struct.Struct("<HBBIb20s30s4s4s4sIHHHH2s")
assert _RECORD_86.size == RECORD_LENGTH
assert _RECORD_85.size == RECORD_LENGTH_NO_SOC

_FIXED_FIELD_COUNT = 14  # header through calibrationFactorZ


@dataclass(frozen=True)
class StatusRecord:
    """One GET_STATUS record. batterySOC is None in the 85-byte class (255 means not measured)."""

    platform_address: int
    commandCode: int
    errorFlags: int
    temperature: int
    serialParams: str
    wifiSSID: str
    wifiIP: tuple[int, int, int, int]
    wifiMask: tuple[int, int, int, int]
    wifiGW: tuple[int, int, int, int]
    cacheFrames: int
    calibrationFactorX: int
    calibrationFactorY: int
    calibrationFactorZ: int
    batterySOC: int | None
    raw: bytes = field(repr=False, compare=False)


@dataclass(frozen=True)
class Status:
    """A GET_STATUS reply: its records in wire order, and the length class they came in.

    length_class is "85" or "86" for one record, and "85xN" or "86xN" for N records (N is 2 or 3).
    """

    records: tuple[StatusRecord, ...]
    length_class: str

    @property
    def general(self) -> StatusRecord | None:
        """The record for address 0, or None when the reply has none."""
        return next((record for record in self.records if record.platform_address == 0), None)

    @property
    def platforms(self) -> tuple[StatusRecord, ...]:
        """The records for platform addresses 1 and up."""
        return tuple(record for record in self.records if record.platform_address != 0)


def _text(field_bytes: bytes) -> str:
    return field_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def decode_status_record(frame: bytes) -> StatusRecord:
    """Decode one 85-byte or 86-byte GET_STATUS record, checking header, command, end marker and CRC."""
    raw = bytes(frame)
    if len(raw) == RECORD_LENGTH:
        layout = _RECORD_86
    elif len(raw) == RECORD_LENGTH_NO_SOC:
        layout = _RECORD_85
    else:
        raise FrameError("bad_length", f"a GET_STATUS record is 85 or 86 bytes, got {len(raw)}")
    check_envelope(raw, len(raw))
    if raw[3] != STATUS_COMMAND:
        raise FrameError("bad_command")
    values = layout.unpack(raw)
    (
        _header, platform_address, command, error_flags, temperature, serial, ssid,
        ip, mask, gateway, cache, factor_x, factor_y, factor_z,
    ) = values[:_FIXED_FIELD_COUNT]
    battery = values[_FIXED_FIELD_COUNT] if layout is _RECORD_86 else None
    return StatusRecord(
        platform_address=platform_address,
        commandCode=command,
        errorFlags=error_flags,
        temperature=temperature,
        serialParams=_text(serial),
        wifiSSID=_text(ssid),
        wifiIP=tuple(ip),
        wifiMask=tuple(mask),
        wifiGW=tuple(gateway),
        cacheFrames=cache,
        calibrationFactorX=factor_x,
        calibrationFactorY=factor_y,
        calibrationFactorZ=factor_z,
        batterySOC=battery,
        raw=raw,
    )


def _record_count(total: int, record_length: int) -> int | None:
    """How many records of record_length make up total, when that is 1 to STATUS_MAX_RECORDS; else None."""
    count, remainder = divmod(total, record_length)
    if remainder == 0 and 1 <= count <= STATUS_MAX_RECORDS:
        return count
    return None


def _mixes_both_lengths(total: int) -> bool:
    """True when total is some 85-byte records and some 86-byte records together, at most STATUS_MAX_RECORDS."""
    return any(
        ones * RECORD_LENGTH_NO_SOC + others * RECORD_LENGTH == total
        for ones in range(1, STATUS_MAX_RECORDS)
        for others in range(1, STATUS_MAX_RECORDS)
        if ones + others <= STATUS_MAX_RECORDS
    )


def _check_platform_order(records: tuple[StatusRecord, ...]) -> None:
    """Refuse a reply whose records are out of place, as ts/src/status.ts does.

    Every address must be at most _HIGHEST_PLATFORM_ADDRESS. Every reply starts with the general record (address 0),
    even when it holds one record (the firmware), and the platform addresses after it strictly increase.
    A lone platform record is a valid record (decode_status_record accepts it), but it is not a valid reply.
    """
    addresses = [record.platform_address for record in records]
    for address in addresses:
        if address > _HIGHEST_PLATFORM_ADDRESS:
            raise FrameError(
                "bad_platform_order",
                f"platform address {address} is above the highest platform address {_HIGHEST_PLATFORM_ADDRESS}",
            )
    if addresses[0] != 0 or any(later <= earlier for earlier, later in zip(addresses, addresses[1:])):
        raise FrameError(
            "bad_platform_order",
            f"status records at addresses {addresses}: expected address 0 first, then platforms in increasing order",
        )


def parse_status(data: bytes) -> Status:
    """Parse a whole GET_STATUS reply: 1 to STATUS_MAX_RECORDS records, all 85 bytes or all 86 bytes long.

    Every record is decoded with its own envelope and CRC check, so a damaged record raises FrameError with
    reason crc_mismatch. Any other length raises unsupported_length. A length that is a sum of 85-byte and
    86-byte records raises mixed_record_lengths. A reply that does not start with the general record, a platform
    address above _HIGHEST_PLATFORM_ADDRESS, or platforms out of increasing order, raises bad_platform_order.
    """
    raw = bytes(data)
    for record_length, class_name in ((RECORD_LENGTH_NO_SOC, "85"), (RECORD_LENGTH, "86")):
        count = _record_count(len(raw), record_length)
        if count is None:
            continue
        records = tuple(
            decode_status_record(raw[offset : offset + record_length])
            for offset in range(0, len(raw), record_length)
        )
        _check_platform_order(records)
        length_class = class_name if count == 1 else f"{class_name}x{count}"
        return Status(records=records, length_class=length_class)
    if _mixes_both_lengths(len(raw)):
        raise FrameError(
            "mixed_record_lengths",
            f"GET_STATUS reply of {len(raw)} bytes mixes 85-byte and 86-byte records",
        )
    raise FrameError(
        "unsupported_length",
        f"GET_STATUS reply of {len(raw)} bytes: expected 1 to {STATUS_MAX_RECORDS} records of 85 or of 86 bytes",
    )
