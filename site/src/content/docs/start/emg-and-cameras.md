---
title: Record with EMG and cameras
description: Lab Streaming Layer for LabRecorder, and sync pulses for sample-level alignment.
---

Two ways to put force data on one time base with EMG, EEG, eye tracking or video.

## Without a cable: Lab Streaming Layer

LabRecorder records every LSL stream on the network into one XDF file: the FDT next to Noraxon (through its LSL bridge), Delsys, PLUX OpenSignals, EEG amplifiers and many more.

```sh
pip install "movetrics-fdt[lsl,serial] @ git+https://github.com/movetrics/sdk#subdirectory=python"
python examples/python/lsl_stream.py --port COM3 --rate 2000      # or --simulate to try without an FDT
```

Then start LabRecorder, tick `Movetrics FDT plate 1`, `plate 2` and `markers`, and record. Load with `pyxdf.load_xdf()` in Python or `load_xdf` in MATLAB.

Each sample's time is the FDT's own stamp mapped onto the LSL clock with a fitted offset and drift, so USB delivery jitter (up to 16 ms) does not enter the data. Alignment between devices is as good as LSL's own clock sync between computers, typically about a millisecond on one machine or a local network. [Details](../../reference/22-lsl-and-sync/).

## With a cable: sync pulses

For sample-level alignment the FDT can send a pulse train on SYNC OUT to your EMG system's trigger input, or start when a pulse arrives on SYNC IN. Every edge is reported with its exact FDT time, and `movetrics_fdt.sync.align()` gives offset, drift and residual from the two lists of edge times.

This uses the FDT's sync modes, which are **in development**: the host side and a simulator exist, the firmware is on the bench plan. Ask us before you plan a study on it.

## Through the analog outputs

FDTs with the analog board put each plate's Fz, Fx, Fy, moments and centre of pressure on sixteen ±10 V outputs (A1 to A8 plate 1, A9 to A16 plate 2) that an EMG amplifier's auxiliary inputs or a DAQ card can record. Fz is 800 N per volt, Fx and Fy 200 N per volt, moments 72 N·m per volt. In Python:

```python
from movetrics_fdt.analog import to_vocabulary
plate, name, value = to_vocabulary("A1", 0.205)     # (1, "fz", 164.0)
```

Three things to know before you use them in a study: they update at most 500 times per second and lag the force by about 12 ms, so they are not a time reference (use the pulses or LSL for that); the centre of pressure comes in 1 cm steps, so compute it from the forces and moments instead; and A3, A5, A11, A13 (Fy, Mx) have the opposite sign to Studio and our files. [Full scale table and limits](../../reference/23-analog-outputs/).

## Two FDTs as one four-plate system

FDT A sends the pulse train, FDT B listens on SYNC IN; `movetrics_fdt.sync.merge()` puts B's plates 3 and 4 onto A's clock. Simulated today, same status as above.

**Tested on:** LSL end to end with a real LSL inlet and the simulator; alignment and merging on simulated clocks. Not yet with a real FDT and LabRecorder.
