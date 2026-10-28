# AGENTS.md

Context for AI coding agents (Claude Code, Cursor, Copilot, ChatGPT, Codex and others) that build software with the Movetrics SDK. Read this file in full before you write code. It is written for you; humans are welcome too. The human-facing start prompt is in [START_PROMPT.md](START_PROMPT.md).

## 1. What you are working with

- **F1-3D force plate**: measures the force a person applies to the ground. Per plate and per sample: three forces `fx fy fz` (N), three moments `mx my mz` (N·m), and the centre of pressure `cop_x cop_y` (m), the point under the feet where the force acts.
- **FDT** (Force Data Terminal): the box one or two plates connect to. It sends one 24-byte frame per plate per sample to a host over USB-C (a serial port) or Bluetooth (through an ESP32-S3 bridge). Default 1,000 samples per second per plate from firmware 1.2.8.8 (500 before); the host can set 50 to 2,000.
- **Movetrics Studio**: the desktop recorder. It exports CSV and C3D files. The SDK reads both.
- **Movetrics Cloud**: stores recordings and computes results (jump height and others) with the Movetrics engine. Read-only HTTP API at `https://beta.movetrics.com/api/v1`, personal access token in `MOVETRICS_TOKEN`. Every result names its `method` and `method_version`.
- **This SDK**: the protocol specification, shared test vectors (`vectors/`), clients in Python (`python/`), TypeScript (`ts/`) and MATLAB (`matlab/`), Excel Power Query (`excel/`), examples (`examples/`), contracts (`contracts/`) and the docs site (`site/`). Apache 2.0.

## 2. Pick the path from the user's goal

| The user wants | Use | Start from |
|---|---|---|
| Results or recordings they already have in Movetrics Cloud | `CloudClient` (Python), `movetrics.Cloud` (MATLAB), Power Query (Excel) | `examples/python/cloud_results.py`, `excel/README.md` |
| Live data from an FDT on this computer | `FdtClient` + `SerialTransport` (Python), `FdtClient` + `WebSerialTransport` (browser), `movetrics.Fdt` (MATLAB) | `examples/python/read_stream.py`, `examples/web/` |
| Files from Studio | `read_studio_csv`, `read_studio_c3d` → `Recording.from_studio` | `docs/18-export-formats.md` |
| Files for other tools | `write_csv`, `write_c3d`, `write_mot` | `docs/21-writing-files.md` |
| Recording next to EMG, EEG or cameras | `LslBridge` (Lab Streaming Layer), the sync modes, `sync.align` | `docs/22-lsl-and-sync.md`, `examples/python/lsl_stream.py` |
| Voltages recorded from the FDT's analog outputs | `movetrics_fdt.analog.to_vocabulary` | `docs/23-analog-outputs.md` |
| A client in another language | the specification and the vectors | the firmware, `vectors/README.md` |

If the user has no FDT, or you cannot reach one, **build against the simulator**. It speaks the real protocol:

```sh
pip install "movetrics-fdt[serial,c3d,lsl] @ git+https://github.com/movetrics/sdk#subdirectory=python"
movetrics-fdt simulate --tcp 7800 --signal cmj        # prints READY 127.0.0.1:7800; a jump every 6 s
```

Options: `--signal stand|cmj|empty`, `--bodyweight N`, `--replay studio-channels.csv`, `--profile` (firmware line), `--sync-pulse-s`, `--clock-ppm`, `--drop-every N` (simulated frame loss, to test gap handling), `--pty PATH` for a serial-like device on Linux and macOS. Swap `TcpTransport("127.0.0.1", 7800)` for `SerialTransport("COM3")` or `"/dev/tty.usbserial-…"` when the real FDT is plugged in; nothing else changes.

## 3. The minimum working program (Python)

```python
import asyncio
from movetrics_fdt import FdtClient, TcpTransport, Sample, Gap, Event

async def main():
    async with FdtClient(TcpTransport("127.0.0.1", 7800)) as fdt:
        await fdt.set_rate(2000)               # samples per second per plate; send after every connect
        await fdt.start_stream()
        async for item in fdt.samples():       # Sample | Event | Gap, in FDT time
            if isinstance(item, Sample) and item.plate == 1:
                print(item.t, item.fz, item.cop_x)
            elif isinstance(item, Gap):
                print("plate", item.plate, "missed", item.missing, "samples")
            if getattr(item, "t", 0) >= 5:
                break
        await fdt.stop_stream()

asyncio.run(main())
```

TypeScript in a browser: `new FdtClient(await WebSerialTransport.open(await navigator.serial.requestPort()))`, then `setRate`, `startStream`, `for await (const item of client.samples())`. MATLAB: `f = movetrics.Fdt("COM3"); f.setRate(1000); f.start(); d = f.read(2); f.stop();`. Check the exact signatures in `python/README.md`, `ts/README.md` and `matlab/README.md` before you rely on them; they are the source of truth, this file is a map.

## 4. Invariants you must keep

