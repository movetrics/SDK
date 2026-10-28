"""GET_STATUS replies: 1 to 3 records of one length (85 or 86 bytes), their platform order, the refusals,
and the per-record CRC.
"""

from __future__ import annotations

import unittest

from movetrics_fdt.crc import crc16_ccitt_false
from movetrics_fdt.errors import FrameError
from movetrics_fdt.status import decode_status_record, parse_status

from .support import find_case

STATUS_85 = bytes.fromhex(find_case("status.json", "status-anchor-identification-85")["frame_hex"])
RECORD_86_GENERAL = bytes.fromhex(find_case("status.json", "status-derived-86-general-record")["frame_hex"])
RECORD_86_PLATFORM_1 = bytes.fromhex(find_case("status.json", "status-derived-86-platform-1-record")["frame_hex"])
RECORD_86_PLATFORM_2 = bytes.fromhex(find_case("status.json", "status-derived-86-platform-2-record")["frame_hex"])
REPLY_86X3 = bytes.fromhex(find_case("status.json", "status-derived-86x3-reply")["frame_hex"])


def record_with_address(template: bytes, address: int) -> bytes:
    """A vector record with another platform address, and a CRC that matches the change."""
    body = bytearray(template)
    body[2] = address
    crc = crc16_ccitt_false(bytes(body[2:-4]))
    body[-4:-2] = bytes((crc & 0xFF, crc >> 8))
    return bytes(body)


def record_85_at(address: int) -> bytes:
    """The 85-byte vector record with another platform address, and a CRC that matches the change."""
    return record_with_address(STATUS_85, address)


def reply_at(*addresses: int) -> bytes:
    """A reply of 85-byte records, one for each address, in the order given."""
    return b"".join(record_85_at(address) for address in addresses)


class StatusLengthClassTests(unittest.TestCase):
    def test_85_bytes_is_one_record_without_battery(self) -> None:
        status = parse_status(STATUS_85)
        self.assertEqual(status.length_class, "85")
        self.assertEqual(len(status.records), 1)
        self.assertIsNone(status.records[0].batterySOC)

    def test_two_85_byte_records(self) -> None:
        status = parse_status(record_85_at(0) + record_85_at(1))
        self.assertEqual(status.length_class, "85x2")
        self.assertEqual([record.platform_address for record in status.records], [0, 1])
        self.assertTrue(all(record.batterySOC is None for record in status.records))

    def test_three_85_byte_records(self) -> None:
        status = parse_status(record_85_at(0) + record_85_at(1) + record_85_at(2))
        self.assertEqual(status.length_class, "85x3")
        self.assertEqual([record.platform_address for record in status.records], [0, 1, 2])

    def test_one_86_byte_record(self) -> None:
        status = parse_status(RECORD_86_GENERAL)
        self.assertEqual(status.length_class, "86")
        self.assertEqual(status.records[0].batterySOC, 87)

    def test_two_86_byte_records(self) -> None:
        status = parse_status(RECORD_86_GENERAL + RECORD_86_PLATFORM_1)
        self.assertEqual(status.length_class, "86x2")
        self.assertEqual([record.platform_address for record in status.records], [0, 1])

    def test_three_86_byte_records_from_the_general_and_two_platforms(self) -> None:
        status = parse_status(REPLY_86X3)
        self.assertEqual(status.length_class, "86x3")
        self.assertEqual(len(status.records), 3)
        self.assertIsNotNone(status.general)
        self.assertEqual(status.general.batterySOC, 87)
        self.assertEqual([record.platform_address for record in status.platforms], [1, 2])
        self.assertEqual(status.platforms[1].calibrationFactorZ, 514)

    def test_four_records_are_refused_in_either_length(self) -> None:
        replies = (
            record_85_at(0) + record_85_at(1) + record_85_at(2) + record_85_at(0),  # 340 bytes: 85 x 4
            REPLY_86X3 + RECORD_86_GENERAL,  # 344 bytes: 86 x 4
        )
        for reply in replies:
            with self.subTest(length=len(reply)):
                with self.assertRaises(FrameError) as raised:
                    parse_status(reply)
                self.assertEqual(raised.exception.reason, "unsupported_length")

    def test_a_mix_of_85_and_86_byte_records_is_refused(self) -> None:
        replies = (
            STATUS_85 + RECORD_86_GENERAL,  # 171 bytes: 85 + 86
            record_85_at(0) + record_85_at(1) + RECORD_86_GENERAL,  # 256 bytes: 85 + 85 + 86
            record_85_at(0) + RECORD_86_GENERAL + RECORD_86_PLATFORM_1,  # 257 bytes: 85 + 86 + 86
        )
        for reply in replies:
            with self.subTest(length=len(reply)):
                with self.assertRaises(FrameError) as raised:
                    parse_status(reply)
                self.assertEqual(raised.exception.reason, "mixed_record_lengths")

    def test_lengths_that_are_no_multiple_of_a_record_length_are_refused(self) -> None:
        for length in (0, 84, 87, 100, 173):
            with self.subTest(length=length):
                with self.assertRaises(FrameError) as raised:
                    parse_status(bytes(length))
                self.assertEqual(raised.exception.reason, "unsupported_length")


