#!/usr/bin/env python3
"""Generate vectors/clock_map.json: (FDT time, arrival time) pairs in, the host time every client must map them to.

Chapter 22's clock mapping (LslBridge and the relay in Python, movetrics.LslBridge in MATLAB) puts each sample's
FDT stamp on the host clock. This file pins the method down so every client maps the same way. The expected values
are computed here from the method as chapter 22 states it ("Clock mapping, exactly"), not by calling any client:

  - Pairs are taken in order; diff = arrival - device. A pair belongs to block floor(device / block_seconds).
  - In each block the pair with the smallest diff (the first one on a tie) gives the block's point (device, diff).
    A block closes when the first pair of a later block arrives.
  - Once three blocks have closed, offset(t) = mean_diff + slope * (t - mean_device) from the least-squares line
    through the last window_blocks points. Before that, offset is the smallest diff seen so far, the current pair
    included.
  - host = device + offset - latency_seconds, computed right after the pair is taken.

Standard library only. Run with python3 -I tools/gen_clock_map_vectors.py; it rewrites the file deterministically.
"""

import json
import math
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parent.parent
OUT = SDK_DIR / "vectors" / "clock_map.json"


def line(points):
    """Least squares diff = mean_diff + slope * (device - mean_device): ((mean_device, mean_diff, slope), rms residual)."""
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sxx if sxx > 0 else 0.0
    residual = math.sqrt(sum((y - (mean_y + slope * (x - mean_x))) ** 2 for x, y in points) / n)
    return (mean_x, mean_y, slope), residual


def expected(device, arrival, block_seconds, window_blocks, latency_seconds):
    points, block, point, floor, fit, residual, host = [], None, None, math.inf, None, None, []
    for d, a in zip(device, arrival):
        diff = a - d
        b = math.floor(d / block_seconds)
        if b != block:
            if point is not None:
                points.append(point)
                if len(points) >= 3:
                    fit, residual = line(points[-window_blocks:])
            block, point = b, (d, diff)
        elif diff < point[1]:
            point = (d, diff)
        floor = min(floor, diff)
        offset = floor if fit is None else fit[1] + fit[2] * (d - fit[0])
        host.append(d + offset - latency_seconds)
    return host, None if fit is None else fit[2] * 1e6, residual


def case(case_id, description, device, arrival, block_seconds=1.0, window_blocks=300, latency_seconds=0.0):
    host, drift_ppm, residual = expected(device, arrival, block_seconds, window_blocks, latency_seconds)
    return {
        "id": case_id,
        "description": description,
        "block_seconds": block_seconds,
        "window_blocks": window_blocks,
        "latency_seconds": latency_seconds,
        "device_s": device,
        "arrival_s": arrival,
        "expect_host_s": host,
        "expect_drift_ppm": drift_ppm,
        "expect_residual_s": residual,
    }


def cases():
    k1 = range(1, 301)
    drift = case(
        "drift_and_jitter",
        "25 pairs per second for 12 s; the FDT clock 40 ppm slow against the host, 2 to 14 ms of delivery jitter and "
        "a 50 ms stall every 97th pair. Covers the warm-up floor, then the fitted line.",
        [k / 25 for k in k1],
        [1000.0 + (k / 25) * (1 + 40e-6) + 0.002 + ((7 * k) % 13) / 1000 + (0.05 if k % 97 == 0 else 0.0) for k in k1],
    )
    window = case(
        "sliding_window_and_latency",
        "50 pairs per second for 6 s in half-second blocks; the line uses only the last 4 points, the FDT clock is "
        "25 ppm fast, and 4 ms of measured latency is subtracted.",
        [k / 50 for k in k1],
        [52.25 + (k / 50) * (1 - 25e-6) + 0.001 + ((11 * k) % 17) / 2000 for k in k1],
        block_seconds=0.5, window_blocks=4, latency_seconds=0.004,
    )
    k3 = range(0, 80)
    ties = case(
        "ties_take_the_first",
        "16 pairs per second for 5 s, in exact binary fractions. In each block the smallest diff (block/256 s) occurs "
        "at the first and the last pair; the first gives the point, which moves the fitted line.",
        [k / 16 for k in k3],
        [10.0 + k / 16 + (k // 16) / 256 + (0.0 if k % 16 in (0, 15) else 1 / 64) for k in k3],
    )
    return [drift, window, ties]


def main():
    document = {
        "schema": "movetrics-fdt-clock-map-vectors/1",
        "method": "docs/22-lsl-and-sync.md, Clock mapping, exactly",
        "generator": "tools/gen_clock_map_vectors.py",
        "rules": "For each case make a new clock map with block_seconds, window_blocks and latency_seconds. Take the "
                 "pairs (device_s, arrival_s) in order; after each pair, map that pair's device time. The results "
                 "must equal expect_host_s within 1e-9 s. After the last pair, the drift (ppm) and the rms residual "
                 "of the fitted line must equal expect_drift_ppm within 1e-6 and expect_residual_s within 1e-12 "
                 "(null: no line yet).",
        "cases": cases(),
    }
    lines = ["{"]
    for key in ("schema", "method", "generator", "rules"):
        lines.append(f"  {json.dumps(key)}: {json.dumps(document[key])},")
    lines.append('  "cases": [')
    for index, item in enumerate(document["cases"]):
        lines.append("    {")
        fields = list(item.items())
        for position, (key, value) in enumerate(fields):
            comma = "," if position < len(fields) - 1 else ""
            lines.append(f"      {json.dumps(key)}: {json.dumps(value)}{comma}")
        lines.append("    }" + ("," if index < len(document["cases"]) - 1 else ""))
    lines.append("  ]")
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"wrote {OUT.relative_to(SDK_DIR)}: {len(document['cases'])} cases")


if __name__ == "__main__":
    main()
