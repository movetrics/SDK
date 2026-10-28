#!/usr/bin/env python3
"""Generate vectors/vocabulary.json: wire frames in, the samples, events and gaps every client must produce.

The byte vectors (gen_vectors.py) say how a frame decodes. These say what a client makes of the decoded frames under
the shared vocabulary (contract K4, contracts/vocabulary.v1.json): placeholders dropped, Studio's sign map, CoP
from the moment reference depth, the 50 N CoP threshold, gaps from 1.5 nominal periods, the uint32 stamp unwrapped,
event times refined by offset_us. Expected values are computed here from the contract's numbers and formulas, not by
calling any client, so the Python client is checked against them like the others.

Standard library only. Run with python3 -I tools/gen_vocabulary_vectors.py; it rewrites the file
deterministically.
"""

import json
import struct
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parent.parent
CONTRACT = json.loads((SDK_DIR / "contracts" / "vocabulary.v1.json").read_text())
OUT = SDK_DIR / "vectors" / "vocabulary.json"

CHANNELS = ("fx", "fy", "fz", "mx", "my", "mz")
SIGN = [CONTRACT["stream_to_plate_frame"]["sign"][c] for c in CHANNELS]
DEPTH = CONTRACT["plate"]["cop_formula"]["d_m"]
COP_MIN = CONTRACT["plate"]["cop_min_fz_n"]
EVENT_NAMES = {int(k): v for k, v in CONTRACT["events"]["types"].items()}
GAP_FACTOR = 1.5  # contract gaps.definition: "longer than 1.5 nominal periods"
TICKS = 10_000


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF), as in vectors/crc16.json."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def wrap(body: bytes) -> str:
    crc = crc16(body)
    return (b"\xbe\xef" + body + bytes((crc & 0xFF, crc >> 8)) + b"\x04\x04").hex()


def stream(plate: int, stamp: int, raw: tuple[int, ...]) -> str:
    return wrap(struct.pack("<BBIhhhhhh", plate, 0x01, stamp, *raw))


def event(stamp: int, kind: int, source: int, count: int, offset_us: int, detail: int, mode: int) -> str:
    return wrap(struct.pack("<BBIBBIhHBx", 0xFD, 0x0E, stamp, kind, source, count, offset_us, detail, mode))


def sample(plate: int, stamp: int, raw: tuple[int, ...]) -> dict:
    fx, fy, fz, mx, my, mz = (float(s * v) for s, v in zip(SIGN, raw))
    if fz >= COP_MIN:
        cop_x, cop_y = (-my - DEPTH * fx) / fz, (-mx + DEPTH * fy) / fz
    else:
        cop_x = cop_y = None
    return {"kind": "sample", "t": stamp / TICKS, "plate": plate, "fx": fx, "fy": fy, "fz": fz, "mx": mx, "my": my,
            "mz": mz, "cop_x": cop_x, "cop_y": cop_y, "stamp": stamp, "raw": list(raw)}


def gap(plate: int, last: int, stamp: int, period: float) -> dict:
    missing = round((stamp - last) / period) - 1
    return {"kind": "gap", "plate": plate, "start_t": last / TICKS, "end_t": stamp / TICKS, "missing": missing}


def ev(stamp: int, kind: int, source: int, count: int, offset_us: int, detail: int) -> dict:
    return {"kind": "event", "t": stamp / TICKS + offset_us / 1e6, "type": kind, "name": EVENT_NAMES[kind],
            "source": source, "count": count, "detail": detail, "stamp": stamp, "offset_us": offset_us}


STAND = (12, 25, 812, 31, -44, 3)
cases = []

frames = [stream(1, 0, (0,) * 6), stream(2, 0, (0,) * 6), stream(1, 100, STAND), stream(2, 100, (-7, -19, 655, -12, 28, -2))]
cases.append({"id": "placeholders_signs_cop", "rate_hz": 2000, "frames": frames,
              "says": "Stamp-0 placeholders after START are dropped; fy and mx flip sign; CoP from the 30 mm reference.",
              "expected": [sample(1, 100, STAND), sample(2, 100, (-7, -19, 655, -12, 28, -2))]})

low, edge = (3, 2, 49, 10, -10, 0), (3, 2, 50, 10, -10, 0)
cases.append({"id": "cop_threshold", "rate_hz": 2000, "frames": [stream(1, 100, low), stream(1, 105, edge)],
              "says": "Below 50 N the CoP is empty (null here, NaN in clients); at exactly 50 N it is computed.",
              "expected": [sample(1, 100, low), sample(1, 105, edge)]})

cases.append({"id": "gap_at_known_rate", "rate_hz": 2000,
              "frames": [stream(1, s, STAND) for s in (100, 105, 120)],
              "says": "At 2000/s the period is 5 ticks; a 15-tick step is a gap with 2 samples missing, reported before "
                      "the first sample after it.",
              "expected": [sample(1, 100, STAND), sample(1, 105, STAND), gap(1, 105, 120, 5), sample(1, 120, STAND)]})

cases.append({"id": "gap_learnt_period", "rate_hz": None,
              "frames": [stream(1, s, STAND) for s in (100, 110, 120, 150)],
              "says": "With no rate given, the period is the smallest step seen per plate (10 ticks here).",
              "expected": [sample(1, s, STAND) for s in (100, 110, 120)] + [gap(1, 120, 150, 10), sample(1, 150, STAND)]})

cases.append({"id": "gaps_per_plate", "rate_hz": 1000,
              "frames": [stream(1, 100, STAND), stream(2, 100, STAND), stream(2, 110, STAND), stream(1, 130, STAND)],
              "says": "Each plate has its own clock of steps: plate 2 is on time, plate 1 misses 2 samples.",
              "expected": [sample(1, 100, STAND), sample(2, 100, STAND), sample(2, 110, STAND), gap(1, 100, 130, 10),
                           sample(1, 130, STAND)]})

top = 2**32
cases.append({"id": "stamp_wrap", "rate_hz": 2000,
              "frames": [stream(1, top - 7, STAND), stream(1, top - 2, STAND), stream(1, 3, STAND)],
              "says": "The uint32 stamp wraps after 4.97 days; t keeps counting (no gap, no jump back).",
              "expected": [sample(1, top - 7, STAND), sample(1, top - 2, STAND), sample(1, top + 3, STAND)]})

cases.append({"id": "events_between_samples", "rate_hz": 2000,
              "frames": [stream(1, 1000, STAND), event(1002, 1, 0, 7, 37, 0, 0x09), stream(1, 1005, STAND),
                         event(1005, 7, 2, 1, 0, 0b0000100, 0x29)],
              "says": "Events keep their place in the stream; t adds offset_us to the tick; saturation names the plate "
                      "in source and the clipped channels in detail (bit 2 = fz).",
              "expected": [sample(1, 1000, STAND), ev(1002, 1, 0, 7, 37, 0), sample(1, 1005, STAND),
                           ev(1005, 7, 2, 1, 0, 0b0000100)]})

document = {
    "schema": "movetrics-fdt-vocabulary-vectors/1",
    "contract": f"{CONTRACT['schema']} {CONTRACT['version']}",
    "generator": "tools/gen_vocabulary_vectors.py",
    "rules": "Feed each case's frames, in order, to a new converter with rate_hz (null: learn the period). Its output "
             "must equal expected, in order: integers exactly, floats within 1e-9, null CoP as NaN.",
    "cases": cases,
}
OUT.write_text(json.dumps(document, indent=1) + "\n")
print(f"{OUT.relative_to(SDK_DIR)}: {len(cases)} cases, {sum(len(c['expected']) for c in cases)} expected items")
