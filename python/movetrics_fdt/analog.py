"""The FDT's analog outputs (A1-A16) as numbers: volts from a DAQ or EMG system back to N, N*m and m.

Scale from Nur Engineering's sheet of 27 Oct 2026 for firmware 1.2.8.22 (contracts/analog-outputs.v1.json,
docs/23-analog-outputs.md). The outputs carry the FDT's wire signs, so to_vocabulary() flips fy and mx into the
plate frame that every Movetrics file and client uses (Studio's). The centre of pressure comes back in m but keeps
the outputs' 1 cm steps, its sign and origin are not stated by the maker, and it reads 0 below 30 N: prefer the CoP
computed from forces and moments (vocabulary.plate_cop) when you have them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .vocabulary import STREAM_SIGN, CHANNELS


@dataclass(frozen=True)
class AnalogOutput:
    output: str
    plate: int
    signal: str
    unit: str
    full_scale: float
    units_per_volt: float


_SCALE: Final = (("fz", "N", 8000, 800), ("fx", "N", 2000, 200), ("fy", "N", 2000, 200), ("mz", "N·m", 720, 72),
                 ("mx", "N·m", 720, 72), ("my", "N·m", 720, 72), ("cop_x", "cm", 15, 1.5), ("cop_y", "cm", 30, 3))
OUTPUTS: Final = {f"A{(plate - 1) * 8 + i + 1}": AnalogOutput(f"A{(plate - 1) * 8 + i + 1}", plate, signal, unit,
                                                              full_scale, per_volt)
                  for plate in (1, 2) for i, (signal, unit, full_scale, per_volt) in enumerate(_SCALE)}
RANGE_V: Final = 10.0


def to_value(output: str, volts: float) -> float:
    """Volts on one output to its value in the output's own unit and sign (N, N*m or cm, wire signs)."""
    return volts * OUTPUTS[output].units_per_volt


def to_vocabulary(output: str, volts: float) -> tuple[int, str, float]:
    """Volts on one output to (plate, vocabulary name, value in SI and the plate frame)."""
    spec = OUTPUTS[output]
    value = to_value(output, volts)
    if spec.signal.startswith("cop"):
        return spec.plate, spec.signal, value / 100.0
    return spec.plate, spec.signal, STREAM_SIGN[CHANNELS.index(spec.signal)] * value


def clipped(output: str, volts: float, margin: float = 0.01) -> bool:
    """True when the output sits at the end of its range, where a larger load reads the same (the FDT clips)."""
    return abs(volts) >= RANGE_V * (1 - margin)
