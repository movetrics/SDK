"""Plate samples on PTP time (IEEE 1588, Precision Time Protocol): docs/25-ptp.md.

The FDT has no network port, so it cannot be a PTP clock itself: it reaches a computer over USB or Bluetooth, and
PTP needs Ethernet with hardware timestamps. Two routes still put every sample on a PTP network's time base.

- **Pulse** (sample-accurate, the route to use): a device on the PTP network sends a pulse at known PTP times into
  SYNC IN, usually one per second at the start of each second (a pulse-per-second output), with EVENT_FRAMES on. The
  FDT stamps each rising edge on its own clock to the microsecond (docs/05 section 13), so every pulse is a pair
  (FDT time, PTP time). PulseMap fits those pairs; a sample's PTP time comes from the pairs around it. The host only
  has to know PTP time to within a quarter of the pulse period, to tell which second a pulse marks; NTP is enough.
- **Host** (no cable): the FDT's stamps are mapped onto the host's clock with the clock map of the LSL bridge
  (sync.ClockMap), and that clock is assumed to follow PTP (ptp4l and phc2sys on Linux, the PTP client of Windows).
  Its error is the host's own PTP error, plus the clock map's, plus a constant the map cannot see: plate frames leave
  the FDT 10 to 15 ms after their stamp (docs/05 section 4.8, from code), plus the USB delay. latency_s subtracts a
  measured value; PtpRecorder measures it whenever pulses are present (PtpMap.host_minus_pulse_s).

PTP time is TAI: whole nanoseconds since 1970-01-01 00:00:00 TAI, as PTP and GigE Vision cameras count it. TAI is
UTC plus 37 s since 1 January 2017 (utc_offset_s). A pulse per second marks whole seconds of both, since the
difference is a whole number of seconds.

Nothing here has run with a real FDT or a PTP network yet; the tests run the simulator and synthetic clocks.
"""

from __future__ import annotations

import asyncio
import bisect
import csv
import json
import math
import shutil
import statistics
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from .sync import ClockMap, _line
from .vocabulary import Event, Gap, Sample

NS: Final = 1_000_000_000
TAI_MINUS_UTC_S: Final = 37  # since 2017-01-01 (IERS Bulletin C); PTP announces the current value as currentUtcOffset


def host_tai_ns(utc_offset_s: int = TAI_MINUS_UTC_S) -> int:
    """The host's wall clock (UTC) as TAI nanoseconds. On a host that follows PTP, this is PTP time."""
    return time.time_ns() + utc_offset_s * NS


def kernel_tai_ns() -> int | None:
    """Linux CLOCK_TAI, or None where it does not exist or its offset to UTC was never set (it then equals UTC, and
    taking it for TAI would be 37 s wrong)."""
    clock = getattr(time, "CLOCK_TAI", None)
    if clock is None:
        return None
    tai = time.clock_gettime_ns(clock)
    return None if abs(tai - time.time_ns()) < NS // 2 else tai


def make_host_clock(kind: str = "utc", utc_offset_s: int = TAI_MINUS_UTC_S) -> Callable[[], int]:
    """A function giving TAI nanoseconds from the host. kind 'utc': the wall clock plus utc_offset_s (any system);
    'tai': Linux CLOCK_TAI, refused when the kernel's TAI offset is not set."""
    if kind == "utc":
        return lambda: host_tai_ns(utc_offset_s)
    if kind == "tai":
        if kernel_tai_ns() is None:
            raise ValueError("CLOCK_TAI is not available or its offset is not set on this host; use the utc clock "
                             "(the wall clock plus the UTC offset) instead")
        clock = time.CLOCK_TAI  # type: ignore[attr-defined]
        return lambda: time.clock_gettime_ns(clock)
    raise ValueError(f"unknown host clock {kind!r}: use 'utc' or 'tai'")


