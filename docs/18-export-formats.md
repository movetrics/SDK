# 18 Export formats: Studio files, the live stream and the Cloud API

This document says what is in each file or stream a customer gets from a Movetrics system: units, axes, origins, timestamps, filtering and sample rate, with one annotated example each. It covers the live FDT stream (USB or Bluetooth), the three files Movetrics Studio writes per exam (`-channels.csv`, `-details.csv`, `.c3d`), and the Movetrics Cloud read API. Each statement is marked **measured** (checked on a real file or capture, named), **owner** (decided by Movetrics), **code** (read from firmware or Studio configuration) or **inferred** (fitted, not confirmed by the plate maker). Readers: Python `movetrics_fdt.files` and `movetrics_fdt.cloud`, MATLAB `matlab/+movetrics`.

Sources checked on 28 Oct 2026: Studio exports of 10 Oct 2026 (Free Run, 7,761 rows) and 14 Oct 2026 (CMJ Analysis, double platform, 10,561 rows, CSV and C3D of the same exam); discovery firmware 1.2.8.2; the firmware (Studio `config.ini`); `the Movetrics firmware repository (private)` `services/api/app/api_v1.py`, `profiles/movetrics-studio/1.0.0.json` and `python/movetrics-ingestion/movetrics_ingestion/fdt_geometry.py`.

## 1. The plates and their axes

An F1-3D plate is 35 cm by 60 cm (owner, 26 Oct 2026). A double-platform system puts two plates side by side, the 35 cm sides along x and touching, the 60 cm sides along y. Plate 1 (`p1`) is at negative x, plate 2 (`p2`) at positive x (inferred: fitted from the 14 Oct export, residual 0.37 mm, and the same order as the C3D corners in Section 4).

| Quantity | Unit | Direction | Status |
|---|---|---|---|
| Fx, Fy, Fz | N | Fz vertical, positive when loaded. Fx along the 35 cm side, Fy along the 60 cm side | owner (14 Oct 2026); direction of Fx and Fy relative to the room is not stated by the maker |
| Mx, My, Mz | N·m | Moments about a point 30 mm below the centre of the top surface | inferred (fit, 0.28 mm rms) and stated by the C3D ORIGIN z = -30 mm |
| CoP x, y | m | Plate CoP from the centre of that plate; combined CoP from the midpoint between the two plates | measured (14 Oct export) |

The plate CoP follows from its own columns of a Studio export as

    x = (-My - d·Fx) / Fz        y = (-Mx + d·Fy) / Fz        d = 0.030 m

This reproduces Studio's CoP columns to 0.28 mm rms on both plates of the 14 Oct export, which is the 1 mm rounding of those columns (measured). The y formula has the opposite sign to the textbook -Mx/Fz because Studio negates Fy and Mx (Section 2.3). Moments alone (d = 0) are 0.3 to 3.4 mm off. Studio writes no CoP below |Fz| = 50 N (`CopForceThreshold`, code). The combined CoP is the Fz-weighted mean of the plate CoPs moved by ∓0.175 m in x (measured, within 2 mm, the rounding).

## 2. The live stream (USB and Bluetooth)

### 2.1 Frame

Each plate sends one 24-byte frame per sample: `BE EF`, plate address (1 or 2), `01`, a uint32 stamp, six int16 values Fx Fy Fz Mx My Mz, a CRC-16/CCITT-FALSE over bytes 2 to 19, `04 04`; all little-endian (code, [05-measurement-stream.md](05-measurement-stream.md) Section 2). The format is shared with Studio and the apps and does not change without Movetrics.

Annotated example (stream vector `stream-derived-decode-fdt-index-19056`):

    be ef | 01 | 01 | 85 0d 03 00 | de ff | 00 00 | 05 00 | ff ff | 00 00 | 02 00 | b7 d3 | 04 04
    head  | plate 1 | START | stamp 200,069 = 20.0069 s | Fx -34 | Fy 0 | Fz 5 | Mx -1 | My 0 | Mz 2 | CRC | end

### 2.2 Values

The integers are whole newtons and whole newton-metres (owner, 14 Oct 2026; the firmware source names no unit). Resolution is therefore 1 N and 1 N·m: a moment of 1 N·m at Fz = 700 N is 1.4 mm of CoP, so compute CoP from an export with decimals (Studio comb columns) or average over samples. Values beyond ±32,767 wrap instead of clipping (code, doc 05 Section 3.2). The firmware has already removed the tare offset taken at power-up or by SET_TARE (code).

