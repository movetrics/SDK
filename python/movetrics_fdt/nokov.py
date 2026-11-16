"""NOKOV XINGYING: take-synchronised recording, and the FDT's analog outputs as a XINGYING force plate (docs/24).

XINGYING, NOKOV's motion-capture software, tells other programs when it records ("Remote Trigger": a small XML
message broadcast over UDP, port 7061 by default, when a recording starts and when it stops) and starts or stops a
recording when told to ("Remote Control": it listens on UDP port 7060). Both are described in its manual (XingYing
4.7, Plugins & SDKs). This module reads and writes those messages, and TakeCutter cuts takes out of a continuous FDT
stream at the trigger times, mapped onto the FDT clock with sync.ClockMap. A UDP trigger aligns takes, not samples:
the packet's network delay is in the cut and has not been measured. For sample-level alignment use a sync cable or
LSL (docs/22).

The manual's examples are not consistent (the stop example names another take than the start example, the field
tables differ from the examples, and one example has a bare '&'), so parsing is safe but lenient: document type and
entity declarations are refused, a message that needed repair is marked lenient, and the raw bytes are kept.

analog_worksheet() gives what to enter in XINGYING to read the FDT's analog outputs through an NI DAQ as an analog
force plate: the values that follow from our analog contract, the points XINGYING's manual does not settle, and the
known-load check that settles them on site. It has not been run in XINGYING.
"""

from __future__ import annotations

import asyncio
import glob
import json
import math
import re
import socket
import time
import unicodedata
from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from .analog import OUTPUTS
from .sync import ClockMap
from .vocabulary import MOMENT_REFERENCE_DEPTH_M, Event, Gap, Sample

TRIGGER_PORT = 7061  # XINGYING broadcasts CaptureStart / CaptureStop here (Remote Trigger)
CONTROL_PORT = 7060  # XINGYING listens here for CaptureStart / CaptureStop (Remote Control)
MAX_MESSAGE_BYTES = 65_536
ALIGNMENT = ("take-level: the arrival of XINGYING's UDP trigger, mapped onto the FDT clock; the trigger's network "
             "delay is in the cut and has not been measured")

_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>'
_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>", re.S)
_BARE_AMPERSAND = re.compile(r"&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)")
_KINDS = {"CaptureStart": "start", "CaptureStop": "stop"}
_WINDOWS_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                               *(f"LPT{i}" for i in range(1, 10))})


class NokovMessageError(ValueError):
    """A datagram that is not a XINGYING capture message, or one this module refuses to parse."""


@dataclass(frozen=True)
class CaptureMessage:
    """One CaptureStart or CaptureStop, with every field as sent (each child element's VALUE, by tag)."""

    kind: str  # "start" or "stop"
    name: str
    fields: dict[str, str]
    result: str | None  # the RESULT attribute of a CaptureStop, when present
    raw: bytes
    lenient: bool = False  # True when the message needed repair to parse
    encoding: str = "utf-8"
    warnings: tuple[str, ...] = ()

    @property
    def packet_id(self) -> str | None:
        return self.fields.get("PacketID")

    def key(self) -> tuple[str, str, str | None]:
        """Identity for de-duplication: one broadcast can arrive once per network card."""
        return (self.kind, self.name, self.packet_id)

    def summary(self, arrival: float | None = None) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "fields": dict(self.fields), "result": self.result,
                "lenient": self.lenient, "encoding": self.encoding, "warnings": list(self.warnings),
                "raw": self.raw.decode(self.encoding, errors="replace"), "arrival_host_s": arrival}


