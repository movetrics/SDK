# 22 Recording next to EMG, cameras and a second FDT: LSL and sync helpers

Two routes put FDT data on one time base with other devices. **LSL** (Lab Streaming Layer) needs no cable: LabRecorder records the FDT and any LSL device (EMG, EEG, eye tracking, PLUX OpenSignals, Noraxon's LSL bridge) into one XDF file, aligned to within the clock-mapping error below. **Sync pulses** need a cable to the FDT's SYNC IN or SYNC OUT and give sample-level alignment; they depend on the sync modes in development (the firmware team) and are simulated only so far.

## LSL

```python
import asyncio
from movetrics_fdt import FdtClient, SerialTransport
from movetrics_fdt.lsl import LslBridge

async def main():
    async with FdtClient(SerialTransport("/dev/tty.usbserial-XXXX")) as fdt:   # COM3 on Windows
        version = await fdt.get_firmware_version()
        await fdt.set_rate(2000)
        bridge = LslBridge(2000, plates=(1, 2), firmware=version.stm32FW)
        await fdt.start_stream()
        async for item in fdt.samples():
            bridge.push(item)          # Ctrl-C to stop; LabRecorder records the streams

asyncio.run(main())
```

`pip install 'movetrics-fdt[lsl,serial]'` installs pylsl, whose wheel carries liblsl for Windows, macOS and Linux. The full script is `examples/python/lsl_stream.py`; with `--simulate` it runs against the simulator.

| Stream | Type | Rate | Channels |
|---|---|---|---|
| `Movetrics FDT plate 1`, `… plate 2` | Force | FDT rate | `fx fy fz` N, `mx my mz` N·m, `cop_x cop_y` m (doc 19 names, units and signs) |
| `Movetrics FDT markers` | Markers | irregular | event names (`sync_in_rise`, …), `gap plate=P missing=N`, free text from `mark()` |

Source ids are fixed (`movetrics-fdt-plate1`, …) so LabRecorder reconnects after a restart. **Timing**: each sample's LSL stamp is the FDT stamp mapped onto LSL's clock by a line (offset and drift) fitted through the least-delayed frame of each second, so USB delivery jitter (up to 16 ms with the FT232R) does not enter the time base. Measured in the SDK tests (simulated arrival jitter 0 to 16 ms): stamps spaced at the FDT period within 0.2 ms after a 3 s warm-up; in the FDT repo's simulation (50 ppm drift, 60 s at 2,000 Hz) within 0.3 ms of the truth. What the mapping cannot remove is the constant part: the shortest USB delay and the FDT's filter and processing delay; `latency_s` subtracts a measured value. Gaps stay gaps (LSL carries a stamp per sample) and are announced on the marker stream. Not yet run with a real FDT and LabRecorder (bench queue).

This replaces the streamer of the FDT repo's for SDK users: same clock method, the shared vocabulary instead of wire signs, and the 30 mm term in the CoP.

## Sync helpers (`movetrics_fdt.sync`)

- `align(fdt_edge_times, other_edge_times)` → `Alignment(offset_s, drift_ppm, residual_s, pairs, unmatched)` with `to_other(t)` and `to_fdt(t)`. Matches pulses even when either side missed some. Tested: 30 ppm over 20 minutes with three missed pulses, drift found within 1 ppm, residual below 0.1 ms (synthetic).
- `merge(fdt_a_items, fdt_b_items)` → one recording of four plates on A's clock. FDT A drives SYNC OUT with the pulse train, FDT B sees it on SYNC IN with event frames on; B's samples move onto A's clock and become plates 3 and 4. Tested on two simulated FDTs, B's clock 40 ppm fast and started 0.25 s earlier: 30 of 30 pulses matched, offset recovered within 1 ms.
- `ClockMap`: FDT time to host time, used by the LSL bridge; usable on its own for any host clock.
- `edge_times(items, "sync_in_rise")`: the times of one kind of event.

Wiring and the modes to set on each FDT are in the firmware team the firmware once its bench plan lands. Until then everything in this section is simulated.
