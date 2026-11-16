# 24 Work with NOKOV XINGYING

XINGYING is the motion capture software of NOKOV (Windows). This chapter gives the ways to use the FDT next to it and what each has been checked against. Sources: the XINGYING 4.7 manual in English and Chinese (https://xingying-docs.nokov.com/xingying/XingYing4.7-EN/, chapters Plugins & SDKs and Third-party adaptation) and NOKOV's public GitHub (https://github.com/NOKOV-MOCAP). No XINGYING system was available while this was written: **nothing in this chapter has run with XINGYING yet.** Python: `movetrics_fdt.nokov`.

## 24.1 Which route

| You want | Route | Status |
|---|---|---|
| An FDT file for every XINGYING take, named like the take | Take sync (24.2) | Simulated: the manual's messages and a local UDP sender drive the SDK's simulator. Not yet run with XINGYING |
| To start and stop XINGYING recordings from your own program | Remote Control (24.3) | Messages built to the manual's examples. Not yet sent to XINGYING |
| The plates inside XINGYING: its 3D view, force graphs and C3D export | Analog outputs into an NI DAQ (24.4) | Values derived from the analog contract (chapter 23), computed consistency only. Not run in XINGYING |
| Samples aligned with the markers to a millisecond | A sync cable (24.5) | Not yet: needs the FDT's sync modes, simulated only |
| XINGYING's markers, rigid bodies and force plates (any maker) in Python | NOKOV's SDK library (24.6) | Experimental: checked against NOKOV's two GitHub builds without a server. Not yet run with XINGYING |

Take sync aligns takes, not samples: the trigger travels over the network, and that delay is in the cut. It has not been measured.

## 24.2 Take sync: an FDT file for every XINGYING take

XINGYING broadcasts a short XML message over UDP when a recording starts (`CaptureStart`) and when it stops (`CaptureStop`); the manual calls this Remote Trigger. Switch it on in XINGYING's data broadcast panel, section **Capture-Trigger** (port 7061 by default; the manual says a camera must be connected). Then, on the computer with the FDT:

```sh
pip install "movetrics-fdt[serial] @ git+https://github.com/movetrics/sdk#subdirectory=python"
movetrics-fdt nokov-record --serial COM3 --rate 2000 --out D:\fdt-takes
```

The FDT streams the whole time. Each CaptureStart and CaptureStop pair becomes one take, named after XINGYING's take:

- `<take>.csv` with `<take>.csv.json` (the CSV of chapter 21), or `<take>.c3d` with `--format c3d` (needs the `c3d` extra);
- `<take>.nokov.json`: both messages as received, their arrival times, the FDT times of the cut, the samples per plate and notes.

A name that exists already gets `-2`, `-3`, and so on: nothing is overwritten. Take names keep their script (Chinese names stay as they are); characters a file system refuses become `_`, and Windows device names such as `CON` get a leading `_`.

**Where the cut is.** The trigger's arrival is mapped onto the FDT clock with the clock map of chapter 22, so a take holds the FDT samples from the start time to the stop time in FDT time. A 2 s buffer (`--preroll`) keeps the samples that a trigger arriving a little late still needs. In the first 3 s the clock map is still warming up and the take's notes say so: start the recorder a few seconds before the first take.

**Unusual input.** One broadcast received twice (once per network card) counts once. A stop without a start is logged and ignored. A new start before a stop closes the open take there. A stop naming another take is accepted with a note (the manual's own example pair does this). A stop whose `RESULT` is not `SUCCESS`, and a message that had to be repaired to parse (the manual's example contains a bare `&`), are noted. Without a stop the take closes after `--max-take` seconds (600). XINGYING's `DatabasePath` is recorded, never used as a path.

With `--lsl` the FDT is also published on LSL (chapter 22) and each trigger becomes a marker, `NOKOV CaptureStart <take>`. To see what XINGYING sends, run `movetrics-fdt nokov-listen`. On Windows, allow Python through the firewall for the network XINGYING is on.

In Python, `TakeCutter` cuts takes from any stream of samples, `TriggerListener` receives the messages and `record_takes()` combines both with `FdtClient.samples()`; `parse_capture_message()` reads one message.

**For Movetrics Cloud**, upload the C3D takes: with the simulator they imported with one question, which way is up (16 November 2026). CSV takes are read too, but the Cloud then asks for the force unit, because the units are in the `.csv.json` beside the file.

Status: the unit tests read the manual's four example messages byte for byte, UTF-8 and GBK take names, repeated, stray and hostile datagrams. End to end over local UDP with the simulator at 1,000 frames per second per plate, a take of 2.16 s held 2,162 samples per plate (simulated). Not yet run with XINGYING.

## 24.3 Remote Control: start and stop XINGYING

XINGYING listens for the same two messages; the manual calls this Remote Control. Switch it on in the data broadcast panel, section **Capture-Remote** (port 7060 by default, a camera connected). Then:

```sh
movetrics-fdt nokov-control start --host 192.168.1.20 --name jump01 --database-path "D:\NOKOV\project"
movetrics-fdt nokov-control stop --host 192.168.1.20 --name jump01
```

`--host` can be a broadcast address. With rigid-body or body templates loaded, `--database-path` must be XINGYING's current working directory, or the take cannot be opened in XINGYING's edit mode (the manual). In Python: `capture_start_message()`, `capture_stop_message()` and `send_capture_message()`.

Status: the messages follow the manual's examples, field order and declaration, and read back through `parse_capture_message()`. Not yet sent to XINGYING.

## 24.4 The FDT's analog outputs as a force plate in XINGYING

XINGYING reads analog force plates through an NI USB-6218 or USB-6225 that the main camera clocks through its AUX output (the manual). An FDT with the analog board (chapter 23) can feed one. `movetrics-fdt nokov-analog-setup --firmware <the FDT's version>` prints everything below as a worksheet (`--json` as data); it refuses firmware before 1.2.8.21, whose moment outputs are 100 times too large.

**Wiring.** XINGYING's Bertec analog recipe puts Fx on channel 1, then Fy, Fz, Mx, My and Mz on channels 2 to 6. Wire the FDT the same way:

| XINGYING channel | Signal | Plate 1 output | Plate 2 output | Scale |
|---:|---|---|---|---:|
| 1 | Fx | A2 | A10 | 200 N per V |
| 2 | Fy | A3 | A11 | 200 N per V |
| 3 | Fz | A1 | A9 | 800 N per V |
| 4 | Mx | A5 | A13 | 72 N·m per V |
| 5 | My | A6 | A14 | 72 N·m per V |
| 6 | Mz | A4 | A12 | 72 N·m per V |

Leave A7, A8, A15 and A16 (centre of pressure, 1 cm steps) unconnected: XINGYING computes the centre of pressure from forces and moments.

**In XINGYING** (following its Bertec analog recipe): third-party devices, Channel Configuration: the six channels per plate in the order above, range ±10 V. Then Force Platform Parameter Settings, `+`: a six-channel analog plate type, size 350 mm (x) by 600 mm (y), its position and direction in your lab, and the calibration matrix below; then tick the analog connection option.

**Calibration matrix, candidate A** (rows Fx Fy Fz Mx My Mz; columns channels 1 to 6; N per V and N·m per V). The moments are moved from the FDT's reference 30 mm below the plate's top to the centre of the top surface, Mx − 0.03·Fy and My + 0.03·Fx, as the SDK's C3D files do (chapter 21):

```
Fx   200     0     0     0     0     0
Fy     0   200     0     0     0     0
Fz     0     0   800     0     0     0
Mx     0    -6     0    72     0     0
My     6     0     0     0    72     0
Mz     0     0     0     0     0    72
```

Candidate B is the plain diagonal (200, 200, 800, 72, 72, 72) with the plate origin 30 mm below the top surface, if XINGYING offers an origin field; its sign convention for that field is not documented. Signs are the FDT's wire signs, the frame of the type-2 plates in the SDK's C3D files: Fy and Mx have the opposite sign to Movetrics Studio's CSV (chapter 19).

**Not settled by XINGYING's manual:** which plate type fits a six-channel conditioned plate (no generic type is documented; the AMTI and Bertec analog types take six channels and a matrix); whether its matrix takes moments per volt in N·m or N·mm; the axis convention of the chosen type and how the plate is oriented in the lab; whether an origin field exists; and which way the FDT plate's +x and +y point relative to its cable connector.

**Check on site before use:**

1. Set Force Units to newtons (Force Plate Data window). Zero with the plates empty, with XINGYING's Zeroing Option or by subtracting each channel's empty mean: the FDT's analog zero differs per unit by up to tens of mV, and 58 mV is 46 N of Fz. The manual gives two different defaults for zeroing, so check which one is set.
2. A known weight at the plate centre: Fz reads the weight (within the 1.8 % gain tolerance), Fx and Fy near 0, the centre of pressure at the plate centre.
3. Move the weight 100 mm along the long side, then 100 mm along the short side: the centre of pressure moves 100 mm the same way in XINGYING. The wrong way means the plate is rotated in XINGYING or a moment row has the wrong sign; 1,000 times too little or too much means the moment unit is wrong.
4. Push horizontally along XINGYING's +x and +y: Fx and Fy take the sign XINGYING shows for that direction.
5. Later, record the same take digitally with `nokov-record` and compare it with XINGYING's force export.

**Limits.** The outputs change at most 500 times per second per plate; sampling them faster adds nothing. They lag the force by about 12 ms (chapter 23), so forces sit that far behind the markers. Moments move in whole N·m, so the centre of pressure moves in steps of 1 N·m / Fz: 1.25 mm at 800 N, 10 mm at 100 N. XINGYING's manual says analog force plates and EMG cannot be used interchangeably with digital force plates or digital EMG (Noraxon over its SDK, for example): with digital EMG in XINGYING, use take sync (24.2) or LSL (chapter 22) instead.

Status: derived from the analog contract (`contracts/analog-outputs.v1.json`) and the SDK's C3D convention. The unit tests check computed consistency: the matrix applied to voltages made from known forces and moments gives the centre of pressure of `plate_cop` (chapter 19) and of the SDK's C3D writer read back with ezc3d. Not run in XINGYING.

## 24.5 Sample-level alignment

NOKOV's Sync Unit has 5 V and 3.3 V TTL outputs and TTL inputs (the manual). A pulse between it and the FDT's SYNC IN or SYNC OUT (chapter 22, sync helpers) would align samples to the FDT's clock; a spare NI channel could also record an FDT pulse next to the analog plates. Neither has been tried: the FDT's sync modes are simulated only.

## 24.6 XINGYING's data in Python (experimental)

XINGYING also streams what it tracks to programs that use NOKOV's SDK: labeled and unlabeled markers, rigid bodies, skeletons and the force plates it reads, from any maker. `movetrics_fdt.nokov_sdk` reads that stream with NOKOV's own library, which NOKOV publishes for Linux (x64, aarch64, armhf) in its ROS repositories on GitHub, for example `mocap_nokov/deps/nokov_sdk/lib/x64/libnokov_sdk.so` (BSD-3-Clause). This SDK does not include the library; point to your copy. Switch on the SDK in XINGYING's data broadcast panel, then:

```sh
export MOVETRICS_NOKOV_SDK=/path/to/libnokov_sdk.so
movetrics-fdt nokov-sdk-check                      # the library's version and the layout check
movetrics-fdt nokov-stream --server 10.1.1.198     # the address shown in XINGYING's data broadcast panel
```

```python
from movetrics_fdt.nokov_sdk import NokovClient, NokovForcePlates

if __name__ == "__main__":                          # the library runs in a child process
    with NokovClient("10.1.1.198") as nokov:
        print(nokov.server, nokov.descriptions.force_plates)
        for item in nokov.items():                  # NokovFrame, NokovForcePlates or NokovMessage
            if isinstance(item, NokovForcePlates):
                print(item.frame, [plate.force for plate in item.plates])
```

**How it works.** Every build of the library exports a flat C interface that no header declares; the module calls it with ctypes and the data layouts of NOKOV's header (`NokovSDKTypes.h` 1.3.0.12). Before it connects it checks the layout: it writes a frame with known values, lets the library copy it and reads every field back, and it refuses a library that differs. The library runs in a child process, so a fault in it cannot take your program down. Frames arrive through a bounded queue; what does not fit is counted in `dropped`, not lost silently.

**Nothing is converted.** Positions are in millimetres. Force-plate forces are in XINGYING's Force Units setting (N, kgf or lbf; the stream does not say which). The force plate's point and free moment come as the library gives them: the header defines neither their units nor their frame. Each item carries its arrival time (`time.monotonic()`); the frame's own `timestamp` has no stated unit.

On Windows, NOKOV's library comes from its download page; this module has not been tried with it.

Status: in CI against NOKOV's GitHub builds 2.5.51.57 and 2.5.53.12 (x64), without a XINGYING server: loading, version, the layout check, a connection attempt that fails within the library's 5 s with its reason, and a clean shutdown. The conversions are tested on frames built in memory. Not yet run against XINGYING.

## 24.7 Not here yet

- XINGYING's stream on Lab Streaming Layer, next to the FDT.
- Importing XINGYING's exports (C3D, `.forces`, `.anc`) into Movetrics Cloud: it needs sample files first.
- XINGYING reading the FDT digitally: that needs NOKOV; the FDT protocol and the test vectors in this SDK are open for it.
- This chapter in Chinese.

NOKOV and XINGYING are NOKOV's names. Nothing here is tested or endorsed by NOKOV.
