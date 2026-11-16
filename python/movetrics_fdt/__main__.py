"""Command line: python -m movetrics_fdt simulate ...  (or the movetrics-fdt script after pip install).

    movetrics-fdt simulate --tcp 7800                     # a virtual FDT 1.2.8.20 on 127.0.0.1:7800
    movetrics-fdt simulate --pty /tmp/fdt --profile sync  # a serial-like device with the sync modes
    movetrics-fdt simulate --tcp 7800 --replay exam-channels.csv
    movetrics-fdt simulate --tcp 7800 --signal cmj --sync-pulse-s 1 --clock-ppm 30 --drop-every 500
    movetrics-fdt lsl-relay                               # a web page's FDT stream on to LSL (ws://127.0.0.1:7812)
    movetrics-fdt nokov-record --serial COM3              # FDT takes cut by NOKOV XINGYING's start/stop (docs/24)
    movetrics-fdt nokov-analog-setup                      # the FDT's analog outputs as a XINGYING force plate
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
    relay = commands.add_parser("lsl-relay", help="pass the FDT stream of a web page on to Lab Streaming Layer")
    relay.add_argument("--port", type=int, default=7812, help="listen on 127.0.0.1:PORT (default 7812; 0 picks a free port)")
    relay.add_argument("--allow-origin", action="append", default=[], metavar="ORIGIN",
                       help="also accept pages from ORIGIN, e.g. https://lab.example.org (pages from localhost always are)")
    relay.add_argument("--device", help="label for this FDT when more than one streams on the network; wins over the page's")
    relay.add_argument("--latency-ms", type=float, default=0.0, help="a measured constant delay to subtract from every stamp")

    listen = commands.add_parser("nokov-listen", help="show NOKOV XINGYING's Remote Trigger messages as they arrive")
    listen.add_argument("--port", type=int, default=7061, help="UDP port XINGYING broadcasts to (default 7061)")
    control = commands.add_parser("nokov-control", help="start or stop a recording in NOKOV XINGYING (Remote Control)")
    control.add_argument("action", choices=("start", "stop"))
    control.add_argument("--host", required=True, help="the XINGYING computer (or a broadcast address)")
    control.add_argument("--port", type=int, default=7060, help="XINGYING's Remote Control port (default 7060)")
    control.add_argument("--name", required=True, help="take name")
    control.add_argument("--database-path", help="for start: XINGYING's working directory for the take (required)")
    control.add_argument("--notes", default="")
    record = commands.add_parser("nokov-record", help="record FDT takes cut by NOKOV XINGYING's Remote Trigger")
    where = record.add_mutually_exclusive_group(required=True)
    where.add_argument("--serial", metavar="PORT", help="the FDT's serial port (COM3, /dev/tty.usbserial-...)")
    where.add_argument("--tcp", metavar="HOST:PORT", help="an FDT simulator (movetrics-fdt simulate --tcp PORT)")
    record.add_argument("--rate", type=int, default=2000, help="frames per second per plate (default 2000)")
    record.add_argument("--out", default="nokov-takes", help="folder for the takes (default ./nokov-takes)")
    record.add_argument("--trigger-port", type=int, default=7061, help="XINGYING's Remote Trigger port (default 7061)")
    record.add_argument("--format", choices=("csv", "c3d"), default="csv")
    record.add_argument("--preroll", type=float, default=2.0,
                        help="seconds of stream kept in memory, so a trigger that arrives late still finds its start (default 2)")
    record.add_argument("--max-take", type=float, default=600.0, help="close a take after this many seconds without a stop")
    record.add_argument("--lsl", action="store_true", help="also publish the FDT on LSL, with the triggers as markers")
    record.add_argument("--device", help="LSL label for this FDT (with --lsl)")
    setup = commands.add_parser("nokov-analog-setup", help="what to enter in XINGYING for the FDT's analog outputs")
    setup.add_argument("--firmware", help="the FDT's STM32 firmware version, to check the moment outputs")
    setup.add_argument("--plates", default="1,2", help="plates on the analog board (default 1,2)")
    setup.add_argument("--json", action="store_true", help="print the worksheet as JSON")
    return parser


def _nokov(args: argparse.Namespace) -> int:
    import json

    from . import nokov

    if args.command == "nokov-analog-setup":
        try:
            sheet = nokov.analog_worksheet(args.firmware, tuple(int(p) for p in args.plates.split(",")))
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(sheet, indent=2, ensure_ascii=False) if args.json else nokov.format_worksheet(sheet))
        return 0
    if args.command == "nokov-control":
        try:
            if args.action == "start":
                if not args.database_path:
                    print("error: start needs --database-path (XINGYING's working directory)", file=sys.stderr)
                    return 2
                message = nokov.capture_start_message(args.name, args.database_path, notes=args.notes)
            else:
                message = nokov.capture_stop_message(args.name, notes=args.notes)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        sent = nokov.send_capture_message(message, args.host, args.port)
        print(f"sent Capture{args.action.title()} {args.name!r} to {args.host}:{args.port} ({sent} bytes)")
        return 0
    if args.command == "nokov-record" and args.format == "c3d":
        import importlib.util

        if importlib.util.find_spec("ezc3d") is None:  # say so now, not after the first take
            print('error: --format c3d needs ezc3d: pip install "movetrics-fdt[c3d,serial] @ '
                  'git+https://github.com/movetrics/sdk#subdirectory=python"', file=sys.stderr)
            return 2
    from .errors import FdtError

    try:
        asyncio.run(_nokov_listen(args) if args.command == "nokov-listen" else _nokov_record(args))
    except KeyboardInterrupt:
        return 0
    except (OSError, FdtError) as error:  # no FDT on that port, the trigger port taken, ...
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


async def _nokov_listen(args: argparse.Namespace) -> None:
    from .nokov import TriggerListener

    async with TriggerListener(port=args.port) as listener:
        print(f"READY listening for XINGYING on UDP {listener.port}", flush=True)
        async for message, arrival, address in listener:
            fields = ", ".join(f"{k}={v!r}" for k, v in message.fields.items())
            print(f"{arrival:.3f} {address[0]} Capture{message.kind.title()} {fields}"
                  + (f" RESULT={message.result!r}" if message.result else "")
                  + (f" [{'; '.join(message.warnings)}]" if message.warnings else ""), flush=True)


async def _nokov_record(args: argparse.Namespace) -> None:
    from .client import FdtClient
    from .nokov import TriggerListener, record_takes

    if args.serial:
        from .serial_transport import SerialTransport

        transport = SerialTransport(args.serial)
    else:
        from .tcp_transport import TcpTransport

        host, _, port = args.tcp.rpartition(":")
        transport = TcpTransport(host or "127.0.0.1", int(port))
    bridge = None
    async with FdtClient(transport) as fdt:
        version = await fdt.get_firmware_version()
        await fdt.set_rate(args.rate)
        if args.lsl:
            from .lsl import LslBridge

            bridge = LslBridge(args.rate, device=args.device, firmware=version.stm32FW)
        async with TriggerListener(port=args.trigger_port) as listener:
            await fdt.start_stream()
            print(f"READY FDT {version.stm32FW} streaming at {args.rate} frames/s per plate; waiting for XINGYING on "
                  f"UDP {listener.port}; takes go to {args.out}", flush=True)
            try:
                await record_takes(fdt.samples(), args.rate, args.out, listener, fmt=args.format, preroll_s=args.preroll,
                                   max_take_s=args.max_take, on_item=bridge.push if bridge else None,
                                   on_trigger=(lambda m: bridge.mark(f"NOKOV Capture{m.kind.title()} {m.name}"))
                                   if bridge else None, log=lambda text: print(text, flush=True))
            finally:
                if bridge is not None:
                    bridge.close()
                await fdt.stop_stream()


def _relay(args: argparse.Namespace) -> int:
    from .relay import serve_relay

    def said(url: str) -> None:
        print(f"READY {url}", flush=True)

    try:
        asyncio.run(serve_relay(port=args.port, allow_origins=args.allow_origin, device=args.device,
                                latency_s=args.latency_ms / 1000, ready=said, log=lambda text: print(text, flush=True)))
    except KeyboardInterrupt:
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "lsl-relay":
        return _relay(args)
    if args.command.startswith("nokov-"):
        return _nokov(args)
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