class StatusFieldTests(unittest.TestCase):
    def test_text_fields_stop_at_the_first_nul(self) -> None:
        status = parse_status(STATUS_85)
        self.assertEqual(status.records[0].serialParams, "123")
        self.assertEqual(status.records[0].wifiSSID, "123")
        self.assertEqual(status.records[0].wifiIP, (1, 2, 3, 4))

    def test_battery_255_is_kept_as_the_raw_value(self) -> None:
        record = decode_status_record(RECORD_86_PLATFORM_1)
        self.assertEqual(record.batterySOC, 255)
        self.assertEqual(record.errorFlags, 1)

    def test_a_flipped_bit_in_a_record_fails_its_crc(self) -> None:
        damaged = bytearray(RECORD_86_GENERAL)
        damaged[20] ^= 0x10
        with self.assertRaises(FrameError) as raised:
            parse_status(bytes(damaged))
        self.assertEqual(raised.exception.reason, "crc_mismatch")

    def test_a_damaged_record_in_a_two_record_85_reply_fails_its_crc(self) -> None:
        damaged = bytearray(record_85_at(0) + record_85_at(1))
        damaged[85 + 20] ^= 0x10  # inside the second record
        with self.assertRaises(FrameError) as raised:
            parse_status(bytes(damaged))
        self.assertEqual(raised.exception.reason, "crc_mismatch")

    def test_the_raw_bytes_of_each_record_are_kept(self) -> None:
        status = parse_status(REPLY_86X3)
        self.assertEqual(b"".join(record.raw for record in status.records), REPLY_86X3)


class PlatformOrderTests(unittest.TestCase):
    def assert_bad_platform_order(self, reply: bytes) -> None:
        with self.assertRaises(FrameError) as raised:
            parse_status(reply)
        self.assertEqual(raised.exception.reason, "bad_platform_order")

    def test_general_then_platforms_in_ascending_order_is_accepted(self) -> None:
        status = parse_status(reply_at(0, 1, 2))
        self.assertEqual(status.length_class, "85x3")
        self.assertEqual([record.platform_address for record in status.records], [0, 1, 2])

    def test_general_then_one_platform_is_accepted(self) -> None:
        for platform in (1, 2):
            with self.subTest(platform=platform):
                status = parse_status(reply_at(0, platform))
                self.assertEqual(status.length_class, "85x2")
                self.assertEqual([record.platform_address for record in status.records], [0, platform])

    def test_one_general_record_is_accepted(self) -> None:
        status_85 = parse_status(record_85_at(0))
        self.assertEqual(status_85.length_class, "85")
        self.assertEqual(status_85.records[0].platform_address, 0)
        status_86 = parse_status(RECORD_86_GENERAL)
        self.assertEqual(status_86.length_class, "86")
        self.assertEqual(status_86.records[0].platform_address, 0)

    def test_one_platform_record_is_refused_in_either_length(self) -> None:
        for reply in (record_85_at(1), record_85_at(2), RECORD_86_PLATFORM_1, RECORD_86_PLATFORM_2):
            with self.subTest(length=len(reply), platform=reply[2]):
                self.assert_bad_platform_order(reply)

    def test_a_platform_record_still_decodes_on_its_own(self) -> None:
        self.assertEqual(decode_status_record(record_85_at(1)).platform_address, 1)
        self.assertEqual(decode_status_record(RECORD_86_PLATFORM_2).platform_address, 2)

    def test_the_same_order_rule_applies_to_86_byte_records(self) -> None:
        self.assertEqual(parse_status(REPLY_86X3).length_class, "86x3")
        self.assertEqual(parse_status(RECORD_86_GENERAL + RECORD_86_PLATFORM_2).length_class, "86x2")
        self.assert_bad_platform_order(RECORD_86_PLATFORM_1 + RECORD_86_GENERAL)
        self.assert_bad_platform_order(record_with_address(RECORD_86_GENERAL, 2) + RECORD_86_PLATFORM_1)

    def test_every_reply_must_start_with_the_general_record(self) -> None:
        for addresses in ((1, 0), (2, 0), (1, 2), (2, 1)):
            with self.subTest(addresses=addresses):
                self.assert_bad_platform_order(reply_at(*addresses))

    def test_platforms_must_be_in_strictly_increasing_order(self) -> None:
        for addresses in ((0, 2, 1), (0, 1, 1), (0, 0), (0, 0, 1)):
            with self.subTest(addresses=addresses):
                self.assert_bad_platform_order(reply_at(*addresses))

    def test_an_address_above_the_highest_platform_is_refused(self) -> None:
        for addresses in ((3,), (0, 3), (0, 1, 3)):
            with self.subTest(addresses=addresses):
                self.assert_bad_platform_order(reply_at(*addresses))


if __name__ == "__main__":
    unittest.main()
