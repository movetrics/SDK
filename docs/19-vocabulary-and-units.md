# 19 Vocabulary, units and frames (contract K4)

Every Movetrics client, file writer and API uses the names, units and frames below, so that a sample read live in Python, decoded in MATLAB, captured in Chrome, recorded on Android or downloaded from the Cloud is the same sample with the same numbers. The machine-readable form is [`contracts/vocabulary.v1.json`](../contracts/vocabulary.v1.json); the Python reference is `movetrics_fdt.vocabulary`.

Status: **draft 1.0.0**, published 28 Oct 2026 for agreement with the Cloud and Android work. It becomes 1.0.0 when both agree; a later change bumps the version and keeps 1.x readable. Each fact is marked measured, code, owner or inferred, as in doc 18.

## 1. Names and units

| Name | Unit | Meaning |
|---|---|---|
| `t` | s | Time from the FDT clock: stamp / 10,000. Live: since START (the stamp restarts at 0 on every START). Files: since the first row. Never the host's receive time, never the row number. |
| `stamp` | tick (0.1 ms) | The wire stamp, unwrapped past 2^32 (the uint32 wraps after about 4.97 days). |
| `plate` | | 1 or 2, the FDT's plate address. Two FDTs merged: plates 3 and 4 are the second FDT's 1 and 2. |
| `fx` `fy` `fz` | N | Force, plate frame. `fz` vertical, positive when loaded. |
| `mx` `my` `mz` | N·m | Moment about the plate's moment reference, 30 mm below the centre of the top surface (measured, section 3). |
| `cop_x` `cop_y` | m | Centre of pressure from the plate centre, plate frame. Empty (`null`, `NaN` in arrays) below 50 N. |
| `raw` | N, N·m | The six int16 wire integers in wire order and wire signs (forceX, forceY, forceZ, momentX, momentY, momentZ). Whole newtons and newton-metres (owner, 14 Oct 2026). |
| `events` | | Things at an instant: sync edges, trigger start, saturation (from the FDT), gaps and notes (from the host). Section 4. |
| `gaps` | | Holes in the stream: `plate`, `start_t`, `end_t`, `missing`. Section 5. |
| `t_host` | s | Optional: host clock when a frame was read. Diagnostics and clock mapping (LSL) only. |

