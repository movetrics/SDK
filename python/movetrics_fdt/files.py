"""Readers for the files Movetrics Studio exports: <stem>-channels.csv, <stem>-details.csv and <stem>.c3d.

Standard library only, except read_studio_c3d, which needs ezc3d (pip install ezc3d). The format, its units and
axes are specified in docs/18-export-formats.md. Facts this module relies on, checked on Studio exports of
10 Oct 2026 (500 rows/s) and 14 Oct 2026 (1,000 rows/s, 10,560 rows):

- Timestamp counts FDT ticks of 100 us from the start of the stream. Rows are not on a fixed grid: the 14 Oct
  file has one 41 ms hole (a step of 410 ticks among steps of 10). read_studio_csv reports such gaps instead of
  hiding them; the C3D of the same exam is written on a uniform 1,000 Hz grid and does not show the hole.
- Forces in N and moments in N*m, per plate (p1, p2) and combined (comb). Fz is vertical, positive under load.
- CoP columns, when present, are in m: per plate from the plate centre, combined from the middle between the two
  plates. A plate's CoP follows from its own columns as x = (-My - d*Fx) / Fz and y = (-Mx + d*Fy) / Fz with
  d = 0.030 m, the depth of the moment reference below the top (0.28 mm rms against the recorded columns, which
  are rounded to 1 mm; the C3D FORCE_PLATFORM ORIGIN states the same 30 mm).
"""

from __future__ import annotations

import csv
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

TICKS_PER_SECOND: Final = 10_000
MOMENT_REFERENCE_DEPTH_M: Final = 0.030
# Plate centres in the combined frame of the CSV: the two 35 cm x 60 cm plates side by side along x.
PLATE_CENTRE_X_M: Final = {"p1": -0.175, "p2": 0.175}
# Studio leaves CoP empty below its CopForceThreshold (50 N in the bench config.ini).
COP_MIN_FZ_N: Final = 50.0

_COLUMN = re.compile(r"^(p1|p2|comb)_(ForceX|ForceY|ForceZ|MomentX|MomentY|MomentZ|COPx|COPy)$")


@dataclass(frozen=True)
class Gap:
    """A step between two rows longer than 1.5 times the usual step."""

    row: int  # index of the row after the gap
    start_s: float
    length_s: float


@dataclass
class StudioRecording:
    """One Studio exam. columns maps a Studio column name (p1_ForceZ, comb_COPx, ...) to its values; an empty
    cell is None. time_s starts at 0 at the first row."""

    path: Path
    time_s: list[float]
    columns: dict[str, list[float | None]]
    ticks: list[int]
    details: dict[str, str] = field(default_factory=dict)

    @property
    def plates(self) -> list[str]:
        return [plate for plate in ("p1", "p2") if f"{plate}_ForceZ" in self.columns]

    @property
    def sample_rate_hz(self) -> float:
        """Rows per second from the median step; the file itself has no fixed rate (see gaps)."""
        steps = [b - a for a, b in zip(self.ticks, self.ticks[1:])]
        return TICKS_PER_SECOND / statistics.median(steps) if steps else 0.0

    @property
    def gaps(self) -> list[Gap]:
        steps = [b - a for a, b in zip(self.ticks, self.ticks[1:])]
        if not steps:
            return []
        usual = statistics.median(steps)
        return [Gap(row=index + 1, start_s=self.time_s[index], length_s=step / TICKS_PER_SECOND)
                for index, step in enumerate(steps) if step > 1.5 * usual]

    def plate_cop(self, plate: str, min_fz_n: float = COP_MIN_FZ_N) -> tuple[list[float | None], list[float | None]]:
        """CoP x and y of one plate in m from the plate centre, from its force and moment columns (formula above).
        None where Fz is below min_fz_n. Works on files without CoP columns (Studio before October 2026)."""
        fx, fy, fz = (self.columns[f"{plate}_Force{axis}"] for axis in "XYZ")
        mx, my = self.columns[f"{plate}_MomentX"], self.columns[f"{plate}_MomentY"]
        xs: list[float | None] = []
        ys: list[float | None] = []
        d = MOMENT_REFERENCE_DEPTH_M
        for i, load in enumerate(fz):
            if load is None or load < min_fz_n or None in (fx[i], fy[i], mx[i], my[i]):
                xs.append(None)
                ys.append(None)
                continue
            xs.append((-my[i] - d * fx[i]) / load)  # type: ignore[operator]
            ys.append((-mx[i] + d * fy[i]) / load)  # type: ignore[operator]
        return xs, ys


