# Changelog

All notable changes to the Movetrics SDK. Each entry says how it was checked: **measured** (a real FDT or a real recording), **simulated** (the SDK's simulator), or not yet run.

## Unreleased 0.3.1 (2026-11-08): four plates on one FDT

Some FDTs read four plates. Nothing in this entry was run on a real FDT by the SDK; the firmware facts are **measured** on real FDTs or read from the firmware's code.

- **Status from a four-plate FDT**: `get_status()` (Python) and `getStatus()` (TypeScript) accept up to five records, the general one and plates 1 to 4. Version 0.3.0 refused that reply. Tested on derived records.
- **`combine()`** refuses a plate other than 1 and 2, and the CSV writer adds `comb_` columns only for exactly plates 1 and 2. Before, a recording of plates 3 and 4 alone got `comb_` columns as if both stood in the middle.
- **Ask the FDT**: builds numbered 1.2.8.24 and 1.2.8.25 differ. Probe with GET_SYNC_MODE and count the plates in the stream instead of trusting the version. The capability table says so and gains four-plate rows ([chapter 5](docs/05-measurement-stream.md), section 14).
- **Four plates in the docs** ([chapter 5](docs/05-measurement-stream.md) section 14, [chapter 6](docs/06-status-health-versions.md) section 2.1): plate addresses 1 to 4, one START placeholder per plate slot, up to 1,000 frames per second per plate with four plates (2,000 loses about 22 %, measured), a first frame 2.4 s after a reset (measured), a watchdog restart after a hang (send START again), and the pad clip bit in the SATURATION event.
- **Docs site**: "Four plates on one FDT" on the units page; the sync page says to ask the FDT for sync.
- **Docs wording**: the reference chapters now describe the protocol a host relies on. Internal review notes (lists of open questions and of differences between sources) are no longer published.

## Unreleased (Python, 2026-11-02)

First run of the Python client against a real FDT (firmware 1.2.8.24, two plates), **measured** on a Mac.

- **USB**: firmware and status replies decode; KEEP_ALIVE 300 is accepted and 0 is refused before sending; 30 s at 2,000 frames per second per plate arrived complete in three runs; opening the port does not reset the FDT; after STOP the port is silent.
- **Bluetooth**: 100 to 500 frames per second stream; 1,000 drops the Mac's link within about a second (a phone streams faster through the same bridge). When a link drops without STOP, the bridge stops the stream itself.
- **`BleTransport`** refuses the name `Movetrics-BLE` when more than one FDT answers to it, and lists their addresses. Every FDT advertises that name.
- **`discover_bridges()`** (new) lists the FDTs in Bluetooth range, strongest signal first.
- **STOP and KEEP_ALIVE** are retried for up to about 4.5 s when the bridge is busy (ATT error 0x11). START and the other commands are never retried.
- **`set_rate()`**: a low rate needs a lower filter, for example `set_rate(100, cutoff_hz=40)`; the default 50 Hz cutoff must be below half the rate.

## Unreleased (docs, 2026-11-01)

No code or protocol change; the packages stay at 0.3.0.

- **Android app CSV** ([chapter 18](docs/18-export-formats.md), section 7): the Movetrics Android app's "Data as CSV" now writes the same wide table as the SDK's CSV writer (newtons, newton-metres, metres, Studio's signs, CoP empty below 50 N), named with the FDT firmware. Read from the app's code, not run on a phone here.
- **Where each client stands** ([chapter 19](docs/19-vocabulary-and-units.md), section 7): TypeScript, MATLAB and the Android app now speak the shared vocabulary; the table said "not yet" or "raw wire values" for them. The Cloud API still uses Studio's channel names.
- **Compatibility**: the sync-modes row says which firmware line 1.2.8.24 is built on; versions 1.2.8.21 to 1.2.8.23 have no sync. Not yet measured on hardware.
- **Wording**: chapter 18's sources and the Cloud export note name the Cloud, not the firmware, as their source; chapter 22 says where the sync wiring will appear instead of a garbled internal reference.
- **Docs site**: the Cloud API page uses the Movetrics brand colours and fonts, light and dark (already live since 28 Oct; now kept in the source).

## 0.3.0 (2026-10-28): first public release

One vocabulary for every client, a simulator, files for other tools, and sync.

### Added

- **Shared vocabulary** ([chapter 19](docs/19-vocabulary-and-units.md), [`contracts/vocabulary.v1.json`](contracts/vocabulary.v1.json)): `t` in seconds from the FDT clock, `fx fy fz` in N, `mx my mz` in N·m, `cop_x cop_y` in m, plus `events` and `gaps`, with the signs of Movetrics Studio's files. Python `FdtClient.samples()`, TypeScript `client.samples()`, MATLAB `Fdt.read()`. Combined two-plate moments and CoP agree with Studio's export within 0.004 N·m and 0.29 mm rms (measured).
- **Simulator** (`movetrics-fdt simulate`, [chapter 20](docs/20-simulator.md)): a virtual FDT on TCP or a pseudo-terminal that speaks the real protocol, with standing, jumping or empty plates, a Studio replay, sleep and wake, dropped frames, stalls and clock drift.
- **File writers** ([chapter 21](docs/21-writing-files.md)): CSV with a JSON companion (units, gaps, events), C3D that OpenSim's reader places within 0.30 mm rms of Studio's CoP (measured), and OpenSim `.mot` external loads. Gaps are refused or split, never hidden.
- **Lab Streaming Layer** ([chapter 22](docs/22-lsl-and-sync.md)): one outlet per plate plus markers, FDT time mapped to the LSL clock (drift 0.13 ppm, residual 0.012 ms, simulated).
- **Sync**: clock alignment from sync pulses (`movetrics_fdt.sync`), and the FDT's sync modes (start or stop on the SYNC IN jack, SYNC OUT pulses, event frames) on firmware with the sync jack, found by asking the FDT (`get_sync_mode()`). Not yet measured on hardware.
- **Analog outputs** ([chapter 23](docs/23-analog-outputs.md)): scale, signs and limits of the sixteen ±10 V outputs, and `movetrics_fdt.analog` to turn recorded volts back into the vocabulary.
- **Excel**: a ready workbook and Power Query code that pull Movetrics Cloud results, recordings and samples. Not yet run in Excel itself.
- **TypeScript client 0.3.0**: `setRate`, `setSyncMode`, `getSyncMode`, event frames and the vocabulary.
- **MATLAB toolbox**: vocabulary output, sync modes, `writeMot`. Tested in GNU Octave 8.4, not yet in MATLAB.
- **Contracts**: firmware capabilities by version ([`COMPATIBILITY.md`](COMPATIBILITY.md)), the Cloud API as OpenAPI 3.1, and the analog scale.
- **Conformance**: `vectors/vocabulary.json` and `tools/conformance.py`, which runs every client and writes [`CONFORMANCE.md`](CONFORMANCE.md).
- **Docs site** for [developers.movetrics.com](https://developers.movetrics.com), `AGENTS.md` and a start prompt for AI assistants.

### Changed

- Python `keep_alive(0)` is now refused, as in the TypeScript client: 0 would turn the FDT's sleep off and drain its battery.

## 0.2.0 (2026-10-28): rate setting, Studio files, Cloud API, MATLAB

- `set_rate(frames_per_second, cutoff_hz)`: 50 to 2,000 frames per second per plate on firmware 1.2.8.0 and later. 2,000 per plate over USB lost no frame (measured on an FDT with the firmware team's tool).
- Readers for Movetrics Studio CSV, details and C3D exports, tested on real exports.
- `CloudClient` for the Movetrics Cloud read API (personal access token from the environment).
- MATLAB toolbox `+movetrics`: live stream, Studio files, Cloud API, `plateCop`.
- Chapter 18: the files and streams a Movetrics system produces.

## 0.1.0 (2026-10-08): the host link

- The protocol specification of the FDT host link: transports, framing, commands, the stream, status and versions.
- Byte-level test vectors and two reference clients, Python and TypeScript, that pass them.
