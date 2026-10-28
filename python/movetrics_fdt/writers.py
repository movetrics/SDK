"""Writers for the formats labs already use: CSV (with a JSON companion), C3D and OpenSim .mot external loads.

All three start from a Recording in the shared vocabulary (docs/19): SI units, plate frame, t from the FDT
clock, gaps and events kept. None of them hides a gap. Formats that need a uniform clock (C3D, .mot) refuse a
recording with gaps unless the caller says what to do: split it into gap-free parts, or (.mot only) resample with a
flag column.

C3D, measured on a 14 Oct 2026 Studio export (docs/21): a reader that follows the C3D standard (ezc3d,
and OpenSim 4.x, which reads C3D through ezc3d) places the CoP correctly only when the moments are in N*mm to match
the mm geometry and Fy and Mx carry the FDT's wire signs. Studio's own C3D has neither, and ezc3d puts its CoP
26-51 mm rms off Studio's CSV. Written this way, ezc3d's CoP matches Studio's CSV CoP to 0.28 mm (x) and 0.29 mm
(y) rms, the 1 mm rounding of the CSV.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .vocabulary import (
    CHANNELS,
    COP_MIN_FZ_N,
    GAP_FACTOR,
    MOMENT_REFERENCE_DEPTH_M,
    STREAM_SIGN,
    TICKS_PER_SECOND,
    Event,
    Gap,
    Sample,
    combine,
    plate_cop,
)

VOCABULARY_VERSION: Final = "1.0.0-draft"
# Studio's C3D layout (14 Oct 2026 export, measured): plates side by side, corners in mm, Studio's corner order.
STUDIO_CORNERS_MM: Final = {
    1: ((350.0, 600.0, 0.0), (0.0, 600.0, 0.0), (0.0, 0.0, 0.0), (350.0, 0.0, 0.0)),
    2: ((700.0, 600.0, 0.0), (350.0, 600.0, 0.0), (350.0, 0.0, 0.0), (700.0, 0.0, 0.0)),
}
# Moments are moved from the FDT's reference 30 mm below the top to the top surface centre before writing, so
# FORCE_PLATFORM:ORIGIN is (0, 0, 0). Readers can differ on the sign of a non-zero ORIGIN (inferred, not tested
# across vendors); with ORIGIN 0 the sign cannot matter. Same convention as the Cloud writer
# (contract K5). ezc3d CoP against Studio's CSV on the 14 Oct 2026 export: 0.23-0.29 mm rms either way (measured).
ORIGIN_MM: Final = (0.0, 0.0, 0.0)


class GapError(ValueError):
    """The recording has gaps and the format needs a uniform clock. Pass gaps="split" (or resample=True for .mot)."""


@dataclass
class Recording:
    """One recording in the shared vocabulary. t is the common time of each row (both plates of an FDT share the
    grid on 1.2.8.x); plates[n][name] holds fx..mz in SI units and the plate frame, NaN where that plate had no
    sample. layout maps each plate to its corners in the lab frame (mm, Studio corner order)."""

    rate_hz: float
    t: list[float]
    plates: dict[int, dict[str, list[float]]]
    events: list[Event] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    layout: dict[int, Sequence[Sequence[float]]] = field(default_factory=lambda: dict(STUDIO_CORNERS_MM))

    @classmethod
    def from_samples(cls, items: Iterable[Sample | Event | Gap], rate_hz: float,
                     metadata: dict[str, Any] | None = None) -> Recording:
        """Collect FdtClient.samples() (or SampleConverter output) into rows by stamp."""
        rows: dict[int, dict[int, Sample]] = {}
        events: list[Event] = []
        gaps: list[Gap] = []
        for item in items:
            if isinstance(item, Sample):
                rows.setdefault(item.stamp, {})[item.plate] = item
            elif isinstance(item, Event):
                events.append(item)
            else:
                gaps.append(item)
        stamps = sorted(rows)
        plate_ids = sorted({plate for row in rows.values() for plate in row})
        plates = {plate: {name: [] for name in CHANNELS} for plate in plate_ids}
        for stamp in stamps:
            for plate in plate_ids:
                sample = rows[stamp].get(plate)
                for name in CHANNELS:
                    plates[plate][name].append(getattr(sample, name) if sample else math.nan)
        meta = {"source": "live", **(metadata or {}), "rate_hz": rate_hz}
        return cls(rate_hz, [stamp / TICKS_PER_SECOND for stamp in stamps], plates, events, gaps, meta)

    @classmethod
    def from_studio(cls, recording: Any) -> Recording:
        """From files.read_studio_csv(): Studio's signs are the plate frame already."""
        names = dict(zip(("ForceX", "ForceY", "ForceZ", "MomentX", "MomentY", "MomentZ"), CHANNELS))
        plates = {
            int(prefix[1]): {short: [math.nan if v is None else v for v in recording.columns[f"{prefix}_{long}"]]
                             for long, short in names.items()}
            for prefix in recording.plates
        }
        gaps = [Gap(plate=plate, start_t=recording.time_s[g.row - 1], end_t=recording.time_s[g.row],
                    missing=round(g.length_s * recording.sample_rate_hz) - 1)
                for g in recording.gaps for plate in plates]
        meta = {"source": "studio_csv", "rate_hz": recording.sample_rate_hz, "file": recording.path.name}
        return cls(recording.sample_rate_hz, list(recording.time_s), plates, [], gaps, meta)

    def cop(self, plate: int, min_fz_n: float = COP_MIN_FZ_N) -> tuple[list[float], list[float]]:
        p = self.plates[plate]
        pairs = [plate_cop(p["fx"][i], p["fy"][i], p["fz"][i], p["mx"][i], p["my"][i], min_fz_n) for i in range(len(self.t))]
        return [x for x, _ in pairs], [y for _, y in pairs]

    def uniform_parts(self) -> list[tuple[int, int]]:
        """Index ranges [start, stop) of the parts between gaps (all plates together)."""
        if not self.t:
            return []
        period = 1 / self.rate_hz
        cuts = [i + 1 for i in range(len(self.t) - 1) if self.t[i + 1] - self.t[i] > GAP_FACTOR * period]
        bounds = [0] + cuts + [len(self.t)]
        return list(zip(bounds, bounds[1:]))

    def slice(self, start: int, stop: int) -> Recording:
        t0, t1 = self.t[start], self.t[stop - 1]
        return Recording(self.rate_hz, self.t[start:stop],
                         {n: {k: v[start:stop] for k, v in ch.items()} for n, ch in self.plates.items()},
                         [e for e in self.events if t0 <= e.t <= t1], [], dict(self.metadata), dict(self.layout))


