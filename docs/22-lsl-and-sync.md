# 22 Recording next to EMG, cameras and a second FDT: LSL and sync helpers

Two routes put FDT data on one time base with other devices. **LSL** (Lab Streaming Layer) needs no cable: LabRecorder records the FDT and any LSL device (EMG, EEG, eye tracking, PLUX OpenSignals, Noraxon's LSL bridge) into one XDF file, aligned to within the clock-mapping error below. **Sync pulses** need a cable to the FDT's SYNC IN or SYNC OUT and give sample-level alignment; they depend on the sync modes in development (the firmware team) and are simulated only so far.

With NOKOV's XINGYING motion capture, `movetrics-fdt nokov-record` cuts an FDT file for every XINGYING take from XINGYING's own start and stop messages, mapped onto the FDT clock with the clock map below (chapter 24).

Three clients publish the same LSL streams: Python (`LslBridge`), MATLAB (`movetrics.LslBridge`) and, for a web page that reads the FDT in the browser, the TypeScript `LslRelay` through the Python relay. Whichever one publishes, LabRecorder sees the same names, channels, units, description and clock method.

## LSL from Python

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

The package is installed from GitHub (it is not on PyPI). The `lsl` extra brings pylsl, whose wheel carries liblsl for Windows, macOS and Linux:

```sh
pip install "movetrics-fdt[lsl,serial] @ git+https://github.com/movetrics/sdk#subdirectory=python"
```

The full script is `examples/python/lsl_stream.py`; with `--simulate` it runs against the simulator.

| Stream | Type | Rate | Channels |
|---|---|---|---|
| `Movetrics FDT plate 1`, `… plate 2` | Force | FDT rate | `fx fy fz` N, `mx my mz` N·m, `cop_x cop_y` m (doc 19 names, units and signs) |
| `Movetrics FDT markers` | Markers | irregular | event names (`sync_in_rise`, …), `gap plate=P missing=N`, free text from `mark()` |

Source ids are fixed (`movetrics-fdt-plate1`, …) so LabRecorder reconnects after a restart. With more than one FDT on the network, give each bridge a label: `LslBridge(2000, device="B")` publishes `Movetrics FDT B plate 1`, … with source ids `movetrics-fdt-B-plate1`, …, and writes the label into each plate stream's description; the example takes `--device B`. The SDK does not read the FDT's serial number, so the label is yours to choose. Without one, two FDTs publish the same names and ids, and LabRecorder cannot tell them apart. `close()` takes the streams off the network.

**Timing**: each sample's LSL stamp is the FDT stamp mapped onto LSL's clock by a line (offset and drift) fitted through the least-delayed frame of each second, so USB delivery jitter (up to 16 ms with the FT232R) does not enter the time base. Measured in the SDK tests (simulated arrival jitter 0 to 16 ms): stamps spaced at the FDT period within 0.2 ms after a 3 s warm-up; in the FDT repo's simulation (50 ppm drift, 60 s at 2,000 Hz) within 0.3 ms of the truth. What the mapping cannot remove is the constant part: the shortest USB delay and the FDT's filter and processing delay; `latency_s` subtracts a measured value. Gaps stay gaps (LSL carries a stamp per sample) and are announced on the marker stream. Not yet run with a real FDT and LabRecorder.

This replaces the earlier streamer of the FDT tool for SDK users: same clock method, the shared vocabulary instead of wire signs, and the 30 mm term in the CoP.

### Clock mapping, exactly

Every client maps the FDT's stamps onto the LSL clock with this method. `vectors/clock_map.json` pins it down pair by pair; its expected values come from this description (`tools/gen_clock_map_vectors.py`), not from a client.

1. Each sample gives a pair: its FDT time `device` (the stamp in seconds) and `arrival`, the LSL clock when the host read it. `diff = arrival - device`.
2. A pair belongs to block `floor(device / block_seconds)`, 1 s by default. In each block the pair with the smallest `diff`, the first one on a tie, gives the block's point `(device, diff)`. A block closes when the first pair of a later block arrives.
3. Once three blocks have closed, `offset(t) = mean_diff + slope * (t - mean_device)`: the least-squares line through the last `window_blocks` points, 300 by default. Before that, `offset` is the smallest `diff` seen so far, the current pair included, so the first three seconds are a warm-up.
4. A sample's stamp is `device + offset(device) - latency`, computed right after its pair is taken. `latency` is a measured constant delay, 0 by default.
5. Per stream, a sample whose FDT stamp does not rise is dropped (counted as `repeated_dropped`), and a stamp that would not rise above the previous one is held 1 µs above it, because LSL needs rising stamps.

The Python and MATLAB clock maps pass every case of the file, and the relay uses the Python one. A client in another language is correct when it passes them too.

## From a web page: the relay

A page that reads the FDT in the browser (`WebSerialTransport`, `WebBluetoothTransport`) cannot publish LSL: browsers cannot open the sockets LSL uses. The relay is a small program on the same computer that takes the page's samples over a WebSocket and publishes them with `LslBridge`. Only one program can own an FDT's stream, so this is also how a browser recorder and LabRecorder share one FDT.

```sh
pip install "movetrics-fdt[relay] @ git+https://github.com/movetrics/sdk#subdirectory=python"
movetrics-fdt lsl-relay          # prints READY ws://127.0.0.1:7812
```

```ts
import { FdtClient, LslRelay, WebSerialTransport } from 'movetrics-fdt-sdk';

const client = new FdtClient(await WebSerialTransport.open(await navigator.serial.requestPort()));
const version = await client.getFwVersion();
await client.setRate(2000);
const relay = await LslRelay.open({ rateHz: 2000, plates: [1, 2], firmware: version.stm32FW });
console.log(relay.streams);            // what to tick in LabRecorder
await client.startStream();
for await (const item of client.samples()) relay.push(item);
```

- **Who may connect.** The relay listens on 127.0.0.1 only. It accepts pages served from this computer (`http://localhost:…`, `http://127.0.0.1:…`) and programs that send no Origin header. Any other site must be named: `movetrics-fdt lsl-relay --allow-origin https://lab.example.org`. A page from elsewhere is refused at the handshake (HTTP 403). One page at a time: a second one is closed with code 1013.
- **What it checks.** Hello first (protocol version 1, rate, plates 1 to 4, firmware, an optional `device` label), then batches of samples, events and gaps. Numbers must be finite, except `cop_x` and `cop_y`, which travel as `null` where the vocabulary has NaN and are NaN again on LSL. A message the relay cannot accept closes the connection with 1007 (bad data) or 1008 (refused) and a reason; `LslRelay` raises it as `LslRelayError` and resolves `relay.closed` with it. The protocol is described in `python/movetrics_fdt/relay.py`.
- **Timing.** The relay stamps each message when it arrives and maps the FDT clock onto LSL's from those arrivals, by the method above. `LslRelay` sends within `flushMs` (10 ms), and the least-delayed message of each second still carries the mapping. When the page leaves, the relay takes its streams off the network.
- **Labels.** `device` in `LslRelay.open`, or `--device` on the relay (which wins), names the FDT as in Python.

Run end to end with the simulator (simulated): the TypeScript client in Node read the SDK simulator over TCP for 8 s at 1,000 frames per second per plate and pushed through `LslRelay` and the relay to an LSL inlet. All 8,000 samples of plate 1 arrived, stamps rising and within 0.07 ms of the 1 ms spacing after the warm-up, the NaN centre of pressure of the flight phase kept, and the marker delivered. Not yet run from a browser or with a real FDT.

## From MATLAB

`movetrics.LslBridge` publishes the same streams from the MATLAB toolbox. It needs [liblsl-Matlab](https://github.com/labstreaminglayer/liblsl-Matlab) (MIT licence) on the path.

```matlab
addpath('path/to/liblsl-Matlab');                     % with its bin folder holding the liblsl library
fdt = movetrics.Fdt("COM3"); fdt.setRate(2000, 0);
bridge = movetrics.LslBridge(2000, [1 2], 'Firmware', fdt.firmware);   % 'Device', 'B' for a second FDT
disp(bridge.StreamNames)                              % what to tick in LabRecorder
fdt.start();
while true, bridge.push(fdt.read(0.05)); end          % Ctrl-C stops
```

`push` takes what `fdt.read` returns. All the samples of one read share one arrival time, so keep reads short (50 ms or less): the least-delayed read of each second then sets the mapping. The full script is `matlab/examples/lsl_stream.m`; `movetrics.ClockMap` is usable on its own, and `close()` takes the streams off the network.

Tested in GNU Octave 8.4 with liblsl-Matlab and liblsl 1.18 (simulated): 5 s of two plates in 20 ms reads arriving 3 to 13 ms late came out on LSL with rising stamps, within 0.2 ms of the FDT's 1 ms spacing after the warm-up, the NaN centre of pressure kept and the markers delivered; the clock map passes `vectors/clock_map.json`. Not yet run in MATLAB itself, for which the toolbox is written, or with a real FDT.

## Next to Noraxon EMG

Noraxon publishes an LSL bridge for its myoRESEARCH (MR) software: [Noraxon-LSL](https://github.com/Noraxon/Noraxon-LSL) (MIT licence, Python). It runs on the MR computer, reads MR's HTTP streaming and publishes one LSL stream per timed MR channel (type `EMG` for EMG channels), stamped from MR's model of the sensor clock. With it, LabRecorder records Noraxon EMG and the FDT into one XDF file:

1. In MR, turn on HTTP streaming and the setting that synchronises the Ultium and PC clocks (Noraxon-LSL creates no streams without it), and start a measurement.
2. On the MR computer, start Noraxon-LSL as its README describes. On the same computer or another one on the network, start an FDT bridge: `python examples/python/lsl_stream.py --port COM3`, the MATLAB bridge or the relay.
3. In LabRecorder, tick the Noraxon streams and `Movetrics FDT plate 1`, `plate 2` and `markers`, and record.

Each device keeps its own clock on the LSL time base: the FDT's mapped stamps and Noraxon's sensor-clock stamps, aligned by LSL's clock synchronisation between computers. Noraxon-LSL's `Markers` streams carry numbers (MR switch channels), not text. This section follows Noraxon-LSL's code and README as published on 16 Nov 2026; it has not been run with MR or Noraxon hardware and is not an integration tested or endorsed by Noraxon.

## Sync helpers (`movetrics_fdt.sync`)

- `align(fdt_edge_times, other_edge_times)` → `Alignment(offset_s, drift_ppm, residual_s, pairs, unmatched)` with `to_other(t)` and `to_fdt(t)`. Matches pulses even when either side missed some. Tested: 30 ppm over 20 minutes with three missed pulses, drift found within 1 ppm, residual below 0.1 ms (synthetic).
- `merge(fdt_a_items, fdt_b_items)` → one recording of four plates on A's clock. FDT A drives SYNC OUT with the pulse train, FDT B sees it on SYNC IN with event frames on; B's samples move onto A's clock and become plates 3 and 4. Tested on two simulated FDTs, B's clock 40 ppm fast and started 0.25 s earlier: 30 of 30 pulses matched, offset recovered within 1 ms.
- `ClockMap`: FDT time to host time, used by the LSL bridge and the relay; usable on its own for any host clock.
- `edge_times(items, "sync_in_rise")`: the times of one kind of event.

For samples on a PTP (IEEE 1588) network's time, with a pulse per second on SYNC IN, see [chapter 25](25-ptp.md).

Wiring and the modes to set on each FDT will be published here once they have been measured on real FDTs. Until then everything in this section is simulated.