### 2.3 Signs: stream versus Studio files

Studio maps the stream to its files with `QuadrantTransform = 4,3,2,1`, which negates Fy and Mx. So for the same load: `Fy_file = -Fy_stream` and `Mx_file = -Mx_stream`, and in stream terms the plate CoP is `x = (-My - d·Fx)/Fz`, `y = (Mx - d·Fy)/Fz`. Status: from Studio's configuration, not yet confirmed by recording one known off-centre load both ways (bench check still open).

### 2.4 Timestamps

The stamp counts 0.1 ms ticks of the FDT's timer (10 kHz) from START and restarts at 0 on every START (code). The first frame of each plate after START is a placeholder with stamp 0: drop it (code, doc 05 Section 6). Both plates share the clock. On 1.2.8.x the frames of both plates are paced and stamped on one grid when the pads use queued samples, so equal stamps mean the same sample instant (code, doc 05 Sections 4.2 and 5.2). The stamp wraps after 2^32 ticks, about 4.97 days.

### 2.5 Rate and filter

| Setting | Default after power-up or reset | Range | How to change |
|---|---|---|---|
| Frames per second per plate | 500 | 50 to 2,000 | SET_FILTER 0x1C (Python `FdtClient.set_rate`, MATLAB `Fdt.setRate`), Movetrics firmware 1.2.8.0+ |
| Digital low-pass | 2nd-order Butterworth, 50 Hz | 1 to 255 Hz below half the rate, or 0 = off (raw) | same command |
| Analog input filter on the plate electronics | about 80 Hz, RC | fixed in hardware | — |

2,000 frames per second per plate over USB loses no frames on 1.2.8.1 and later (measured on the bench, 10 Oct 2026). The setting lives in RAM: send it after every connect, with the stream stopped, and wait 100 ms before START (code and bench practice). Because of the 80 Hz analog filter, content above about 80 Hz is attenuated whatever the digital setting (code/hardware note; a measured frequency response is not yet written up). The plate's own mechanical resonance was measured at about 60 Hz (26 Oct 2026; method to be confirmed): impact peaks above that are partly plate ringing.

## 3. Studio `-channels.csv`

Annotated first rows of the 14 Oct 2026 export (measured):

    Timestamp,p1_ForceX,p1_ForceY,p1_ForceZ,p1_MomentX,p1_MomentY,p1_MomentZ,p2_ForceX,...,comb_MomentZ,p1_COPx,p1_COPy,p2_COPx,p2_COPy,comb_COPx,comb_COPy
    0,-48.00,6.00,404.00,-20.00,18.00,-2.00,1.00,3.00,583.00,23.00,14.00,0.00,-47.00,9.00,987.00,3.00,0.67,-2.52,-0.041,0.050,-0.024,-0.039,0.001,-0.003

- `Timestamp`: FDT ticks of 0.1 ms from the start of the recording. Steps of 10 ticks (1,000 rows/s) in the 14 Oct export, 20 ticks (500 rows/s) in the 10 Oct export (measured). Whether Studio passes the FDT stamp through or re-times rows is not confirmed.
- **Gaps are real**: the 14 Oct export has one step of 410 ticks, a 41 ms hole at 5.28 s (measured). Use the Timestamp column, never the row number, as time. The readers report gaps (`StudioRecording.gaps`, MATLAB `rec.gaps`).
- `p1_*`, `p2_*`: per plate, N and N·m, Studio signs (Section 2.3). In the October 2026 exports the values are whole numbers written with two decimals; a June 2026 export carries fractions such as 336.61875 (measured), so the Studio version matters.
- `comb_*`: the two plates combined. Forces are the sums (987 = 404 + 583). Moments are about the midpoint between the plates and carry decimals (measured).
- `*_COPx`, `*_COPy`: m, three decimals (1 mm), empty below 50 N (measured; Section 1). Exports from before October 2026 have no CoP columns (June 2026 files, measured): compute CoP with the formula in Section 1.
- Filtering: whatever the FDT applied (Section 2.5). Studio does not send a filter setting with its default `CutoffFreq = 0` (code), so Studio files carry the FDT's 50 Hz low-pass unless something else set it.

