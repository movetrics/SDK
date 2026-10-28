"""A virtual FDT that speaks the real host protocol, for everyone who has no controller on the desk.

VirtualFdt is the protocol and timing model only: bytes in with feed(), bytes out with advance(now). It never
touches a port. simulator_io.py puts it on a TCP port or a pseudo-terminal, and `python -m movetrics_fdt simulate`
runs it from the command line. Clients cannot tell it from a controller on the byte level: same envelopes, same
CRC, same placeholders after START, same NACK codes, same pacing on the 0.1 ms grid.

What it models, and from where (the facts are firmware facts, not guesses about a future build):
- Profiles: "1.2.8.2" (500 frames/s default, 10 min sleep, START streams at once),
  "1.2.8.20" (the production line: 1,000 frames/s default, sleep 5 min after the last command with the pads off, START,
  SET_TARE and GET_CURRENT_CONFIG wait about 4.6 s for the pads after a wake
 ), and "sync" (1.2.8.24: sync modes and event frames,, not released).
- Commands: START 0x01, STOP 0x05, SET_FILTER 0x1C, GET_STATUS 0x22, GET_FW_VERSION 0x23, KEEP_ALIVE 0x26,
  SET_SYNC_MODE 0x28 and GET_SYNC_MODE 0x29 (sync profile, docs/04 section 3.9; NACK 7 elsewhere). Every other code answers NACK 7, as the firmware does for a
  code without a case. Nothing here writes "flash": calibration and tare commands are refused with NACK 7 so a
  script that works on the simulator cannot surprise anyone on a real controller.
- Signals: a standing person with sway, a countermovement jump every few seconds, an empty plate, or a replay of
  a Studio -channels.csv (values converted back to wire signs, its gaps kept when asked).
- Faults to test hosts against: dropped frames, a held stream (no frames for a while), int16 wrap at high load,
  clock drift against the host (ppm), sync edges on SYNC IN.
"""

from __future__ import annotations

import bisect
import math
import random
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .frames import ACK_CODE, NACK_CODE, HostRxSplitter, build_device_frame, parse_host_message
from .errors import FrameError
from .stream import (
    EventFrame, StreamFrame, SyncModeReply, encode_event_frame, encode_stream_frame, encode_sync_mode_reply,
)
from .vocabulary import MOMENT_REFERENCE_DEPTH_M, STREAM_SIGN, TICKS_PER_SECOND

NACK_INVALID_PARAMETER = 3
NACK_UNKNOWN_COMMAND = 7
NACK_NOT_NOW = 8


@dataclass(frozen=True)
class Profile:
    """Behaviour of one firmware line."""

    firmware: str
    default_rate_hz: int
    sleep_s: float
    wake_wait_s: float  # how long START waits for the pads after a sleep; 0 = no wait (older lines)
    keep_alive_max_s: int
    sync_modes: bool


PROFILES: dict[str, Profile] = {
    "1.2.8.2": Profile("1.2.8.2", 500, 600.0, 0.0, 0xFFFF, False),
    "1.2.8.20": Profile("1.2.8.20", 1000, 300.0, 4.6, 300, False),
    "sync": Profile("1.2.8.24", 1000, 300.0, 4.6, 300, True),
}

BODYWEIGHT_N = 750.0


def _wire(value: float) -> int:
    """Round to the wire integer and wrap at int16 like the firmware's output cast (doc 05 section 3.2)."""
    whole = int(round(value))
    return (whole + 0x8000) % 0x10000 - 0x8000


class Signal:
    """A source of plate-frame values: values(plate, t) -> (fx, fy, fz, mx, my, mz) in N and N*m."""

    plates = (1, 2)

    def values(self, plate: int, t: float) -> tuple[float, float, float, float, float, float]:
        raise NotImplementedError


def _wrench(fx: float, fy: float, fz: float, cop_x: float, cop_y: float) -> tuple[float, ...]:
    """Moments about the plate's reference 30 mm below the top for a load at (cop_x, cop_y): the inverse of
    vocabulary.plate_cop."""
    d = MOMENT_REFERENCE_DEPTH_M
    return fx, fy, fz, -cop_y * fz + d * fy, -cop_x * fz - d * fx, 0.0


