"""Writers: CSV + JSON companion, C3D read back with ezc3d (the reader OpenSim 4 uses), OpenSim .mot.

The fixtures are excerpts of a real Studio export (14 Oct 2026); its CoP columns are Studio's own, so the C3D test
checks the written file against Studio's numbers, not against our formula alone."""

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from movetrics_fdt.files import read_studio_csv
from movetrics_fdt.writers import GapError, Recording, write_c3d, write_csv, write_mot

FIXTURES = Path(__file__).parent / "fixtures"
NO_GAP = FIXTURES / "studio-2026-10-14-start-channels.csv"
WITH_GAP = FIXTURES / "studio-2026-10-14-excerpt-channels.csv"  # one 41 ms hole after row 99

try:
    import ezc3d  # noqa: F401
    import numpy as np
except ImportError:  # pragma: no cover
    ezc3d = None


class CsvTests(unittest.TestCase):
    def test_wide_table_and_companion(self):
        source = read_studio_csv(WITH_GAP, details=False)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Recording.from_studio(source), Path(tmp) / "x.csv")
            rows = list(csv.DictReader(path.open()))
            meta = json.loads(Path(str(path) + ".json").read_text())
        self.assertEqual(len(rows), 200)
        self.assertEqual(float(rows[0]["p1_fz"]), source.columns["p1_ForceZ"][0])
        self.assertAlmostEqual(float(rows[100]["t"]) - float(rows[99]["t"]), 0.041)  # the hole stays a hole
        self.assertEqual(len(meta["gaps"]), 2)  # one per plate
        self.assertEqual(meta["units"]["mx"], "N*m")
        for i, row in enumerate(rows):  # comb_ equals Studio's combined columns within its rounding
            if row["comb_cop_x"] and source.columns["comb_COPx"][i] is not None:
                self.assertAlmostEqual(float(row["comb_cop_x"]), source.columns["comb_COPx"][i], delta=0.003)
            self.assertAlmostEqual(float(row["comb_fz"]), source.columns["comb_ForceZ"][i], delta=1e-9)


@unittest.skipIf(ezc3d is None, "ezc3d not installed (pip install ezc3d)")
class C3dTests(unittest.TestCase):
    def test_ezc3d_reads_studio_cop_back_within_1_mm(self):
        source = read_studio_csv(NO_GAP, details=False)
        with tempfile.TemporaryDirectory() as tmp:
            [path] = write_c3d(Recording.from_studio(source), Path(tmp) / "x.c3d")
            c3d = ezc3d.c3d(str(path), extract_forceplat_data=True)
        self.assertEqual(c3d["parameters"]["ANALOG"]["UNITS"]["value"][3], "Nmm")
        for index, platform in enumerate(c3d["data"]["platform"]):
            plate = index + 1
            centre = platform["corners"].mean(axis=1) / 1000
            cop = platform["center_of_pressure"] / 1000
            checked = 0
            for i in range(len(source.time_s)):
                x, y = source.columns[f"p{plate}_COPx"][i], source.columns[f"p{plate}_COPy"][i]
                if x is None:
                    continue
                self.assertAlmostEqual(cop[0][i] - centre[0], x, delta=0.001)
                self.assertAlmostEqual(cop[1][i] - centre[1], y, delta=0.001)
                checked += 1
            self.assertGreater(checked, 150)
            self.assertTrue(np.allclose(platform["force"][2], source.columns[f"p{plate}_ForceZ"]))

    def test_gaps_are_refused_or_split_never_hidden(self):
        recording = Recording.from_studio(read_studio_csv(WITH_GAP, details=False))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GapError):
                write_c3d(recording, Path(tmp) / "x.c3d")
            parts = write_c3d(recording, Path(tmp) / "x.c3d", gaps="split")
            self.assertEqual([p.name for p in parts], ["x-part1.c3d", "x-part2.c3d"])
            first = ezc3d.c3d(str(parts[1]))["parameters"]["MOVETRICS"]["FIRST_T"]["value"][0]
        self.assertAlmostEqual(first, recording.t[100])  # part 2 keeps its true start time


class MotTests(unittest.TestCase):
    def test_columns_frame_and_external_loads(self):
        recording = Recording.from_studio(read_studio_csv(NO_GAP, details=False))
        with tempfile.TemporaryDirectory() as tmp:
            path = write_mot(recording, Path(tmp) / "trial.mot", external_loads={1: "calcn_l", 2: "calcn_r"})
            lines = path.read_text().splitlines()
            xml = (Path(tmp) / "trial_ExternalLoads.xml").read_text()
        header = lines[lines.index("endheader") + 1].split("\t")
        self.assertEqual(header[:4], ["time", "1_ground_force_vx", "1_ground_force_vy", "1_ground_force_vz"])
        row = dict(zip(header, map(float, lines[lines.index("endheader") + 2].split("\t"))))
        self.assertEqual(row["1_ground_force_vy"], recording.plates[1]["fz"][0])  # OpenSim Y is up
        x, y = recording.cop(1)
        self.assertAlmostEqual(row["1_ground_force_px"], 0.175 + x[0], places=6)
        self.assertAlmostEqual(row["1_ground_force_pz"], -(0.300 + y[0]), places=6)
        self.assertIn("<applied_to_body>calcn_r</applied_to_body>", xml)

    def test_gap_needs_resample_and_is_flagged(self):
        recording = Recording.from_studio(read_studio_csv(WITH_GAP, details=False))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GapError):
                write_mot(recording, Path(tmp) / "t.mot")
            lines = write_mot(recording, Path(tmp) / "t.mot", resample=True).read_text().splitlines()
        header = lines[lines.index("endheader") + 1].split("\t")
        flags = [int(line.split("\t")[-1]) for line in lines[lines.index("endheader") + 2:]]
        self.assertEqual(header[-1], "filled")
        self.assertEqual(sum(flags), 40)  # 41 ms hole at 1,000 rows/s: 40 rows filled
        self.assertEqual(len(flags), 240)


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(ezc3d is None, "ezc3d not installed (pip install ezc3d)")
class K5FixtureTests(unittest.TestCase):
    """The shared C3D fixture (contract K5): the Cloud writer runs the same file through its own tests."""

    def test_written_c3d_matches_the_k5_fixture(self):
        fixture = json.loads((FIXTURES / "k5_c3d_cop.json").read_text())
        source = read_studio_csv(NO_GAP, details=False)
        with tempfile.TemporaryDirectory() as tmp:
            [path] = write_c3d(Recording.from_studio(source), Path(tmp) / "x.c3d")
            c3d = ezc3d.c3d(str(path), extract_forceplat_data=True)
        self.assertEqual(list(c3d["parameters"]["FORCE_PLATFORM"]["ORIGIN"]["value"][:, 0]),
                         fixture["convention"]["FORCE_PLATFORM:ORIGIN_mm"])
        for index, platform in enumerate(c3d["data"]["platform"]):
            centre = platform["corners"].mean(axis=1) / 1000
            cop = platform["center_of_pressure"] / 1000
            by_time = {round(t, 4): i for i, t in enumerate(source.time_s)}
            for t, studio_x, studio_y, _, _ in fixture["plates"][str(index + 1)]:
                i = by_time[t]
                self.assertAlmostEqual(cop[0][i] - centre[0], studio_x, delta=fixture["tolerance_m"])
                self.assertAlmostEqual(cop[1][i] - centre[1], studio_y, delta=fixture["tolerance_m"])