def parse_capture_message(data: bytes) -> CaptureMessage:
    """Parse one Remote Trigger / Remote Control datagram. Raises NokovMessageError for anything else."""
    if len(data) > MAX_MESSAGE_BYTES:
        raise NokovMessageError(f"datagram of {len(data)} bytes is larger than {MAX_MESSAGE_BYTES}")
    body = data.rstrip(b"\x00").strip()
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise NokovMessageError("document type and entity declarations are refused")
    warnings: list[str] = []
    try:
        text, encoding = body.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        try:
            text, encoding = body.decode("gbk"), "gbk"
        except UnicodeDecodeError:
            raise NokovMessageError("neither UTF-8 nor GBK text") from None
        warnings.append("decoded as GBK, not UTF-8")
    text = _XML_DECLARATION.sub("", text, count=1)
    lenient = False
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        repaired = _BARE_AMPERSAND.sub("&amp;", text)
        if repaired == text:
            raise NokovMessageError("not well-formed XML") from None
        try:
            root = ElementTree.fromstring(repaired)
        except ElementTree.ParseError:
            raise NokovMessageError("not well-formed XML, even with bare '&' escaped") from None
        lenient = True
        warnings.append("bare '&' escaped to parse")
    if root.tag not in _KINDS:
        raise NokovMessageError(f"root element {root.tag!r} is neither CaptureStart nor CaptureStop")
    fields: dict[str, str] = {}
    for child in root:
        value = child.get("VALUE")
        if value is None:
            continue
        if child.tag in fields:
            warnings.append(f"field {child.tag} repeated; the first is kept")
            continue
        fields[child.tag] = value
    name = fields.get("Name", "").strip()
    if not name:
        raise NokovMessageError(f"{root.tag} without a Name")
    result = root.get("RESULT")
    if result is not None and result.upper() != "SUCCESS":
        warnings.append(f"RESULT is {result!r}, not SUCCESS")
    return CaptureMessage(_KINDS[root.tag], name, fields, result, bytes(data), lenient, encoding, tuple(warnings))


def capture_start_message(name: str, database_path: str, *, session_name: str = "", notes: str = "",
                          delay: str = "", description: str = "", timecode: str = "00:00:00:00",
                          packet_id: int = 0) -> bytes:
    """Remote Control: ask XINGYING to start recording take `name` in `database_path`.

    Field order and declaration as in the manual's example. With rigid-body or body templates loaded, database_path
    must be XINGYING's current working directory, or the take cannot be opened in XINGYING's Edit mode (manual)."""
    _check_value("name", name, required=True)
    _check_value("database_path", database_path, required=True)
    return _message("CaptureStart", [("Name", name), ("SessionName", session_name), ("Notes", notes),
                                     ("Delay", delay), ("Description", description), ("DatabasePath", database_path),
                                     ("TimeCode", timecode), ("PacketID", str(int(packet_id)))])


def capture_stop_message(name: str, *, notes: str = "", assets: str = "", timecode: str = "00:00:00:00",
                         host_name: str = "", process_id: str = "", packet_id: int | None = None) -> bytes:
    """Remote Control: ask XINGYING to stop recording take `name`. Field order as in the manual's example."""
    _check_value("name", name, required=True)
    fields = [("Name", name), ("Notes", notes), ("Assets", assets), ("TimeCode", timecode), ("HostName", host_name),
              ("ProcessID", process_id)]
    if packet_id is not None:
        fields.append(("PacketID", str(int(packet_id))))
    return _message("CaptureStop", fields)


def _check_value(label: str, value: str, *, required: bool = False) -> None:
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{label} must be a non-empty string")
    if any(unicodedata.category(ch) == "Cc" for ch in value):
        raise ValueError(f"{label} must not contain control characters")


def _message(root: str, fields: list[tuple[str, str]]) -> bytes:
    for label, value in fields:
        _check_value(label, value)
    body = "".join(f'<{tag} VALUE="{escape(value, {chr(34): "&quot;"})}"/>' for tag, value in fields)
    return f"{_DECLARATION}<{root}>{body}</{root}>".encode("utf-8")


def take_file_stem(name: str, max_length: int = 100) -> str:
    """A safe file-name stem from a XINGYING take name: no path parts, control or reserved characters, not a Windows
    device name. Letters of every script are kept (take names are often Chinese)."""
    text = unicodedata.normalize("NFC", name)
    text = "".join("_" if ch in '<>:"/\\|?*' or unicodedata.category(ch).startswith("C") else ch for ch in text)
    text = re.sub(r"_{2,}", "_", text.strip().strip("."))[:max_length].rstrip(" .")
    if not text.strip("_ ."):
        text = "take"
    if text.split(".")[0].strip().upper() in _WINDOWS_RESERVED:
        text = "_" + text
    return text


def _item_time(item: Sample | Event | Gap) -> float:
    return item.start_t if isinstance(item, Gap) else item.t


def _finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


