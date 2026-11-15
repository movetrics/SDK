"""The 24-byte stream frame and the device-side demultiplexer that separates frames from replies."""

from __future__ import annotations

import random
import unittest

from movetrics_fdt.crc import crc16_ccitt_false
from movetrics_fdt.errors import FrameError
from movetrics_fdt.frames import AckReply, NackReply, build_device_frame
from movetrics_fdt.stream import (
    STREAM_LENGTH,
    StreamDecoder,
    StreamFrame,
    decode_stream_frame,
    encode_stream_frame,
)


def sample(stamp: int, force_x: int = 0, platform: int = 1) -> bytes:
    return encode_stream_frame(
        StreamFrame(
            platform_address=platform,
            commandCode=1,
            timeStamp=stamp,
            forceX=force_x,
            forceY=-2,
            forceZ=3,
            momentX=4,
            momentY=-5,
            momentZ=6,
        )
    )


class StreamFrameTests(unittest.TestCase):
    def test_frame_is_24_bytes_with_the_stream_envelope(self) -> None:
        frame = sample(7)
        self.assertEqual(len(frame), STREAM_LENGTH)
        self.assertEqual(frame[:2], b"\xbe\xef")
        self.assertEqual(frame[-2:], b"\x04\x04")

    def test_round_trip_over_random_field_values(self) -> None:
        rng = random.Random(7)
        for _ in range(100):
            original = StreamFrame(
                platform_address=rng.randrange(256),
                commandCode=1,
                timeStamp=rng.randrange(2**32),
                forceX=rng.randrange(-32768, 32768),
                forceY=rng.randrange(-32768, 32768),
                forceZ=rng.randrange(-32768, 32768),
                momentX=rng.randrange(-32768, 32768),
                momentY=rng.randrange(-32768, 32768),
                momentZ=rng.randrange(-32768, 32768),
            )
            with self.subTest(frame=original):
                self.assertEqual(decode_stream_frame(encode_stream_frame(original)), original)

    def test_field_outside_its_width_is_a_value_error(self) -> None:
        with self.assertRaises(ValueError):
            encode_stream_frame(
                StreamFrame(1, 1, 0, forceX=40000, forceY=0, forceZ=0, momentX=0, momentY=0, momentZ=0)
            )

    def test_wrong_length_is_bad_length(self) -> None:
        with self.assertRaises(FrameError) as raised:
            decode_stream_frame(sample(1)[:-1])
        self.assertEqual(raised.exception.reason, "bad_length")

    def test_command_other_than_one_is_bad_command(self) -> None:
        body = bytes((1, 2)) + bytes(16)  # pa, command 0x02, then 16 bytes of data: 24 bytes in all
        with self.assertRaises(FrameError) as raised:
            decode_stream_frame(build_device_frame(body))
        self.assertEqual(raised.exception.reason, "bad_command")

    def test_placeholder_is_a_zero_timestamp(self) -> None:
        self.assertTrue(decode_stream_frame(sample(0)).is_placeholder)
        self.assertFalse(decode_stream_frame(sample(1)).is_placeholder)