Wide tables (CSV, spreadsheets, MATLAB tables) prefix per plate: `t, p1_fx, …, p1_cop_y, p2_fx, …, comb_fx, …, comb_cop_y`. `comb_` is the two plates together in the pair frame (Studio's word, kept so Studio users find it). Units are never in the column name; they are fixed here and repeated in the file's metadata.

## 2. Frames

- **Plate frame**: origin at the centre of the plate's top surface; x along the 35 cm side, y along the 60 cm side, z vertical; signs as in Movetrics Studio's `-channels.csv`. Which way +x and +y point relative to the cable connector is not yet stated by the maker (doc 18 section 7, item 4).
- **Pair frame**: origin midway between the two plate centres, same axes; plate 1 centre at x = −0.175 m, plate 2 at +0.175 m (inferred, fitted on the 14 Oct 2026 export, residual 0.37 mm). The `comb_` quantities live here.
- **Lab frame**: right-handed, z up, origin and plate placement from a layout file (the Movetrics Cloud lab setup and the SDK writers share one format, doc 21 when it lands). Default: Studio's C3D, origin at the outer corner of plate 1.

**Stream to plate frame.** The wire integers carry the controller's signs. Studio's `QuadrantTransform = 4,3,2,1` negates Fy and Mx when it writes its files (code: Studio `config.ini`, doc 18 section 2.3). The vocabulary takes the Studio file signs as the plate frame, so

    fx = +forceX   fy = −forceY   fz = +forceZ   mx = −momentX   my = +momentY   mz = +momentZ

Why Studio's signs and not the wire's: every customer file in existence uses them, the CoP formula and the C3D geometry were measured against them, and the Cloud stores Studio uploads as they are. Converting the live stream once is cheaper than converting every file. Status: from Studio's configuration; the bench check (one known off-centre load recorded both as stream and as Studio export) is on the bench queue.

## 3. Centre of pressure and moments

    cop_x = (−my − d·fx) / fz        cop_y = (−mx + d·fy) / fz        d = 0.030 m, fz ≥ 50 N

This reproduces Studio's CoP columns to 0.28 mm rms on both plates of the 14 Oct 2026 export, the 1 mm rounding of those columns (measured). Moments alone (d = 0) are 0.3 to 3.4 mm off. Below 50 N Studio writes no CoP (`CopForceThreshold`); the vocabulary does the same.

Combined (`comb_`): forces add; moments move to the pair origin with M + r × F, r = (±0.175, 0, 0) m; the combined CoP follows from the combined wrench with the same formula, so a lightly loaded plate still counts. Against all 10,561 rows of the 14 Oct export: `comb_` moments within 0.004 N·m rms, combined CoP within 0.29 mm rms in x and 0.23 mm in y, at most 0.5 mm (measured, `movetrics_fdt.vocabulary.combine`).

## 4. Events

One list per recording, ordered by `t`, each with `t`, `stamp`, `offset_us`, `type`, `name`, `source`, `count`, `detail`. `t` = stamp / 10,000 + offset_us / 10^6: the FDT reports where inside its 0.1 ms tick the edge fell.

| type | name | From | source, detail |
|---|---|---|---|
| 1 | `sync_in_rise` | FDT | input 0 |
| 2 | `sync_in_fall` | FDT | input 0 |
| 3 | `sync_out_rise` | FDT (master out, pulse train) | output 0 |
| 4 | `sync_out_fall` | FDT | output 0 |
| 5 | `stream_armed` | FDT: START received, waiting for SYNC IN | detail = arm timeout, min |
| 6 | `stream_started_by_trigger` | FDT: the edge that started the stream | stamp 0 or 1 with its offset |
| 7 | `saturation` | FDT: a plate value left int16, or a pad channel clipped | source = plate, detail = channel mask (bits 0-5 fx..mz, bit 6 pad) |
| 8 | `frames_dropped` | FDT | detail = frames |
| 9 | `saturation_end` | FDT | as 7 |
| 10 | `arm_expired` | FDT: armed START timed out | detail = arm timeout, min |
| 100 | `gap` | host: a hole was found (also in `gaps`) | |
| 101 | `note` | host: a text note (annotation, LabRecorder marker) | |

Types 1 to 10 come from FDT 1.2.8.24's event frame (plate address 0xFD, code 0x0E, opt-in with `SET_SYNC_MODE` 0x28), specified in doc 05 section 13 and `vectors/sync_events.json`. That firmware is not released or benched yet; the SDK decodes every case of its vectors.

## 5. Gaps

A gap is a step between consecutive samples of one plate longer than 1.5 nominal periods. Every reader and decoder reports gaps and never fills, re-times or hides them. A writer that needs a uniform clock (C3D, OpenSim `.mot`) states what it did: refuse, split into segments, or resample with a flag column and a warning. Studio's C3D does none of these: it places the 14 Oct samples on a uniform grid and every sample after the 41 ms hole is 41 ms early (measured, doc 18 section 4).

## 6. Metadata every file and stream carries

`rate_hz` (nominal frames per second per plate), `lowpass_hz` (FDT digital low-pass, 0 = off, null = unknown), `firmware` (GET_FW_VERSION string), `source` (`live`, `studio_csv`, `studio_c3d`, `cloud`, `simulator`), optional `fdt_serial`, and the vocabulary version.

## 7. Where each client stands

| Client | Vocabulary | Notes |
|---|---|---|
| Python `movetrics_fdt` 0.3.0 | yes: `FdtClient.samples()`, `SampleConverter`, `plate_cop`, `combine` | tested against the simulator and the 14 Oct export |
| MATLAB `+movetrics` | partly: `readStudioCsv` gaps and CoP; live samples next | |
| TypeScript `movetrics-fdt-sdk` | not yet | |
| Cloud API v1 | channel ids keep Studio's names (`channel-4-p1_ForceZ`) | mapping to these names: the firmware team |
| Android `fdt-core` | raw wire values | mapping: the firmware team |