def read_studio_details(path: str | Path) -> dict[str, str]:
    """The Field,Value table of <stem>-details.csv (Exam Type, Exam Date, Duration (seconds), Configuration Name,
    subject fields ...). It holds personal data: keep it apart from anything you share."""
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows or [cell.strip() for cell in rows[0][:2]] != ["Field", "Value"]:
        raise ValueError(f"{path} is not a Studio details file (first row must be Field,Value)")
    return {row[0]: row[1] if len(row) > 1 else "" for row in rows[1:] if row}


def read_studio_csv(path: str | Path, *, details: bool = True) -> StudioRecording:
    """Read <stem>-channels.csv. With details=True the partner <stem>-details.csv is read when it exists."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = [cell.strip() for cell in next(reader, [])]
        if not header or header[0] != "Timestamp":
            raise ValueError(f"{path} is not a Studio channels file (first column must be Timestamp)")
        unknown = [name for name in header[1:] if not _COLUMN.match(name)]
        if unknown:
            raise ValueError(f"{path}: unexpected Studio columns {unknown}")
        ticks: list[int] = []
        columns: dict[str, list[float | None]] = {name: [] for name in header[1:]}
        for row in reader:
            if not row:
                continue
            ticks.append(int(float(row[0])))
            for name, cell in zip(header[1:], row[1:] + [""] * (len(header) - len(row))):
                cell = cell.strip()
                columns[name].append(float(cell) if cell else None)
    first = ticks[0] if ticks else 0
    recording = StudioRecording(path=path, time_s=[(tick - first) / TICKS_PER_SECOND for tick in ticks], columns=columns, ticks=ticks)
    if details:
        partner = path.with_name(re.sub(r"-channels\.csv$", "-details.csv", path.name))
        if partner != path and partner.exists():
            recording.details = read_studio_details(partner)
    return recording


def read_studio_c3d(path: str | Path) -> dict[str, object]:
    """Read a Studio .c3d with ezc3d: {"rate_hz", "time_s", "columns", "units", "force_platform"}.

    columns uses the same names as the CSV (p1_ForceX ... comb_MomentZ, N and N*m). The file is on a uniform grid
    (1,000 Hz in the 14 Oct 2026 export), so a hole in the stream is not visible here: use the CSV to find gaps.
    force_platform holds CORNERS and ORIGIN in mm (plate 1 from x 0 to 350, plate 2 from 350 to 700, y 0 to 600,
    origin 30 mm below the top). It has no CoP columns; use StudioRecording.plate_cop on the CSV or compute it.
    """
    try:
        import ezc3d  # type: ignore[import-not-found]
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise ImportError("read_studio_c3d needs ezc3d: pip install ezc3d") from error
    c3d = ezc3d.c3d(str(path))
    analog = c3d["parameters"]["ANALOG"]
    rate = float(analog["RATE"]["value"][0])
    labels = [label.strip() for label in analog["LABELS"]["value"]]
    data = c3d["data"]["analogs"][0]
    platform = c3d["parameters"].get("FORCE_PLATFORM", {})
    return {
        "rate_hz": rate,
        "time_s": [index / rate for index in range(data.shape[1])],
        "columns": {label: [float(value) for value in data[i]] for i, label in enumerate(labels)},
        "units": dict(zip(labels, (unit.strip() for unit in analog["UNITS"]["value"]))),
        "force_platform": {key: platform[key]["value"].tolist() for key in ("CORNERS", "ORIGIN", "CHANNEL") if key in platform},
    }
