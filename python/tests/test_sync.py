"""Clock map, edge alignment and the two-FDT merge, on synthetic clocks and on two simulated FDTs."""

import random
import struct
import unittest

from movetrics_fdt import SyncMode
from movetrics_fdt.frames import encode_host_frame
from movetrics_fdt.simulator import Faults, Synthetic, VirtualFdt
from movetrics_fdt.stream import EventFrame, StreamDecoder
from movetrics_fdt.sync import ClockMap, align, edge_times, merge
from movetrics_fdt.vocabulary import Event, Sample, SampleConverter


class ClockMapTests(unittest.TestCase):
    def test_usb_jitter_does_not_enter_the_time_base(self):
        rng = random.Random(4)
        clock = ClockMap()
        drift = 50e-6
        errors = []
        for k in range(60 * 2000):
            device = k / 2000
            true_host = 100.0 + device * (1 + drift) + 0.003
            clock.observe(device, true_host + rng.uniform(0, 0.016))
            if device > 5:
                errors.append(abs(clock.to_host(device) - true_host))
        self.assertLess(max(errors), 0.0005)
        self.assertAlmostEqual(clock.drift_ppm, 50, delta=5)


class AlignTests(unittest.TestCase):
    def test_30_ppm_over_20_minutes_with_missed_edges(self):
        rng = random.Random(7)
        fdt = [k * 1.0 for k in range(1200)]
        other = [12.345 + t * (1 + 30e-6) + rng.gauss(0, 50e-6) for t in fdt]
        del other[100], other[500]  # the EMG system missed two pulses
        del fdt[900]  # and the FDT one
        result = align(fdt, other)
        self.assertAlmostEqual(result.drift_ppm, 30, delta=1)
        self.assertLess(result.residual_s, 0.0001)
        self.assertEqual(result.pairs, 1197)
        self.assertEqual(result.unmatched, 3)
        self.assertAlmostEqual(result.to_other(600.0), 12.345 + 600 * (1 + 30e-6), delta=0.0002)
        self.assertAlmostEqual(result.to_fdt(result.to_other(600.0)), 600.0, places=9)


def _command(fdt, code, payload, now):
    fdt.feed(encode_host_frame(code, 0xFF if code == 0x01 else 0, 0xFF if code == 0x01 else 0, payload), now)


class MergeTests(unittest.TestCase):
    def test_two_simulated_fdts_merge_onto_one_clock(self):
        a = VirtualFdt("sync", Synthetic("cmj", seed=1))
        b = VirtualFdt("sync", Synthetic("cmj", seed=2), Faults(clock_ppm=40))
        _command(a, 0x28, bytes((int(SyncMode.PULSE_TRAIN | SyncMode.EVENT_FRAMES),)) + struct.pack("<H", 1000), 0.0)
        _command(b, 0x28, bytes((int(SyncMode.EVENT_FRAMES),)), 0.0)
        _command(b, 0x01, b"", 0.0)
        items = {"a": [], "b": []}
        conv = {"a": SampleConverter(1000), "b": SampleConverter(1000)}
        dec = {k: StreamDecoder(on_reply=lambda r, k=k: items[k].extend(conv[k].push(r)) if isinstance(r, EventFrame) else None)
               for k in items}
        now = 0.0
        while now < 30.0:
            if abs(now - 0.25) < 1e-9 or (now > 0.25 and not a.streaming):
                _command(a, 0x01, b"", now)  # A starts a quarter second later: different zero, different rate
            for key, fdt in (("a", a), ("b", b)):
                for frame in dec[key].push(fdt.advance(now)):
                    items[key].extend(conv[key].push(frame))
            b.sync_in(a.sync_out_level, now)  # the cable from A's SYNC OUT to B's SYNC IN
            now += 0.0005
        merged, alignment = merge(items["a"], items["b"])
        self.assertEqual(alignment.pairs, 30)
        # B runs 40 ppm fast against A. The test loop moves the cable every 0.5 ms, so each edge is seen up to
        # 0.5 ms late at random: over 29 s that limits the slope to about +-10 ppm here, not the method.
        self.assertAlmostEqual(alignment.drift_ppm, -40, delta=10)
        self.assertLess(alignment.residual_s, 0.001)
        self.assertAlmostEqual(alignment.to_other(10.0), 10.0 * (1 - 40e-6) - 0.25, delta=0.001)
        plates = {item.plate for item in merged if isinstance(item, Sample)}
        self.assertEqual(plates, {1, 2, 3, 4})
        self.assertEqual(len(edge_times(merged, "sync_in_rise")), 30)


if __name__ == "__main__":
    unittest.main()
