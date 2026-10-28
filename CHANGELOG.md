# Changelog

All notable changes to the Movetrics SDK. Each entry says how it was checked: **measured** (a real FDT or a real recording), **simulated** (the SDK's simulator), or not yet run.

## 0.3.0 (2026-10-28): first public release

One vocabulary for every client, a simulator, files for other tools, and sync.

### Added

- **Shared vocabulary** ([chapter 19](docs/19-vocabulary-and-units.md), [`contracts/vocabulary.v1.json`](contracts/vocabulary.v1.json)): `t` in seconds from the FDT clock, `fx fy fz` in N, `mx my mz` in N·m, `cop_x cop_y` in m, plus `events` and `gaps`, with the signs of Movetrics Studio's files. Python `FdtClient.samples()`, TypeScript `client.samples()`, MATLAB `Fdt.read()`. Combined two-plate moments and CoP agree with Studio's export within 0.004 N·m and 0.29 mm rms (measured).
- **Simulator** (`movetrics-fdt simulate`, [chapter 20](docs/20-simulator.md)): a virtual FDT on TCP or a pseudo-terminal that speaks the real protocol, with standing, jumping or empty plates, a Studio replay, sleep and wake, dropped frames, stalls and clock drift.
- **File writers** ([chapter 21](docs/21-writing-files.md)): CSV with a JSON companion (units, gaps, events), C3D that OpenSim's reader places within 0.30 mm rms of Studio's CoP (measured), and OpenSim `.mot` external loads. Gaps are refused or split, never hidden.
- **Lab Streaming Layer** ([chapter 22](docs/22-lsl-and-sync.md)): one outlet per plate plus markers, FDT time mapped to the LSL clock (drift 0.13 ppm, residual 0.012 ms, simulated).
- **Sync**: clock alignment from sync pulses (`movetrics_fdt.sync`), and the FDT's sync modes (start or stop on the SYNC IN jack, SYNC OUT pulses, event frames) for firmware 1.2.8.24 and later, found by asking the FDT (`get_sync_mode()`). The firmware is a draft and has not run on hardware.
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
