---
title: Python in 5 minutes
description: Live force data from an FDT, or from the simulator, into Python.
---

You need Python 3.10 or later. Everything below runs without an FDT: the first step starts a simulated one.

## 1. Install

```sh
pip install "movetrics-fdt[serial,c3d,lsl] @ git+https://github.com/movetrics/sdk#subdirectory=python"
```

(Until the package is on PyPI. `serial` is for the USB cable, `c3d` for C3D files, `lsl` for Lab Streaming Layer.)

## 2. Start a simulated FDT

```sh
movetrics-fdt simulate --tcp 7800 --signal cmj
```

It prints `READY 127.0.0.1:7800`. Leave it running; it behaves like an FDT with a person doing a countermovement jump every 6 seconds.

## 3. Read one second of data

```python
import asyncio
from movetrics_fdt import FdtClient, TcpTransport, Sample

async def main():
    async with FdtClient(TcpTransport("127.0.0.1", 7800)) as fdt:
        await fdt.set_rate(2000)                  # samples per second per plate
        await fdt.start_stream()
        async for item in fdt.samples():
            if isinstance(item, Sample) and item.plate == 1 and item.stamp % 1000 == 0:
                print(f"t={item.t:.3f} s   fz={item.fz:7.1f} N   cop_x={item.cop_x * 1000:6.1f} mm")
            if item.t >= 1.0:
                break
        await fdt.stop_stream()

asyncio.run(main())
```

## 4. Use your FDT instead

Plug the FDT in with USB-C and change one line:

```python
from movetrics_fdt import SerialTransport
transport = SerialTransport("COM3")                    # Windows; macOS: "/dev/tty.usbserial-XXXX"
```

## 5. Save it in the formats your tools read

```python
from movetrics_fdt.writers import Recording, write_csv, write_c3d, write_mot

rec = Recording.from_samples(items, rate_hz=2000)      # items: what samples() gave you
write_csv(rec, "trial.csv")                            # + trial.csv.json with units, gaps and events
write_c3d(rec, "trial.c3d", gaps="split")              # Visual3D, OpenSim, Mokka, ezc3d
write_mot(rec, "trial.mot")                            # OpenSim external loads
```

Studio exports work too: `Recording.from_studio(read_studio_csv("exam-channels.csv"))`.

## What you get

Each `Sample` has `t`, `plate`, `fx fy fz` (N), `mx my mz` (N·m), `cop_x cop_y` (m, NaN below 50 N), the FDT `stamp` and the six `raw` integers. `samples()` also yields an `Event` for each sync edge and a `Gap` before the first sample after a hole. [Names, units and axes](../../concepts/units-and-axes/).

**Tested on:** the simulator (2,000 samples per second per plate, two plates, no sample lost over a pseudo-terminal) and real Studio exports. Against a real FDT: `set_rate` and the stream were checked on the bench with the older bench tool, not yet with this client.