class StreamDecoderTests(unittest.TestCase):
    def test_back_to_back_frames(self) -> None:
        decoder = StreamDecoder()
        frames = decoder.push(sample(1) + sample(2) + sample(3))
        self.assertEqual([frame.timeStamp for frame in frames], [1, 2, 3])

    def test_every_split_point_gives_the_same_frames(self) -> None:
        stream = sample(10) + sample(11)
        for split in range(1, len(stream)):
            with self.subTest(split=split):
                decoder = StreamDecoder()
                frames = decoder.push(stream[:split]) + decoder.push(stream[split:])
                self.assertEqual([frame.timeStamp for frame in frames], [10, 11])

    def test_one_byte_at_a_time(self) -> None:
        stream = sample(20) + sample(21) + sample(0)
        decoder = StreamDecoder()
        frames: list[StreamFrame] = []
        for index in range(len(stream)):
            frames.extend(decoder.push(stream[index : index + 1]))
        self.assertEqual([frame.timeStamp for frame in frames], [20, 21, 0])
        self.assertEqual(decoder.discarded_bytes, 0)

    def test_frame_containing_04_04_is_not_cut(self) -> None:
        decoder = StreamDecoder()
        frames = decoder.push(sample(5, force_x=0x0404))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].forceX, 0x0404)

    def test_ack_goes_to_the_callback_and_frames_are_returned(self) -> None:
        replies: list[object] = []
        decoder = StreamDecoder(on_reply=replies.append)
        ack = build_device_frame(bytes((0xFF, 0x05, 0x06)))
        frames = decoder.push(sample(1) + ack + sample(2))
        self.assertEqual([frame.timeStamp for frame in frames], [1, 2])
        self.assertEqual(replies, [AckReply(platform_address=0xFF, command=0x05, raw=ack)])

    def test_nack_for_start_is_a_reply(self) -> None:
        replies: list[object] = []
        decoder = StreamDecoder(on_reply=replies.append)
        self.assertEqual(decoder.push(build_device_frame(bytes((0xFF, 0x01, 0x15, 0x03, 0x00)))), [])
        self.assertEqual(len(replies), 1)
        self.assertIsInstance(replies[0], NackReply)
        self.assertEqual(replies[0].error_name, "ERR_INVALID_PARAMETER")

    def test_garbage_before_a_frame_is_discarded_and_counted(self) -> None:
        decoder = StreamDecoder()
        frames = decoder.push(b"\x00\x11\x22" + sample(9))
        self.assertEqual([frame.timeStamp for frame in frames], [9])
        self.assertEqual(decoder.discarded_bytes, 3)

    def test_corrupt_frame_is_skipped_and_the_next_one_decodes(self) -> None:
        corrupt = bytearray(sample(1))
        corrupt[10] ^= 0x01
        decoder = StreamDecoder()
        frames = decoder.push(bytes(corrupt) + sample(2))
        self.assertEqual([frame.timeStamp for frame in frames], [2])
        self.assertGreater(decoder.discarded_bytes, 0)

    def test_partial_frame_is_held_until_the_rest_arrives(self) -> None:
        frame = sample(30)
        decoder = StreamDecoder()
        self.assertEqual(decoder.push(frame[:10]), [])
        self.assertEqual([item.timeStamp for item in decoder.push(frame[10:])], [30])

    def test_a_lone_header_byte_at_the_end_is_kept(self) -> None:
        frame = sample(40)
        decoder = StreamDecoder()
        self.assertEqual(decoder.push(b"\x00\xbe"), [])
        self.assertEqual([item.timeStamp for item in decoder.push(frame[1:])], [40])
        self.assertEqual(decoder.discarded_bytes, 1)


if __name__ == "__main__":
    unittest.main()


def button_burst(op: int, nonce: int) -> bytes:
    """What a Bluetooth host may see after a press of the FDT's reset button (FDT 1.2.8.32 with bridge 1.4.1.0):
    the break read as a NUL, then 'M' 'B' op nonce-lo nonce-hi and the CRC-16/CCITT-FALSE of those five bytes."""
    body = bytes((0x4D, 0x42, op, nonce & 0xFF, nonce >> 8))
    crc = crc16_ccitt_false(body)
    return b"\x00" + body + bytes((crc & 0xFF, crc >> 8))


class ButtonMessageTests(unittest.TestCase):
    """The reset button's 8-byte message between replies is skipped like any other bytes that are not a frame."""

    def test_three_bursts_between_replies_and_frames(self) -> None:
        replies: list[object] = []
        decoder = StreamDecoder(on_reply=replies.append)
        ack = build_device_frame(bytes((0x00, 0x1B, 0x06)))
        burst = button_burst(1, 0x1234)
        data = ack + burst * 3 + sample(7) + burst + sample(8)
        for size in (len(data), 20, 7, 1):  # whole, and split as BLE notifications may split it
            replies.clear()
            decoder = StreamDecoder(on_reply=replies.append)
            frames: list[StreamFrame] = []
            for offset in range(0, len(data), size):
                frames += decoder.push(data[offset : offset + size])
            self.assertEqual([frame.timeStamp for frame in frames], [7, 8], size)
            self.assertEqual(replies, [AckReply(platform_address=0x00, command=0x1B, raw=ack)], size)
            self.assertEqual(decoder.discarded_bytes, 4 * len(burst), size)

    def test_every_nonce_and_both_ops_leave_the_next_frame_intact(self) -> None:
        # Some nonces put BE EF, a frame header, inside the burst.
        frame = sample(42)
        for op in (1, 2):
            for nonce in range(0x10000):
                decoder = StreamDecoder()
                frames = decoder.push(button_burst(op, nonce) + frame)
                self.assertEqual(len(frames), 1, (op, nonce))
                self.assertEqual(frames[0].timeStamp, 42, (op, nonce))

    def test_a_break_read_as_three_nuls(self) -> None:
        decoder = StreamDecoder()
        frames = decoder.push(b"\x00\x00" + button_burst(2, 0xEFBE) + sample(3))
        self.assertEqual([frame.timeStamp for frame in frames], [3])
