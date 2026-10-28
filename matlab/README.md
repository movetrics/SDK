# Movetrics for MATLAB

Three ways to get Movetrics force-plate data into MATLAB, in the package `+movetrics`:

| You have | Use | Needs |
| --- | --- | --- |
| An FDT on USB, and you want the live stream | `movetrics.Fdt` (`setRate`, `start`, `read`, `stop`) | MATLAB R2019b+ (`serialport`) |
| Files exported by Movetrics Studio | `movetrics.readStudioCsv`, `readStudioDetails`, `readStudioC3d`, `plateCop`, `writeMot` (OpenSim .mot) | C3D: [ezc3d](https://github.com/pyomeca/ezc3d) |
| Recordings in the Movetrics Cloud | `movetrics.Cloud` (`recordings`, `samples`, `results`) | an access token, MATLAB R2016b+ |

Add the folder to the path (`addpath('matlab')` from the repository root) and start from `examples/`. Units, axes, timestamps and the
CoP formula are in [../docs/18-export-formats.md](../docs/18-export-formats.md).

## Live stream

```matlab
fdt = movetrics.Fdt("COM5");      % close Movetrics Studio first: one app on the port at a time
fdt.setRate(2000, 0);              % frames/s per plate (50-2000), low-pass cutoff in Hz (0 = off)
m = movetrics.syncModes();         % optional: sync modes (draft, firmware with sync modes only)
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
`setSyncMode` needs firmware with sync modes and raises an error with NACK 7 on older firmware. The event frame
layout and the sync modes are draft until firmware 1.2.8.24 is released.

## Files: CoP and OpenSim

`movetrics.writeMot(path, t, plates)` writes an OpenSim external-loads file from per-plate samples in the plate
frame, using Studio's plate placement (plates 1 and 2 at (0.175, 0.300) m and (0.525, 0.300) m). It refuses a
recording with a gap, because OpenSim needs a uniform clock; it does not resample.

## Tested

Tested in GNU Octave 8.4, not yet in MATLAB. `tests/run_tests.m` (61 checks) runs with no hardware: the SDK's byte
vectors, the sync event vectors (`python/tests/fixtures/sync_events.json`), the Studio excerpts, a Python
reference `.mot` (`tests/mot_reference.py`, needs python3) and `tests/MockSerialPort.m`, a stand-in for the serial
port that answers the host commands. `tests/live_simulator_test.m` runs `movetrics.Fdt` against the SDK simulator
(`python3 -m movetrics_fdt simulate --pty PATH --profile sync`) and needs a serial port class: MATLAB R2019b+ or
the Octave `instrument-control` package. Not yet run: any real FDT, `readStudioC3d` (needs ezc3d's MATLAB binding;
the Python reader was checked on the real 14 Oct C3D), and the Cloud tests (`tests/mock_api.py`).

```sh
octave --no-gui --eval "run tests/run_tests.m"
octave --no-gui --eval "pkg load instrument-control; run tests/live_simulator_test.m"   # needs the package
```
