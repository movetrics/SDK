#!/usr/bin/env python3
"""Draws the four SVG diagrams of the docs site and the README into site/public/diagrams/.

Each SVG carries its own background panel and a prefers-color-scheme block, so it reads on GitHub and on the docs site
in light and dark mode. The jump curve comes from the SDK's own simulator (simulated, never a measured jump) and the
frame diagram from a stream frame captured from a real FDT (vectors/stream_frames.json), so both stay true to the code.

    python3 tools/gen_diagrams.py
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

SDK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK / "python"))

from movetrics_fdt.simulator import Synthetic  # noqa: E402

OUT = SDK / "site" / "public" / "diagrams"
FONT = 'ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif'
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

STYLE = f"""<style>
text{{font-family:{FONT};font-size:12.5px}}
.mono{{font-family:{MONO}}}
.bg{{fill:#fcfcfb;stroke:#e4e3df}}
.t1{{fill:#1b1b1a}} .t2{{fill:#5a5955}} .t3{{fill:#7a7974}}
.box{{fill:#f3f2ef;stroke:#cfcec8}}
.dash{{fill:none;stroke:#9a9993;stroke-dasharray:5 4}}
.acc{{fill:#e3f6f0;stroke:#0f7a63}} .accT{{fill:#0b5e4c}}
.acc2{{fill:#e5f0fb;stroke:#2a78d6}} .acc2T{{fill:#174f91}}
.ln{{stroke:#6a6964;fill:none}} .head{{fill:#6a6964}}
.curve{{stroke:#0f7a63;fill:none}} .band{{fill:#e3f6f0}}
.grid{{stroke:#e9e8e4}} .axis{{stroke:#b5b4ae}}
@media (prefers-color-scheme: dark){{
.bg{{fill:#1a1a19;stroke:#33322f}}
.t1{{fill:#f0efec}} .t2{{fill:#c3c2b7}} .t3{{fill:#9a998f}}
.box{{fill:#252523;stroke:#45443f}} .dash{{stroke:#7a7972}}
.acc{{fill:#0b2f2a;stroke:#3fbf9c}} .accT{{fill:#9fe8d2}}
.acc2{{fill:#13263d;stroke:#3987e5}} .acc2T{{fill:#a9cdf5}}
.ln{{stroke:#a9a89f}} .head{{fill:#a9a89f}}
.curve{{stroke:#3fbf9c}} .band{{fill:#0f2c27}}
.grid{{stroke:#2c2b29}} .axis{{stroke:#4a4944}}
}}
</style>"""

DEFS = """<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
<path class="head" d="M0 0L10 5L0 10z"/></marker></defs>"""


def svg(name: str, width: int, height: int, title: str, desc: str, body: list[str]) -> None:
    text = "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-labelledby="title desc">',
        f"<title id=\"title\">{title}</title>",
        f"<desc id=\"desc\">{desc}</desc>",
        STYLE,
        DEFS,
        f'<rect class="bg" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12"/>',
        *body,
        "</svg>",
        "",
    ])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(text, encoding="utf-8")


def esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def label(x: float, y: float, lines: list[str], cls: str = "t2", anchor: str = "middle", size: float | None = None,
          weight: str | None = None, step: float = 16) -> str:
    style = f' font-size="{size}"' if size else ""
    style += f' font-weight="{weight}"' if weight else ""
    spans = "".join(f'<tspan x="{x}" dy="{0 if i == 0 else step}">{esc(line)}</tspan>' for i, line in enumerate(lines))
    return f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}"{style}>{spans}</text>'


def box(x: float, y: float, w: float, h: float, cls: str, head: str, lines: list[str], head_cls: str = "t1",
        line_cls: str = "t2") -> list[str]:
    total = 18 + 16 * len(lines)
    top = y + (h - total) / 2 + 13
    out = [f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="8" stroke-width="1.5"/>',
           label(x + w / 2, top, [head], head_cls, size=14, weight="600")]
    if lines:
        out.append(label(x + w / 2, top + 18, lines, line_cls))
    return out


def arrow(x1: float, y1: float, x2: float, y2: float) -> str:
    return f'<path class="ln" d="M{x1} {y1}L{x2} {y2}" stroke-width="1.5" marker-end="url(#a)"/>'


def data_path() -> None:
    body = [label(16, 30, ["Where the SDK sits"], "t1", "start", 15, "600")]
    body += box(16, 184, 120, 80, "box", "F1-3D plates", ["one or two", "force and moment", "up to 2,000/s each"])
    body += box(170, 56, 120, 336, "box", "FDT", ["Force Data", "Terminal", "", "stamps every", "sample with", "its own clock"])
    body.append(arrow(136, 224, 168, 224))
    # Lane A: live data through the SDK.
    body += box(420, 56, 170, 100, "acc", "Movetrics SDK", ["Python, TypeScript,", "MATLAB; a real FDT", "or the simulator"], "accT", "accT")
    body += box(616, 56, 188, 100, "box", "Your tools", ["your app or dashboard", "CSV, C3D, OpenSim .mot", "LabRecorder with EMG,", "EEG and cameras"])
    body.append(arrow(290, 106, 418, 106))
    body.append(label(355, 84, ["USB-C or Bluetooth", "every sample, live"], "t3", size=11.5, step=14))
    body.append(arrow(590, 106, 614, 106))
    # Lane B: recordings through the Cloud.
    body += box(420, 180, 170, 56, "box", "Studio or the app", ["records and uploads"])
    body += box(616, 180, 188, 56, "box", "Movetrics Cloud", ["results from the engine"])
    body += box(616, 256, 188, 56, "acc", "Read-only Cloud API", ["Excel, Python, MATLAB, AI"], "accT", "accT")
    body.append(arrow(290, 208, 418, 208))
    body.append(label(355, 200, ["recordings"], "t3", size=11.5))
    body.append(arrow(590, 208, 614, 208))
    body.append(arrow(710, 236, 710, 254))
    # Lane C: analog outputs.
    body += box(420, 336, 170, 56, "box", "Your DAQ or EMG", ["records the voltages"])
    body += box(616, 336, 188, 56, "acc", "movetrics_fdt.analog", ["volts back to N and N·m"], "accT", "accT")
    body.append(arrow(290, 364, 418, 364))
    body.append(label(355, 342, ["±10 V analog outputs", "(analog FDT)"], "t3", size=11.5, step=14))
    body.append(arrow(590, 364, 614, 364))
    # Legend.
    body.append('<rect class="acc" x="16" y="414" width="14" height="14" rx="3" stroke-width="1.5"/>')
    body.append(label(36, 425, ["part of the SDK"], "t2", "start"))
    body.append('<rect class="box" x="150" y="414" width="14" height="14" rx="3" stroke-width="1.5"/>')
    body.append(label(170, 425, ["Movetrics product or your own system"], "t2", "start"))
    svg("data-path.svg", 820, 446, "Where the Movetrics SDK sits",
        "Plates feed the FDT. Live data reaches the SDK over USB-C or Bluetooth and goes on to your tools; recordings "
        "go through Studio or the app to Movetrics Cloud, whose read-only API the SDK reads; voltages from the analog "
        "outputs are turned back into newtons by the SDK.", body)


def jump_curve() -> None:
    signal = Synthetic(kind="cmj")
    t_lo, t_hi, f_hi = 0.5, 4.5, 3200.0
    x0, x1, y_top, y_zero = 64.0, 800.0, 60.0, 320.0

    def x(t: float) -> float:
        return x0 + (t - t_lo) / (t_hi - t_lo) * (x1 - x0)

    def y(force: float) -> float:
        return y_zero - max(force, 0.0) / f_hi * (y_zero - y_top)

    # 2,000 samples per second as the simulator streams them, both plates added; every 5th sample is drawn.
    points = []
    for i in range(int(t_lo * 2000), int(t_hi * 2000) + 1, 5):
        t = i / 2000
        total = signal.values(1, t)[2] + signal.values(2, t)[2]
        points.append(f"{x(t):.1f} {y(total):.1f}")
    weight = signal.bodyweight_n
    flight = 3.3 - 2.85  # the simulator's flight phase, simulator.py Synthetic._total
    height = 9.81 * flight ** 2 / 8

    body = [label(16, 30, ["A countermovement jump, as the SDK delivers it"], "t1", "start", 15, "600")]
    body.append(f'<rect class="band" x="{x(2.85):.1f}" y="{y_top}" width="{x(3.3) - x(2.85):.1f}" height="{y_zero - y_top}"/>')
    for force in (1000, 2000, 3000):
        body.append(f'<path class="grid" d="M{x0} {y(force):.1f}H{x1}" stroke-width="1"/>')
        body.append(label(x0 - 8, y(force) + 4, [f"{force:,}"], "t3", "end", 11.5))
    body.append(f'<path class="axis" d="M{x0} {y_zero}H{x1}" stroke-width="1"/>')
    body.append(label(x0 - 8, y_zero + 4, ["0"], "t3", "end", 11.5))
    for second in (1, 2, 3, 4):
        body.append(f'<path class="axis" d="M{x(second):.1f} {y_zero}v5" stroke-width="1"/>')
        body.append(label(x(second), y_zero + 19, [f"{second} s"], "t3", size=11.5))
    body.append(label(x0, 50, ["vertical force, both plates (N)"], "t3", "start", 11.5))
    body.append(f'<path class="ln" d="M{x0} {y(weight):.1f}H{x1}" stroke-width="1" stroke-dasharray="4 4"/>')
    body.append(f'<path class="curve" d="M{"L".join(points)}" stroke-width="2" stroke-linejoin="round"/>')
    body.append(label(x(0.55), y(weight) - 8, ["standing still"], "t2", "start"))
    body.append(label(x(0.55), y(weight) + 18, [f"body weight {weight:.0f} N"], "t3", "start", 11.5))
    body.append(label(x(2.17), y(0) - 8, ["dip"], "t2"))
    body.append(label(x(2.6), y(weight * 2.4) - 10, ["push-off"], "t2"))
    body.append(label(x(3.075), y(0) - 26, [f"{flight:.2f} s"], "accT", weight="600"))
    body.append(label(x(3.075), y(0) - 10, ["in the air"], "accT", size=11.5))
    body.append(label(x(3.52), y(weight * 4) + 4, ["landing"], "t2", "start"))
    body.append(label(x(3.62), y(2300), ["Jump height from the time", "in the air: g·t²/8",
                                         f"= 9.81 × {flight:.2f}² / 8 ≈ {height:.2f} m"], "t2", "start", step=17))
    body.append(label(16, 368, ["Simulated, not measured: movetrics-fdt simulate --signal cmj, body weight 750 N, "
                                "2,000 samples per second per plate."], "t3", "start", 11.5))
    svg("cmj.svg", 820, 386, "A countermovement jump from the SDK's simulator",
        f"Total vertical force of both plates over time: standing at {weight:.0f} N, a dip, a push-off to about "
        f"{weight * 2.4:.0f} N, {flight:.2f} s in the air at 0 N, and a landing spike. Jump height from flight time is "
        f"about {height:.2f} m. Simulated.", body)


def frame_layout() -> None:
    cases = json.loads((SDK / "vectors" / "stream_frames.json").read_text(encoding="utf-8"))["cases"]
    case = next(c for c in cases if c["id"] == "stream-anchor-fdt-index-19056")
    raw = bytes.fromhex(case["frame_hex"])
    plate, code, stamp, *values = struct.unpack("<BBIhhhhhh", raw[2:20])
    x0, w, top = 26.0, 32.0, 76.0

    def cx(index: float) -> float:
        return x0 + index * w + w / 2

    groups = [  # first byte, last byte, class, label lines
        (0, 1, "box", ["start"]), (2, 2, "box", ["plate"]), (3, 3, "box", ["", "code"]),
        (4, 7, "acc2", ["time stamp", "0.1 ms ticks"]), (8, 19, "acc", ["Fx  Fy  Fz  Mx  My  Mz", "2 bytes each, signed"]),
        (20, 21, "box", ["CRC"]), (22, 23, "box", ["end"]),
    ]
    body = [label(16, 28, ["One stream frame: 24 bytes per plate per sample"], "t1", "start", 15, "600")]
    left, right = x0 + 2 * w, x0 + 20 * w
    body.append(f'<path class="ln" d="M{left + 2} 58v-6H{right - 2}v6" stroke-width="1.2"/>')
    body.append(label((left + right) / 2, 46, ["CRC-16/CCITT-FALSE over bytes 2 to 19, stored low byte first"], "t3", size=11.5))
    for first, last, cls, lines in groups:
        for index in range(first, last + 1):
            body.append(f'<rect class="{cls}" x="{x0 + index * w + 1}" y="{top}" width="{w - 2}" height="38" rx="4" stroke-width="1.2"/>')
            body.append(f'<text class="mono {"accT" if cls == "acc" else "acc2T" if cls == "acc2" else "t1"}" x="{cx(index)}" '
                        f'y="{top + 24}" text-anchor="middle" font-size="13">{raw[index]:02X}</text>')
            body.append(f'<text class="mono t3" x="{cx(index)}" y="{top - 6}" text-anchor="middle" font-size="10.5">{index}</text>')
        a, b = x0 + first * w + 3, x0 + (last + 1) * w - 3
        body.append(f'<path class="ln" d="M{a} {top + 46}v5H{b}v-5" stroke-width="1.2"/>')
        size = 11 if last == first else 12.5
        body.append(label((a + b) / 2, top + 68, lines, "t2", size=size, step=15))
    fields = ", ".join(str(v) for v in values)
    body.append(label(16, 204, [f"Captured from a real FDT: plate {plate}, code {code:02X}, stamp {stamp:,} ticks = {stamp / 10000:.4f} s, "
                                f"readings {fields}."], "t3", "start", 11.5))
    body.append(label(16, 221, ["The vocabulary (chapter 19) turns the readings into N and N·m with Studio's signs."], "t3", "start", 11.5))
    svg("frame.svg", 820, 238, "The 24-byte stream frame",
        "Bytes 0 and 1 are BE EF, byte 2 the plate, byte 3 the code 01, bytes 4 to 7 the time stamp in 0.1 ms ticks, "
        "bytes 8 to 19 six signed 16-bit readings, bytes 20 and 21 the CRC over bytes 2 to 19, and bytes 22 and 23 the "
        "end marker 04 04.", body)


def contract() -> None:
    body = [label(16, 30, ["One contract, one set of test data, every client"], "t1", "start", 15, "600")]
    body += box(16, 92, 180, 118, "acc", "The contract", ["docs/: every byte", "vocabulary: names,", "units, axes, signs"], "accT", "accT")
    body += box(236, 92, 190, 118, "box", "Shared test data", ["vectors/: 53 byte cases,", "7 vocabulary cases,", "sync and C3D golden files"])
    body.append(arrow(196, 151, 234, 151))
    rows = [("Python", "250 tests", "acc"), ("TypeScript", "202 tests", "acc"), ("MATLAB", "61 checks, in Octave", "acc"),
            ("Your client", "C#, Swift, Rust, …", "dash")]
    for i, (name, note, cls) in enumerate(rows):
        top = 48 + i * 58
        if cls == "dash":
            body.append(f'<rect class="dash" x="466" y="{top}" width="168" height="46" rx="8" stroke-width="1.5"/>')
        else:
            body.append(f'<rect class="box" x="466" y="{top}" width="168" height="46" rx="8" stroke-width="1.5"/>')
        body.append(label(550, top + 20, [name], "t1", size=13.5, weight="600"))
        body.append(label(550, top + 36, [note], "t2", size=11.5))
        body.append(f'<path class="ln" d="M426 151C446 151 446 {top + 23} 464 {top + 23}" stroke-width="1.5" marker-end="url(#a)"/>')
        body.append(f'<path class="ln" d="M634 {top + 23}C652 {top + 23} 652 151 670 151" stroke-width="1.5" marker-end="url(#a)"/>')
    body += box(672, 102, 132, 98, "box", "CONFORMANCE.md", ["which client", "read which file,", "and passed"])
    body.append(label(16, 292, ["A client is correct when it passes every case; the report never marks a file passed for a client that does not read it."],
                      "t3", "start", 11.5))
    svg("contract.svg", 820, 310, "How the SDK is checked",
        "A written contract produces shared test data: 53 byte-level cases, 7 vocabulary cases and golden files. The "
        "Python, TypeScript and MATLAB clients, and any client you write, run the same files; CONFORMANCE.md records "
        "which client read which file and passed.", body)


if __name__ == "__main__":
    data_path()
    jump_curve()
    frame_layout()
    contract()
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.svg"))))
