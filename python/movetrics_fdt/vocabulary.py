"""The shared vocabulary: one set of names, units and frames for every Movetrics client, file and API.

The contract is contracts/vocabulary.v1.json (machine-readable) and docs/19-vocabulary-and-units.md. In
short: t in s from the FDT clock; fx fy fz in N; mx my mz in N*m about the plate's moment reference 30 mm below the
top; cop_x cop_y in m from the plate centre; plate 1 or 2; the wire integers stay available as raw.

SampleConverter turns decoded wire frames into Samples, Events and Gaps. It drops the stamp-0 placeholders after
START, unwraps the uint32 stamp, applies Studio's sign map (so a live sample carries the same numbers as the same
sample in a Studio export) and reports every hole in the stream instead of hiding it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Final

from .stream import EventFrame, StreamFrame

TICKS_PER_SECOND: Final = 10_000
STAMP_MODULUS: Final = 1 << 32
MOMENT_REFERENCE_DEPTH_M: Final = 0.030
COP_MIN_FZ_N: Final = 50.0
# Plate-frame value = sign * wire value: Studio's QuadrantTransform 4,3,2,1 negates Fy and Mx (Studio config.ini,
# docs/STUDIO_COMPATIBILITY.md). From configuration, not yet checked with one known off-centre load both ways.
STREAM_SIGN: Final = (1, -1, 1, -1, 1, 1)
CHANNELS: Final = ("fx", "fy", "fz", "mx", "my", "mz")
# Plate centres in the pair frame (Studio's comb_ frame), fitted on the 14 Oct 2026 export (residual 0.37 mm).
PAIR_CENTRE_X_M: Final = {1: -0.175, 2: 0.175}
# A step longer than this many nominal periods is a gap.
GAP_FACTOR: Final = 1.5


def plate_cop(fx: float, fy: float, fz: float, mx: float, my: float,
              min_fz_n: float = COP_MIN_FZ_N, depth_m: float = MOMENT_REFERENCE_DEPTH_M) -> tuple[float, float]:
    """CoP (x, y) in m from the plate centre, plate frame. NaN below min_fz_n.

    x = (-my - d*fx) / fz, y = (-mx + d*fy) / fz with d = 0.030 m reproduces Studio's CoP columns to 0.28 mm rms on
    the 14 Oct 2026 export (measured)."""
    if not fz >= min_fz_n:
        return math.nan, math.nan
    return (-my - depth_m * fx) / fz, (-mx + depth_m * fy) / fz


@dataclass(frozen=True)
class Sample:
    """One plate at one instant, in SI units and the plate frame."""

    t: float
    plate: int
    fx: float
    fy: float
    fz: float
    mx: float
    my: float
    mz: float
    cop_x: float
    cop_y: float
    stamp: int
    raw: tuple[int, int, int, int, int, int] = field(repr=False)


@dataclass(frozen=True)
class Event:
    """Something that happened at t: a sync edge, a trigger start, saturation (from the FDT), or a gap or note
    (from the host). type and name follow vocabulary.v1.json "events"."""

    t: float
    type: int
    name: str
    source: int = 0
    count: int = 0
    detail: int = 0
    stamp: int = 0
    offset_us: int = 0


@dataclass(frozen=True)
class Gap:
    """A hole in one plate's stream: no sample between start_t and end_t, missing whole periods."""

    plate: int
    start_t: float
    end_t: float
    missing: int


GAP_EVENT: Final = 100
NOTE_EVENT: Final = 101


