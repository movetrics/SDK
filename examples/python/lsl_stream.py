"""Stream an FDT to Lab Streaming Layer (one outlet per plate plus markers). Record with LabRecorder.

    python lsl_stream.py --port /dev/tty.usbserial-XXXX --rate 2000      # a real FDT (COM3 on Windows)
    python lsl_stream.py --simulate --rate 2000                          # the simulator, nothing to plug in

Needs: pip install 'movetrics-fdt[lsl,serial]'. Units, names and signs: docs/19; timing: docs/22.
"""

import argparse
import asyncio
import subprocess
import sys

from movetrics_fdt import FdtClient, SerialTransport, TcpTransport
from movetrics_fdt.lsl import LslBridge


async def main(args: argparse.Namespace) -> None:
    simulator = None
    if args.simulate:
        simulator = subprocess.Popen([sys.executable, "-m", "movetrics_fdt", "simulate", "--tcp", "7811"],
                                     stdout=subprocess.PIPE, text=True)
        simulator.stdout.readline()  # READY
        transport = TcpTransport("127.0.0.1", 7811)
    else:
        transport = SerialTransport(args.port)
    try:
        async with FdtClient(transport) as fdt:
            version = await fdt.get_firmware_version()
            await fdt.set_rate(args.rate)
            bridge = LslBridge(args.rate, plates=(1, 2), firmware=version.stm32FW)
            await fdt.start_stream()
            print(f"Streaming FDT {version.stm32FW} at {args.rate} frames/s per plate to LSL. Ctrl-C stops.")
            count = 0
            async for item in fdt.samples():
                bridge.push(item)
                count += 1
                if count % (args.rate * 10) == 0:
                    print(bridge.stats())
    finally:
        if simulator:
            simulator.terminate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--port")
    where.add_argument("--simulate", action="store_true")
    parser.add_argument("--rate", type=int, default=2000)
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        pass