# ----- CSV ------------------------------------------------------------------------------------------------------

def _companion(recording: Recording, fmt: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "format": fmt,
        "vocabulary": VOCABULARY_VERSION,
        "units": {"t": "s", "fx": "N", "fy": "N", "fz": "N", "mx": "N*m", "my": "N*m", "mz": "N*m", "cop_x": "m", "cop_y": "m"},
        "frame": "plate (docs/19); comb_ in the pair frame",
        "metadata": recording.metadata,
        "gaps": [vars(g) for g in recording.gaps],
        "events": [vars(e) for e in recording.events],
        **(extra or {}),
    }


def write_csv(recording: Recording, path: str | Path, *, combined: bool = True) -> Path:
    """Wide table t, p1_fx ... p1_cop_y, p2_..., comb_... in SI units, plus <path>.json with units, metadata, gaps
    and events. Empty cells where a plate had no sample or CoP is undefined. Rows keep their real times."""
    path = Path(path)
    plates = sorted(recording.plates)
    cops = {plate: recording.cop(plate) for plate in plates}
    header = ["t"]
    for plate in plates:
        header += [f"p{plate}_{name}" for name in CHANNELS + ("cop_x", "cop_y")]
    if combined and len(plates) == 2:
        header += [f"comb_{name}" for name in CHANNELS + ("cop_x", "cop_y")]

    def cell(value: float) -> str:
        return "" if value is None or math.isnan(value) else repr(float(value))

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for i, t in enumerate(recording.t):
            row = [repr(t)]
            samples = {}
            for plate in plates:
                ch = recording.plates[plate]
                values = [ch[name][i] for name in CHANNELS]
                row += [cell(v) for v in values] + [cell(cops[plate][0][i]), cell(cops[plate][1][i])]
                if not math.isnan(values[2]):
                    samples[plate] = Sample(t, plate, *values, cops[plate][0][i], cops[plate][1][i], 0, (0,) * 6)
            if combined and len(plates) == 2:
                if len(samples) == 2:
                    comb = combine(samples)
                    row += [cell(comb[name]) for name in CHANNELS + ("cop_x", "cop_y")]
                else:
                    row += [""] * 8
            writer.writerow(row)
    Path(str(path) + ".json").write_text(json.dumps(_companion(recording, "movetrics-csv/1"), indent=2), encoding="utf-8")
    return path


