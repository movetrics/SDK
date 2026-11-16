# Changelog

All notable changes to the Movetrics SDK. Each entry says how it was checked: **measured** (a real FDT or a real recording), **simulated** (the SDK's simulator), or not yet run.

## Unreleased (2026-11-16): LSL from a web page and from MATLAB, the clock map pinned down

The FDT reaches LabRecorder from every client: Python as before, a web page through a local relay, and MATLAB. Nothing in this entry was run with a real FDT, LabRecorder, a browser, MATLAB itself or Noraxon hardware; what was run is said for each item.

- **LSL relay for web pages**: `movetrics-fdt lsl-relay` (Python, extra `relay`: pylsl and websockets) takes what a page's `FdtClient.samples()` yields over a WebSocket on 127.0.0.1 and publishes it with `LslBridge`, so a browser recorder and LabRecorder can share one FDT. It accepts pages served from this computer and programs without an Origin header, other sites only with `--allow-origin`; one page at a time (1013 to a second); it refuses bad data with 1007 or 1008 and a reason, and takes the streams off the network when the page leaves. TypeScript `LslRelay` (no runtime dependencies) sends the items within 10 ms, a missing centre of pressure as `null`, and stops with `LslRelayError` when the relay closes. Tested: message checks without a network, the relay end to end with a WebSocket page and an LSL inlet, `LslRelay` against a fake socket, and the whole chain with the simulator: the TypeScript client in Node read it over TCP for 8 s at 1,000 frames per second per plate, and all 8,000 samples of plate 1 reached an LSL inlet within 0.07 ms of the 1 ms spacing after the warm-up (simulated).
- **MATLAB**: `movetrics.LslBridge` publishes the same streams (names, channels, units, description, device label) with liblsl-Matlab, from what `movetrics.Fdt.read` returns; `movetrics.ClockMap` is the clock map. Tested in GNU Octave 8.4 with liblsl-Matlab and liblsl 1.18: 20 ms reads arriving 3 to 13 ms late gave rising stamps within 0.2 ms of the 1 ms spacing after the warm-up, NaN centre of pressure and markers kept (simulated). The Octave suite has 68 checks, one more with liblsl-Matlab on the path. Not yet run in MATLAB.
- **The clock map, exactly**: [chapter 22](docs/22-lsl-and-sync.md) states the method step by step, and `vectors/clock_map.json` (3 cases, from `tools/gen_clock_map_vectors.py`, not from a client) pins it pair by pair. The Python and MATLAB clock maps pass it, the MATLAB one also in batches of 7.
- **`LslBridge.close()`** (Python) pushes what is pending and takes the streams off the network; pushing afterwards raises `RuntimeError`.
- **Next to Noraxon EMG**: chapter 22 and the EMG page say how to record Noraxon EMG with the FDT in LabRecorder through Noraxon's own MIT-licensed bridge, Noraxon-LSL. Written from its published code and README; not run with Noraxon software or hardware.
- **Docs**: the Python, TypeScript and MATLAB READMEs, the EMG and cameras page, the tested page, the vectors README and AGENTS.md describe the relay and the MATLAB bridge.

## Unreleased (2026-11-16): LSL install line, two FDTs on one network

- **LSL install line**: [chapter 22](docs/22-lsl-and-sync.md) and `examples/python/lsl_stream.py` said `pip install 'movetrics-fdt[lsl,serial]'`, which fails because the package is not on PyPI. Both now give the GitHub install, as the README and the site already did; the example also gives the editable install from a checkout, and so does the examples README. The LSL test's skip message names `pylsl`. Checked on Linux: the GitHub install, pylsl 1.18.7 from the `lsl` extra, and the LSL test.
- **Two FDTs on LSL**: `LslBridge(..., device="B")` publishes `Movetrics FDT B plate 1`, … with source ids `movetrics-fdt-B-plate1`, …, and writes the label into each plate stream's description; `examples/python/lsl_stream.py` takes `--device B` and prints the stream names to tick in LabRecorder. Before, two FDTs on one network published the same names and ids, and the module docstring said the id held the FDT's serial number, which the SDK does not read. Without `device`, names and ids are unchanged. Tested with two bridges through pylsl on one machine (Linux, pylsl 1.18.7); not run with two real FDTs.

## Unreleased 0.3.2 (2026-11-15): one stream owner, paired Bluetooth, analog zero

Newer FDT firmware keeps a stream with the host that started it, and newer Bluetooth bridges talk only to a paired host. Nothing in this entry was run on a real FDT by the SDK; the firmware facts are read from the firmware's code and its own tests.

- **NACK 8 to START or STOP** now says what it most likely means: from firmware 1.2.8.28 the stream stays with the port (USB or Bluetooth) that started it, and the other port may only ask seven questions. `NackError.hint` (Python) and `FdtNackError.hint` (TypeScript) carry the explanation. Tested against fake transports.
- **Bluetooth pairing**: `BleTransport(address, pair=True)` asks the system to pair before subscribing (Linux, or a system that does not ask by itself); `bridge_needs_pairing(transport.bridge_status)` tells a pairing bridge (1.4 and later) from an older one. When the bridge refuses an unpaired host, `open()` or the write raises `TransportError` that explains the pairing window. Tested against a fake bleak. The Bluetooth example gained `--pair`.
- **Bytes between frames**: after a press of the FDT's reset button a Bluetooth host can receive up to three 8-byte bursts between replies. The Python and TypeScript decoders skip them; new tests feed every nonce of both kinds of burst, including those that put a frame header inside the burst.
- **Docs**: [chapter 2](docs/02-transports.md) sections 2.3 and 2.12 (stream owner, pairing, status fields, the burst), [chapter 5](docs/05-measurement-stream.md) section 4.5, the command registry gains 0x66 (factory test). The capability table gains `stream_stays_with_starting_port`.
- **Analog outputs** ([chapter 23](docs/23-analog-outputs.md), `contracts/analog-outputs.v1.json` 1.1.0): the zero offset is per unit (tens of mV possible; subtract the empty-plate mean), firmware before 1.2.8.21 gives moment outputs 100 times too large, keep the plates empty while Studio starts a test, start recording after the stream runs, use one rate and filter, and on an F1-3D S plate Mz is computed from Fx. The scale applies from 1.2.8.21.
- **Docs site**: the Python page shows Bluetooth with pairing; the EMG and cameras page adds the analog zero and firmware notes.

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
