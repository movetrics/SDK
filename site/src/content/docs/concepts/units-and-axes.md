---
title: Names, units and axes
description: One set of names, units and axes in every Movetrics client, file and API.
---

Every Movetrics client (Python, MATLAB, TypeScript, Android), every file the SDK writes and the Cloud API use the same names. Learn them once. The full contract is [Vocabulary and units](../../reference/19-vocabulary-and-units/) and the machine-readable `contracts/vocabulary.v1.json`.

| Name | Unit | Meaning |
|---|---|---|
| `t` | s | Time on the FDT's own clock, from its 0.1 ms counter. Never the time a packet reached your computer. |
| `plate` | 1, 2 | Which plate. A second FDT merged in becomes 3 and 4. |
| `fx fy fz` | N | Force on the plate. `fz` is positive when someone stands on it. |
| `mx my mz` | N·m | Moment about the plate's reference point, 30 mm below the top surface, under the plate centre. |
| `cop_x cop_y` | m | Centre of pressure from the plate centre. Empty (NaN) below 50 N, because it means nothing there. |
| `stamp` | 0.1 ms | The FDT's counter, kept so you can check the time base yourself. |
| `raw` | integers | The six numbers exactly as they came over the cable. |

## Axes

The plate frame matches a Movetrics Studio export, so a live sample and the same sample in a Studio CSV carry the same numbers. On the wire the FDT sends `fy` and `mx` with the opposite sign; the clients flip them for you and keep the wire values in `raw`.

The centre of pressure is

```
cop_x = (-my - 0.030 · fx) / fz
cop_y = (-mx + 0.030 · fy) / fz
```

which reproduces Studio's CoP columns to 0.28 mm rms on a real two-plate export (measured, 14 Oct 2026).

## Two plates together

The `comb_` columns are the two plates as one: plate 1's centre at x = -0.175 m and plate 2's at +0.175 m. Forces add, moments move to the middle, and the combined centre of pressure comes from the combined values, so it stays right when one foot is light. Against Studio's own combined columns: 0.29 mm rms (measured).

## Four plates on one FDT

Draft firmware 1.2.8.27 (and an earlier four-plate build) reads plates 1 to 4 on one FDT; samples carry `plate` 3 and 4 like 1 and 2, and a CSV gets `p3_` and `p4_` columns. The `comb_` columns stay Studio's pair of plates 1 and 2, so a file with plates 3 or 4 has none, and `combine()` refuses a plate it cannot place. Where plates 3 and 4 stand is up to your lab: give them corners in `recording.layout` before writing C3D. With four plates, stream at up to 1,000 samples per second per plate; at 2,000 the USB link drops about a fifth of the frames (measured). The SDK reads a four-plate FDT's status from version 0.3.1. Details: [the stream reference, section 14](../../reference/05-measurement-stream/).

## In files

- **CSV**: these names as column headers (`p1_fz`, `comb_cop_x`), plus a `.json` file next to it with units, gaps and events.
- **C3D**: what Visual3D, OpenSim and Mokka expect: millimetres and N·mm, corners and origin of each plate. Studio's own C3D puts the centre of pressure 26 to 51 mm off; ours is within 0.3 mm of Studio's CSV (measured with ezc3d).
- **OpenSim .mot**: OpenSim's Y-up axes, centre of pressure on the floor, free moment. See [OpenSim](../../start/opensim/).
