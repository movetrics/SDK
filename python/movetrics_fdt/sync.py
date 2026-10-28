"""Time alignment: FDT clock to host clock, FDT to an external device, and two FDTs into one recording.

Every function works on the FDT's own stamps (docs/19: t from the 0.1 ms device clock), never on the time a
frame happened to arrive over USB: the FT232R delivers in bursts, so arrival jitters by up to 16 ms.

- ClockMap: device seconds to host seconds (for LSL), from (device, arrival) pairs. Ported from the FDT repo's
  LSL streamer (the Movetrics firmware repository (private), livestream.py): the lower envelope of arrival - device per block,
  then a least-squares line, which gives offset and drift. Its simulation there: 50 ppm drift, 0-16 ms jitter,
  60 s at 2,000 Hz, mapped times within 0.3 ms of the truth.
- align(): offset, drift and residual between edge times seen by two clocks (an EMG system's trigger log and the
  FDT's sync events), with edges matched even when one side missed some.
- merge(): two FDTs as one four-plate recording: B's samples moved onto A's clock by A's pulses seen on B's SYNC IN.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from .vocabulary import Event, Gap, Sample


class ClockMap:
    """Maps FDT device seconds to host seconds from (device, arrival) pairs.

    The frame that waited least in each block of block_seconds gives one point (device, arrival - device); a
    least-squares line through the last window_blocks points gives offset and drift. Until three blocks exist the
    lowest offset seen so far is used with zero drift, so treat the first three seconds as warm-up.
    """

    def __init__(self, *, block_seconds: float = 1.0, window_blocks: int = 300, latency_seconds: float = 0.0) -> None:
        if not block_seconds > 0 or window_blocks < 3:
            raise ValueError("block_seconds must be positive and window_blocks at least 3")
        self.block_seconds, self.window_blocks, self.latency_seconds = block_seconds, window_blocks, latency_seconds
        self.reset()

    def reset(self) -> None:
        self._points: deque[tuple[float, float]] = deque(maxlen=self.window_blocks)
        self._block: int | None = None
        self._block_min: tuple[float, float] | None = None
        self._floor = math.inf
        self._fit: tuple[float, float, float] | None = None  # reference device s, offset there, slope
        self.residual_seconds: float | None = None

    @property
    def drift_ppm(self) -> float | None:
        return None if self._fit is None else self._fit[2] * 1e6

    def observe(self, device_s: float, arrival_s: float) -> None:
        diff = arrival_s - device_s
        block = math.floor(device_s / self.block_seconds)
        if block != self._block:
            if self._block_min is not None:
                self._close_block()
            self._block, self._block_min = block, (device_s, diff)
        elif self._block_min is not None and diff < self._block_min[1]:
            self._block_min = (device_s, diff)
        self._floor = min(self._floor, diff)

    def _close_block(self) -> None:
        assert self._block_min is not None
        self._points.append(self._block_min)
        if len(self._points) >= 3:
            fit = _line(self._points)
            self._fit = fit[:3]
            self.residual_seconds = fit[3]

    def to_host(self, device_s: float) -> float:
        if self._fit is None:
            offset = self._floor
        else:
            reference, offset_at_reference, slope = self._fit
            offset = offset_at_reference + slope * (device_s - reference)
        return device_s + offset - self.latency_seconds


def _line(points: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Least squares y = mean_y + slope * (x - mean_x): (mean_x, mean_y, slope, rms residual)."""
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sxx if sxx > 0 else 0.0
    residual = math.sqrt(sum((y - (mean_y + slope * (x - mean_x))) ** 2 for x, y in points) / n)
    return mean_x, mean_y, slope, residual


@dataclass(frozen=True)
class Alignment:
    """t_other = t_fdt + offset_s + drift * (t_fdt - reference_s), drift = drift_ppm * 1e-6.

    pairs: how many edges were matched; residual_s: rms of the matched edges around the line; unmatched: edges
    on either side with no partner (a missed edge on one device shows up here instead of shifting everything)."""

    offset_s: float
    drift_ppm: float
    reference_s: float
    residual_s: float
    pairs: int
    unmatched: int

    def to_other(self, t_fdt: float) -> float:
        return t_fdt + self.offset_s + self.drift_ppm * 1e-6 * (t_fdt - self.reference_s)

    def to_fdt(self, t_other: float) -> float:
        scale = 1 + self.drift_ppm * 1e-6
        return (t_other - self.offset_s + self.drift_ppm * 1e-6 * self.reference_s) / scale


