"""CRC-16/CCITT-FALSE: the published check value, edge cases, and a bitwise reference on random data."""

from __future__ import annotations

import random
import unittest

from movetrics_fdt.crc import crc16_ccitt_false


def _bitwise_crc16(data: bytes, init: int = 0xFFFF) -> int:
    """A bit-at-a-time reference, written apart from the table-driven code under test."""
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class Crc16Tests(unittest.TestCase):
    def test_published_check_value(self) -> None:
        self.assertEqual(crc16_ccitt_false(b"123456789"), 0x29B1)

    def test_empty_input_returns_the_initial_value(self) -> None:
        self.assertEqual(crc16_ccitt_false(b""), 0xFFFF)

    def test_single_byte_00(self) -> None:
        self.assertEqual(crc16_ccitt_false(b"\x00"), 0xE1F0)

    def test_single_byte_ff(self) -> None:
        self.assertEqual(crc16_ccitt_false(b"\xff"), 0xFF00)

    def test_get_status_body_has_the_crc_the_vector_gives(self) -> None:
        self.assertEqual(crc16_ccitt_false(b"\x00\x00\x22"), 0xC8BC)

    def test_init_argument_is_the_starting_register(self) -> None:
        self.assertEqual(crc16_ccitt_false(b"", init=0), 0)
        self.assertEqual(crc16_ccitt_false(b"", init=0x1234), 0x1234)

    def test_chaining_from_a_partial_result_equals_one_pass(self) -> None:
        data = b"movetrics stream"
        partial = crc16_ccitt_false(data[:5])
        self.assertEqual(crc16_ccitt_false(data[5:], init=partial), crc16_ccitt_false(data))

    def test_accepts_bytearray_and_memoryview(self) -> None:
        data = b"\x01\x02\x03"
        self.assertEqual(crc16_ccitt_false(bytearray(data)), crc16_ccitt_false(data))
        self.assertEqual(crc16_ccitt_false(memoryview(data)), crc16_ccitt_false(data))

    def test_matches_the_bitwise_reference_on_random_data(self) -> None:
        rng = random.Random(0x5EED)
        for _ in range(200):
            data = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 80)))
            with self.subTest(data=data.hex()):
                self.assertEqual(crc16_ccitt_false(data), _bitwise_crc16(data))


if __name__ == "__main__":
    unittest.main()