# ----- pulse route --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Anchor:
    """One pulse: its rising edge on the FDT clock, the PTP time it marks, and how far the raw edge lay from the
    smoothed line through its neighbours (residual_s, the edge's timing jitter as the FDT saw it)."""

    fdt_s: float
    ptp_ns: int
    residual_s: float


@dataclass(frozen=True)
class PulseMap:
    """FDT seconds to PTP nanoseconds from pulses at known PTP times (see pulse_map).

    Between the first and last anchor a time is placed by linear interpolation between the smoothed anchors around
    it; outside, by the line through the nearest end anchors, which covers() reports as False.

    drift_ppm: how far the PTP-minus-FDT offset grows per second of FDT time, in ppm (negative: the FDT runs fast),
    as in sync.Alignment. jitter_rms_s, jitter_max_s: the raw edges around the smoothed line. missing: pulse slots
    between the first and the last anchor with no accepted edge. rejected: FDT times of edges not used (noise, a
    second edge in one slot, an edge too far from the line). host_offset_s: the median of host minus PTP at the
    pulses, how far the coarse clock was off; above a quarter of the period a pulse can be given the wrong second,
    and warnings says so.
    """

    anchors: tuple[Anchor, ...]
    smoothed_ns: tuple[int, ...]
    period_s: float
    drift_ppm: float
    jitter_rms_s: float
    jitter_max_s: float
    missing: int
    rejected: tuple[float, ...]
    host_offset_s: float
    warnings: tuple[str, ...] = ()

    def covers(self, t_fdt: float) -> bool:
        return self.anchors[0].fdt_s <= t_fdt <= self.anchors[-1].fdt_s

    def to_ptp_ns(self, t_fdt: float) -> int:
        xs = [a.fdt_s for a in self.anchors]  # small; the recorder calls mapper() for long runs
        return _interpolate(xs, self.smoothed_ns, t_fdt)

    def mapper(self) -> Callable[[float], int]:
        """A fast to_ptp_ns for many calls (the anchor times are listed once)."""
        xs = [a.fdt_s for a in self.anchors]
        ys = self.smoothed_ns
        return lambda t: _interpolate(xs, ys, t)


def _interpolate(xs: Sequence[float], ys: Sequence[int], t: float) -> int:
    n = len(xs)
    i = bisect.bisect_right(xs, t)
    if i <= 0:
        a, b = 0, 1
    elif i >= n:
        a, b = n - 2, n - 1
    else:
        a, b = i - 1, i
    # Differences in ns fit a float exactly enough (a pulse period is 1e9 ns); only the base stays an int.
    slope = (ys[b] - ys[a]) / (xs[b] - xs[a])
    return ys[a] + round((t - xs[a]) * slope)


