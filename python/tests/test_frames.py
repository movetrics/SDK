"""Host request frames (encode, RX delimiter, parse) and device reply envelopes."""

from __future__ import annotations

import unittest

from movetrics_fdt.commands import IMPLEMENTED, IMPLEMENTED_CODES, NOT_IMPLEMENTED
from movetrics_fdt.crc import crc16_ccitt_false
from movetrics_fdt.errors import FrameError, UnsupportedCommandError
from movetrics_fdt.frames import (
    ACK_LENGTH,
    MAX_MESSAGE_LENGTH,
    HostFrameReader,
    HostRxSplitter,
    build_device_frame,
    check_envelope,
    decode_ack,
    decode_firmware_version,
    decode_nack,
    encode_host_frame,
    envelope_is_valid,
    parse_host_message,
)

FW_VERSION_REPLY = bytes.fromhex(
    "beef00233030312e3030322e303033000000003030322e3030352e30303100000000acc80404"
)


class EncodeTests(unittest.TestCase):
    def test_get_status_to_00_00(self) -> None:
        self.assertEqual(encode_host_frame(0x22, 0x00, 0x00).hex(), "feed000022bcc80404")

    def test_start_stream_to_ff_ff(self) -> None:
        self.assertEqual(encode_host_frame(0x01, 0xFF, 0xFF).hex(), "feedffff0121100404")

    def test_stop_stream_to_ff_00(self) -> None:
        self.assertEqual(encode_host_frame(0x05, 0xFF, 0x00).hex(), "feedff00055a530404")

    def test_keep_alive_with_600_seconds(self) -> None:
        self.assertEqual(encode_host_frame(0x26, 0x00, 0x00, b"\x58\x02").hex(), "feed00002658023e820404")

    def test_implemented_commands_are_the_five_in_the_brief_plus_set_filter_and_sync_mode(self) -> None:
        self.assertEqual(sorted(IMPLEMENTED_CODES), [0x01, 0x05, 0x1C, 0x22, 0x23, 0x26, 0x28, 0x29])
        self.assertEqual(len(IMPLEMENTED), 8)

    def test_set_filter_bytes_match_the_bench_tool(self) -> None:
        # tools/bench/fdtproto.cmd(0x1C, params=bytes([50, 0xF4, 1])) is the frame the bench sends to restore
        # 500 frames/s with the 50 Hz low-pass; 2,000 raw is the frame of stream_check.py rate 2000:0.
        self.assertEqual(encode_host_frame(0x1C, 0x00, 0x00, bytes([50, 0xF4, 0x01])),
                         _bench_cmd(0x1C, bytes([50, 0xF4, 0x01])))
        self.assertEqual(encode_host_frame(0x1C, 0x00, 0x00, bytes([0, 0xD0, 0x07])),
                         _bench_cmd(0x1C, bytes([0, 0xD0, 0x07])))

    def test_get_fw_version_to_00_00_is_the_probe_frame(self) -> None:
        self.assertEqual(encode_host_frame(0x23, 0x00, 0x00).hex(), "feed0000239dd80404")

    def test_every_not_implemented_command_is_refused_with_its_reason(self) -> None:
        for entry in NOT_IMPLEMENTED:
            with self.subTest(command=f"{entry.code:02X} {entry.name}"):
                with self.assertRaises(UnsupportedCommandError) as raised:
                    encode_host_frame(entry.code, 0x00, 0x00)
                self.assertEqual(raised.exception.reason, entry.reason)

    def test_unknown_command_code_is_refused(self) -> None:
        with self.assertRaises(UnsupportedCommandError) as raised:
            encode_host_frame(0x99, 0x00, 0x00)
        self.assertEqual(raised.exception.reason, "not a known command code")

    def test_frame_where_04_04_ends_early_is_refused_with_the_would_be_frame(self) -> None:
        with self.assertRaises(FrameError) as raised:
            encode_host_frame(0x22, 0xFF, 0xFF)
        self.assertEqual(raised.exception.reason, "early_04_04_delimiter")
        self.assertEqual(raised.exception.would_be, bytes.fromhex("feedffff2220040404"))

    def test_payload_that_contains_04_04_is_refused(self) -> None:
        with self.assertRaises(FrameError) as raised:
            encode_host_frame(0x26, 0x00, 0x00, b"\x04\x04")
        self.assertEqual(raised.exception.reason, "early_04_04_delimiter")

    def test_frame_longer_than_the_controller_buffer_is_refused(self) -> None:
        with self.assertRaises(FrameError) as raised:
            encode_host_frame(0x26, 0x00, 0x00, bytes(MAX_MESSAGE_LENGTH))
        self.assertEqual(raised.exception.reason, "too_long")

    def test_out_of_range_bytes_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            encode_host_frame(0x22, 256, 0)
        with self.assertRaises(ValueError):
            encode_host_frame(0x22, 0, -1)


