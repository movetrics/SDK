"""Read the measurement stream from a controller on USB serial for a fixed time, then stop it.

    python3 read_stream.py /dev/ttyUSB0 --seconds 5

The example sends GET_STATUS, START_STREAM and STOP_STREAM, and nothing else. The stream values are wire
integers. Their physical units are not defined by the vectors (vectors/README.md, not covered item 11).

Install the package first, from this directory: python3 -m pip install -e "../../python[serial]"
This example has not been run against hardware in this SDK. It is checked with py_compile only.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from movetrics_fdt import FdtClient, FdtError, SerialTransport, StreamFrame


def describe(frame: StreamFrame) -> str:
    """One line per frame: platform, timestamp (0 for the two START placeholders), force and moment values."""
    forces = f"({frame.forceX}, {frame.forceY}, {frame.forceZ})"
    moments = f"({frame.momentX}, {frame.momentY}, {frame.momentZ})"
    marker = " placeholder" if frame.is_placeholder else ""
    return f"platform {frame.platform_address} t={frame.timeStamp}{marker} F={forces} M={moments}"


async def read_stream(port: str, seconds: float, show: int) -> int:
    async with FdtClient(SerialTransport(port)) as fdt:
        status = await fdt.get_status()
        general = status.general
        if general is not None:
            print(f"serial settings reported by the controller: {general.serialParams}")
        print(f"status reply: class {status.length_class}, {len(status.records)} record(s)")

        await fdt.start_stream()
        count = 0

        async def consume() -> None:
            nonlocal count
            async for frame in fdt.frames():
                count += 1
                if count <= show:
                    print(describe(frame))

        try:
            await asyncio.wait_for(consume(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
        await fdt.stop_stream()
        print(f"frames received: {count}; dropped by the client: {fdt.dropped_frames}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read the Movetrics FDT stream over USB serial.")
    parser.add_argument("port", help="serial device, for example /dev/ttyUSB0 or COM3")
    parser.add_argument("--seconds", type=float, default=5.0, help="how long to read (default: 5)")
    parser.add_argument("--show", type=int, default=10, help="how many frames to print (default: 10)")
    args = parser.parse_args(argv)
    if args.seconds <= 0 or args.show < 0:
        parser.error("--seconds must be positive and --show must not be negative")
    try:
        return asyncio.run(read_stream(args.port, args.seconds, args.show))
    except (FdtError, ImportError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