# ----- C3D ------------------------------------------------------------------------------------------------------

def _check_gaps(recording: Recording, gaps: str) -> list[tuple[int, int]]:
    parts = recording.uniform_parts()
    if len(parts) > 1 and gaps != "split":
        raise GapError(f"{len(parts) - 1} gap(s) in the recording; this format needs a uniform clock. "
                       "Use gaps='split' to write one file per gap-free part.")
    if gaps not in ("refuse", "split"):
        raise ValueError("gaps must be 'refuse' or 'split'")
    return parts


def _int_parameter(c3d: Any, group: str, name: str, values: list[int], dims: list[int] | None = None) -> None:
    """An INT parameter. ezc3d's add_parameter stores integers as float, and readers (ezc3d itself among them)
    refuse a FORCE_PLATFORM:USED that is not INT, so the parameter is built through ezc3d's own types."""
    from ezc3d import ezc3d as swig

    parameter = swig.Parameter(name, "")
    parameter.set(swig.VecInt(values), swig.VecUInt(dims or [len(values)]))
    c3d._storage["parameters"].add_parameter(group, parameter)


def write_c3d(recording: Recording, path: str | Path, *, gaps: str = "refuse") -> list[Path]:
    """Write C3D with TYPE-2 force platforms that standard readers interpret correctly (module docstring).

    Analog channels Fx1 Fy1 Fz1 Mx1 My1 Mz1 per plate at the FDT rate, forces in N, moments in N*mm about the top
    surface centre, FDT wire signs; CORNERS from recording.layout (default Studio's), ORIGIN 0. Events go to the EVENT
    group, gaps and the vocabulary version to a MOVETRICS group. A recording with gaps is refused unless
    gaps='split', which writes <stem>-part1.c3d, -part2.c3d ... Needs ezc3d (pip install ezc3d).
    """
    import ezc3d
    import numpy as np

    path = Path(path)
    parts = _check_gaps(recording, gaps)
    if len(parts) > 1:
        return [write_c3d(recording.slice(a, b), path.with_name(f"{path.stem}-part{n}{path.suffix}"))[0]
                for n, (a, b) in enumerate(parts, 1)]
    plates = sorted(recording.plates)
    missing = [plate for plate in plates if plate not in recording.layout]
    if missing:
        raise ValueError(f"no layout (corners) for plate(s) {missing}; set recording.layout")
    rows = []
    labels: list[str] = []
    units: list[str] = []
    for plate in plates:
        ch = recording.plates[plate]
        for k, name in enumerate(CHANNELS):
            scale = STREAM_SIGN[k] * (1000.0 if name.startswith("m") else 1.0)
            values = np.asarray(ch[name], dtype=float)
            # Plate frame, moment at the surface: Mx - d*Fy, My + d*Fx (d = 0.030 m; Mx, My here are about the
            # reference d below the top). The relation holds in wire signs too, since Fy and Mx flip together.
            if name == "mx":
                values = values - MOMENT_REFERENCE_DEPTH_M * np.asarray(ch["fy"], dtype=float)
            elif name == "my":
                values = values + MOMENT_REFERENCE_DEPTH_M * np.asarray(ch["fx"], dtype=float)
            rows.append(np.nan_to_num(values) * scale)
            labels.append(f"{name[0].upper()}{name[1]}{plate}")
            units.append("Nmm" if name.startswith("m") else "N")
    c3d = ezc3d.c3d()
    c3d["parameters"]["POINT"]["RATE"]["value"] = [float(recording.rate_hz)]
    c3d["parameters"]["POINT"]["UNITS"]["value"] = ["mm"]
    c3d["parameters"]["ANALOG"]["RATE"]["value"] = [float(recording.rate_hz)]
    c3d["parameters"]["ANALOG"]["LABELS"]["value"] = labels
    c3d["parameters"]["ANALOG"]["UNITS"]["value"] = units
    _int_parameter(c3d, "FORCE_PLATFORM", "USED", [len(plates)])
    _int_parameter(c3d, "FORCE_PLATFORM", "TYPE", [2] * len(plates))
    _int_parameter(c3d, "FORCE_PLATFORM", "ZERO", [0, 0])
    corners = np.zeros((3, 4, len(plates)))
    origin = np.zeros((3, len(plates)))
    channel = np.zeros((6, len(plates)), dtype=int)
    for n, plate in enumerate(plates):
        corners[:, :, n] = np.asarray(recording.layout[plate], dtype=float).T
        origin[:, n] = ORIGIN_MM
        channel[:, n] = np.arange(6) + 6 * n + 1
    c3d.add_parameter("FORCE_PLATFORM", "CORNERS", corners)
    c3d.add_parameter("FORCE_PLATFORM", "ORIGIN", origin)
    _int_parameter(c3d, "FORCE_PLATFORM", "CHANNEL", [int(v) for v in channel.reshape(-1, order="F")], [6, len(plates)])
    if recording.events:
        times = np.array([[0.0, e.t - recording.t[0]] for e in recording.events]).T
        _int_parameter(c3d, "EVENT", "USED", [len(recording.events)])
        c3d.add_parameter("EVENT", "LABELS", [e.name for e in recording.events])
        c3d.add_parameter("EVENT", "CONTEXTS", ["General"] * len(recording.events))
        c3d.add_parameter("EVENT", "TIMES", times)
    c3d.add_parameter("MOVETRICS", "VOCABULARY", [VOCABULARY_VERSION])
    c3d.add_parameter("MOVETRICS", "MOMENT_REF", ["surface"])
    c3d.add_parameter("MOVETRICS", "FIRST_T", [float(recording.t[0])])
    c3d.add_parameter("MOVETRICS", "FIRMWARE", [str(recording.metadata.get("firmware", "unknown"))])
    analogs = np.asarray(rows)[np.newaxis, :, :]
    c3d["data"]["analogs"] = analogs
    c3d["data"]["points"] = np.zeros((4, 0, analogs.shape[2]))
    c3d.write(str(path))
    return [path]