class ParseHostMessageTests(unittest.TestCase):
    def test_valid_frame_fields(self) -> None:
        frame = parse_host_message(bytes.fromhex("feed000022bcc80404"))
        self.assertEqual((frame.address, frame.destination, frame.command), (0x00, 0x00, 0x22))
        self.assertEqual(frame.payload, b"")

    def test_payload_is_the_bytes_between_command_and_crc(self) -> None:
        frame = parse_host_message(bytes.fromhex("feed00002658023e820404"))
        self.assertEqual(frame.payload, b"\x58\x02")

    def test_resynchronises_at_the_first_header(self) -> None:
        frame = parse_host_message(bytes.fromhex("aa55feed0000239dd80404"))
        self.assertEqual(frame.command, 0x23)

    def test_fewer_than_nine_bytes_is_shorter_than_9_bytes(self) -> None:
        with self.assertRaises(FrameError) as raised:
            parse_host_message(bytes.fromhex("feed0000230404"))
        self.assertEqual(raised.exception.reason, "shorter_than_9_bytes")

    def test_wrong_header_is_bad_header(self) -> None:
        with self.assertRaises(FrameError) as raised:
            parse_host_message(bytes.fromhex("edfe0000239dd80404"))
        self.assertEqual(raised.exception.reason, "bad_header")

    def test_crc_mismatch(self) -> None:
        with self.assertRaises(FrameError) as raised:
            parse_host_message(bytes.fromhex("feed0000239dd90404"))
        self.assertEqual(raised.exception.reason, "crc_mismatch")

    def test_bad_end_marker_with_a_correct_crc(self) -> None:
        body = bytes((0x00, 0x00, 0x23))
        crc = crc16_ccitt_false(body)
        message = b"\xfe\xed" + body + bytes((crc & 0xFF, crc >> 8)) + b"\x04\x05"
        with self.assertRaises(FrameError) as raised:
            parse_host_message(message)
        self.assertEqual(raised.exception.reason, "bad_end_marker")


class RxSplitterTests(unittest.TestCase):
    def test_splits_at_the_first_pair_of_04_bytes(self) -> None:
        stream = bytes.fromhex("feed000022bcc80404") + bytes.fromhex("feed0000239dd80404")
        messages = HostRxSplitter().feed(stream)
        self.assertEqual([m.hex() for m in messages], ["feed000022bcc80404", "feed0000239dd80404"])

    def test_keeps_a_trailing_partial_message(self) -> None:
        splitter = HostRxSplitter()
        self.assertEqual(splitter.feed(b"\xfe\xed\x00\x00\x22\xbc\xc8\x04\x04\xfe\xed"),
                         [b"\xfe\xed\x00\x00\x22\xbc\xc8\x04\x04"])
        self.assertEqual(splitter.feed(b"\x00\x00\x23\x9d\xd8\x04\x04"), [b"\xfe\xed\x00\x00\x23\x9d\xd8\x04\x04"])

    def test_byte_by_byte_gives_the_same_messages(self) -> None:
        stream = bytes.fromhex("feedffff0121100404") + bytes.fromhex("feedff00055a530404")
        whole = HostRxSplitter().feed(stream)
        piecewise: list[bytes] = []
        splitter = HostRxSplitter()
        for index in range(len(stream)):
            piecewise.extend(splitter.feed(stream[index : index + 1]))
        self.assertEqual(piecewise, whole)

    def test_a_message_longer_than_the_buffer_is_dropped(self) -> None:
        splitter = HostRxSplitter()
        self.assertEqual(splitter.feed(b"\x11" * (MAX_MESSAGE_LENGTH + 10) + b"\x04\x04"), [])
        self.assertEqual(splitter.feed(bytes.fromhex("feed0000239dd80404")), [bytes.fromhex("feed0000239dd80404")])

    def test_reader_keeps_rejected_messages_with_their_reason(self) -> None:
        reader = HostFrameReader()
        self.assertEqual(reader.feed(bytes.fromhex("feed0000230404")), [])
        self.assertEqual(reader.rejected, [(bytes.fromhex("feed0000230404"), "shorter_than_9_bytes")])


