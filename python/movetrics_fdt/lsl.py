"""Lab Streaming Layer outlets: one per plate plus a marker stream, on the LSL clock, from FdtClient.samples().

Record the FDT next to EMG, EEG, eye tracking and cameras with LabRecorder; load the XDF with pyxdf, MNE or EEGLAB.
Design follows the earlier FDT LSL streamer (least-delayed frame per block, then offset and drift), with the
shared vocabulary (docs/19) for names, units, signs and CoP:

- Streams "Movetrics FDT plate N" (type Force, nominal rate = FDT rate, float32): fx fy fz [N], mx my mz [N*m],
  cop_x cop_y [m]; source id movetrics-fdt-<serial or 'fdt'>-plateN, so LabRecorder reconnects after a restart.
- "Movetrics FDT markers" (type Markers, irregular, string): every Event by name (sync_in_rise, ...), gaps as
  "gap plate=P missing=N", and notes from mark().
- Time stamps: the FDT stamp mapped onto local_clock() by sync.ClockMap (offset and drift fitted on the frames
  that waited least), never the USB arrival time. The fit residual is in stats().
"""

from __future__ import annotations

import time
from typing import Any

from .sync import ClockMap
from .vocabulary import CHANNELS, Event, Gap, Sample

CHANNEL_UNITS = (("fx", "N"), ("fy", "N"), ("fz", "N"), ("mx", "N*m"), ("my", "N*m"), ("mz", "N*m"),
                 ("cop_x", "m"), ("cop_y", "m"))


def _import_pylsl() -> Any:
    try:
        import pylsl
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise ImportError("LSL needs pylsl: pip install 'movetrics-fdt[lsl]'") from error
    return pylsl


class LslBridge:
    """Feed it the items of FdtClient.samples(); it pushes them to LSL.

        bridge = LslBridge(rate_hz=2000, plates=(1, 2), firmware=version.stm32FW)
        async for item in fdt.samples():
            bridge.push(item)
    """

    def __init__(self, rate_hz: float, plates: tuple[int, ...] = (1, 2), *, name: str = "Movetrics FDT",
                 source_id: str = "movetrics-fdt", firmware: str = "unknown", latency_s: float = 0.0,
                 chunk: int = 20) -> None:
        pylsl = _import_pylsl()
        self._pylsl = pylsl
        self.clock = ClockMap(latency_seconds=latency_s)
        self._chunk = max(1, chunk)
        self._pending: dict[int, tuple[list[list[float]], list[float]]] = {plate: ([], []) for plate in plates}
        self._last_stamp: dict[int, float] = {}
        self._last_device: dict[int, int] = {}
        self.outlets: dict[int, Any] = {}
        for plate in plates:
            info = pylsl.StreamInfo(f"{name} plate {plate}", "Force", len(CHANNEL_UNITS), float(rate_hz),
                                    pylsl.cf_float32, f"{source_id}-plate{plate}")
            desc = info.desc()
            channels = desc.append_child("channels")
            for label, unit in CHANNEL_UNITS:
                channel = channels.append_child("channel")
                channel.append_child_value("label", label)
                channel.append_child_value("unit", unit)
                channel.append_child_value("type", "Force" if unit == "N" else "Moment" if unit == "N*m" else "CoP")
            acquisition = desc.append_child("acquisition")
            acquisition.append_child_value("manufacturer", "Movetrics")
            acquisition.append_child_value("firmware", firmware)
            acquisition.append_child_value("vocabulary", "movetrics.vocabulary/1 (docs/19)")
            acquisition.append_child_value("frame", "plate: Studio file signs; CoP from the plate centre")
            clock = desc.append_child("clock")
            clock.append_child_value("source", "FDT stamp, 0.1 ms ticks, one clock for all plates")
            clock.append_child_value("mapping", "least-squares line through the least-delayed frame of each second")
            self.outlets[plate] = pylsl.StreamOutlet(info, chunk_size=self._chunk)
        markers = pylsl.StreamInfo(f"{name} markers", "Markers", 1, pylsl.IRREGULAR_RATE, pylsl.cf_string,
                                   f"{source_id}-markers")
        self.markers = pylsl.StreamOutlet(markers)
        self.repeated = 0

    def push(self, item: Sample | Event | Gap, arrival: float | None = None) -> None:
        """Push one item. arrival is local_clock() when the frame was read; default: now."""
        now = self._pylsl.local_clock() if arrival is None else arrival
        if isinstance(item, Sample):
            self.clock.observe(item.t, now)
            stamp = self.clock.to_host(item.t)
            if item.stamp <= self._last_device.get(item.plate, -1):
                self.repeated += 1  # a repeated or backward device stamp is not a new sample: dropped
                return
            self._last_device[item.plate] = item.stamp
            # LSL needs increasing stamps per stream. In the warm-up the fitted offset can still fall by a few ms;
            # hold the stamp just above the previous one rather than drop a real sample.
            last = self._last_stamp.get(item.plate)
            if last is not None and stamp <= last:
                stamp = last + 1e-6
            self._last_stamp[item.plate] = stamp
            values, stamps = self._pending.setdefault(item.plate, ([], []))
            values.append([getattr(item, name) for name in CHANNELS] + [item.cop_x, item.cop_y])
            stamps.append(stamp)
            if len(values) >= self._chunk:
                self._flush(item.plate)
        elif isinstance(item, Event):
            self.markers.push_sample([item.name], self.clock.to_host(item.t))
        else:
            self.markers.push_sample([f"gap plate={item.plate} missing={item.missing}"], self.clock.to_host(item.start_t))

    def mark(self, text: str) -> None:
        """A free-text marker at the current time (trial names, 'jump 3', ...)."""
        self.markers.push_sample([text], self._pylsl.local_clock())

    def _flush(self, plate: int) -> None:
        values, stamps = self._pending[plate]
        if values and plate in self.outlets:
            self.outlets[plate].push_chunk(values, stamps)
        values.clear()
        stamps.clear()

    def flush(self) -> None:
        for plate in list(self._pending):
            self._flush(plate)

    def stats(self) -> dict[str, Any]:
        residual = self.clock.residual_seconds
        return {"drift_ppm": self.clock.drift_ppm,
                "residual_ms": None if residual is None else residual * 1000,
                "repeated_dropped": self.repeated}


def wait_for_consumers(bridge: LslBridge, timeout_s: float = 0.0) -> bool:
    """True when every plate outlet has a consumer (for example LabRecorder recording)."""
    deadline = time.monotonic() + timeout_s
    while True:
        if all(outlet.have_consumers() for outlet in bridge.outlets.values()):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


