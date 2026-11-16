"""The LSL relay: its message checks without a network, then a page's stream through the relay to an LSL inlet."""

import asyncio
import contextlib
import json
import math
import time
import unittest

from movetrics_fdt.relay import (CLOSE_BAD_DATA, CLOSE_BUSY, CLOSE_REFUSED, Hello, RelayError, decode, origin_allowed,
                                 parse_hello, parse_items)
from movetrics_fdt.vocabulary import Event, Gap, Sample

try:
    import pylsl
except ImportError:  # pragma: no cover
    pylsl = None
try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None

HELLO = {"type": "hello", "version": 1, "rate_hz": 1000, "plates": [1, 2], "firmware": "1.2.8.20", "device": None}


def sample(t, plate=1, fz=700.0, cop=(0.0057, -0.0043)):
    return {"kind": "sample", "t": t, "plate": plate, "fx": 1.0, "fy": 2.0, "fz": fz, "mx": 3.0, "my": -4.0,
            "mz": 0.5, "cop_x": cop[0], "cop_y": cop[1], "stamp": round(t * 10000)}


class RelayMessageTests(unittest.TestCase):
    def test_hello_is_checked(self):
        self.assertEqual(parse_hello(HELLO), Hello(1000.0, (1, 2), "1.2.8.20", None))
        for change, code in (({"type": "items"}, CLOSE_REFUSED), ({"version": 2}, CLOSE_REFUSED),
                             ({"rate_hz": 0}, CLOSE_BAD_DATA), ({"rate_hz": True}, CLOSE_BAD_DATA),
                             ({"rate_hz": "2000"}, CLOSE_BAD_DATA), ({"plates": []}, CLOSE_BAD_DATA),
                             ({"plates": [1, 1]}, CLOSE_BAD_DATA), ({"plates": [5]}, CLOSE_BAD_DATA),
                             ({"firmware": ""}, CLOSE_BAD_DATA), ({"device": "B/2"}, CLOSE_BAD_DATA)):
            with self.subTest(change=change), self.assertRaises(RelayError) as caught:
                parse_hello({**HELLO, **change})
            self.assertEqual(caught.exception.code, code)

    def test_items_become_the_vocabulary(self):
        first, second, event, gap = parse_items({"type": "items", "items": [
            sample(1.0), sample(1.001, plate=2, fz=20.0, cop=(None, None)),
            {"kind": "event", "t": 1.25, "name": "sync_in_rise", "type": 1, "source": 1, "stamp": 12500},
            {"kind": "gap", "plate": 1, "start_t": 2.0, "end_t": 2.01, "missing": 9}]}, (1, 2))
        self.assertIsInstance(first, Sample)
        self.assertEqual((first.t, first.plate, first.fz, first.cop_x, first.stamp), (1.0, 1, 700.0, 0.0057, 10000))
        self.assertTrue(math.isnan(second.cop_x) and math.isnan(second.cop_y))  # null on the wire, NaN again here
        self.assertIsInstance(event, Event)
        self.assertEqual((event.name, event.type, event.source, event.stamp), ("sync_in_rise", 1, 1, 12500))
        self.assertEqual(gap, Gap(1, 2.0, 2.01, 9))

    def test_bad_items_are_refused(self):
        bad = [{**sample(1.0), "fx": float("nan")}, {**sample(1.0), "t": True}, {**sample(1.0), "plate": 3},
               {**sample(1.0), "stamp": 1.5}, {**sample(1.0), "fz": None}, {"kind": "event", "t": 1.0, "name": ""},
               {"kind": "event", "t": 1.0, "name": "x", "type": 1.5},
               {"kind": "gap", "plate": 1, "start_t": 1.0, "end_t": 1.1, "missing": -1}, {"kind": "frame"}, "sample"]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(RelayError):
                parse_items({"items": [item]}, (1, 2))
        with self.assertRaises(RelayError):
            parse_items({"items": [sample(1.0)] * 20_001}, (1, 2))

    def test_only_json_objects_are_messages(self):
        for text in (b"binary", "not json", "[1, 2]"):
            with self.subTest(text=text), self.assertRaises(RelayError):
                decode(text)
        self.assertEqual(decode('{"type": "mark", "text": "jump 3"}')["text"], "jump 3")

    def test_pages_from_this_computer_and_named_origins_only(self):
        for origin in (None, "http://localhost:5173", "http://127.0.0.1", "https://localhost:8443", "http://[::1]:8000"):
            self.assertTrue(origin_allowed(origin), origin)
        for origin in ("https://evil.example", "http://localhost.evil.example", "http://127.0.0.1.evil.example", "null"):
            self.assertFalse(origin_allowed(origin), origin)
        self.assertTrue(origin_allowed("https://lab.example.org", ["https://lab.example.org"]))


