# 20 The simulator: a virtual FDT for everyone without one (contract K10)

`movetrics-fdt simulate` runs a virtual controller that speaks the real host protocol on a TCP port or a pseudo-terminal. A client cannot tell it from an FDT on the byte level: same envelopes and CRC, the stamp-0 placeholders after START, the 0.1 ms grid, NACK codes, sleep and wake. Use it to build and test anything that talks to an FDT, in CI and on a laptop. It never replaces a bench check: it models what the firmware is documented to do, not what a particular board does.

## Run it

    pip install ./sdk/python                       # gives the movetrics-fdt command
    movetrics-fdt simulate --tcp 7800              # FDT 1.2.8.20 on 127.0.0.1:7800
    movetrics-fdt simulate --pty /tmp/fdt          # a serial-like device (Linux, macOS); open /tmp/fdt like a COM port
    movetrics-fdt simulate --tcp 7800 --profile sync --sync-pulse-s 1     # sync modes (draft) and a 1 Hz SYNC IN pulse
    movetrics-fdt simulate --tcp 7800 --replay exam-channels.csv          # replay a Studio export, gaps kept

It prints `READY host:port` (or `READY path`) when it accepts connections. From Python:

```python
import asyncio
from movetrics_fdt import FdtClient, TcpTransport, Sample

async def main():
    async with FdtClient(TcpTransport("127.0.0.1", 7800)) as fdt:
        await fdt.set_rate(2000)
        await fdt.start_stream()
        async for item in fdt.samples():
            if isinstance(item, Sample) and item.plate == 1:
                print(f"{item.t:.4f} s  fz {item.fz:.0f} N  cop_x {item.cop_x * 1000:.1f} mm")
            if item.t > 1:
                break
        await fdt.stop_stream()

asyncio.run(main())
```

## What it models

| Behaviour | Profiles | Source |
|---|---|---|
| GET_FW_VERSION string | `1.2.8.2`, `1.2.8.20`, `sync` (reports `1.2.8.24`) | code |
| Default rate after power-up: 500 (1.2.8.2) or 1,000 (1.2.8.5 and later) frames/s per plate | all | code, the firmware |
| SET_FILTER 0x1C: ACK, NACK 3 for a cutoff at or above half the rate or a rate outside 50 to 2,000 | all | code |
| START: one placeholder per plate with stamp 0, then frames on the grid of 10,000 / rate ticks | all | code, doc 05 section 6 |
| STOP: ACK from address 0xFF | all | code |
| GET_STATUS: general record plus one per plate, 86 bytes, battery 255 | all | code |
| KEEP_ALIVE 0x26: sleep interval, no reply; capped at 300 s on 1.2.8.9 and later | all | code, measured |
| Sleep after the last command (600 s or 300 s); the first command wakes it; START waits about 4.6 s for the pads on 1.2.8.10 and later | all | measured on a bench FDT (20 Oct) |
| Every other code, including calibration and tare: NACK 7. A script that works here cannot write anything on a real FDT that the simulator would not have refused | all | deliberate |
| A request with a payload and a bad CRC: NACK 9 | all | doc 03 |
| SET_SYNC_MODE 0x28 and GET_SYNC_MODE 0x29 with their refusals (NACK 3, NACK 8), event frames at address 0xFD code 0x0E with sub-tick offsets, armed start with placeholders and arm timeout, stop on fall, master out, pulse train rising at ticks 1, 1 + P, ..., saturation start and end with the channel mask | `sync` | FDT 1.2.8.24 spec, (not benched) |
| int16 wrap of values beyond ±32,767 | all | code, doc 05 section 3.2 |

Signals: `--signal stand` (a standing person, sway), `cmj` (a countermovement jump every 6 s), `empty`, or `--replay` a Studio `-channels.csv` (Studio signs are converted back to wire signs, so the decoded values equal the file's; the file's gaps stay gaps unless `--fill-gaps`).

Faults for host tests: `--drop-every N` (one frame in N lost), `--hold AT FOR` (nothing sent for FOR s from AT s, as in a USB stall), `--clock-ppm P` (FDT clock P ppm fast against the host, for drift and alignment tests), `--scale K` (multiply every load; 20 provokes the int16 wrap), `--asleep` (start asleep, so the first START waits for the pads).

## In tests

The protocol model `movetrics_fdt.simulator.VirtualFdt` has no I/O: `feed(bytes, now)` and `advance(now)` on a clock you pass in, so a test of ten minutes of stream runs in a second. `python/tests/test_simulator.py` shows both styles: the model on a fake clock, and `FdtClient` over TCP to a served instance (2 s at 2,000 frames/s per plate, no frame lost, pulse train events every 0.5 s).

Measured on the build container (28 Oct 2026): `FdtClient` over the pseudo-terminal at 2,000 frames/s per plate, two plates, 2 s: 7,999 samples, none dropped.

## Not modelled

Bluetooth timing, USB latency and its jitter (frames arrive as fast as the host reads), the pads' own sample queue and its stale frames, GET_CURRENT_CONFIG, SET_TARE, firmware update, the analog outputs. A host that needs one of these is checked on the bench.