## 4. Studio `.c3d`

The 14 Oct 2026 C3D of the same exam (measured with ezc3d):

| Parameter | Value |
|---|---|
| `ANALOG:RATE` | 1,000 Hz; 10,561 samples |
| `ANALOG:LABELS` / `UNITS` | the 18 force and moment columns of the CSV, same names, `N` and `Nm`; no CoP channels |
| `ANALOG:SCALE` / `OFFSET` | 1 / 0: values are stored in N and N·m |
| `FORCE_PLATFORM:TYPE` | 2 and 2 (six channels per plate) |
| `FORCE_PLATFORM:CORNERS` | mm. Plate 1: x 0 to 350, y 0 to 600; plate 2: x 350 to 700, y 0 to 600; z 0 |
| `FORCE_PLATFORM:ORIGIN` | (0, 0, -30) mm for both plates: the moment reference 30 mm below the top |
| `POINT:RATE` | 1,000 Hz; no markers |

**The C3D hides gaps.** It has the same 10,561 samples as the CSV but places them on a uniform 1 ms grid, so after the 41 ms hole every C3D time is 41 ms earlier than the FDT clock, and the file ends at 10.560 s where the CSV ends at 10.600 s (measured). Align C3D data with other devices only before a gap, or use the CSV. The C3D lab frame (origin at a corner of plate 1) differs from the CSV CoP frame (plate centres): convert with the corners above.

## 5. Studio `-details.csv`

Two columns, `Field,Value`. Fields seen (measured): Exam ID, Examinator, Exam Type (for example `CMJ Analysis`, `Free Run`), Exam Date, Start Time, End Time, Duration (seconds), Recording duration (seconds), Subject First Name, Subject Last Name, Subject Height (mm), Subject Weight (g), Subject Date of Birth, Subject Sex, Project Name, Project Description, Configuration Name (`Double Platform`), Configuration Description, Notes. It holds personal data. `Duration` is the exam window; `Recording duration` matches the last Timestamp (10.600 s, measured).

## 6. Movetrics Cloud read API v1

Base URL `https://beta.movetrics.com/api/v1` (beta). Authentication: an access token from Account > Access tokens, sent as `Authorization: Bearer mvt_…`; Excel's From Web uses Basic sign-in with any user name and the token as password. A token reads one workspace, read only, with its owner's current role; removing the member ends it. Athletes appear as codes unless the token was created with names on (code).

| Endpoint | Returns |
|---|---|
| `GET /me` | workspace, role, whether names are shown, token expiry |
| `GET /athletes` | athletes (codes, names if allowed) |
| `GET /recordings?since=&until=&athlete_id=&cursor=&limit=` | recordings newest first, each with the movement, key result and every engine result; follow `next_cursor` |
| `GET /recordings/{id}` | one recording, its channel list (`id`, `quantity`, `unit`, `component`) and sample count |
| `GET /recordings/{id}/samples?start=&stop=&channel=&format=json|csv` | stored samples, unfiltered, at most 100,000 per page; JSON gives `next_start`, CSV the header `X-Movetrics-Next-Start` |
| `GET /recordings/{id}/samples.parquet` | the stored signal file, byte for byte |
| `GET /results?metric_id=&since=&format=json|csv` | one row per result: recording_id, recorded_at, athlete_code, movement, metric_id, label, value, unit, method, method_version, engine_version, origin |

Samples are the recording as uploaded, after unit mapping and before any analysis filter: a Studio upload keeps Studio's columns and signs (channel ids such as `channel-4-p1_ForceZ` for CSV, `c3d-analog-3-p1_ForceZ` and `c3d-platform-1-center_of_pressure-x` for C3D). Time is in seconds (`time_s`). Results use SI units (m, s, N, W) and name the method and version that computed them. The contract is additive within v1: fields may be added, never renamed or removed (code). The Cloud's own derived downloads are specified in `the Movetrics firmware repository (private)` the firmware.

## 7. Open points

1. Confirm the stream-to-file sign change (Section 2.3) with one known off-centre load recorded both as stream and as a Studio export.
2. Ask the Studio developer whether Studio re-times rows or passes the FDT stamp, and why the C3D drops the gap.
3. Measure and publish the frequency response of the 80 Hz analog input filter and the 50 Hz digital default.
4. State the direction of +x and +y relative to the plate's cable connector, with a drawing.