def pulse_map(edges_fdt_s: Sequence[float], coarse_ptp_ns: Callable[[float], int], *, period_s: float = 1.0,
              phase_ns: int = 0, tolerance_s: float = 0.0005, smooth: int = 5) -> PulseMap:
    """Fit FDT edge times of pulses sent at PTP times phase_ns + n * period_s (n whole) to those PTP times.

    coarse_ptp_ns gives an estimate of PTP time for an FDT time (the host clock map); it only chooses n, so it must
    be within a quarter of the period. An edge farther than tolerance_s from the line through its neighbours is
    rejected, as is a second edge for the same n (the one nearer the line stays). smooth: each anchor's PTP time is
    taken from a line through it and up to smooth anchors on each side, which averages the edge jitter down; the
    crystal does not bend measurably over that many seconds. Needs two accepted pulses.
    """
    if not period_s > 0:
        raise ValueError("period_s must be positive")
    period_ns = round(period_s * NS)
    edges = sorted(set(edges_fdt_s))
    if len(edges) < 2:
        raise ValueError("at least two pulse edges are needed; is the pulse wired to SYNC IN and EVENT_FRAMES on?")
    slots: list[tuple[float, int, int]] = []  # (fdt s, n, coarse - ptp in ns)
    for t in edges:
        coarse = coarse_ptp_ns(t)
        n = (coarse - phase_ns + period_ns // 2) // period_ns
        slots.append((t, n, coarse - (phase_ns + n * period_ns)))
    base_n = slots[0][1]

    def y_of(n: int) -> float:  # PTP seconds relative to the first slot, exact for whole periods
        return (n - base_n) * period_ns / NS

    x0 = slots[0][0]
    points = [(t - x0, y_of(n)) for t, n, _ in slots]
    # 1. A robust start: the host clock follows the FDT's drift, so every real pulse lies about the same distance
    #    from its whole second on the host clock (its constant delay), however long the recording. Keep the edges
    #    within a quarter period of the median distance (noise at a random phase mostly goes here), then a
    #    least-squares line.
    typical = statistics.median(d for _, _, d in slots)
    keep = [i for i, (_, _, d) in enumerate(slots) if abs(d - typical) < period_ns / 4]
    if len(keep) < 2:
        raise ValueError("fewer than two edges lie on a line of pulses; check the pulse period and phase")
    mean_x, mean_y, slope, _ = _line([points[i] for i in keep])
    coarse_tol = max(20 * tolerance_s, 1e-3)
    keep = [i for i in keep if abs(points[i][1] - (mean_y + slope * (points[i][0] - mean_x))) <= coarse_tol]
    # 2. One edge per slot, the one nearest the line.
    best: dict[int, int] = {}
    for i in keep:
        n = slots[i][1]
        r = abs(points[i][1] - (mean_y + slope * (points[i][0] - mean_x)))
        if n not in best or r < abs(points[best[n]][1] - (mean_y + slope * (points[best[n]][0] - mean_x))):
            best[n] = i
    keep = sorted(best.values())
    # 3. Leave-one-out against the neighbours: an edge that disagrees with the line through the others near it is out.
    for _ in range(2):
        if len(keep) < 3:
            break
        kept = []
        for j, i in enumerate(keep):
            others = [points[k] for k in keep[max(0, j - smooth):j] + keep[j + 1:j + 1 + smooth]]
            if len(others) < 2:
                kept.append(i)
                continue
            mx, my, s, _ = _line(others)
            if abs(points[i][1] - (my + s * (points[i][0] - mx))) <= tolerance_s:
                kept.append(i)
        if len(kept) == len(keep) or len(kept) < 2:
            keep = kept if len(kept) >= 2 else keep
            break
        keep = kept
    if len(keep) < 2:
        raise ValueError("fewer than two pulses passed the checks")
    accepted = [points[i] for i in keep]
    # 4. Smoothed anchors: each from the line through it and its neighbours.
    smoothed: list[float] = []
    for j in range(len(accepted)):
        window = accepted[max(0, j - smooth):j + smooth + 1]
        mx, my, s, _ = _line(window) if len(window) >= 2 else (accepted[j][0], accepted[j][1], 1.0, 0.0)
        smoothed.append(my + s * (accepted[j][0] - mx))
    residuals = [y - z for (_, y), z in zip(accepted, smoothed)]
    base_ptp = phase_ns + base_n * period_ns
    anchors = tuple(Anchor(fdt_s=slots[i][0], ptp_ns=phase_ns + slots[i][1] * period_ns, residual_s=r)
                    for i, r in zip(keep, residuals))
    smoothed_ns = tuple(base_ptp + round(z * NS) for z in smoothed)
    _, _, full_slope, _ = _line(accepted)
    accepted_ns = {slots[i][1] for i in keep}
    missing = (max(accepted_ns) - min(accepted_ns) + 1) - len(accepted_ns)
    host_offset_s = statistics.median(slots[i][2] for i in keep) / NS
    warnings = []
    if abs(host_offset_s) > period_s / 4:
        warnings.append(f"the host clock was {host_offset_s * 1000:.0f} ms from PTP time at the pulses, more than a quarter "
                        f"of the {period_s:g} s period: pulses may be given the wrong second; synchronise the host clock")
    rejected = tuple(slots[i][0] for i in range(len(slots)) if i not in set(keep))
    return PulseMap(anchors=anchors, smoothed_ns=smoothed_ns, period_s=period_s, drift_ppm=(full_slope - 1) * 1e6,
                    jitter_rms_s=math.sqrt(sum(r * r for r in residuals) / len(residuals)),
                    jitter_max_s=max(abs(r) for r in residuals), missing=missing, rejected=rejected,
                    host_offset_s=host_offset_s, warnings=tuple(warnings))


# ----- host route ---------------------------------------------------------------------------------------------------

class HostMap:
    """FDT seconds to PTP nanoseconds through the host clock, by the LSL bridge's clock map (docs/22, 'Clock mapping,
    exactly') fitted over the whole recording. Feed it plate samples only: event frames leave the FDT at once, plate
    frames 10 to 15 ms after their stamp, and mixing them would bend the map."""

    def __init__(self, *, latency_s: float = 0.0, block_seconds: float = 1.0) -> None:
        self.latency_s = latency_s
        self._map = ClockMap(block_seconds=block_seconds, window_blocks=1_000_000, latency_seconds=latency_s)
        self._epoch_ns: int | None = None
        self.pairs = 0

    def observe(self, device_s: float, host_ns: int) -> None:
        if self._epoch_ns is None:
            self._epoch_ns = host_ns - host_ns % NS  # seconds relative to this keep a float exact to well under 1 us
        self._map.observe(device_s, (host_ns - self._epoch_ns) / NS)
        self.pairs += 1

    @property
    def ready(self) -> bool:
        return self._epoch_ns is not None

    @property
    def drift_ppm(self) -> float | None:
        return self._map.drift_ppm

    @property
    def residual_s(self) -> float | None:
        return self._map.residual_seconds

    def to_ptp_ns(self, t_fdt: float) -> int:
        if self._epoch_ns is None:
            raise ValueError("no (FDT time, host time) pair observed yet")
        return self._epoch_ns + round(self._map.to_host(t_fdt) * NS)

    def finish(self) -> None:
        """Close the last block, so the fit uses every second of the recording."""
        if self._map._block_min is not None:  # noqa: SLF001 - same package
            self._map._close_block()  # noqa: SLF001
            self._map._block_min = None  # noqa: SLF001


# ----- both, for a recording ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PtpMap:
    """The time base chosen for a recording: 'pulse' when at least two pulses passed, else 'host'.

    host_minus_pulse_s (pulse route only): the host route's error at the pulses, its mean and spread. With latency_s
    0 its mean is the constant the host route needs as latency_s for this FDT, firmware, rate and computer.
    """

    method: str
    pulse: PulseMap | None
    host: HostMap
    host_minus_pulse_s: tuple[float, float] | None
    warnings: tuple[str, ...]

    def mapper(self) -> Callable[[float], int]:
        return self.pulse.mapper() if self.pulse is not None else self.host.to_ptp_ns

    def quality(self) -> dict[str, object]:
        """What the JSON beside a recording says about its time base: method, numbers, warnings."""
        out: dict[str, object] = {"method": self.method, "warnings": list(self.warnings)}
        if self.pulse is not None:
            p = self.pulse
            out["pulse"] = {"pulses": len(p.anchors), "missing": p.missing, "rejected": len(p.rejected),
                            "period_s": p.period_s, "drift_ppm": round(p.drift_ppm, 3),
                            "edge_jitter_rms_us": round(p.jitter_rms_s * 1e6, 2),
                            "edge_jitter_max_us": round(p.jitter_max_s * 1e6, 2),
                            "host_offset_ms": round(p.host_offset_s * 1000, 3),
                            "first_fdt_s": p.anchors[0].fdt_s, "last_fdt_s": p.anchors[-1].fdt_s}
        if self.host.ready:
            out["host"] = {"latency_s": self.host.latency_s, "drift_ppm": _round(self.host.drift_ppm, 3),
                           "fit_residual_ms": _round(None if self.host.residual_s is None else self.host.residual_s * 1000, 3)}
        if self.host_minus_pulse_s is not None:
            mean, sd = self.host_minus_pulse_s
            out["host_minus_pulse_ms"] = {"mean": round(mean * 1000, 3), "sd": round(sd * 1000, 3)}
        return out


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


@dataclass
class PtpRecorder:
    """Collects what a recording needs for its PTP time base: (FDT time, host time) of each plate sample and the FDT
    times of the pulse edges. push() every item of FdtClient.samples() as it arrives; finish() returns the map.

    clock: TAI nanoseconds from the host (make_host_clock). edge: the event that marks a pulse. period_s, phase_ns:
    when the pulses are sent in PTP time (default: every whole second). latency_s: for the host route.
    """

    clock: Callable[[], int] = host_tai_ns
    edge: str = "sync_in_rise"
    period_s: float = 1.0
    phase_ns: int = 0
    tolerance_s: float = 0.0005
    latency_s: float = 0.0
    edges: list[float] = field(default_factory=list)
    host: HostMap = field(init=False)

    def __post_init__(self) -> None:
        self.host = HostMap(latency_s=self.latency_s)

    def push(self, item: Sample | Event | Gap, host_ns: int | None = None) -> None:
        if isinstance(item, Sample):
            self.host.observe(item.t, self.clock() if host_ns is None else host_ns)
        elif isinstance(item, Event) and item.name == self.edge:
            self.edges.append(item.t)

    def finish(self) -> PtpMap:
        self.host.finish()
        if not self.host.ready:
            raise ValueError("no plate sample was recorded")
        warnings: list[str] = []
        pulse = None
        if len(self.edges) >= 2:
            try:
                pulse = pulse_map(self.edges, self.host.to_ptp_ns, period_s=self.period_s, phase_ns=self.phase_ns,
                                  tolerance_s=self.tolerance_s)
                warnings += pulse.warnings
            except ValueError as error:
                warnings.append(f"pulses not usable ({error}); the time base falls back to the host clock")
        elif self.edges:
            warnings.append("only one pulse edge was seen; the time base falls back to the host clock")
        else:
            warnings.append("no pulse on SYNC IN: the time base is the host clock (host route), accurate only as far "
                            "as the host follows PTP and latency_s is measured")
        difference = None
        if pulse is not None:
            # Compare the host clock map with the pulse map at the anchors (latency_s already applied to the host one).
            diffs = [(self.host.to_ptp_ns(a.fdt_s) - z) / NS for a, z in zip(pulse.anchors, pulse.smoothed_ns)]
            difference = (statistics.fmean(diffs), statistics.pstdev(diffs) if len(diffs) > 1 else 0.0)
        return PtpMap(method="pulse" if pulse is not None else "host", pulse=pulse, host=self.host,
                      host_minus_pulse_s=difference, warnings=tuple(warnings))


# ----- the host's PTP state (linuxptp) ------------------------------------------------------------------------------

@dataclass(frozen=True)
class PtpStatus:
    """What ptp4l says through pmc (GET TIME_STATUS_NP): whether a grandmaster is present, which one, and the offset
    of this computer's network card clock from it. It says nothing about the system clock, which phc2sys steers."""

    gm_present: bool
    gm_identity: str
    master_offset_ns: int
    port_identity: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"gm_present": self.gm_present, "gm_identity": self.gm_identity,
                "master_offset_ns": self.master_offset_ns, "port_identity": self.port_identity}


