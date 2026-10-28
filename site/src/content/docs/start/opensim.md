---
title: OpenSim and Pose2Sim
description: C3D and external loads files that put the centre of pressure where it belongs.
---

## The short version

```python
from movetrics_fdt.files import read_studio_csv
from movetrics_fdt.writers import Recording, write_c3d, write_mot

rec = Recording.from_studio(read_studio_csv("exam-channels.csv"))
write_c3d(rec, "exam.c3d", gaps="split")
write_mot(rec, "exam.mot", external_loads={1: "calcn_l", 2: "calcn_r"})   # + exam_ExternalLoads.xml
```

## Why not Studio's C3D

We read Movetrics Studio's own C3D with ezc3d, the library OpenSim 4 uses for C3D. The centre of pressure came out 26 to 51 mm (rms) away from Studio's own CSV. Two reasons: Studio stores moments in N·m while its plate geometry is in mm, and it writes two channels with flipped signs. A C3D written by the SDK gives a centre of pressure within 0.3 mm of Studio's CSV on both plates (measured on a real exam of 14 Oct 2026). If you already have Studio exports, convert the `-channels.csv` with the lines above rather than using the `.c3d`.

Studio's C3D also hides gaps: when a sample is missing, every later sample is shifted earlier. The SDK refuses to write a C3D across a gap unless you ask it to split the file there.

## OpenSim external loads

`write_mot` writes the OpenSim layout: `n_ground_force_v*`, `n_ground_force_p*`, `n_ground_torque_*` per plate, in OpenSim's ground frame (Y up), metres and newtons. With `external_loads` it also writes the XML that names the body each plate pushes on. For walking, which foot is on which plate changes per step; that assignment is yours (or Movetrics Cloud's gait analysis, when it lands).

## Pose2Sim

Pose2Sim gives you marker trajectories from video; the plates give you external loads. Put the plates into the same lab frame as your cameras: set each plate's corners in your lab (`rec.layout[1] = [...]`, mm, see [writing files](../../reference/21-writing-files/)), then load the `.mot` together with Pose2Sim's `.trc` in OpenSim's inverse dynamics. For time alignment between cameras and plates, see [Record with EMG and cameras](../emg-and-cameras/).

**Tested on:** ezc3d 1.6 with the 14 Oct 2026 Studio exam. The `.mot` layout follows OpenSim's documentation; it has not been run through OpenSim itself by us yet. The direction of the horizontal forces relative to the plate's connector is still to be confirmed with the plate maker.
