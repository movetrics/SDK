---
title: Time, gaps and sync
description: Why every time comes from the FDT's clock, what a gap is, and how to line the FDT up with EMG, cameras or a second FDT.
---

## One clock

Every `t` comes from the FDT's own 0.1 ms counter. The USB adapter delivers data in bursts, so the moment a sample reaches your computer can be up to 16 ms late and varies from packet to packet. Timing from arrival would put that jitter into every rate of force development and every flight time. Timing from the FDT does not.

## Gaps

If samples go missing (a loose cable, an overloaded laptop), the clients do not hide it. Before the first sample after a hole you get a `Gap` with the plate, the start and end time and how many samples are missing. Files keep the hole: the CSV `.json` lists it, C3D refuses or splits (C3D cannot store a hole), `.mot` refuses unless you ask it to resample and mark the filled rows. A Studio C3D export hides a 41 ms hole in a real recording by moving every later sample 41 ms early; ours does not.

## Sync with other systems

FDTs with sync ports (firmware 1.2.8.24 and later; draft) have a SYNC IN and a SYNC OUT socket.

- **Start on a trigger**: the stream waits for a rising edge on SYNC IN.
- **Mark every edge**: each edge on SYNC IN or SYNC OUT arrives as an `Event` with its time on the FDT clock, finer than one sample.
- **Send a pulse train**: SYNC OUT sends a pulse every second (adjustable) for EMG or cameras to record.

`movetrics_fdt.sync.align()` takes the edge times on both clocks and returns offset, drift and how well they matched. Missed edges on either side are reported, not smeared into the result. `merge()` puts two FDTs into one four-plate recording: FDT A sends pulses, FDT B records them.

For Lab Streaming Layer (LabRecorder, EMG, eye trackers), see [EMG and cameras](../../start/emg-and-cameras/). Full detail: [LSL and sync](../../reference/22-lsl-and-sync/).

**Tested on:** the simulator with a clock running 50 ppm off (drift recovered within the test tolerance of 10 ppm). Not yet on a real FDT; the sync firmware is a draft waiting for the bench.