1. **Units and names are fixed**: `t` s, forces N, moments N·m, CoP m, plate frame with Studio's signs. Never invent other names (`Fz`, `force_z`, `COP_X`) in data you hand on; convert at the edge of your program if the user's tool needs different ones.
2. **Time is the FDT's clock** (`t`, from the frame stamp), not the host clock. Never timestamp samples with `time.time()` or `Date.now()`.
3. **Gaps are data.** A `Gap` means samples are missing. Do not interpolate across it unless the user asks, and then say so in the output. Writers refuse or split at gaps by default (`write_c3d(..., gaps="refuse"|"split")`).
4. **CoP is empty below 50 N** of vertical force (`NaN` in every client). It is not zero: zero is a real position.
5. **The first frame of each plate after START is a placeholder** (stamp 0). The clients drop it; a client you write must too.
6. **The rate setting is lost on every reset.** Call `set_rate` after each connect, then leave 100 ms before START (the clients do this).
7. **Results come from the engine.** If you compute a value yourself (jump height from samples, say), label it as yours and, when a Cloud result exists, show both with the difference. Do not present your number as a Movetrics result.
8. **Never put a token in code, files or logs.** Read `MOVETRICS_TOKEN` from the environment.

## 5. What the clients will not do, and why

The FDT also accepts commands that update firmware, write calibration, reset the device, re-zero the plates or change the plate bus. The clients implement eight commands only: START_STREAM, STOP_STREAM, SET_FILTER (the rate), GET_STATUS, GET_FW_VERSION, KEEP_ALIVE, SET_SYNC_MODE, GET_SYNC_MODE. Every other code is in `NOT_IMPLEMENTED` (`python/movetrics_fdt/commands.py`, `ts/src/commands.ts`) with its reason, and asking for it raises `UnsupportedCommandError` / `FdtRefusedError` before a byte is sent.

Do not work around this by writing raw bytes to the port. If the user needs one of those functions (zeroing the plates, a firmware update), tell them it is done in Movetrics Studio or the Movetrics app, and point to `docs/04-host-commands.md` section 1 for why. Calibration can be destroyed by a wrong command, and it cannot be restored from the host.

One program at a time may talk to an FDT. If Studio or the app is connected, your program will not get the stream.

## 6. Sync modes are new: probe, do not assume

Start-on-trigger, SYNC OUT and event frames (`Event` items: `sync_in_rise`, `sync_in_fall`, …) exist only in firmware that has the sync modes. Call `get_sync_mode()`: it returns `None` (Python) / `null` (TS) when the FDT does not have them (NACK 7). Use that answer, not the version number. If the user's plan depends on hardware sync and the probe says no, say so and offer the software path.

## 7. Files

- **CSV** (`write_csv`): one row per sample time, columns from `wide_columns()`, plus `name.csv.json` beside it with units, gaps, events and the source. Keep the JSON with the CSV.
- **C3D** (`write_c3d`): force platform type 2, moments moved to the plate surface, ORIGIN (0, 0, 0), N·mm, as Visual3D, OpenSim (ezc3d) and Mokka expect. Read back with ezc3d, the CoP lands within 0.3 mm rms of Studio's CSV (measured).
- **OpenSim .mot** (`write_mot`): external loads in OpenSim's axes (y up). Map plates to bodies in OpenSim's ExternalLoads file.
- Studio's own C3D puts the plate origin 30 mm below the surface; a standard reader then misplaces the CoP by 26 to 51 mm (measured). Prefer Studio's CSV, or re-write through this SDK.

## 8. Testing what you build

Run the SDK's own tests once to confirm the environment:

```sh
(cd python && python3 -m unittest discover -s tests -t .)    # from the repository root; the -t . is required
(cd ts && npm install && npm test)
(cd matlab && octave-cli --eval "run tests/run_tests.m")      # or run tests/run_tests.m in MATLAB
```

For the user's program: test it against the simulator with `--drop-every 500` (gaps) and `--signal cmj` (real-looking movement), and against a recorded Studio CSV with `--replay`. A client in a new language is correct when it passes every case in `vectors/*.json`; `vectors/README.md` gives the pass rule.

## 9. How to report back to the user

Say what you ran and on what: **measured** (a real FDT or a real recording), **simulated** (the simulator), or **not yet run**. A program that worked on the simulator has not been tested on hardware; say so and give the one-line change for the real device. Do not write "validated", "certified", "clinically accurate" or "research grade".

## 10. Where to look

| Question | File |
|---|---|
| Bytes of a frame, CRC, framing | `docs/03-host-link-framing.md`, `docs/05-measurement-stream.md`, `vectors/` |
| Commands, replies, NACK codes | `docs/04-host-commands.md` |
| Status, battery, versions | `docs/06-status-health-versions.md` |
| Names, units, axes, signs, CoP formula | `docs/19-vocabulary-and-units.md` |
| Studio files | `docs/18-export-formats.md` |
| Writing CSV, C3D, .mot | `docs/21-writing-files.md` |
| LSL, sync, clock alignment | `docs/22-lsl-and-sync.md` |
| Analog outputs | `docs/23-analog-outputs.md` |
| Simulator | `docs/20-simulator.md` |
| Which firmware does what | `contracts/firmware-capabilities.v1.json`, `COMPATIBILITY.md` |
| Cloud API | `contracts/movetrics-public-api-v1.json` (OpenAPI), `python/movetrics_fdt/cloud.py` |
| What has been tested | `CONFORMANCE.md`, `site/src/content/docs/concepts/tested.md` |