# ----- OpenSim .mot ---------------------------------------------------------------------------------------------

def _lab_centre_m(corners: Sequence[Sequence[float]]) -> tuple[float, float]:
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return sum(xs) / 4000.0, sum(ys) / 4000.0


def write_mot(recording: Recording, path: str | Path, *, resample: bool = False,
              min_fz_n: float = 20.0, external_loads: dict[int, str] | None = None) -> Path:
    """OpenSim external loads (.mot): time, then per plate n the columns n_ground_force_vx/vy/vz,
    n_ground_force_px/py/pz, n_ground_torque_x/y/z, in OpenSim's ground frame (Y up): X = lab x, Y = lab z,
    Z = -lab y, metres and newtons. The point is the CoP in the lab (recording.layout), the torque the free
    moment about the vertical at the CoP. Below min_fz_n a plate's force and torque are 0 and its point is the
    plate centre (OpenSim must not see a CoP of noise over zero load).

    A recording with gaps is refused unless resample=True: then the rows are linearly interpolated onto the
    nominal grid and a column 'filled' is 1 inside a gap; a warning is the caller's to show. With external_loads
    {plate: body}, also writes <stem>_ExternalLoads.xml naming those bodies (for example {1: 'calcn_l', 2: 'calcn_r'}).
    """
    path = Path(path)
    rec = recording
    filled = [0] * len(rec.t)
    if len(rec.uniform_parts()) > 1:
        if not resample:
            raise GapError("the recording has gaps; OpenSim needs a uniform clock. Pass resample=True to fill them "
                           "by linear interpolation (marked in a 'filled' column) or split it first.")
        rec, filled = _resample(rec)
    plates = sorted(rec.plates)
    header = ["time"]
    for plate in plates:
        header += [f"{plate}_ground_force_v{a}" for a in "xyz"] + [f"{plate}_ground_force_p{a}" for a in "xyz"]
        header += [f"{plate}_ground_torque_{a}" for a in "xyz"]
    if any(filled):
        header.append("filled")
    cops = {plate: rec.cop(plate, min_fz_n) for plate in plates}
    lines = []
    for i, t in enumerate(rec.t):
        row = [t - rec.t[0]]
        for plate in plates:
            ch = rec.plates[plate]
            cx, cy = _lab_centre_m(rec.layout[plate])
            fx, fy, fz, mz = ch["fx"][i], ch["fy"][i], ch["fz"][i], ch["mz"][i]
            x, y = cops[plate][0][i], cops[plate][1][i]
            if math.isnan(fz) or math.isnan(x) or fz < min_fz_n:
                row += [0.0, 0.0, 0.0, cx, 0.0, -cy, 0.0, 0.0, 0.0]
                continue
            # Free moment about the vertical through the CoP: Tz = Mz - (x*Fy - y*Fx) (the vertical offset of the
            # moment reference does not enter the z component).
            tz = mz - (x * fy - y * fx)
            lab = (fx, fy, fz)
            row += [lab[0], lab[2], -lab[1], cx + x, 0.0, -(cy + y), 0.0, tz, 0.0]
        if any(filled):
            row.append(filled[i])
        lines.append("\t".join(f"{v:.6f}" if isinstance(v, float) else str(v) for v in row))
    text = (f"{path.stem}\nversion=1\nnRows={len(lines)}\nnColumns={len(header)}\ninDegrees=yes\n"
            "endheader\n" + "\t".join(header) + "\n" + "\n".join(lines) + "\n")
    path.write_text(text, encoding="utf-8")
    if external_loads:
        _write_external_loads(path, external_loads)
    return path