class SampleConverter:
    """Wire frames in, Samples / Events / Gaps out. One converter per stream (create a new one after each START).

    rate_hz is the nominal frames per second per plate (set_rate). When it is None the period is learnt as the
    smallest step seen per plate, which is right as soon as two consecutive frames arrived without a hole.
    """

    def __init__(self, rate_hz: float | None = None, *, cop_min_fz_n: float = COP_MIN_FZ_N) -> None:
        self._period = TICKS_PER_SECOND / rate_hz if rate_hz else None
        self._cop_min = cop_min_fz_n
        self._last: dict[int, int] = {}
        self._learnt: dict[int, int] = {}
        self._high = 0
        self._previous_wire = 0
        self.gaps: list[Gap] = []
        self.placeholders = 0

    def _unwrap(self, stamp: int) -> int:
        # The wire stamp is uint32; a jump back by more than half the range is a wrap, not disorder.
        if stamp < self._previous_wire and self._previous_wire - stamp > STAMP_MODULUS // 2:
            self._high += STAMP_MODULUS
        self._previous_wire = stamp
        return self._high + stamp

    def push(self, item: StreamFrame | EventFrame) -> list[Sample | Event | Gap]:
        """Convert one frame. Returns nothing for a placeholder, a Gap then the Sample after a hole."""
        if isinstance(item, EventFrame):
            stamp = self._unwrap(item.timeStamp)
            # The edge lies offset_us after the start of its tick, so t is finer than the 0.1 ms stamp.
            return [Event(t=stamp / TICKS_PER_SECOND + item.offset_us / 1e6, type=item.event_type, name=item.name,
                          source=item.source, count=item.count, detail=item.detail, stamp=stamp,
                          offset_us=item.offset_us)]
        if item.is_placeholder:
            self.placeholders += 1
            return []
        stamp = self._unwrap(item.timeStamp)
        plate = item.platform_address
        out: list[Sample | Event | Gap] = []
        last = self._last.get(plate)
        if last is not None:
            step = stamp - last
            if step > 0 and self._period is None:
                self._learnt[plate] = min(step, self._learnt.get(plate, step))
            period = self._period or self._learnt.get(plate)
            if period and step > GAP_FACTOR * period:
                gap = Gap(plate=plate, start_t=last / TICKS_PER_SECOND, end_t=stamp / TICKS_PER_SECOND,
                          missing=round(step / period) - 1)
                self.gaps.append(gap)
                out.append(gap)
        self._last[plate] = stamp
        raw = (item.forceX, item.forceY, item.forceZ, item.momentX, item.momentY, item.momentZ)
        fx, fy, fz, mx, my, mz = (float(sign * value) for sign, value in zip(STREAM_SIGN, raw))
        cop_x, cop_y = plate_cop(fx, fy, fz, mx, my, self._cop_min)
        out.append(Sample(t=stamp / TICKS_PER_SECOND, plate=plate, fx=fx, fy=fy, fz=fz, mx=mx, my=my, mz=mz,
                          cop_x=cop_x, cop_y=cop_y, stamp=stamp, raw=raw))
        return out

    def convert(self, items: Iterable[StreamFrame | EventFrame]) -> Iterator[Sample | Event | Gap]:
        for item in items:
            yield from self.push(item)


def wide_columns(plates: Iterable[int] = (1, 2), *, combined: bool = True) -> list[str]:
    """Column names of the wide table: t, p1_fx ... p1_cop_y, p2_..., comb_fx ... comb_cop_y."""
    names = ["t"]
    prefixes = [f"p{plate}" for plate in plates] + (["comb"] if combined else [])
    for prefix in prefixes:
        names += [f"{prefix}_{name}" for name in CHANNELS + ("cop_x", "cop_y")]
    return names


def combine(samples: dict[int, Sample], *, cop_min_fz_n: float = COP_MIN_FZ_N) -> dict[str, float]:
    """Sum of the plates of one instant in the pair frame (Studio's comb_ columns): forces add, moments move to the
    pair origin, CoP from the combined wrench."""
    fx = sum(s.fx for s in samples.values())
    fy = sum(s.fy for s in samples.values())
    fz = sum(s.fz for s in samples.values())
    mx = my = mz = 0.0
    for plate, s in samples.items():
        cx = PAIR_CENTRE_X_M.get(plate, 0.0)
        # Moment about the pair origin: M + r x F with r = (cx, 0, 0) from the pair origin to the plate centre.
        mx += s.mx
        my += s.my - cx * s.fz
        mz += s.mz + cx * s.fy
    # The combined CoP follows from the combined wrench like a plate's, so a lightly loaded plate still counts.
    cop_x, cop_y = plate_cop(fx, fy, fz, mx, my, cop_min_fz_n)
    return {"fx": fx, "fy": fy, "fz": fz, "mx": mx, "my": my, "mz": mz, "cop_x": cop_x, "cop_y": cop_y}
