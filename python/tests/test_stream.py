"""The 24-byte stream frame and the device-side demultiplexer that separates frames from replies."""

from __future__ import annotations

import random
import unittest

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