@unittest.skipIf(pylsl is None or websockets is None, "needs pylsl and websockets (pip install pylsl websockets)")
class RelayEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.label = f"relaytest{time.time_ns()}"

    def run_with_relay(self, scenario):
        async def main():
            from movetrics_fdt.relay import serve_relay

            url = asyncio.get_running_loop().create_future()
            server = asyncio.create_task(serve_relay(port=0, ready=url.set_result))
            try:
                await scenario(await asyncio.wait_for(url, 5))
            finally:
                server.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await server

        asyncio.run(main())

    def test_a_page_streams_through_the_relay_to_an_inlet(self):
        from websockets.asyncio.client import connect

        async def scenario(url):
            async with connect(url, origin="http://localhost:5173") as page:
                await page.send(json.dumps({**HELLO, "plates": [1], "device": self.label}))
                ready = json.loads(await page.recv())
                self.assertEqual(ready["streams"], [f"Movetrics FDT {self.label} plate 1",
                                                    f"Movetrics FDT {self.label} markers"])
                found = await asyncio.to_thread(pylsl.resolve_byprop, "source_id", f"movetrics-fdt-{self.label}-plate1", 1, 5)
                marks = await asyncio.to_thread(pylsl.resolve_byprop, "source_id", f"movetrics-fdt-{self.label}-markers", 1, 5)
                inlet, marker_inlet = pylsl.StreamInlet(found[0]), pylsl.StreamInlet(marks[0])
                await asyncio.to_thread(inlet.open_stream, 5)
                await asyncio.to_thread(marker_inlet.open_stream, 5)
                await asyncio.sleep(0.3)
                for batch in range(20):
                    items = [sample((batch * 100 + k + 1) / 1000, fz=20.0 if k % 10 == 0 else 700.0,
                                    cop=(None, None) if k % 10 == 0 else (0.0057, -0.0043)) for k in range(100)]
                    if batch == 10:
                        items.append({"kind": "event", "t": 1.0005, "name": "sync_in_rise", "type": 1})
                    await page.send(json.dumps({"type": "items", "items": items}))
                await page.send(json.dumps({"type": "mark", "text": "jump 3"}))
                samples, stamps = [], []
                deadline = time.monotonic() + 5
                while len(samples) < 2000 and time.monotonic() < deadline:
                    chunk, ts = await asyncio.to_thread(inlet.pull_chunk, 0.5)
                    samples += chunk
                    stamps += ts
                names = [(await asyncio.to_thread(marker_inlet.pull_sample, 2))[0][0] for _ in range(2)]
            self.assertEqual(len(samples), 2000)
            self.assertTrue(math.isnan(samples[0][6]) and math.isnan(samples[0][7]))  # no CoP below 50 N: NaN on LSL
            self.assertEqual(samples[1][:3], [1.0, 2.0, 700.0])
            self.assertTrue(all(later > earlier for earlier, later in zip(stamps, stamps[1:])))
            self.assertEqual(names, ["sync_in_rise", "jump 3"])

        self.run_with_relay(scenario)

    def test_one_page_at_a_time_bad_data_and_foreign_origins(self):
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed, InvalidStatus

        async def scenario(url):
            async with connect(url) as first:  # no Origin header: a program on this computer
                await first.send(json.dumps({**HELLO, "device": self.label}))
                self.assertEqual(json.loads(await first.recv())["type"], "ready")
                async with connect(url, origin="http://localhost:5173") as second:
                    with self.assertRaises(ConnectionClosed) as busy:
                        await second.recv()
                self.assertEqual(busy.exception.rcvd.code, CLOSE_BUSY)
                await first.send(json.dumps({"type": "items", "items": [sample(1.0, plate=3)]}))
                with self.assertRaises(ConnectionClosed) as refused:
                    await first.recv()
                self.assertEqual(refused.exception.rcvd.code, CLOSE_BAD_DATA)
                self.assertIn("plate 3", refused.exception.rcvd.reason)
            with self.assertRaises(InvalidStatus) as foreign:
                async with connect(url, origin="https://evil.example"):
                    pass
            self.assertEqual(foreign.exception.response.status_code, 403)
            async with connect(url, origin="http://localhost:5173") as again:  # free again once the first page left
                await again.send(json.dumps({**HELLO, "device": self.label}))
                self.assertEqual(json.loads(await again.recv())["type"], "ready")

        self.run_with_relay(scenario)


if __name__ == "__main__":
    unittest.main()