@dataclass
class Synthetic(Signal):
    """kind: "stand" (sway around the plate centres), "cmj" (a jump every period_s), "empty" (noise only)."""

    kind: str = "stand"
    bodyweight_n: float = BODYWEIGHT_N
    period_s: float = 6.0
    noise_n: float = 1.0
    seed: int = 1
    _random: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.kind not in ("stand", "cmj", "empty"):
            raise ValueError(f"unknown synthetic signal {self.kind!r}: stand, cmj or empty")
        self._random = random.Random(self.seed)

    def _total(self, t: float) -> float:
        if self.kind == "empty":
            return 0.0
        if self.kind == "stand":
            return self.bodyweight_n
        # A plain countermovement jump: unweighting, braking and push-off, flight, landing, then quiet standing.
        phase = t % self.period_s
        w = self.bodyweight_n
        if phase < 2.0:
            return w
        if phase < 2.35:
            return w * (1 - 0.6 * math.sin(math.pi * (phase - 2.0) / 0.35))
        if phase < 2.85:
            return w * (1 + 1.4 * math.sin(math.pi * (phase - 2.35) / 0.5))
        if phase < 3.3:
            return 0.0
        if phase < 3.45:
            return w * (1 + 3.0 * math.sin(math.pi * (phase - 3.3) / 0.15))
        return w

    def values(self, plate: int, t: float) -> tuple[float, ...]:
        total = self._total(t)
        share = 0.5 + (0.02 if plate == 1 else -0.02) * math.sin(2 * math.pi * 0.3 * t)
        fz = total * share + self._random.gauss(0.0, self.noise_n)
        fx = 0.02 * fz * math.sin(2 * math.pi * 0.5 * t) + self._random.gauss(0.0, self.noise_n)
        fy = 0.015 * fz * math.cos(2 * math.pi * 0.4 * t) + self._random.gauss(0.0, self.noise_n)
        if fz < 20:
            return fx, fy, fz, 0.0, 0.0, 0.0
        cop_x = 0.01 * math.sin(2 * math.pi * 0.2 * t + plate)
        cop_y = 0.02 * math.sin(2 * math.pi * 0.15 * t)
        return _wrench(fx, fy, fz, cop_x, cop_y)


class StudioReplay(Signal):
    """Replays a Studio -channels.csv in a loop. t is seconds since START; the row in effect at t is used, so the
    replay works at any stream rate. Gaps in the file stay gaps when keep_gaps is True (no frame is sent while
    the file has none)."""

    def __init__(self, path: str | Path, *, keep_gaps: bool = True) -> None:
        from .files import read_studio_csv

        recording = read_studio_csv(path, details=False)
        self.plates = tuple(int(name[1]) for name in recording.plates)
        if not self.plates:
            raise ValueError(f"{path} has no p1_ or p2_ columns")
        self._time = recording.time_s
        self._duration = recording.time_s[-1] + 1 / max(recording.sample_rate_hz, 1.0)
        self._period = 1 / recording.sample_rate_hz
        self._keep_gaps = keep_gaps
        names = ("ForceX", "ForceY", "ForceZ", "MomentX", "MomentY", "MomentZ")
        self._rows = {
            plate: list(zip(*(recording.columns[f"p{plate}_{name}"] for name in names))) for plate in self.plates
        }

    def in_gap(self, t: float) -> bool:
        if not self._keep_gaps:
            return False
        local = t % self._duration
        index = bisect.bisect_right(self._time, local) - 1
        nxt = self._time[index + 1] if index + 1 < len(self._time) else self._duration
        return nxt - self._time[max(index, 0)] > 1.5 * self._period and local - self._time[max(index, 0)] >= self._period

    def values(self, plate: int, t: float) -> tuple[float, ...]:
        index = max(bisect.bisect_right(self._time, t % self._duration) - 1, 0)
        row = self._rows[plate][index]
        return tuple(0.0 if value is None else value for value in row)


@dataclass
class Faults:
    """Faults to inject. drop_every: drop one frame in every N (0 = never). hold_at_s/hold_s: send nothing for
    hold_s seconds from hold_at_s after START (the frames are lost, as in a USB stall). clock_ppm: the FDT clock runs
    this fast against the host. scale: multiply every load (use 20 to provoke the int16 wrap)."""

    drop_every: int = 0
    hold_at_s: float = -1.0
    hold_s: float = 0.0
    clock_ppm: float = 0.0
    scale: float = 1.0