@dataclass
class Take:
    """One take: the FDT items between XINGYING's CaptureStart and CaptureStop, both mapped onto the FDT clock."""

    name: str
    start: CaptureMessage
    start_arrival: float
    start_t: float
    items: list[Sample | Event | Gap] = field(default_factory=list)
    stop: CaptureMessage | None = None
    stop_arrival: float | None = None
    stop_t: float | None = None
    notes: list[str] = field(default_factory=list)

    def samples(self) -> list[Sample]:
        return [item for item in self.items if isinstance(item, Sample)]

    def summary(self) -> dict[str, Any]:
        samples = self.samples()
        return {
            "name": self.name,
            "start": self.start.summary(self.start_arrival),
            "stop": None if self.stop is None else self.stop.summary(self.stop_arrival),
            "start_fdt_s": _finite(self.start_t),
            "stop_fdt_s": _finite(self.stop_t),
            "first_sample_fdt_s": samples[0].t if samples else None,
            "last_sample_fdt_s": samples[-1].t if samples else None,
            "samples_per_plate": {str(plate): n for plate, n in sorted(Counter(s.plate for s in samples).items())},
            "notes": list(self.notes),
            "alignment": ALIGNMENT,
        }


class TakeCutter:
    """Cuts takes out of a continuous FDT stream at XINGYING's CaptureStart and CaptureStop, in FDT time.

    Give it every item of FdtClient.samples() with add(item, arrival) and every trigger with trigger(message,
    arrival), both arrivals on one host clock (time.monotonic by default). Each call returns the takes it completed.
    A CaptureStart's arrival is mapped onto the FDT clock (sync.ClockMap, fitted on the samples' arrivals) and the
    take holds the items from there on, the pre-roll included, so a trigger that arrives after the take's first frames
    loses nothing. A CaptureStop ends the take at its mapped time once a sample at or past that time has arrived.
    Repeats of one broadcast (one per network card) are ignored; whatever else is unusual goes into the take's notes.
    """

    def __init__(self, *, preroll_s: float = 2.0, max_take_s: float = 600.0, dedupe_s: float = 2.0,
                 clock: ClockMap | None = None) -> None:
        if preroll_s < 0 or max_take_s <= 0 or dedupe_s < 0:
            raise ValueError("preroll_s and dedupe_s must be 0 or more and max_take_s above 0")
        self.clock = clock if clock is not None else ClockMap()
        self.preroll_s, self.max_take_s, self.dedupe_s = preroll_s, max_take_s, dedupe_s
        self.ignored: list[tuple[CaptureMessage, str]] = []
        self._buffer: deque[Sample | Event | Gap] = deque()
        self._open: Take | None = None
        self._latest_t: float | None = None
        self._seen: dict[tuple[str, str, str | None], float] = {}

    @property
    def open_take(self) -> Take | None:
        return self._open

    def add(self, item: Sample | Event | Gap, arrival: float) -> list[Take]:
        done: list[Take] = []
        if isinstance(item, Sample):
            self.clock.observe(item.t, arrival)
            self._latest_t = item.t if self._latest_t is None else max(self._latest_t, item.t)
            take = self._open
            if take is not None and math.isinf(take.start_t):
                take.start_t = item.t  # the CaptureStart came before any sample: the take starts with this one
            if take is not None and take.stop_t is not None and item.t >= take.stop_t:
                done.append(self._finish())
            elif take is not None and item.t - take.start_t > self.max_take_s:
                take.notes.append(f"no CaptureStop within {self.max_take_s:g} s: the take was closed there")
                done.append(self._finish(take.start_t + self.max_take_s))
        take = self._open
        if take is not None and _item_time(item) >= take.start_t:
            take.items.append(item)
        self._buffer.append(item)
        if self._latest_t is not None:
            while self._buffer and _item_time(self._buffer[0]) < self._latest_t - self.preroll_s:
                self._buffer.popleft()
        return done

    def trigger(self, message: CaptureMessage, arrival: float) -> list[Take]:
        last = self._seen.get(message.key())
        self._seen[message.key()] = arrival
        if last is not None and arrival - last <= self.dedupe_s:
            self.ignored.append((message, "repeat of a message already received (one copy per network card)"))
            return []
        done: list[Take] = []
        if message.kind == "start":
            if self._open is not None:
                self._open.notes.append(f"CaptureStart {message.name!r} arrived before a CaptureStop: closed there")
                done.append(self._finish(self._to_fdt(arrival)))
            start_t, notes = self._start_time(arrival)
            take = Take(message.name, message, arrival, start_t, notes=notes)
            if message.lenient:
                take.notes.append("CaptureStart needed repair to parse: " + "; ".join(message.warnings))
            take.items = [item for item in self._buffer if _item_time(item) >= start_t]
            self._open = take
            return done
        take = self._open
        if take is None:
            self.ignored.append((message, "CaptureStop without an open take"))
            return done
        if take.stop is not None:
            self.ignored.append((message, "a second CaptureStop for the same take"))
            return done
        take.stop, take.stop_arrival, take.stop_t = message, arrival, self._to_fdt(arrival)
        if message.name != take.name:
            take.notes.append(f"CaptureStop names {message.name!r}, CaptureStart named {take.name!r}")
        if message.result is not None and message.result.upper() != "SUCCESS":
            take.notes.append(f"CaptureStop RESULT is {message.result!r}")
        if message.lenient:
            take.notes.append("CaptureStop needed repair to parse: " + "; ".join(message.warnings))
        if self._latest_t is not None and self._latest_t >= take.stop_t:
            done.append(self._finish())
        return done

    def close(self) -> list[Take]:
        """End of the recording: an open take is closed with what it has."""
        if self._open is None:
            return []
        take = self._open
        if take.stop is None:
            take.notes.append("the recorder stopped before a CaptureStop arrived")
            return [self._finish(math.inf)]
        take.notes.append("the recorder stopped before samples past the CaptureStop time arrived")
        return [self._finish()]

    def _start_time(self, arrival: float) -> tuple[float, list[str]]:
        try:
            start_t = self.clock.to_device(arrival)
        except ValueError:
            return -math.inf, ["CaptureStart arrived before any FDT sample: the take starts with the first sample"]
        notes = [] if self.clock.drift_ppm is not None else ["clock mapping still in its warm-up (first 3 s)"]
        return start_t, notes

    def _to_fdt(self, arrival: float) -> float:
        try:
            return self.clock.to_device(arrival)
        except ValueError:
            return -math.inf

    def _finish(self, stop_t: float | None = None) -> Take:
        take = self._open
        assert take is not None
        if stop_t is not None:
            take.stop_t = stop_t
        end = take.stop_t if take.stop_t is not None else math.inf
        take.items = [item for item in take.items if _item_time(item) < end]
        self._open = None
        return take


