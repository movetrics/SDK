"""vectors/vocabulary.json: the same frames give the same samples, events and gaps in every client (contract K4)."""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from movetrics_fdt.stream import EventFrame, StreamDecoder, StreamFrame
from movetrics_fdt.vocabulary import Event, Gap, Sample, SampleConverter

VECTORS = Path(__file__).resolve().parents[2] / "vectors" / "vocabulary.json"


def as_dict(item: Sample | Event | Gap) -> dict:
    if isinstance(item, Sample):
        return {"kind": "sample", "t": item.t, "plate": item.plate, "fx": item.fx, "fy": item.fy, "fz": item.fz,
                "mx": item.mx, "my": item.my, "mz": item.mz, "cop_x": item.cop_x, "cop_y": item.cop_y,
                "stamp": item.stamp, "raw": list(item.raw)}
    if isinstance(item, Event):
        return {"kind": "event", "t": item.t, "type": item.type, "name": item.name, "source": item.source,
                "count": item.count, "detail": item.detail, "stamp": item.stamp, "offset_us": item.offset_us}
    return {"kind": "gap", "plate": item.plate, "start_t": item.start_t, "end_t": item.end_t, "missing": item.missing}


class VocabularyVectorTests(unittest.TestCase):
    def test_every_case(self):
        document = json.loads(VECTORS.read_text())
        self.assertGreaterEqual(len(document["cases"]), 7)
        for case in document["cases"]:
            with self.subTest(case=case["id"]):
                frames: list[StreamFrame | EventFrame] = []
                decoder = StreamDecoder(on_reply=lambda r: frames.append(r) if isinstance(r, EventFrame) else None)
                for hex_frame in case["frames"]:  # one frame per push keeps events in stream order
                    frames.extend(decoder.push(bytes.fromhex(hex_frame)))
                converter = SampleConverter(case["rate_hz"])
                got = [as_dict(item) for item in converter.convert(frames)]
                self.assertEqual(len(got), len(case["expected"]))
                for actual, expected in zip(got, case["expected"]):
                    self.assertEqual(actual.keys(), expected.keys())
                    for key, want in expected.items():
                        have = actual[key]
                        if want is None:
                            self.assertTrue(math.isnan(have), key)
                        elif isinstance(want, float):
                            self.assertAlmostEqual(have, want, delta=1e-9, msg=key)
                        else:
                            self.assertEqual(have, want, key)


if __name__ == "__main__":
    unittest.main()
