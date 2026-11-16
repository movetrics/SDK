"""LSL bridge end to end: simulated samples out through pylsl, read back by an inlet on the same machine."""

import time
import unittest

try:
    import pylsl
except ImportError:  # pragma: no cover
    pylsl = None

from movetrics_fdt.vocabulary import Event, Gap, Sample


@unittest.skipIf(pylsl is None, "pylsl not installed (pip install pylsl)")
class LslTests(unittest.TestCase):
    def test_samples_and_markers_reach_an_inlet_with_device_spacing(self):
        from movetrics_fdt.lsl import LslBridge

        bridge = LslBridge(1000, plates=(1,), source_id=f"movetrics-test-{time.time_ns()}", chunk=10)
        found = pylsl.resolve_byprop("source_id", bridge.outlets[1].get_info().source_id(), timeout=5)
        markers = pylsl.resolve_byprop("source_id", bridge.markers.get_info().source_id(), timeout=5)
        inlet, marker_inlet = pylsl.StreamInlet(found[0]), pylsl.StreamInlet(markers[0])
        inlet.open_stream(timeout=5)
        marker_inlet.open_stream(timeout=5)
        time.sleep(0.5)
        start = pylsl.local_clock()
        for k in range(1, 3001):
            t = k / 1000
            # Arrival jitters by up to 16 ms; the stamps must not.
            bridge.push(Sample(t, 1, 1.0, 2.0, 700.0, 3.0, -4.0, 0.5, 0.0057, -0.0043, k * 10, (1, -2, 700, -3, -4, 0)),
                        arrival=start + t + 0.003 + (k % 16) / 1000)
            if k == 1500:
                bridge.push(Event(t, 1, "sync_in_rise"), arrival=start + t)
                bridge.push(Gap(1, t, t + 0.01, 9), arrival=start + t)
        bridge.flush()
        samples, stamps = [], []
        deadline = time.monotonic() + 5
        while len(samples) < 3000 and time.monotonic() < deadline:
            chunk, ts = inlet.pull_chunk(timeout=0.5)
            samples += chunk
            stamps += ts
        names = [marker_inlet.pull_sample(timeout=2)[0][0] for _ in range(2)]
        self.assertEqual(len(samples), 3000)
        self.assertAlmostEqual(samples[0][2], 700.0)
        steps = [b - a for a, b in zip(stamps[2000:], stamps[2001:])]
        self.assertLess(max(abs(s - 0.001) for s in steps), 0.0002)  # after warm-up: device spacing, not USB jitter
        self.assertEqual(names, ["sync_in_rise", "gap plate=1 missing=9"])
        self.assertLess(bridge.stats()["residual_ms"], 1.0)

    def test_two_fdts_get_their_own_names_and_source_ids(self):
        from movetrics_fdt.lsl import LslBridge

        source = f"movetrics-test-{time.time_ns()}"
        a = LslBridge(1000, plates=(1, 2), source_id=source, device="A")
        b = LslBridge(1000, plates=(1, 2), source_id=source, device="B")
        infos = [outlet.get_info() for bridge in (a, b) for outlet in (*bridge.outlets.values(), bridge.markers)]
        self.assertEqual([info.name() for info in infos],
                         ["Movetrics FDT A plate 1", "Movetrics FDT A plate 2", "Movetrics FDT A markers",
                          "Movetrics FDT B plate 1", "Movetrics FDT B plate 2", "Movetrics FDT B markers"])
        self.assertEqual([info.source_id() for info in infos],
                         [f"{source}-{d}-{s}" for d in "AB" for s in ("plate1", "plate2", "markers")])
        self.assertEqual(infos[3].desc().child("acquisition").child_value("device"), "B")
        # Without a label, names and ids stay as they were.
        plain = LslBridge(1000, plates=(1,), source_id=source).outlets[1].get_info()
        self.assertEqual((plain.name(), plain.source_id()), ("Movetrics FDT plate 1", f"{source}-plate1"))
        self.assertEqual(plain.desc().child("acquisition").child_value("device"), "")

    def test_close_takes_the_streams_off_the_network(self):
        from movetrics_fdt.lsl import LslBridge

        bridge = LslBridge(1000, plates=(1,), source_id=f"movetrics-test-{time.time_ns()}")
        source_id = bridge.outlets[1].get_info().source_id()
        self.assertEqual(len(pylsl.resolve_byprop("source_id", source_id, timeout=5)), 1)
        bridge.close()
        bridge.close()  # a second close does nothing
        self.assertEqual(bridge.outlets, {})
        self.assertEqual(pylsl.resolve_byprop("source_id", source_id, timeout=1), [])
        with self.assertRaises(RuntimeError):
            bridge.push(Sample(1.0, 1, 0.0, 0.0, 700.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10000, (0, 0, 700, 0, 0, 0)))
        with self.assertRaises(RuntimeError):
            bridge.mark("too late")


class LslLabelTests(unittest.TestCase):
    """Runs without pylsl: a bad label is refused before anything is published."""

    def test_a_device_label_must_fit_a_source_id(self):
        from movetrics_fdt.lsl import LslBridge

        for label in ("", "left plate", "B/2", "ü"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                LslBridge(1000, device=label)


if __name__ == "__main__":
    unittest.main()