def write_take(take: Take, out_dir: str | Path, rate_hz: float, fmt: str = "csv") -> list[Path]:
    """Write a take as <name>.csv (+ .csv.json) or <name>.c3d, and <name>.nokov.json with the triggers. A name that
    exists already gets -2, -3, ...: nothing is overwritten. A take without samples gets only the .nokov.json."""
    from .writers import Recording, write_c3d, write_csv

    if fmt not in ("csv", "c3d"):
        raise ValueError("fmt is 'csv' or 'c3d'")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = _free_stem(out, take_file_stem(take.name))
    summary = take.summary()
    paths: list[Path] = []
    if take.samples():
        recording = Recording.from_samples(take.items, rate_hz, metadata={
            "source": "live FDT stream, cut by XINGYING Remote Trigger", "nokov": summary})
        if fmt == "csv":
            paths.append(write_csv(recording, out / f"{stem}.csv"))
        else:
            paths.extend(write_c3d(recording, out / f"{stem}.c3d", gaps="split"))
    else:
        summary["notes"].append("no FDT samples in the take")
    sidecar = out / f"{stem}.nokov.json"
    sidecar.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return [*paths, sidecar]


def _free_stem(out: Path, stem: str) -> str:
    candidate, n = stem, 1
    while any((out / f"{candidate}{suffix}").exists() for suffix in (".csv", ".csv.json", ".c3d", ".nokov.json")) \
            or any(out.glob(f"{glob.escape(candidate)}-part*.c3d")):
        n += 1
        candidate = f"{stem}-{n}"
    return candidate


class _TriggerProtocol(asyncio.DatagramProtocol):
    def __init__(self, listener: TriggerListener) -> None:
        self.listener = listener

    def datagram_received(self, data: bytes, addr: Any) -> None:
        self.listener._received(data, addr)

    def error_received(self, exc: Exception) -> None:  # pragma: no cover - platform dependent
        self.listener.rejected.append((None, f"socket error: {exc}"))


