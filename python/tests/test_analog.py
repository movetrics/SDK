"""Analog output scale (contracts/analog-outputs.v1.json, Nur Engineering sheet of 27 Oct 2026)."""

import json
import unittest
from pathlib import Path

from movetrics_fdt.analog import OUTPUTS, clipped, to_value, to_vocabulary

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "analog-outputs.v1.json"


class AnalogTests(unittest.TestCase):
    def test_table_matches_the_contract(self):
        rows = json.loads(CONTRACT.read_text())["outputs"]
        self.assertEqual(len(rows), 16)
        for row in rows:
            spec = OUTPUTS[row["output"]]
            self.assertEqual((spec.plate, spec.signal, spec.unit), (row["plate"], row["signal"], row["unit"]))
            self.assertEqual(spec.units_per_volt, row["units_per_volt"])
            # Full scale is reached at 10 V.
            self.assertAlmostEqual(to_value(row["output"], 10.0), row["full_scale"])

    def test_sheet_examples(self):
        self.assertAlmostEqual(to_value("A1", 0.205), 164.0)          # 164 N Fz metered on 27 Oct 2026
        self.assertAlmostEqual(to_value("A5", 24.6 / 72), 24.6)       # 24.6 N*m Mx

    def test_wire_signs_become_the_plate_frame(self):
        self.assertEqual(to_vocabulary("A3", 1.0), (1, "fy", -200.0))
        self.assertEqual(to_vocabulary("A13", 1.0), (2, "mx", -72.0))
        self.assertEqual(to_vocabulary("A9", 1.0), (2, "fz", 800.0))
        self.assertEqual(to_vocabulary("A8", 1.0), (1, "cop_y", 0.03))
        self.assertTrue(clipped("A1", 9.95))
        self.assertFalse(clipped("A1", 5.0))


if __name__ == "__main__":
    unittest.main()
