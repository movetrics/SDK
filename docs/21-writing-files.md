# 21 Writing files other tools read: CSV, C3D, OpenSim (contract K5, SDK side)

`movetrics_fdt.writers` turns a recording in the shared vocabulary (doc 19) into the files labs already use. One rule holds for all three: **a gap is never hidden.** CSV keeps the real times; C3D and OpenSim, which need a uniform clock, refuse a recording with gaps until the caller chooses to split it (C3D) or to resample with a flag column (OpenSim).

```python
from movetrics_fdt.files import read_studio_csv
from movetrics_fdt.writers import Recording, write_c3d, write_csv, write_mot

rec = Recording.from_studio(read_studio_csv("exam-channels.csv"))      # or Recording.from_samples(live_items, 2000)
write_csv(rec, "exam.csv")                                             # + exam.csv.json (units, gaps, events)
write_c3d(rec, "exam.c3d", gaps="split")                               # exam-part1.c3d, exam-part2.c3d if a gap
write_mot(rec, "exam.mot", external_loads={1: "calcn_l", 2: "calcn_r"}) # + exam_ExternalLoads.xml
```

## CSV

Wide table `t, p1_fx … p1_cop_y, p2_…, comb_…` in SI units, decimal point, empty cells where nothing was measured or CoP is undefined (below 50 N). The companion `<file>.json` holds units, frame, metadata (rate, firmware, source), gaps and events. Rows keep the FDT time, so a hole is visible as a jump in `t`.

## C3D: what Studio's file gets wrong and how ours differs

Measured on the 14 Oct 2026 exam (double platform), reading with ezc3d 1.6, the C3D library OpenSim 4.x uses:

| C3D | CoP that ezc3d computes vs Studio's own CSV CoP |
|---|---|
| Studio's C3D as exported | 26 to 51 mm rms off |
| Studio's C3D, moments rescaled to N·mm | x within 0.29 mm, y mirrored (wrong sign) |
| Written by `write_c3d` | within 0.30 mm rms on both plates and both axes, max 0.50 mm (the 1 mm rounding of the CSV) |

Two causes. Studio stores moments in N·m while the plate geometry (CORNERS, ORIGIN) is in mm; a standard reader moves moments with the mm offset without converting, so the 30 mm ORIGIN term is 1,000 times too strong. And Studio writes Fy and Mx with the signs of its CSV, which its `QuadrantTransform` flipped; the C3D standard's plate convention matches the FDT's wire signs. `write_c3d` therefore writes:

- `ANALOG`: `Fx1 Fy1 Fz1 Mx1 My1 Mz1` (then plate 2), forces in N, moments in **N·mm** about the **top surface centre**, **wire signs**, at the FDT rate. The FDT's moments are about a point 30 mm below the top; the writer moves them up (Mx − 0.030·Fy, My + 0.030·Fx) so that `ORIGIN` can be 0 and no reader's sign convention for a non-zero `ORIGIN` matters.
- `FORCE_PLATFORM`: `USED`, `TYPE` 2, `CORNERS` (Studio's layout by default: plate 1 x 0 to 350 mm, plate 2 350 to 700 mm, y 0 to 600 mm, Studio's corner order), `ORIGIN` (0, 0, 0), `CHANNEL`, `ZERO` (0, 0: no baseline subtraction; the FDT has tared).
- `EVENT`: sync edges and notes, `MOVETRICS`: vocabulary version, first `t`, firmware.
- A gap: `GapError`, or `gaps="split"` writes one file per gap-free part, each with its true start time in `MOVETRICS:FIRST_T`.

The Cloud's C3D export uses the same convention (contract K5); both test suites run the fixture `python/tests/fixtures/k5_c3d_cop.json`.

Two FDTs or another layout: set `rec.layout[plate]` to that plate's four corners in the lab, in mm, in Studio's order.

## OpenSim `.mot`

Columns `time`, then per plate n: `n_ground_force_vx/vy/vz` (N), `n_ground_force_px/py/pz` (m), `n_ground_torque_x/y/z` (N·m), in OpenSim's ground frame with **Y up**: X = lab x, Y = lab z, Z = −lab y. The point is the CoP in the lab, the torque is the free moment about the vertical through the CoP (Tz = Mz − (x·Fy − y·Fx)). Below 20 N a plate's force and torque are written as 0 and its point as the plate centre, so OpenSim never applies noise at a wandering point. `external_loads={plate: body}` also writes the `ExternalLoads` XML that names the bodies (for a walking trial, which foot is on which plate per step is the caller's choice).

Status: the vertical force, the CoP and the time base follow from measured facts above. The direction of the horizontal forces in the lab follows the plate frame, whose +x and +y relative to the plate's connector the maker has not stated yet (doc 18 section 7); the bench check with one known horizontal push is on the bench queue. Not yet run through OpenSim itself; the file layout follows the OpenSim external loads documentation.

## Not here yet

XDF comes from LSL (doc 22, next). Parquet for long sessions on demand.