def parse_pmc_time_status(text: str) -> PtpStatus | None:
    """Parse the output of pmc -u -b 0 'GET TIME_STATUS_NP' (linuxptp). None when no response is in it."""
    if "TIME_STATUS_NP" not in text or "RESPONSE" not in text:
        return None
    values: dict[str, str] = {}
    port = ""
    for line in text.splitlines():
        parts = line.split()
        if "RESPONSE" in parts and parts:
            port = parts[0]
        elif len(parts) == 2:
            values[parts[0]] = parts[1]
    try:
        return PtpStatus(gm_present=values.get("gmPresent", "false").lower() == "true",
                         gm_identity=values.get("gmIdentity", ""), master_offset_ns=int(values["master_offset"]),
                         port_identity=port)
    except (KeyError, ValueError):
        return None


def query_pmc(timeout_s: float = 3.0) -> PtpStatus | None:
    """Ask the local ptp4l through pmc (Linux, linuxptp). None where pmc is missing or no ptp4l answers."""
    if sys.platform != "linux" or shutil.which("pmc") is None:
        return None
    try:
        done = subprocess.run(["pmc", "-u", "-b", "0", "GET TIME_STATUS_NP"], capture_output=True, text=True,
                              timeout=timeout_s, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_pmc_time_status(done.stdout)


# ----- a recording on PTP time --------------------------------------------------------------------------------------

PTP_CSV_COLUMNS: Final = ("t_ptp_ns", "t", "plate", "fx", "fy", "fz", "mx", "my", "mz", "cop_x", "cop_y")


async def record_ptp(items: AsyncIterator[Sample | Event | Gap], recorder: PtpRecorder, out: str | Path, *,
                     seconds: float = 0.0, metadata: dict[str, object] | None = None,
                     log: Callable[[str], None] | None = None) -> tuple[Path, PtpMap]:
    """Record a stream to out (CSV, one row per plate sample) with each sample's PTP time, and out + '.json' with
    the time base, its quality, the events and gaps.

    Rows are written to out + '.partial' as they arrive (FDT time only), since PTP times are known only once the
    pulses after them are in; finish() then writes the final file and removes the partial one. seconds: stop after
    this much FDT time (0: until the iterator ends or Ctrl-C).
    """
    out = Path(out)
    partial = out.with_name(out.name + ".partial")
    events: list[Event] = []
    gaps: list[Gap] = []
    rows = 0
    last_report = 0.0
    with partial.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        try:
            async for item in items:
                recorder.push(item)
                if isinstance(item, Sample):
                    writer.writerow((repr(item.t), item.plate, *(repr(float(v)) for v in (
                        item.fx, item.fy, item.fz, item.mx, item.my, item.mz)), _cell(item.cop_x), _cell(item.cop_y)))
                    rows += 1
                    if log is not None and item.t - last_report >= 10:
                        last_report = item.t
                        log(f"{item.t:7.1f} s  {rows} samples, {len(recorder.edges)} pulses")
                    if seconds and item.t >= seconds:
                        break
                elif isinstance(item, Event):
                    events.append(item)
                else:
                    gaps.append(item)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
    ptp_map = recorder.finish()
    to_ptp = ptp_map.mapper()
    with partial.open(newline="", encoding="utf-8") as source, out.open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(PTP_CSV_COLUMNS)
        for row in csv.reader(source):
            writer.writerow((to_ptp(float(row[0])), *row))
    partial.unlink()
    sidecar = {
        "time_base": "t_ptp_ns: PTP time (TAI), whole nanoseconds since 1970-01-01 00:00:00 TAI; t: FDT seconds",
        "units": {"t": "s", "fx": "N", "fy": "N", "fz": "N", "mx": "N*m", "my": "N*m", "mz": "N*m", "cop_x": "m",
                  "cop_y": "m"},
        "rows": rows,
        **ptp_map.quality(),
        "events": [{"name": e.name, "t": e.t, "t_ptp_ns": to_ptp(e.t), "source": e.source, "count": e.count}
                   for e in events],
        "gaps": [{"plate": g.plate, "start_t": g.start_t, "end_t": g.end_t, "missing": g.missing,
                  "start_ptp_ns": to_ptp(g.start_t), "end_ptp_ns": to_ptp(g.end_t)} for g in gaps],
        **(metadata or {}),
    }
    Path(str(out) + ".json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return out, ptp_map


def _cell(value: float) -> str:
    return "" if value is None or math.isnan(value) else repr(float(value))
