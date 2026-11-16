# Movetrics for MATLAB

Movetrics force-plate data in MATLAB, in the package `+movetrics`:

| You have | Use | Needs |
| --- | --- | --- |
| An FDT on USB, and you want the live stream | `movetrics.Fdt` (`setRate`, `start`, `read`, `stop`) | MATLAB R2019b+ (`serialport`) |
| Files exported by Movetrics Studio | `movetrics.readStudioCsv`, `readStudioDetails`, `readStudioC3d`, `plateCop`, `writeMot` (OpenSim .mot) | C3D: [ezc3d](https://github.com/pyomeca/ezc3d) |
| Recordings in the Movetrics Cloud | `movetrics.Cloud` (`recordings`, `samples`, `results`) | an access token, MATLAB R2016b+ |
| The live stream in LabRecorder, next to EMG or EEG | `movetrics.LslBridge` (`push`, `mark`, `stats`, `close`) | [liblsl-Matlab](https://github.com/labstreaminglayer/liblsl-Matlab) |

Add the folder to the path (`addpath('matlab')` from the repository root) and start from `examples/`. Units, axes, timestamps and the
CoP formula are in [../docs/18-export-formats.md](../docs/18-export-formats.md).

## Live stream

```matlab
fdt = movetrics.Fdt("COM5");      % close Movetrics Studio first: one app on the port at a time
fdt.setRate(2000, 0);              % frames/s per plate (50-2000), low-pass cutoff in Hz (0 = off)
m = movetrics.syncModes();         % optional: sync modes (firmware with the sync jack only)
fdt.setSyncMode(bitor(m.START_ON_RISE, m.EVENT_FRAMES));
fdt.start();
data = fdt.read(10);
fdt.stop();
```

`setRate` works on Movetrics firmware 1.2.8.0 and later and refuses older firmware. The FDT forgets the rate on
reset: it then streams its default (1,000 frames/s per plate from firmware 1.2.8.8, 500 before) with a 50 Hz low-pass.

`read` returns the shared vocabulary ([docs/19](../docs/19-vocabulary-and-units.md)), one row per sample:

| Field | Meaning |
| --- | --- |
| `plate`, `ticks`, `time_s`, `t` | plate 1 or 2; the FDT clock in 0.1 ms ticks; `t` = `time_s` in s from START |
| `fx fy fz` | N, plate frame. `fy` is the wire value with the sign changed |
| `mx my mz` | N*m, plate frame. `mx` is the wire value with the sign changed |
| `cop_x cop_y` | m from the plate centre; NaN below 50 N |
| `raw` | the six wire integers, columns forceX forceY forceZ momentX momentY momentZ |
| `events` | struct array of event frames: `t`, `stamp`, `type`, `name`, `source`, `count`, `offset_us`, `detail`, `mode` |
| `gaps` | struct array of holes: `plate`, `start_t`, `end_t`, `missing` (never filled) |

Older versions returned the wire values in `fy` and `mx`. Code that expects the Studio signs now gets them
without changes; code that used `raw` values from `fy`/`mx` should read `raw`.
`setSyncMode` needs firmware with the sync jack. On firmware
without the sync jack it stops with an error that names NACK 7.

## Lab Streaming Layer

`movetrics.LslBridge` publishes the live stream to LSL, so LabRecorder records it next to EMG, EEG or eye tracking.
The streams are the same as from the Python SDK ([docs/22](../docs/22-lsl-and-sync.md)). It needs
[liblsl-Matlab](https://github.com/labstreaminglayer/liblsl-Matlab) on the path.

```matlab
bridge = movetrics.LslBridge(2000, [1 2], 'Firmware', fdt.firmware);   % 'Device', 'B' for a second FDT
fdt.start();
while true, bridge.push(fdt.read(0.05)); end      % short reads: the clock mapping uses when each read returned
```

Each sample's stamp is its FDT time mapped onto the LSL clock by `movetrics.ClockMap` (the method of docs/22, checked
against `vectors/clock_map.json`). `bridge.StreamNames` lists what to tick in LabRecorder, `bridge.mark('jump 3')`
adds a note, `bridge.stats()` gives drift and residual, and `bridge.close()` takes the streams off the network. The
full script is `examples/lsl_stream.m`.

## Files: CoP and OpenSim

`movetrics.writeMot(path, t, plates)` writes an OpenSim external-loads file from per-plate samples in the plate
frame, using Studio's plate placement (plates 1 and 2 at (0.175, 0.300) m and (0.525, 0.300) m). It refuses a
recording with a gap, because OpenSim needs a uniform clock; it does not resample.

## Tested

Tested in GNU Octave 8.4, not yet in MATLAB. `tests/run_tests.m` (68 checks) runs with no hardware: the SDK's byte
vectors, the sync event vectors (`python/tests/fixtures/sync_events.json`), the clock-mapping vectors, the Studio
excerpts, a Python reference `.mot` (`tests/mot_reference.py`, needs python3) and `tests/MockSerialPort.m`, a
stand-in for the serial port that answers the host commands. With liblsl-Matlab on the path it adds one more check:
`movetrics.LslBridge` end to end through real LSL outlets and inlets (run in Octave 8.4 with liblsl 1.18). `tests/live_simulator_test.m` runs `movetrics.Fdt` against the SDK simulator
(`python3 -m movetrics_fdt simulate --pty PATH --profile sync`) and needs a serial port class: MATLAB R2019b+ or
the Octave `instrument-control` package. Not yet run: any real FDT, `readStudioC3d` (needs ezc3d's MATLAB binding;
the Python reader was checked on the real 14 Oct C3D), and the Cloud tests (`tests/mock_api.py`).

```sh
octave --no-gui --eval "run tests/run_tests.m"
octave --no-gui --eval "pkg load instrument-control; run tests/live_simulator_test.m"   # needs the package
```