def _resample(rec: Recording) -> tuple[Recording, list[int]]:
    period = 1 / rec.rate_hz
    n = int(round((rec.t[-1] - rec.t[0]) / period)) + 1
    grid = [rec.t[0] + k * period for k in range(n)]
    filled: list[int] = []
    out = {plate: {name: [] for name in CHANNELS} for plate in rec.plates}
    j = 0
    for t in grid:
        while j + 1 < len(rec.t) and rec.t[j + 1] <= t + 1e-9:
            j += 1
        k = min(j + 1, len(rec.t) - 1)
        span = rec.t[k] - rec.t[j]
        w = 0.0 if span <= 0 else (t - rec.t[j]) / span
        filled.append(1 if span > GAP_FACTOR * period and 0 < w < 1 else 0)
        for plate, ch in rec.plates.items():
            for name in CHANNELS:
                a, b = ch[name][j], ch[name][k]
                out[plate][name].append(a + (b - a) * w)
    return Recording(rec.rate_hz, grid, out, rec.events, rec.gaps, rec.metadata, rec.layout), filled


def _write_external_loads(mot: Path, bodies: dict[int, str]) -> Path:
    forces = "".join(f"""
            <ExternalForce name="plate{plate}">
                <applied_to_body>{body}</applied_to_body>
                <force_expressed_in_body>ground</force_expressed_in_body>
                <point_expressed_in_body>ground</point_expressed_in_body>
                <force_identifier>{plate}_ground_force_v</force_identifier>
                <point_identifier>{plate}_ground_force_p</point_identifier>
                <torque_identifier>{plate}_ground_torque_</torque_identifier>
            </ExternalForce>""" for plate, body in sorted(bodies.items()))
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<OpenSimDocument Version="40000">
    <ExternalLoads name="{mot.stem}">
        <objects>{forces}
        </objects>
        <datafile>{mot.name}</datafile>
    </ExternalLoads>
</OpenSimDocument>
"""
    out = mot.with_name(f"{mot.stem}_ExternalLoads.xml")
    out.write_text(xml, encoding="utf-8")
    return out


def median_rate(t: Sequence[float]) -> float:
    steps = [b - a for a, b in zip(t, t[1:]) if b > a]
    return 1 / statistics.median(steps) if steps else 0.0