def align(fdt_times: Sequence[float], other_times: Sequence[float], *, tolerance_s: float | None = None) -> Alignment:
    """Align two lists of edge times of the same pulses, seen on the FDT clock and on another clock.

    The first offset is guessed from every pairing of the first few edges (the one that makes most later edges
    agree wins), then each FDT edge is matched to the nearest other edge within tolerance_s (default: a quarter of
    the median pulse interval) and a line is fitted through the matched pairs. Needs at least two matched edges.
    """
    a = sorted(fdt_times)
    b = sorted(other_times)
    if len(a) < 2 or len(b) < 2:
        raise ValueError("align needs at least two edges on each clock")
    intervals = [y - x for x, y in zip(a, a[1:]) if y > x]
    period = sorted(intervals)[len(intervals) // 2]
    tol = tolerance_s if tolerance_s is not None else period / 4

    def matches(offset: float) -> list[tuple[float, float]]:
        pairs = []
        j = 0
        for t in a:
            target = t + offset
            while j + 1 < len(b) and abs(b[j + 1] - target) <= abs(b[j] - target):
                j += 1
            if abs(b[j] - target) <= tol:
                pairs.append((t, b[j] - t))
        return pairs

    candidates = [y - x for x in a[:5] for y in b[:5]]
    best = max(candidates, key=lambda offset: len(matches(offset)))
    pairs = matches(best)
    if len(pairs) < 2:
        raise ValueError("fewer than two edges could be matched; check that both lists hold the same pulses")
    # Refit once around the line, which removes the drift's pull on the matching over long sessions.
    reference, offset, slope, _ = _line(pairs)
    pairs = [(t, d) for t, d in matches(offset) if abs(d - (offset + slope * (t - reference))) <= tol]
    reference, offset, slope, residual = _line(pairs)
    matched = len(pairs)
    return Alignment(offset_s=offset, drift_ppm=slope * 1e6, reference_s=reference,
                     residual_s=residual, pairs=matched, unmatched=(len(a) - matched) + (len(b) - matched))


def edge_times(items: Iterable[Sample | Event | Gap], name: str) -> list[float]:
    """t of every event with this name (for example 'sync_in_rise' or 'sync_out_rise')."""
    return [item.t for item in items if isinstance(item, Event) and item.name == name]


def merge(fdt_a: Sequence[Sample | Event | Gap], fdt_b: Sequence[Sample | Event | Gap], *,
          a_edge: str = "sync_out_rise", b_edge: str = "sync_in_rise",
          plate_offset: int = 2) -> tuple[list[Sample | Event | Gap], Alignment]:
    """Two FDTs as one recording on A's clock: FDT A drives SYNC OUT (pulse train), FDT B sees it on SYNC IN with
    event frames on. B's samples, events and gaps move onto A's time base and its plates become 3 and 4.

    Returns the merged items in time order and the alignment (drift in ppm, residual), which a caller should show:
    a residual above half a sample period means the pulses were not seen cleanly.
    """
    alignment = align(edge_times(fdt_b, b_edge), edge_times(fdt_a, a_edge))
    moved: list[Sample | Event | Gap] = []
    for item in fdt_b:
        if isinstance(item, Sample):
            moved.append(replace(item, t=alignment.to_other(item.t), plate=item.plate + plate_offset))
        elif isinstance(item, Event):
            moved.append(replace(item, t=alignment.to_other(item.t),
                                 source=item.source + plate_offset if item.name.startswith('saturation') else item.source))
        else:
            moved.append(replace(item, plate=item.plate + plate_offset, start_t=alignment.to_other(item.start_t),
                                 end_t=alignment.to_other(item.end_t)))

    def when(item: Sample | Event | Gap) -> float:
        return item.start_t if isinstance(item, Gap) else item.t

    return sorted(list(fdt_a) + moved, key=when), alignment
