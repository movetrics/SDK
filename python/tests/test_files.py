"""Studio export readers against an excerpt of a real Studio export (14 Oct 2026, double platform, 1,000 rows/s).

Fixtures: rows 5,182 to 5,381 of the channels file, cut around the stream's one 41 ms hole (take-off, little load
on plate 1); its first 200 rows (quiet standing on both plates); and the details file without its name, date of
birth, height, weight and exam id.
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from movetrics_fdt.files import read_studio_csv, read_studio_details

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CHANNELS = FIXTURES / "studio-2026-10-14-excerpt-channels.csv"
STANDING = FIXTURES / "studio-2026-10-14-start-channels.csv"


class StudioCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recording = read_studio_csv(CHANNELS)

    def test_columns_units_and_plates(self) -> None:
        self.assertEqual(self.recording.plates, ["p1", "p2"])
        self.assertEqual(len(self.recording.time_s), 200)
        self.assertEqual(self.recording.time_s[0], 0.0)
        self.assertEqual(self.recording.columns["comb_ForceZ"][0], 1418.0)
        self.assertEqual(self.recording.columns["p1_COPx"][0], -0.043)

    def test_rate_is_the_median_step_and_the_hole_is_reported(self) -> None:
        self.assertEqual(self.recording.sample_rate_hz, 1000.0)
        gaps = self.recording.gaps
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0].length_s, 0.041)

    def test_plate_cop_from_moments_matches_the_recorded_columns_to_the_rounding(self) -> None:
        standing = read_studio_csv(STANDING)
        self.assertEqual(standing.gaps, [])
        self.assertEqual(standing.details, {})  # no partner file for this excerpt
        for plate in ("p1", "p2"):
            xs, ys = standing.plate_cop(plate)
            pairs = [(x, standing.columns[f"{plate}_COPx"][i], y, standing.columns[f"{plate}_COPy"][i])
                     for i, (x, y) in enumerate(zip(xs, ys)) if x is not None and standing.columns[f"{plate}_COPx"][i] is not None]
            self.assertGreater(len(pairs), 100)
            for x, rx, y, ry in pairs:
                # Studio rounds CoP to 1 mm; 1.5 mm leaves room for rounding of the force and moment columns.
                self.assertLess(abs(x - rx), 0.0015)
                self.assertLess(abs(y - ry), 0.0015)

    def test_details_partner_is_read(self) -> None:
        self.assertEqual(self.recording.details["Exam Type"], "CMJ Analysis")
        self.assertEqual(self.recording.details["Configuration Name"], "Double Platform")

    def test_wrong_files_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            read_studio_csv(FIXTURES / "studio-2026-10-14-excerpt-details.csv")
        with self.assertRaises(ValueError):
            read_studio_details(CHANNELS)


class CombinedCopTests(unittest.TestCase):
    def test_combined_cop_is_the_fz_weighted_plate_cop_about_the_middle(self) -> None:
        recording = read_studio_csv(STANDING)
        c = recording.columns
        checked = 0
        for i in range(len(recording.time_s)):
            if None in (c["p1_COPx"][i], c["p2_COPx"][i], c["comb_COPx"][i]):
                continue
            fz1, fz2 = c["p1_ForceZ"][i], c["p2_ForceZ"][i]
            x = (fz1 * (c["p1_COPx"][i] - 0.175) + fz2 * (c["p2_COPx"][i] + 0.175)) / (fz1 + fz2)  # type: ignore[operator]
            self.assertTrue(math.isclose(x, c["comb_COPx"][i], abs_tol=0.002))  # type: ignore[arg-type]
            checked += 1
        self.assertGreater(checked, 100)


if __name__ == "__main__":
    unittest.main()
