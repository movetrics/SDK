"""Command line: python -m movetrics_fdt simulate ...  (or the movetrics-fdt script after pip install).

    movetrics-fdt simulate --tcp 7800                     # a virtual FDT 1.2.8.20 on 127.0.0.1:7800
    movetrics-fdt simulate --pty /tmp/fdt --profile sync  # a serial-like device with the sync modes (draft)
    movetrics-fdt simulate --tcp 7800 --replay exam-channels.csv
    movetrics-fdt simulate --tcp 7800 --signal cmj --sync-pulse-s 1 --clock-ppm 30 --drop-every 500
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from . import __version__
from .simulator import PROFILES, Faults, StudioReplay, Synthetic, VirtualFdt
from .simulator_io import serve_pty, serve_tcp


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="movetrics-fdt", description=f"Movetrics FDT tools, SDK {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    sim = commands.add_parser("simulate", help="run a virtual FDT that speaks the real protocol")
    where = sim.add_mutually_exclusive_group(required=True)
    where.add_argument("--tcp", type=int, metavar="PORT", help="listen on 127.0.0.1:PORT (0 picks a free port)")
    where.add_argument("--pty", metavar="PATH", help="create a pseudo-terminal at PATH (Linux, macOS)")
    sim.add_argument("--host", default="127.0.0.1", help="address for --tcp (default 127.0.0.1)")
    sim.add_argument("--profile", choices=sorted(PROFILES), default="1.2.8.20", help="firmware line to behave like")
    sim.add_argument("--signal", choices=("stand", "cmj", "empty"), default="stand")
    sim.add_argument("--bodyweight", type=float, default=750.0, help="N, for --signal stand and cmj")
    sim.add_argument("--replay", metavar="CSV", help="replay a Movetrics Studio -channels.csv instead")
    sim.add_argument("--fill-gaps", action="store_true", help="with --replay: send frames through the file's gaps")
    sim.add_argument("--plates", type=int, choices=(1, 2), default=2)
    sim.add_argument("--drop-every", type=int, default=0, metavar="N", help="drop one frame in N")
    sim.add_argument("--hold", nargs=2, type=float, metavar=("AT_S", "FOR_S"), help="send nothing for FOR_S s from AT_S")
    sim.add_argument("--clock-ppm", type=float, default=0.0, help="FDT clock runs this many ppm fast")
    sim.add_argument("--scale", type=float, default=1.0, help="multiply every load (20 provokes the int16 wrap)")
    sim.add_argument("--asleep", action="store_true", help="start asleep (pads off), as 5 minutes after the last command")
    sim.add_argument("--sync-pulse-s", type=float, default=0.0, metavar="S",
                     help="drive SYNC IN with a 5 ms pulse every S seconds (needs --profile sync to be seen)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    signal = StudioReplay(args.replay, keep_gaps=not args.fill_gaps) if args.replay else Synthetic(args.signal, args.bodyweight)
    hold_at, hold_for = args.hold or (-1.0, 0.0)
    faults = Faults(drop_every=args.drop_every, hold_at_s=hold_at, hold_s=hold_for, clock_ppm=args.clock_ppm, scale=args.scale)
    plates = tuple(plate for plate in signal.plates if plate <= args.plates)

    def make() -> VirtualFdt:
        import time

        fdt = VirtualFdt(args.profile, signal, faults, now=time.monotonic(), plates=plates)
        fdt.asleep = args.asleep
        return fdt

    tick = None
    if args.sync_pulse_s > 0:
        def tick(fdt: VirtualFdt, now: float) -> None:
            phase = now % args.sync_pulse_s
            fdt.sync_in(1 if phase < 0.005 else 0, now)

    def said(*where: object) -> None:
        print("READY " + ":".join(str(part) for part in where), flush=True)

    try:
        if args.tcp is not None:
            asyncio.run(serve_tcp(make, args.host, args.tcp, ready=said, on_tick=tick))
        else:
            asyncio.run(serve_pty(make, args.pty, ready=said, on_tick=tick))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
