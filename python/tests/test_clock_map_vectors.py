"""vectors/clock_map.json: the clock mapping of chapter 22, pair by pair, against the Python ClockMap."""

import unittest

from movetrics_fdt.sync import ClockMap

from .support import load_vector_file


class ClockMapVectorTests(unittest.TestCase):
    def test_every_case_maps_every_pair(self):
        document = load_vector_file("clock_map.json")
        self.assertEqual(document["schema"], "movetrics-fdt-clock-map-vectors/1")
        for case in document["cases"]:
            with self.subTest(case=case["id"]):
                clock = ClockMap(block_seconds=case["block_seconds"], window_blocks=case["window_blocks"],
                                 latency_seconds=case["latency_seconds"])
                for device, arrival, want in zip(case["device_s"], case["arrival_s"], case["expect_host_s"], strict=True):
                    clock.observe(device, arrival)
                    self.assertAlmostEqual(clock.to_host(device), want, delta=1e-9)
                if case["expect_drift_ppm"] is None:
                    self.assertIsNone(clock.drift_ppm)
                else:
                    self.assertAlmostEqual(clock.drift_ppm, case["expect_drift_ppm"], delta=1e-6)
                    self.assertAlmostEqual(clock.residual_seconds, case["expect_residual_s"], delta=1e-12)


if __name__ == "__main__":
    unittest.main()
