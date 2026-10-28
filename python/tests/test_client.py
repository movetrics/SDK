"""FdtClient against the fake controller: the five implemented commands, failures, and the stream lifecycle."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import AsyncIterator
from typing import Any

from movetrics_fdt.client import FdtClient
from movetrics_fdt.commands import IMPLEMENTED_CODES
from movetrics_fdt.errors import FdtError, FrameError, NackError, ReplyTimeoutError, TransportError
from movetrics_fdt.frames import build_device_frame
from movetrics_fdt.stream import StreamFrame, encode_stream_frame

from .support import FakeController, FakeTransport, find_case

STATUS_86X3 = bytes.fromhex(find_case("status.json", "status-derived-86x3-reply")["frame_hex"])
STATUS_85 = bytes.fromhex(find_case("status.json", "status-anchor-identification-85")["frame_hex"])
RECORD_86_GENERAL = bytes.fromhex(find_case("status.json", "status-derived-86-general-record")["frame_hex"])
FW_VERSION_REPLY = bytes.fromhex(
    "beef00233030312e3030322e303033000000003030322e3030352e30303100000000acc80404"
)
GET_STATUS_FRAME = bytes.fromhex("feed000022bcc80404")
GET_FW_VERSION_FRAME = bytes.fromhex("feed0000239dd80404")
START_FRAME = bytes.fromhex("feedffff0121100404")
STOP_FRAME = bytes.fromhex("feedff00055a530404")
KEEP_ALIVE_600_FRAME = bytes.fromhex("feed00002658023e820404")

FAST: dict[str, Any] = {"timeout": 0.5, "record_gap": 0.02, "start_check": 0.02}


def stream_sample(stamp: int, force_x: int = 0) -> bytes:
    return encode_stream_frame(
        StreamFrame(
            platform_address=1,
            commandCode=1,
            timeStamp=stamp,
            forceX=force_x,
            forceY=0,
            forceZ=0,
            momentX=0,
            momentY=0,
            momentZ=0,
        )
    )


async def _take(frames: AsyncIterator[StreamFrame], count: int) -> list[StreamFrame]:
    taken: list[StreamFrame] = []
    async for frame in frames:
        taken.append(frame)
        if len(taken) == count:
            break
    return taken


async def _take_all(frames: AsyncIterator[StreamFrame]) -> list[StreamFrame]:
    return [frame async for frame in frames]


class GetStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_one_record_per_platform(self) -> None:
        transport = FakeTransport(FakeController(status_reply=STATUS_86X3))
        async with FdtClient(transport, **FAST) as fdt:
            status = await fdt.get_status()
        self.assertEqual(status.length_class, "86x3")
        self.assertIsNotNone(status.general)
        self.assertEqual(status.general.batterySOC, 87)
        self.assertEqual([record.platform_address for record in status.platforms], [1, 2])
        self.assertEqual(transport.written, [GET_STATUS_FRAME])

    async def test_85_byte_reply_has_no_battery_value(self) -> None:
        transport = FakeTransport(FakeController(status_reply=STATUS_85))
        async with FdtClient(transport, **FAST) as fdt:
            status = await fdt.get_status()
        self.assertEqual(status.length_class, "85")
        self.assertIsNone(status.records[0].batterySOC)

    async def test_one_byte_chunks_give_the_same_status(self) -> None:
        transport = FakeTransport(FakeController(status_reply=STATUS_86X3), chunk_size=1)
        async with FdtClient(transport, **FAST) as fdt:
            status = await fdt.get_status()
        self.assertEqual(status.length_class, "86x3")
        self.assertEqual(len(status.records), 3)

    async def test_silent_controller_times_out(self) -> None:
        transport = FakeTransport(FakeController(silent=True))
        async with FdtClient(transport, timeout=0.05, record_gap=0.02, start_check=0.02) as fdt:
            with self.assertRaises(ReplyTimeoutError):
                await fdt.get_status()

    async def test_link_failure_while_waiting_is_a_transport_error(self) -> None:
        transport = FakeTransport(FakeController(silent=True))
        async with FdtClient(transport, timeout=2.0, record_gap=0.02, start_check=0.02) as fdt:
            waiting = asyncio.create_task(fdt.get_status())
            await asyncio.sleep(0.01)
            transport.fail(OSError("unplugged"))
            with self.assertRaises(TransportError) as raised:
                await waiting
        self.assertIn("unplugged", str(raised.exception))

    async def test_a_damaged_record_is_not_taken_as_a_reply(self) -> None:
        damaged = bytearray(STATUS_85)
        damaged[20] ^= 0x01
        transport = FakeTransport(FakeController(status_reply=bytes(damaged)))
        async with FdtClient(transport, timeout=0.05, record_gap=0.02, start_check=0.02) as fdt:
            with self.assertRaises(ReplyTimeoutError):
                await fdt.get_status()

    async def test_a_reply_of_four_records_is_refused(self) -> None:
        transport = FakeTransport(FakeController(status_reply=STATUS_86X3 + RECORD_86_GENERAL))
        async with FdtClient(transport, **FAST) as fdt:
            with self.assertRaises(FrameError) as raised:
                await fdt.get_status()
        self.assertEqual(raised.exception.reason, "unsupported_length")

    async def test_a_reply_that_mixes_85_and_86_byte_records_is_refused(self) -> None:
        transport = FakeTransport(FakeController(status_reply=STATUS_85 + RECORD_86_GENERAL))
        async with FdtClient(transport, **FAST) as fdt:
            with self.assertRaises(FrameError) as raised:
                await fdt.get_status()
        self.assertEqual(raised.exception.reason, "mixed_record_lengths")


class GetFirmwareVersionTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_0x23_to_00_00_and_returns_the_versions(self) -> None:
        transport = FakeTransport(FakeController(fw_version_reply=FW_VERSION_REPLY))
        async with FdtClient(transport, **FAST) as fdt:
            reply = await fdt.get_firmware_version()
        self.assertEqual(transport.written, [GET_FW_VERSION_FRAME])
        self.assertEqual((reply.platform_address, reply.command), (0x00, 0x23))
        self.assertEqual((reply.stm32FW, reply.esp32FW), ("001.002.003", "002.005.001"))

    async def test_a_nack_is_raised_as_nack_error(self) -> None:
        nack = build_device_frame(bytes((0x00, 0x23, 0x15, 0x07, 0x00)))
        transport = FakeTransport(lambda frame: [nack])
        async with FdtClient(transport, **FAST) as fdt:
            with self.assertRaises(NackError) as raised:
                await fdt.get_firmware_version()
        self.assertEqual((raised.exception.command, raised.exception.error_name), (0x23, "ERR_UNKNOWN_COMMAND"))

    async def test_silent_controller_times_out(self) -> None:
        transport = FakeTransport(FakeController())
        async with FdtClient(transport, timeout=0.05, record_gap=0.02, start_check=0.02) as fdt:
            with self.assertRaises(ReplyTimeoutError):
                await fdt.get_firmware_version()

    async def test_a_damaged_reply_is_not_taken_as_a_reply(self) -> None:
        damaged = bytearray(FW_VERSION_REPLY)
        damaged[10] ^= 0x01
        transport = FakeTransport(FakeController(fw_version_reply=bytes(damaged)))
        async with FdtClient(transport, timeout=0.05, record_gap=0.02, start_check=0.02) as fdt:
            with self.assertRaises(ReplyTimeoutError):
                await fdt.get_firmware_version()


class StreamLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_frames_and_stop(self) -> None:
        stream = [stream_sample(0), stream_sample(0), stream_sample(1000, force_x=-5)]
        transport = FakeTransport(FakeController(stream=stream))
        async with FdtClient(transport, **FAST) as fdt:
            await fdt.start_stream()
            self.assertTrue(fdt.streaming)
            received = await asyncio.wait_for(_take(fdt.frames(), 3), 1.0)
            await fdt.stop_stream()
            self.assertFalse(fdt.streaming)
        self.assertEqual([frame.timeStamp for frame in received], [0, 0, 1000])
        self.assertTrue(received[0].is_placeholder)
        self.assertFalse(received[2].is_placeholder)
        self.assertEqual(received[2].forceX, -5)
        self.assertEqual(transport.written, [START_FRAME, STOP_FRAME])
        self.assertTrue(transport.closed)

    async def test_refused_start_raises_nack_and_leaves_no_stream(self) -> None:
        transport = FakeTransport(FakeController(refuse_start=True))
        async with FdtClient(transport, **FAST) as fdt:
            with self.assertRaises(NackError) as raised:
                await fdt.start_stream()
            self.assertEqual(raised.exception.error_name, "ERR_INVALID_PARAMETER")
            self.assertFalse(fdt.streaming)

    async def test_starting_twice_is_refused(self) -> None:
        async with FdtClient(FakeTransport(FakeController()), **FAST) as fdt:
            await fdt.start_stream()
            with self.assertRaises(FdtError):
                await fdt.start_stream()
            await fdt.stop_stream()

    async def test_leaving_the_block_stops_a_stream_this_client_started(self) -> None:
        transport = FakeTransport(FakeController())
        async with FdtClient(transport, **FAST) as fdt:
            await fdt.start_stream()
        self.assertEqual(transport.written, [START_FRAME, STOP_FRAME])

    async def test_stop_without_an_ack_times_out_and_the_stream_still_counts_as_running(self) -> None:
        transport = FakeTransport(FakeController(silent_stop=True))
        client = FdtClient(transport, timeout=0.05, record_gap=0.02, start_check=0.02)
        with self.assertRaises(ReplyTimeoutError):
            async with client as fdt:
                await fdt.start_stream()
                await fdt.stop_stream()
        self.assertTrue(client.streaming)

    async def test_frames_end_after_the_link_closes_and_queued_frames_are_delivered(self) -> None:
        transport = FakeTransport(FakeController(stream=[stream_sample(5)]))
        async with FdtClient(transport, **FAST) as fdt:
            await fdt.start_stream()
            transport.end()
            received = await asyncio.wait_for(_take_all(fdt.frames()), 1.0)
        self.assertEqual([frame.timeStamp for frame in received], [5])

    async def test_a_full_frame_queue_drops_the_oldest_frames_and_counts_them(self) -> None:
        stream = [stream_sample(stamp) for stamp in range(1, 6)]
        transport = FakeTransport(FakeController(stream=stream))
        async with FdtClient(transport, frame_queue_size=2, **FAST) as fdt:
            await fdt.start_stream()
            await asyncio.sleep(0.02)
            self.assertEqual(fdt.dropped_frames, 3)
            received = await asyncio.wait_for(_take(fdt.frames(), 2), 1.0)
            await fdt.stop_stream()
        self.assertEqual([frame.timeStamp for frame in received], [4, 5])


class KeepAliveTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_interval_is_600_seconds(self) -> None:
        transport = FakeTransport()
        async with FdtClient(transport, **FAST) as fdt:
            await fdt.keep_alive()
        self.assertEqual(transport.written, [KEEP_ALIVE_600_FRAME])

    async def test_zero_is_refused_and_nothing_is_sent(self) -> None:
        # 0 would turn the FDT's sleep off and drain its battery; the TypeScript client refuses it too.
        transport = FakeTransport()
        async with FdtClient(transport, **FAST) as fdt:
            with self.assertRaises(ValueError):
                await fdt.keep_alive(0)
        self.assertEqual(transport.written, [])

    async def test_interval_outside_uint16_is_a_value_error(self) -> None:
        async with FdtClient(FakeTransport(), **FAST) as fdt:
            for value in (-1, 0x10000):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        await fdt.keep_alive(value)

    async def test_interval_whose_bytes_form_04_04_is_refused_and_nothing_is_sent(self) -> None:
        transport = FakeTransport()
        async with FdtClient(transport, **FAST) as fdt:
            with self.assertRaises(FrameError) as raised:
                await fdt.keep_alive(1028)  # 0x0404 in little-endian
        self.assertEqual(raised.exception.reason, "early_04_04_delimiter")
        self.assertEqual(transport.written, [])


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_commands_before_open_are_refused(self) -> None:
        client = FdtClient(FakeTransport(), **FAST)
        with self.assertRaises(FdtError):
            await client.get_status()

    async def test_frames_before_open_are_refused(self) -> None:
        client = FdtClient(FakeTransport(), **FAST)
        with self.assertRaises(FdtError):
            await _take_all(client.frames())

    async def test_a_client_opens_once(self) -> None:
        client = FdtClient(FakeTransport(), **FAST)
        async with client:
            pass
        with self.assertRaises(FdtError):
            async with client:
                pass

    async def test_only_the_five_implemented_commands_are_sent(self) -> None:
        transport = FakeTransport(
            FakeController(status_reply=STATUS_85, stream=[stream_sample(1)], fw_version_reply=FW_VERSION_REPLY)
        )
        async with FdtClient(transport, **FAST) as fdt:
            await fdt.get_status()
            await fdt.get_firmware_version()
            await fdt.start_stream()
            await fdt.keep_alive(10)
            await fdt.stop_stream()
        sent = {frame[4] for frame in transport.written}
        self.assertEqual(sent, {0x22, 0x23, 0x01, 0x26, 0x05})
        self.assertTrue(sent <= IMPLEMENTED_CODES)

    async def test_timeout_arguments_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            FdtClient(FakeTransport(), timeout=0)
        with self.assertRaises(ValueError):
            FdtClient(FakeTransport(), record_gap=0)
        with self.assertRaises(ValueError):
            FdtClient(FakeTransport(), start_check=-1)
        with self.assertRaises(ValueError):
            FdtClient(FakeTransport(), frame_queue_size=0)


if __name__ == "__main__":
    unittest.main()


MOVETRICS_FW_REPLY = build_device_frame(bytes((0x00, 0x23)) + b"1.2.8.2".ljust(15, b"\0") + b"000.000.000".ljust(15, b"\0"))


class SetRateTests(unittest.IsolatedAsyncioTestCase):
    async def test_2000_hz_raw_sends_the_bench_frame_after_the_version_check(self) -> None:
        transport = FakeTransport(FakeController(fw_version_reply=MOVETRICS_FW_REPLY))
        async with FdtClient(transport, **FAST) as fdt:
            await fdt.set_rate(2000, cutoff_hz=0)
        self.assertEqual(transport.written[0], GET_FW_VERSION_FRAME)
        self.assertEqual(transport.written[1][:8], bytes.fromhex("feed00001c00d007"))

    async def test_set_rate_then_start_streams(self) -> None:
        transport = FakeTransport(FakeController(fw_version_reply=MOVETRICS_FW_REPLY, stream=[stream_sample(5)]))
        async with FdtClient(transport, **FAST) as fdt:
            await fdt.set_rate(1000, cutoff_hz=100)
            await fdt.start_stream()
            frames = await _take(fdt.frames(), 1)
        self.assertEqual(frames[0].timeStamp, 5)
        self.assertEqual([frame[4] for frame in transport.written], [0x23, 0x1C, 0x01, 0x05])

    async def test_vendor_firmware_is_refused_and_no_set_filter_is_sent(self) -> None:
        transport = FakeTransport(FakeController(fw_version_reply=FW_VERSION_REPLY))
        async with FdtClient(transport, **FAST) as fdt:
            with self.assertRaises(FdtError):
                await fdt.set_rate(2000)
        self.assertEqual([frame[4] for frame in transport.written], [0x23])

    async def test_values_outside_the_firmware_limits_are_refused_before_sending(self) -> None:
        transport = FakeTransport(FakeController(fw_version_reply=MOVETRICS_FW_REPLY))
        async with FdtClient(transport, **FAST) as fdt:
            for rate, cutoff in ((49, 0), (2001, 0), (500, 250), (500, 256), (500, -1)):
                with self.subTest(rate=rate, cutoff=cutoff), self.assertRaises(ValueError):
                    await fdt.set_rate(rate, cutoff_hz=cutoff)
        self.assertEqual(transport.written, [])

    async def test_refused_while_streaming(self) -> None:
        transport = FakeTransport(FakeController(fw_version_reply=MOVETRICS_FW_REPLY, stream=[stream_sample(1)]))
        async with FdtClient(transport, **FAST) as fdt:
            await fdt.start_stream()
            with self.assertRaises(FdtError):
                await fdt.set_rate(2000)

    async def test_rate_1028_would_be_split_by_04_04_and_is_a_frame_error(self) -> None:
        transport = FakeTransport(FakeController(fw_version_reply=MOVETRICS_FW_REPLY))
        async with FdtClient(transport, **FAST) as fdt:
            with self.assertRaises(FrameError):
                await fdt.set_rate(1028, cutoff_hz=0)
        self.assertEqual(transport.written, [])
