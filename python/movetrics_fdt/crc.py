"""CRC-16/CCITT-FALSE, the checksum of every host and device frame.

Same routine as crc16() in the firmware: initial value 0xFFFF, polynomial 0x1021,
no reflection, no final XOR. The check value of b"123456789" is 0x29B1.
"""

from __future__ import annotations

_POLYNOMIAL = 0x1021


def _build_table() -> tuple[int, ...]:
    table: list[int] = []
    for index in range(256):
        crc = index << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ _POLYNOMIAL) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
        table.append(crc)
    return tuple(table)


_TABLE: tuple[int, ...] = _build_table()


def crc16_ccitt_false(data: bytes | bytearray | memoryview, init: int = 0xFFFF) -> int:
    """Return the CRC-16/CCITT-FALSE of data, starting from init."""
    crc = init & 0xFFFF
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _TABLE[((crc >> 8) ^ byte) & 0xFF]
    return crc