class DeviceEnvelopeTests(unittest.TestCase):
    def test_build_then_check_round_trip(self) -> None:
        frame = build_device_frame(bytes((0x00, 0x05, 0x06)))
        self.assertTrue(envelope_is_valid(frame))
        check_envelope(frame, ACK_LENGTH)

    def test_envelope_rejects_bad_header_end_and_crc(self) -> None:
        frame = build_device_frame(bytes((0x00, 0x05, 0x06)))
        self.assertFalse(envelope_is_valid(b"\xef\xbe" + frame[2:]))
        self.assertFalse(envelope_is_valid(frame[:-1] + b"\x05"))
        self.assertFalse(envelope_is_valid(frame[:4] + bytes((frame[4] ^ 1,)) + frame[5:]))

    def test_check_envelope_rejects_the_wrong_length(self) -> None:
        frame = build_device_frame(bytes((0x00, 0x05, 0x06)))
        with self.assertRaises(FrameError) as raised:
            check_envelope(frame, 11)
        self.assertEqual(raised.exception.reason, "bad_length")

    def test_ack_decodes(self) -> None:
        ack = decode_ack(build_device_frame(bytes((0x00, 0x05, 0x06))))
        self.assertEqual((ack.platform_address, ack.command), (0x00, 0x05))

    def test_nack_decodes_its_error_name(self) -> None:
        nack = decode_nack(build_device_frame(bytes((0x00, 0x22, 0x15, 0x07, 0x00))))
        self.assertEqual((nack.command, nack.error_code, nack.error_name), (0x22, 7, "ERR_UNKNOWN_COMMAND"))

    def test_nack_with_an_unlisted_error_code_is_unknown(self) -> None:
        nack = decode_nack(build_device_frame(bytes((0x00, 0x22, 0x15, 0x63, 0x00))))
        self.assertEqual(nack.error_name, "UNKNOWN")

    def test_firmware_version_reply_from_the_identification_capture(self) -> None:
        reply = decode_firmware_version(FW_VERSION_REPLY)
        self.assertEqual((reply.platform_address, reply.command), (0x00, 0x23))
        self.assertEqual((reply.stm32FW, reply.esp32FW), ("001.002.003", "002.005.001"))

    def test_firmware_version_decoder_rejects_another_command(self) -> None:
        frame = build_device_frame(bytes((0x00, 0x22)) + bytes(30))  # 38 bytes in all, as the envelope needs
        with self.assertRaises(FrameError) as raised:
            decode_firmware_version(frame)
        self.assertEqual(raised.exception.reason, "bad_command")


if __name__ == "__main__":
    unittest.main()


def _bench_cmd(code: int, params: bytes) -> bytes:
    """tools/bench/fdtproto.cmd, copied: FE ED 00 00 code params CRC(LE) 04 04."""
    from movetrics_fdt.crc import crc16_ccitt_false
    inner = bytes([0, 0, code]) + params
    crc = crc16_ccitt_false(inner)
    return b"\xfe\xed" + inner + bytes([crc & 0xFF, crc >> 8, 4, 4])
