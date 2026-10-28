---
title: MATLAB in 5 minutes
description: Studio files, Cloud results and the live stream in MATLAB.
---

Copy the folder `matlab` from the [SDK](https://github.com/movetrics/sdk/tree/main/matlab) and add it to the path:

```matlab
addpath('/path/to/sdk/matlab')
```

## A Studio export

```matlab
rec = movetrics.readStudioCsv('2026-10-14 exam-channels.csv');
plot(rec.time_s, rec.columns.p1_ForceZ); xlabel('s'); ylabel('N')
rec.gaps          % [row, start_s, length_s] for every hole; never hidden
```

## The live stream

```matlab
fdt = movetrics.Fdt('COM3');      % macOS: '/dev/tty.usbserial-XXXX'
fdt.setRate(2000);
fdt.start();
pause(5);
d = fdt.read();                   % everything since the last read: t, fx ... mz, cop_x, cop_y per plate
fdt.stop();
```

No FDT? Run the simulator in a terminal with `movetrics-fdt simulate --pty /tmp/fdt` and open `movetrics.Fdt('/tmp/fdt')` (macOS and Linux).

## Cloud results

```matlab
cloud = movetrics.Cloud(getenv('MOVETRICS_TOKEN'));
results = cloud.results('metric_id', 'jump_height_flight_time');
```

## OpenSim

`movetrics.writeMot(...)` writes external loads; see [OpenSim and Pose2Sim](../opensim/).

**Tested on:** GNU Octave 8 with the simulator and the real Studio exports of 10 and 14 Oct 2026. Not yet run in MATLAB itself: if you run it, the test suite is `matlab/tests/run_tests.m`, and we would like to hear the result.
