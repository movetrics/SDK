"""Connect to a Movetrics BLE bridge and print its status line and the controller's GET_STATUS records.

    python3 ble_status.py Movetrics-BLE
    python3 ble_status.py AA:BB:CC:DD:EE:FF

The example sends GET_STATUS only. When a session that sent commands ends, the bridge writes STOP to the
controller (docs/02-transports.md section 2.5). Whether that stops a stream on hardware is item U8 there.

Install the package first, from this directory: python3 -m pip install -e "../../python[ble]"
This example has not been run against hardware in this SDK. It is checked with py_compile only.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from movetrics_fdt import BleTransport, FdtClient, FdtError


async def show_status(target: str, connect_timeout: float) -> int:
    transport = BleTransport(target, connect_timeout=connect_timeout)
    async with FdtClient(transport) as fdt:
        print("bridge status line:")
        for key, value in transport.bridge_status.items():
            print(f"  {key} = {value}")
        status = await fdt.get_status()
    print(f"controller status reply: class {status.length_class}, {len(status.records)} record(s)")
    for record in status.records:
        battery = "not in this record class" if record.batterySOC is None else str(record.batterySOC)
        print(
            f"  platform {record.platform_address}: errorFlags={record.errorFlags} "
            f"serial={record.serialParams!r} batterySOC={battery} cacheFrames={record.cacheFrames}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the status of a Movetrics BLE bridge and controller.")
    parser.add_argument("target", help="advertised name (Movetrics-BLE) or the device address")
    parser.add_argument(
        "--connect-timeout", type=float, default=20.0, help="seconds to wait for the connection (default: 20)"
    )
    args = parser.parse_args(argv)
    if args.connect_timeout <= 0:
        parser.error("--connect-timeout must be positive")
    try:
        return asyncio.run(show_status(args.target, args.connect_timeout))
    except (FdtError, ImportError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
