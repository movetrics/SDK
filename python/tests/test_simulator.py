"""The virtual FDT: protocol replies, pacing, sleep and wake, faults, sync events; and FdtClient over TCP to it."""

import asyncio
import math
import pathlib
import struct
import unittest

from movetrics_fdt import FdtClient, FdtError, SyncMode, TcpTransport
from movetrics_fdt.frames import encode_host_frame
from movetrics_fdt.simulator import Faults, StudioReplay, Synthetic, VirtualFdt
from movetrics_fdt.simulator_io import serve_tcp
from movetrics_fdt.stream import EventFrame, StreamDecoder, StreamFrame
from movetrics_fdt.vocabulary import Event, Gap, Sample, SampleConverter

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def run(fdt, until, step=0.001, start=0.0):
    """Advance the controller from start to until and decode everything it sent."""
    replies, frames = [], []
    decoder = StreamDecoder(on_reply=replies.append)
    now = start
    while now <= until + 1e-9:
        frames += decoder.push(fdt.advance(now))
        now += step
    return frames, replies


def host(code, address=0, destination=0, payload=b""):
    return encode_host_frame(code, address, destination, payload)


class ProtocolTests(unittest.TestCase):
    def test_version_and_default_rate_follow_the_profile(self):
        for profile, rate in (("1.2.8.2", 500), ("1.2.8.20", 1000)):
            fdt = VirtualFdt(profile)
            fdt.feed(host(0x23), 0.0)
            _, replies = run(fdt, 0.0)
            self.assertEqual(replies[0].stm32FW, profile)
            fdt.feed(host(0x01, 0xFF, 0xFF), 0.0)
            frames, _ = run(fdt, 1.0)
            stamped = [f for f in frames if f.platform_address == 1 and f.timeStamp]
            self.assertEqual(len(stamped), rate)
            self.assertEqual(stamped[1].timeStamp - stamped[0].timeStamp, 10_000 // rate)

    def test_start_sends_one_placeholder_per_plate_then_the_grid(self):
        fdt = VirtualFdt("1.2.8.20")
        fdt.feed(host(0x01, 0xFF, 0xFF), 0.0)
        frames, _ = run(fdt, 0.01)
        self.assertEqual([(f.platform_address, f.timeStamp) for f in frames[:4]], [(1, 0), (2, 0), (1, 10), (2, 10)])

    def test_set_filter_ack_and_nack(self):
        fdt = VirtualFdt("1.2.8.20")
        fdt.feed(host(0x1C, payload=bytes((50,)) + struct.pack("<H", 2000)), 0.0)
        fdt.feed(host(0x1C, payload=bytes((200,)) + struct.pack("<H", 300)), 0.0)
        _, replies = run(fdt, 0.0)
        self.assertEqual(type(replies[0]).__name__, "AckReply")
        self.assertEqual((type(replies[1]).__name__, replies[1].error_code), ("NackReply", 3))
        self.assertEqual(fdt.rate_hz, 2000)

    def test_unknown_and_calibration_codes_get_nack_7(self):
        fdt = VirtualFdt("1.2.8.20")
        # Built by hand: the SDK refuses to encode these codes.
        from movetrics_fdt.frames import build_device_frame  # noqa: F401
        from movetrics_fdt.crc import crc16_ccitt_false
        for code in (0x19, 0x53, 0x28):
            body = bytes((0, 0, code))
            crc = crc16_ccitt_false(body)
            fdt.feed(b"\xfe\xed" + body + bytes((crc & 0xFF, crc >> 8)) + b"\x04\x04", 0.0)
        _, replies = run(fdt, 0.0)
        self.assertEqual([(r.command, r.error_code) for r in replies], [(0x19, 7), (0x53, 7), (0x28, 7)])

    def test_status_parses(self):
        from movetrics_fdt.status import parse_status
        fdt = VirtualFdt("1.2.8.20")
        fdt.feed(host(0x22), 0.0)
        status = parse_status(fdt.advance(0.0))
        self.assertEqual([r.platform_address for r in status.records], [0, 1, 2])


class SleepTests(unittest.TestCase):
    def test_sleeps_after_five_minutes_and_start_waits_for_the_pads(self):
        fdt = VirtualFdt("1.2.8.20")
        fdt.advance(301.0)
        self.assertTrue(fdt.asleep)
        fdt.feed(host(0x01, 0xFF, 0xFF), 301.0)
        frames, _ = run(fdt, 305.5, step=0.01, start=301.0)
        self.assertEqual(frames, [])  # pads still powering up (4.6 s, measured on a bench FDT)
        frames, _ = run(fdt, 306.0, step=0.01, start=305.6)
        self.assertTrue(frames)

    def test_old_line_streams_at_once_and_keep_alive_delays_sleep(self):
        fdt = VirtualFdt("1.2.8.2")
        fdt.feed(host(0x26, payload=struct.pack("<H", 0)), 0.0)  # 0 = never sleep
        fdt.advance(10_000.0)
        self.assertFalse(fdt.asleep)


class FaultTests(unittest.TestCase):
    def test_hold_creates_one_gap_per_plate_with_the_right_length(self):
        fdt = VirtualFdt("1.2.8.20", faults=Faults(hold_at_s=0.5, hold_s=0.041))
        fdt.feed(host(0x01, 0xFF, 0xFF), 0.0)
        frames, _ = run(fdt, 1.0)
        converter = SampleConverter(1000)
        out = list(converter.convert(frames))
        gaps = [o for o in out if isinstance(o, Gap)]
        self.assertEqual(len(gaps), 2)
        self.assertEqual(gaps[0].missing, 41)
        self.assertEqual(converter.placeholders, 2)

    def test_scale_wraps_and_reports_saturation_when_asked(self):
        fdt = VirtualFdt("sync", Synthetic("stand", 750.0), Faults(scale=100))
        fdt.feed(host(0x28, payload=bytes((int(SyncMode.SATURATION_EVENTS),)) + struct.pack("<H", 1000)), 0.0)
        fdt.feed(host(0x01, 0xFF, 0xFF), 0.0)
        frames, replies = run(fdt, 0.1)
        events = [r for r in replies if isinstance(r, EventFrame)]
        self.assertEqual({(e.name, e.source) for e in events}, {("saturation", 1), ("saturation", 2)})
        self.assertTrue(all(e.detail & 0x04 for e in events))  # fz wrapped
        self.assertTrue(any(f.forceZ < 0 for f in frames if f.timeStamp))  # 37,500 N wrapped below zero

    def test_clock_drift_is_visible_against_the_host(self):
        fdt = VirtualFdt("1.2.8.20", faults=Faults(clock_ppm=1000))
        fdt.feed(host(0x01, 0xFF, 0xFF), 0.0)
        frames, _ = run(fdt, 2.0, step=0.01)
        last = max(f.timeStamp for f in frames)
        self.assertAlmostEqual(last / 10_000, 2.002, delta=0.002)


class SyncTests(unittest.TestCase):
    def test_armed_start_waits_for_the_edge_and_reports_it(self):
        fdt = VirtualFdt("sync")
        mode = SyncMode.START_ON_RISE | SyncMode.EVENT_FRAMES | SyncMode.STOP_ON_FALL
        fdt.feed(host(0x28, payload=bytes((int(mode),)) + struct.pack("<H", 1000)), 0.0)
        fdt.feed(host(0x01, 0xFF, 0xFF), 0.0)
        frames, replies = run(fdt, 1.0)
        self.assertEqual([f.timeStamp for f in frames], [0, 0])  # START sends its placeholders, then arms
        self.assertEqual([(r.name, r.detail) for r in replies if isinstance(r, EventFrame)], [("stream_armed", 30)])
        fdt.sync_in(1, 1.0)
        frames, replies = run(fdt, 2.0, start=1.0)
        self.assertEqual([r.name for r in replies if isinstance(r, EventFrame)], ["sync_in_rise", "stream_started_by_trigger"])
        self.assertGreater(len(frames), 1900)
        fdt.sync_in(0, 2.0)
        self.assertFalse(fdt.streaming)
        frames, replies = run(fdt, 2.0, start=2.0)
        self.assertEqual([r.name for r in replies if isinstance(r, EventFrame)], ["sync_in_fall"])

    def test_pulse_train_every_second(self):
        fdt = VirtualFdt("sync")
        mode = SyncMode.PULSE_TRAIN | SyncMode.EVENT_FRAMES
        fdt.feed(host(0x28, payload=bytes((int(mode),)) + struct.pack("<H", 1000)), 0.0)
        fdt.feed(host(0x01, 0xFF, 0xFF), 0.0)
        _, replies = run(fdt, 3.05, step=0.01)
        rises = [r.timeStamp for r in replies if isinstance(r, EventFrame) and r.name == "sync_out_rise"]
        self.assertEqual(rises, [1, 10_001, 20_001, 30_001])  # ticks 1, 1 + P, ... (docs/04 section 3.9)

    def test_set_sync_mode_on_old_firmware_says_so(self):
        async def scenario():
            port = await start_server("1.2.8.20")
            async with FdtClient(TcpTransport("127.0.0.1", port)) as fdt:
                self.assertIsNone(await fdt.get_sync_mode())
                with self.assertRaisesRegex(FdtError, "no sync modes"):
                    await fdt.set_sync_mode(SyncMode.EVENT_FRAMES)
        asyncio.run(scenario())

    def test_get_sync_mode_and_refusals(self):
        async def scenario():
            port = await start_server("sync")
            async with FdtClient(TcpTransport("127.0.0.1", port)) as fdt:
                await fdt.set_sync_mode(SyncMode.START_ON_RISE | SyncMode.EVENT_FRAMES, pulse_period_ms=500)
                reply = await fdt.get_sync_mode()
                await fdt.start_stream()
                with self.assertRaisesRegex(FdtError, "waits for its trigger"):
                    fdt._streaming = False  # armed, not streaming: the FDT itself must refuse
                    await fdt.set_sync_mode(SyncMode.EVENT_FRAMES)
                armed = await fdt.get_sync_mode()
                return reply, armed
        reply, armed = asyncio.run(scenario())
        self.assertEqual((reply.mode, reply.pulse_period_ms, reply.pulse_width_ms, reply.arm_timeout_min), (9, 500, 5, 30))
        self.assertTrue(armed.state & 0x01)
        with self.assertRaises(ValueError):
            asyncio.run(FdtClient(TcpTransport()).set_sync_mode(SyncMode.MASTER_OUT | SyncMode.PULSE_TRAIN))


class ReplayTests(unittest.TestCase):
    def test_studio_replay_gives_back_the_file_values_in_si(self):
        path = FIXTURES / "studio-2026-10-14-excerpt-channels.csv"
        replay = StudioReplay(path)
        fdt = VirtualFdt("1.2.8.20", replay)
        fdt.feed(host(0x01, 0xFF, 0xFF), 0.0)
        frames, _ = run(fdt, 0.05)
        samples = [o for o in SampleConverter(1000).convert(frames) if isinstance(o, Sample)]
        first = samples[0]
        from movetrics_fdt.files import read_studio_csv
        rec = read_studio_csv(path, details=False)
        import bisect
        index = bisect.bisect_right(rec.time_s, first.t) - 1
        self.assertEqual(first.fz, rec.columns["p1_ForceZ"][index])
        self.assertEqual(first.fy, rec.columns["p1_ForceY"][index])  # Studio signs survive the round trip
        self.assertEqual(first.mx, rec.columns["p1_MomentX"][index])


async def start_server(profile, **kwargs):
    loop = asyncio.get_running_loop()
    ready = loop.create_future()
    asyncio.ensure_future(serve_tcp(lambda: VirtualFdt(profile, now=loop.time(), **kwargs), "127.0.0.1", 0,
                                    ready=lambda h, p: ready.set_result(p)))
    return await ready


class ClientOverTcpTests(unittest.TestCase):
    def test_client_records_two_seconds_at_2000_hz_without_loss(self):
        async def scenario():
            port = await start_server("sync", signal=Synthetic("cmj"))
            async with FdtClient(TcpTransport("127.0.0.1", port)) as fdt:
                version = await fdt.get_firmware_version()
                await fdt.set_rate(2000)
                await fdt.set_sync_mode(SyncMode.EVENT_FRAMES | SyncMode.PULSE_TRAIN, 500)
                await fdt.start_stream()
                samples, events, gaps = [], [], []

                async def read():
                    async for item in fdt.samples():
                        (samples if isinstance(item, Sample) else events if isinstance(item, Event) else gaps).append(item)
                        if isinstance(item, Sample) and item.t >= 2.0:
                            return
                await asyncio.wait_for(read(), 10)
                await fdt.stop_stream()
                return version, samples, events, gaps
        version, samples, events, gaps = asyncio.run(scenario())
        self.assertEqual(version.stm32FW, "1.2.8.24")
        self.assertEqual(gaps, [])
        per_plate = [s for s in samples if s.plate == 1]
        self.assertGreaterEqual(len(per_plate), 3999)
        self.assertTrue(all(b.stamp - a.stamp == 5 for a, b in zip(per_plate, per_plate[1:])))
        self.assertEqual([e.stamp for e in events if e.name == "sync_out_rise"][:4], [1, 5001, 10001, 15001])
        loaded = [s for s in samples if s.fz > 100]
        self.assertTrue(all(abs(s.cop_x) < 0.02 and abs(s.cop_y) < 0.03 for s in loaded))


if __name__ == "__main__":
    unittest.main()
