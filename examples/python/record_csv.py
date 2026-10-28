"""Record the FDT stream to a CSV file at a chosen rate, for example 2,000 frames per second per plate, raw.

    python3 record_csv.py COM5 --rate 2000 --cutoff 0 --seconds 10 --out jump.csv

Columns: plate, ticks (FDT clock, 0.1 ms, restarting at 0 on START), time_s, Fx, Fy, Fz (N), Mx, My, Mz (N*m) as
the FDT sends them. The stream's Fy and Mx have the opposite sign to Movetrics Studio exports; see
docs/18-export-formats.md. The two start-up placeholders (ticks 0) are left out.

One commanding host at a time: close Movetrics Studio first. --rate needs Movetrics firmware 1.2.8.0 or later.
Install: python3 -m pip install -e "../../python[serial]". Tested against the fake controller in
matlab/tests/fake_fdt.py; not yet run against an FDT.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys

from movetrics_fdt import FdtClient, FdtError, SerialTransport

TICKS_PER_SECOND = 10_000


async def record(port: str, rate: int, cutoff: int, seconds: float, out: str) -> int:
    rows = 0
    async with FdtClient(SerialTransport(port)) as fdt:
        await fdt.set_rate(rate, cutoff_hz=cutoff)
        await fdt.start_stream()
        with open(out, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["plate", "ticks", "time_s", "Fx", "Fy", "Fz", "Mx", "My", "Mz"])

            async def consume() -> None:
                nonlocal rows
                async for f in fdt.frames():
                    if f.is_placeholder:
                        continue
                    writer.writerow([f.platform_address, f.timeStamp, f.timeStamp / TICKS_PER_SECOND,
                                     f.forceX, f.forceY, f.forceZ, f.momentX, f.momentY, f.momentZ])
                    rows += 1

            try:
                await asyncio.wait_for(consume(), timeout=seconds)
            except asyncio.TimeoutError:
                pass
        await fdt.stop_stream()
        print(f"{rows} frames written to {out}; dropped by the client: {fdt.dropped_frames}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record the Movetrics FDT stream to CSV.")
    parser.add_argument("port", help="serial device, for example COM5 or /dev/tty.usbserial-XXXX")
    parser.add_argument("--rate", type=int, default=2000, help="frames per second per plate, 50-2000 (default 2000)")
    parser.add_argument("--cutoff", type=int, default=0, help="low-pass cutoff in Hz, 0 = off (default 0)")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--out", default="fdt-recording.csv")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(record(args.port, args.rate, args.cutoff, args.seconds, args.out))
    except (FdtError, ValueError, ImportError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