class VirtualFdt:
    """The controller. Feed host bytes with feed(data, now); collect device bytes with advance(now).

    now is the host's monotonic clock in seconds. Everything the controller does is scheduled on it, so tests can
    run faster than real time by passing their own clock.
    """

    def __init__(self, profile: str | Profile = "1.2.8.20", signal: Signal | None = None,
                 faults: Faults | None = None, *, now: float = 0.0, plates: tuple[int, ...] | None = None) -> None:
        self.profile = PROFILES[profile] if isinstance(profile, str) else profile
        self.signal = signal or Synthetic()
        self.faults = faults or Faults()
        self.plates = plates or self.signal.plates
        self.rate_hz = self.profile.default_rate_hz
        self.cutoff_hz = 50
        self.sync_mode = 0
        self.pulse_period_ms = 1000
        self.pulse_width_ms = 5
        self.debounce_ticks = 5
        self.arm_timeout_min = 30
        self.edges_in = 0
        self.edges_out = 0
        self._armed_at = 0.0
        self.keep_alive_s = self.profile.sleep_s
        self.asleep = False
        self.pads_ready_at = now
        self.last_command_at = now
        self.streaming = False
        self.armed = False
        self.sync_in_level = 0
        self.sync_out_level = 0
        self.commands: list[int] = []  # every command code received, for tests
        self._splitter = HostRxSplitter()
        self._out = bytearray()
        self._pending: list[tuple[float, Callable[[float], None]]] = []
        self._start_host = 0.0
        self._next_tick = 0
        self._frame_count = 0
        self._next_pulse_tick = 0
        self._pulse_off_tick: int | None = None
        self._saturated: set[int] = set()

    # ----- time base -----------------------------------------------------------------------------------------
    def _ticks_exact(self, now: float) -> float:
        return (now - self._start_host) * TICKS_PER_SECOND * (1 + self.faults.clock_ppm * 1e-6)

    def _ticks(self, now: float) -> int:
        """FDT ticks since START at host time now, with the clock drift fault."""
        return int(self._ticks_exact(now))

    def _period_ticks(self) -> int:
        return TICKS_PER_SECOND // self.rate_hz

    # ----- host side -----------------------------------------------------------------------------------------
    def feed(self, data: bytes, now: float) -> None:
        """Bytes from the host. Replies appear in the next advance()."""
        for message in self._splitter.feed(data):
            try:
                frame = parse_host_message(message)
            except FrameError as error:
                # The controller drops a bad zero-payload request silently and answers NACK 9 to one with a
                # payload (doc 03, introduction).
                if error.reason == "crc_mismatch" and len(message) > 9:
                    self._nack(0x00, message[4], 9)
                continue
            self._command(frame.command, frame.address, frame.payload, now)

    def advance(self, now: float) -> bytes:
        """Run the controller up to host time now and return the bytes it sent."""
        if self.armed and now - self._armed_at >= self.arm_timeout_min * 60:
            self.armed = False
            self._event(10, 0, stamp=0, detail=self.arm_timeout_min)
        for due, action in sorted(self._pending, key=lambda item: item[0]):
            if due <= now:
                action(due)
        self._pending = [(due, action) for due, action in self._pending if due > now]
        if not self.streaming and not self.armed and now - self.last_command_at >= self.keep_alive_s > 0:
            self.asleep = True
        if self.streaming:
            self._stream_until(now)
        out = bytes(self._out)
        self._out.clear()
        return out

    def sync_in(self, level: int, now: float) -> None:
        """Drive SYNC IN (a function generator, a camera's strobe, a button). Debounce is not modelled: every
        level change counts, so drive pulses longer than the debounce as on the real input."""
        level = 1 if level else 0
        if level == self.sync_in_level:
            return
        self.sync_in_level = level
        self.edges_in += 1
        if self.sync_mode == 0:
            self.sync_out_level = level  # mode 0: SYNC OUT copies SYNC IN, as before 1.2.8.24
            return
        if level and self.armed:
            # The edge starts the stream from the interrupt: tick 0 lies within one tick before the edge.
            self.armed = False
            self._begin_stream(now, placeholders=False)
            self._event(1, 0, stamp=0)
            self._event(6, 0, stamp=0)
            return
        if self.streaming:
            self._stream_until(now)  # frames before the edge go out first
            exact = self._ticks_exact(now)
            self._event(1 if level else 2, 0, stamp=int(exact), offset_us=int((exact - int(exact)) * 100))
            if not level and self.sync_mode & 0x02:
                self._end_stream(now)

    # ----- commands ------------------------------------------------------------------------------------------
    def _reply(self, address: int, command: int, body: bytes = b"") -> None:
        self._out += build_device_frame(bytes((address, command)) + body)

    def _ack(self, address: int, command: int) -> None:
        self._reply(address, command, bytes((ACK_CODE,)))

    def _nack(self, address: int, command: int, error: int) -> None:
        self._reply(address, command, bytes((NACK_CODE,)) + struct.pack("<H", error))

    def _command(self, code: int, address: int, payload: bytes, now: float) -> None:
        self.commands.append(code)
        self.last_command_at = now
        if self.asleep:
            self.asleep = False  # the first command wakes it in 16 ms (measured); the pads need longer
            self.pads_ready_at = now + self.profile.wake_wait_s
        if code == 0x01:
            self._start(now)
        elif code == 0x05:
            self._end_stream(now)
            self.armed = False
            self._ack(0xFF, 0x05)
        elif code == 0x1C:
            self._set_filter(payload)
        elif code == 0x22:
            self._status()
        elif code == 0x23:
            self._reply(0x00, 0x23, self.profile.firmware.encode().ljust(15, b"\0")[:15] + b"000.000.000".ljust(15, b"\0"))
        elif code == 0x26:
            interval = struct.unpack("<H", payload[:2])[0] if len(payload) >= 2 else 0
            self.keep_alive_s = float(min(interval, self.profile.keep_alive_max_s)) if interval else 0.0
        elif code == 0x28 and self.profile.sync_modes:
            self._set_sync_mode(payload)
        elif code == 0x29 and self.profile.sync_modes:
            state = (0x01 if self.armed else 0) | 0x04 | (0x08 if self.sync_in_level else 0) \
                | (0x10 if self.sync_out_level else 0) | (0x20 if self.streaming else 0)
            self._out += encode_sync_mode_reply(SyncModeReply(
                self.sync_mode, self.pulse_period_ms, self.pulse_width_ms, self.debounce_ticks, self.arm_timeout_min,
                state, 1, self.edges_in, self.edges_out, 0))
        else:
            self._nack(0x00, code, NACK_UNKNOWN_COMMAND)

    def _set_sync_mode(self, payload: bytes) -> None:
        """docs/04 section 3.9: 0 in an optional byte takes the default."""
        if self.streaming or self.armed:
            self._nack(0x00, 0x28, NACK_NOT_NOW)
            return
        fields = list(payload[:6]) + [0] * (6 - len(payload[:6]))
        mode = fields[0]
        period = (fields[1] | (fields[2] << 8)) or 1000
        width, debounce, timeout = fields[3] or 5, fields[4] or 5, fields[5] or 30
        if (not payload or mode & ~0x3F or (mode & 0x04 and mode & 0x10) or not 10 <= period <= 60000
                or width >= period):
            self._nack(0x00, 0x28, NACK_INVALID_PARAMETER)
            return
        self.sync_mode, self.pulse_period_ms, self.pulse_width_ms = mode, period, width
        self.debounce_ticks, self.arm_timeout_min = debounce, timeout
        self._ack(0x00, 0x28)

    def _set_filter(self, payload: bytes) -> None:
        if len(payload) < 3:
            self._nack(0x00, 0x1C, NACK_INVALID_PARAMETER)
            return
        cutoff, rate = payload[0], payload[1] | (payload[2] << 8)
        if not 50 <= rate <= 2000 or (cutoff and cutoff * 2 >= rate) or self.streaming:
            self._nack(0x00, 0x1C, NACK_INVALID_PARAMETER)
            return
        self.cutoff_hz, self.rate_hz = cutoff, rate
        self._ack(0x00, 0x1C)

    def _status(self) -> None:
        layout = struct.Struct("<BBIb20s30s4s4s4sIHHHB")
        for address in (0,) + tuple(self.plates):
            body = layout.pack(address, 0x22, 0, 30, b"1500000,8,N,1", b"", b"\0" * 4, b"\0" * 4, b"\0" * 4,
                               0, 100, 100, 100, 255)
            self._out += build_device_frame(body)

    def _start(self, now: float) -> None:
        if self.streaming:
            return
        if self.sync_mode & 0x01:
            # START sends its placeholders as always and arms; the next rising edge starts the stream.
            for plate in self.plates:
                self._out += encode_stream_frame(StreamFrame(plate, 0x01, 0, 0, 0, 1, 0, 0, 0))
            self.armed = True
            self._armed_at = now
            self._event(5, 0, stamp=0, detail=self.arm_timeout_min)
            return
        wait = max(0.0, self.pads_ready_at - now)
        if wait > 0:
            # 1.2.8.10+: START waits for the pads after a wake; the stream begins when they answer.
            self._pending.append((now + wait, self._begin_stream))
        else:
            self._begin_stream(now)

    def _begin_stream(self, now: float, placeholders: bool = True) -> None:
        self.streaming = True
        self._start_host = now
        self._next_tick = self._period_ticks()
        self._frame_count = 0
        self._saturated.clear()
        for plate in self.plates if placeholders else ():  # one frame per plate with stamp 0 (doc 05 section 6)
            self._out += encode_stream_frame(StreamFrame(plate, 0x01, 0, 0, 0, 1, 0, 0, 0))
        if self.sync_mode & 0x04:
            self._set_out(1, 0)
        self._next_pulse_tick = 1  # pulses rise at stream ticks 1, 1 + P, 1 + 2P ...
        self._pulse_off_tick = None

    def _end_stream(self, now: float) -> None:
        if not self.streaming:
            return
        self._stream_until(now)
        self.streaming = False
        if self.sync_out_level:
            self._set_out(0, self._ticks(now))

    def _set_out(self, level: int, stamp: int) -> None:
        self.sync_out_level = level
        if level:
            self.edges_out += 1
        self._event(3 if level else 4, 0, stamp=stamp)

    def _event(self, event_type: int, source: int, *, stamp: int, detail: int = 0, offset_us: int = 0) -> None:
        saturation = event_type in (7, 9)
        if (self.sync_mode & 0x20) if saturation else (self.sync_mode & 0x08):
            count = self.edges_out if event_type in (3, 4) else 1 if saturation else self.edges_in
            self._out += encode_event_frame(EventFrame(stamp & 0xFFFFFFFF, event_type, source, count, detail,
                                                       offset_us, self.sync_mode))

    def _stream_until(self, now: float) -> None:
        end = self._ticks(now)
        period = self._period_ticks()
        faults = self.faults
        while self._next_tick <= end:
            tick = self._next_tick
            self._next_tick += period
            self._pulses_until(tick)
            t = tick / TICKS_PER_SECOND
            if faults.hold_s > 0 and faults.hold_at_s <= t < faults.hold_at_s + faults.hold_s:
                continue
            if isinstance(self.signal, StudioReplay) and self.signal.in_gap(t):
                continue
            for plate in self.plates:
                self._frame_count += 1
                if faults.drop_every and self._frame_count % faults.drop_every == 0:
                    continue
                values = [faults.scale * sign * value for sign, value in zip(STREAM_SIGN, self.signal.values(plate, t))]
                mask = sum(1 << k for k, value in enumerate(values) if abs(value) > 32767)
                if mask and plate not in self._saturated:
                    self._saturated.add(plate)
                    self._event(7, plate, stamp=tick, detail=mask)
                elif not mask and plate in self._saturated:
                    self._saturated.discard(plate)
                    self._event(9, plate, stamp=tick)
                wire = [_wire(value) for value in values]
                self._out += encode_stream_frame(StreamFrame(plate, 0x01, tick & 0xFFFFFFFF, *wire))
        # The pulse pin follows the timer tick, not the frame grid: bring it up to date between frames too.
        self._pulses_until(end)

    def _pulses_until(self, tick: int) -> None:
        if not self.sync_mode & 0x10:
            return
        if self._pulse_off_tick is not None and self._pulse_off_tick <= tick:
            self._set_out(0, self._pulse_off_tick)
            self._pulse_off_tick = None
        if self._next_pulse_tick <= tick:
            self._set_out(1, self._next_pulse_tick)
            self._pulse_off_tick = self._next_pulse_tick + self.pulse_width_ms * 10
            self._next_pulse_tick += self.pulse_period_ms * 10


__all__ = ["PROFILES", "Faults", "Profile", "Signal", "StudioReplay", "Synthetic", "VirtualFdt"]