class TriggerListener:
    """Receives XINGYING's Remote Trigger broadcasts (UDP, port 7061 by default).

        async with TriggerListener() as listener:
            async for message, arrival, address in listener: ...

    arrival is clock() when the datagram arrived (time.monotonic by default). Datagrams that are not capture messages
    are kept in .rejected (address, reason), the last 100, and never raised. On Windows the firewall must let
    XINGYING's broadcasts in (allow Python, or the port, for the network XINGYING is on)."""

    def __init__(self, host: str = "0.0.0.0", port: int = TRIGGER_PORT, *, clock: Callable[[], float] = time.monotonic,
                 queue_size: int = 256) -> None:
        self.host, self.requested_port, self.clock = host, port, clock
        self.rejected: deque[tuple[Any, str]] = deque(maxlen=100)
        self.dropped = 0
        self._queue: asyncio.Queue[tuple[CaptureMessage, float, Any]] = asyncio.Queue(maxsize=queue_size)
        self._transport: asyncio.DatagramTransport | None = None

    @property
    def port(self) -> int:
        if self._transport is None:
            return self.requested_port
        return int(self._transport.get_extra_info("sockname")[1])

    async def __aenter__(self) -> TriggerListener:
        loop = asyncio.get_running_loop()
        try:
            transport, _ = await loop.create_datagram_endpoint(lambda: _TriggerProtocol(self),
                                                               local_addr=(self.host, self.requested_port))
        except OSError as error:
            raise OSError(error.errno, f"cannot listen on UDP {self.host}:{self.requested_port} for XINGYING's "
                                       f"Remote Trigger ({error.strerror}); is another program using the port?") from None
        self._transport = transport
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def __aiter__(self) -> TriggerListener:
        return self

    async def __anext__(self) -> tuple[CaptureMessage, float, Any]:
        return await self._queue.get()

    def _received(self, data: bytes, addr: Any) -> None:
        arrival = self.clock()
        try:
            message = parse_capture_message(data)
        except NokovMessageError as error:
            self.rejected.append((addr, str(error)))
            return
        try:
            self._queue.put_nowait((message, arrival, addr))
        except asyncio.QueueFull:
            self.dropped += 1


def send_capture_message(message: bytes, host: str, port: int = CONTROL_PORT) -> int:
    """Send one Remote Control message (capture_start_message / capture_stop_message) to XINGYING. Returns bytes sent.
    Broadcast addresses work too (SO_BROADCAST is set)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        return sock.sendto(message, (host, port))


async def record_takes(items: Any, rate_hz: float, out_dir: str | Path, listener: TriggerListener, *,
                       fmt: str = "csv", preroll_s: float = 2.0, max_take_s: float = 600.0,
                       on_item: Callable[[Sample | Event | Gap], None] | None = None,
                       on_trigger: Callable[[CaptureMessage], None] | None = None,
                       log: Callable[[str], None] = print) -> list[list[Path]]:
    """Record takes until `items` ends (or the task is cancelled): items is FdtClient.samples(), listener an open
    TriggerListener on the same host clock (time.monotonic). Returns the paths written, one list per take."""
    cutter = TakeCutter(preroll_s=preroll_s, max_take_s=max_take_s)
    written: list[list[Path]] = []

    def finished(takes: Iterable[Take]) -> None:
        for take in takes:
            paths = write_take(take, out_dir, rate_hz, fmt)
            written.append(paths)
            counts = ", ".join(f"plate {p}: {n}" for p, n in take.summary()["samples_per_plate"].items()) or "no samples"
            log(f"take {take.name!r} ({counts}) -> {paths[0].name}" + (f"; {'; '.join(take.notes)}" if take.notes else ""))

    async def triggers() -> None:
        async for message, arrival, address in listener:
            host = address[0] if isinstance(address, tuple) else address
            log(f"Capture{message.kind.title()} {message.name!r} from {host}" + (" (repaired)" if message.lenient else ""))
            known = len(cutter.ignored)
            finished(cutter.trigger(message, arrival))
            repeat = any(reason.startswith("repeat") for _, reason in cutter.ignored[known:])
            if on_trigger is not None and not repeat:  # one marker per broadcast, not one per network card
                on_trigger(message)
            while cutter.ignored:
                ignored, reason = cutter.ignored.pop(0)
                log(f"ignored Capture{ignored.kind.title()} {ignored.name!r}: {reason}")

    task = asyncio.create_task(triggers())
    try:
        async for item in items:
            arrival = time.monotonic()
            if on_item is not None:
                on_item(item)
            finished(cutter.add(item, arrival))
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finished(cutter.close())
    return written


# --- The FDT's analog outputs as an analog force plate in XINGYING (worksheet) ------------------------------------

_XINGYING_ORDER = ("fx", "fy", "fz", "mx", "my", "mz")


def analog_worksheet(firmware: str | None = None, plates: Iterable[int] = (1, 2)) -> dict[str, Any]:
    """What to enter in XINGYING for the FDT's analog outputs read through an NI DAQ, as data.

    'derived' holds what follows from our analog contract (contracts/analog-outputs.v1.json) and the C3D type-2
    convention our C3D writer uses (forces and moments in the FDT's wire signs, moments about the top surface centre,
    origin 0; read back correctly by Visual3D and OpenSim, measured); 'unknown' lists what XINGYING's manual does not
    settle; 'check' is the known-load procedure that settles it on site. Not run in XINGYING."""
    plates = tuple(plates)
    if not set(plates) <= {1, 2}:
        raise ValueError("the analog board has outputs for plates 1 and 2")
    if firmware is not None:
        parts = [int(p) for p in re.findall(r"\d+", firmware)][:4]
        if len(parts) == 4 and parts < [1, 2, 8, 21]:
            raise ValueError(f"firmware {firmware}: the moment outputs are 100 times too large before 1.2.8.21; "
                             "update the FDT before using its analog outputs (docs/23)")
    d = MOMENT_REFERENCE_DEPTH_M
    per_plate = []
    for plate in plates:
        by_signal = {spec.signal: spec for spec in OUTPUTS.values() if spec.plate == plate}
        wiring = [{"xingying_channel": k + 1, "signal": name, "fdt_output": by_signal[name].output,
                   "unit_per_volt": by_signal[name].units_per_volt, "unit": by_signal[name].unit.replace("·", "*")}
                  for k, name in enumerate(_XINGYING_ORDER)]
        gain = [by_signal[name].units_per_volt for name in _XINGYING_ORDER]
        # Rows Fx Fy Fz Mx My Mz, columns XINGYING channels 1-6 (wired as above). Moments moved from the FDT's reference
        # d below the top to the top surface centre, as write_c3d does: Mx - d*Fy, My + d*Fx (wire signs).
        surface = [[0.0] * 6 for _ in range(6)]
        for k in range(6):
            surface[k][k] = gain[k]
        surface[3][1] = -d * gain[1]
        surface[4][0] = d * gain[0]
        diagonal = [[gain[k] if j == k else 0.0 for j in range(6)] for k in range(6)]
        per_plate.append({
            "plate": plate,
            "wiring": wiring,
            "unused_outputs": [by_signal["cop_x"].output, by_signal["cop_y"].output],
            "matrix_surface_moments": surface,
            "matrix_diagonal": diagonal,
        })
    return {
        "derived": {
            "plates": per_plate,
            "plate_size_mm": {"x_width": 350, "y_length": 600},
            "matrix_units": "rows Fx Fy Fz in N per V, Mx My Mz in N*m per V; columns are XINGYING channels 1-6",
            "candidate_a": "matrix_surface_moments with the plate origin at (0, 0, 0): moments already at the top "
                           "surface, as in our C3D files (preferred: no origin sign to get right)",
            "candidate_b": f"matrix_diagonal with the plate origin {d * 1000:.0f} mm below the top surface centre, if "
                           "XINGYING has an origin field (its sign convention is not documented)",
            "signs": "the FDT's wire signs, the frame of the C3D type-2 plates our C3D writer produces "
                     "(Fy and Mx opposite to Movetrics Studio's CSV)",
            "firmware": "moment outputs are valid from firmware 1.2.8.21; on an F1-3D S plate Mz is derived (0.02 m x Fx)",
            "ni_range_v": 10,
        },
        "unknown": [
            "which XINGYING force plate type to select for a six-channel conditioned plate (no generic type is "
            "documented; the AMTI and Bertec analog types take six channels and a calibration matrix)",
            "whether XINGYING's matrix takes N*m per V or N*mm per V for moments (its AMTI recipe applies one formula "
            "to all six channels, which suggests N*m); the off-centre load below tells",
            "the axis convention of the selected type, and how XINGYING orients the plate in the lab",
            "whether XINGYING has an origin (offset) field for analog plates (needed only for candidate_b)",
            "which way the FDT plate's +x and +y point relative to its cable connector (not yet stated by the maker)",
        ],
        "check": [
            "Set Force Units to Newtons. Zero with the plates empty (XINGYING's zeroing option, or subtract each "
            "channel's mean over a few seconds empty): the FDT's analog zero differs per unit by up to tens of mV, "
            "and 58 mV is 46 N of Fz.",
            "Put a known weight W at the plate centre: Fz must read W (within the 1.8 % gain tolerance), Fx and Fy "
            "near 0, the centre of pressure at the plate centre.",
            "Move the weight 100 mm along the plate's long side, then 100 mm along the short side: the centre of "
            "pressure must move 100 mm the same way in XINGYING's view. Moving the other way means the plate is "
            "rotated in XINGYING (or a moment row has the wrong sign); moving 1000 times too little or too much means "
            "the moment unit is wrong (N*m vs N*mm).",
            "Push horizontally along +x and +y of XINGYING's plate: Fx and Fy must take the sign XINGYING shows for "
            "that direction.",
            "Later, for a proper comparison: record the same take digitally with movetrics-fdt nokov-record and "
            "compare with XINGYING's Forces export.",
        ],
        "limits": [
            "the outputs update at most 500 times per second per plate; sampling them faster adds nothing",
            "they lag the force by about 12 ms (frame latency, docs/23), so forces sit about 12 ms behind the markers",
            "moments travel as whole N*m, so the centre of pressure moves in steps of 1 N*m / Fz "
            "(1.25 mm at 800 N, 10 mm at 100 N)",
            "do not use the CoP outputs (1 cm steps, origin and sign not stated): XINGYING computes the centre of "
            "pressure from forces and moments",
            "XINGYING says analog devices cannot be used interchangeably with digital force plates or digital EMG "
            "(for example Noraxon over its SDK): with digital EMG in XINGYING use take sync or LSL instead",
        ],
    }


def format_worksheet(sheet: dict[str, Any]) -> str:
    """The worksheet as text, for a terminal or a lab notebook."""
    derived = sheet["derived"]
    lines = ["FDT analog outputs as a XINGYING analog force plate (derived from the Movetrics analog contract; "
             "not run in XINGYING)", ""]
    for plate in derived["plates"]:
        lines.append(f"Plate {plate['plate']}: wire FDT output -> XINGYING channel")
        for wire in plate["wiring"]:
            lines.append(f"  channel {wire['xingying_channel']} ({wire['signal']}): {wire['fdt_output']}, "
                         f"{wire['unit_per_volt']:g} {wire['unit']} per V")
        lines.append(f"  leave unconnected: {', '.join(plate['unused_outputs'])} (centre of pressure, 1 cm steps)")
        lines.append("  calibration matrix, candidate A (moments at the top surface, origin 0):")
        for name, row in zip(("Fx", "Fy", "Fz", "Mx", "My", "Mz"), plate["matrix_surface_moments"]):
            lines.append(f"    {name}: " + "  ".join(f"{value:8.3f}" for value in row))
        lines.append("")
    lines += [f"Units: {derived['matrix_units']}.", f"Candidate A: {derived['candidate_a']}.",
              f"Candidate B: {derived['candidate_b']}.", f"Signs: {derived['signs']}.",
              f"Plate size: {derived['plate_size_mm']['x_width']} mm (x) by {derived['plate_size_mm']['y_length']} mm (y). "
              f"NI range: +/-{derived['ni_range_v']} V. {derived['firmware'][:1].upper()}{derived['firmware'][1:]}.", "",
              "Not settled by XINGYING's manual:"]
    lines += [f"  - {item}" for item in sheet["unknown"]]
    lines += ["", "Check on site before use:"]
    lines += [f"  {n}. {item}" for n, item in enumerate(sheet["check"], start=1)]
    lines += ["", "Limits:"]
    lines += [f"  - {item}" for item in sheet["limits"]]
    return "\n".join(lines)
