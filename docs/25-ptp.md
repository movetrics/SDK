# 25 Plate samples on PTP time (IEEE 1588)

Labs whose cameras and other devices share a PTP (Precision Time Protocol, IEEE 1588) network want force data on the same clock. This chapter says what the FDT can and cannot do there, the two routes the SDK offers, what each needs, and how accurate each is, with every number marked as measured, simulated or inferred.

Status: written 24 November 2026. Nothing in this chapter has run with a real FDT or a PTP network yet. The numbers marked simulated come from the SDK's tests and its simulator.

## 1. What the FDT can and cannot do

The FDT is not a PTP clock and cannot join a PTP network. It reaches a computer over USB or Bluetooth, and PTP needs an Ethernet port that timestamps packets in hardware. The RJ45 sockets on the plates carry the plate bus, not Ethernet.

The FDT keeps its own clock: every sample carries a stamp in 0.1 ms ticks (chapter 05, section 5), and firmware with the sync modes (1.2.8.24 and later, on FDTs with the sync jack) stamps every edge on SYNC IN to the microsecond (chapter 04, section 3.9; chapter 05, section 13). The SDK puts that clock onto PTP time in one of two ways.

| Route | What it needs | Accuracy of the time base | Status |
|---|---|---|---|
| **Pulse** | A pulse at known PTP times into SYNC IN, usually one per second (a "PPS" output); firmware with the sync modes | The FDT's timing of the edge: the interrupt latency, a few microseconds (inferred from code). Averaged over 11 pulses, smaller | Simulated: every sample within 1 µs of the true PTP time, a clock 35 ppm fast. Not run on hardware |
| **Host** | A computer whose clock follows PTP (linuxptp on Linux, the PTP client of Windows); no cable | The computer's own PTP error, plus the clock map's error (about 1 ms in simulation), plus a constant delay that must be measured once (section 4) | Simulated: within 1.3 ms once the constant is known. Not run on hardware |

Use the pulse route whenever the PTP network has a device with a pulse output. The host only has to know PTP time to within a quarter of a second there, so a computer on NTP is enough, and Windows and macOS need no PTP software.

## 2. Pulse route: wiring and recording

1. Take a pulse-per-second output from the PTP network: many grandmaster clocks have one, and so do network cards and boards whose PTP clock drives a pin. It must rise at the start of each PTP second (or at a fixed, known time past it; `--pulse-phase-ms`).
2. Connect it to the FDT's SYNC IN (3.5 mm mono jack, TTL logic, 3.3 V high; check the pulse level against the FDT's documentation first) with a shielded cable and a common ground.
3. Record:

```sh
pip install "movetrics-fdt[serial] @ git+https://github.com/movetrics/sdk#subdirectory=python"
movetrics-fdt ptp-record --serial COM3 --pps --rate 2000 --out trial.csv     # Ctrl-C stops; --seconds 60 stops by itself
```

`ptp-record` probes the sync modes with GET_SYNC_MODE and refuses `--pps` on firmware without them. It sets EVENT_FRAMES (0x08) with a 0.1 ms debounce, so pulses of 0.2 ms and longer count, records, and sets the sync mode back to 0 at the end. It turns the FDT's own low-pass off unless `--cutoff` says otherwise (section 4).

After the recording it prints the pulses used, the pulses missing, the edges rejected, the FDT's drift against PTP in ppm and the edge jitter, and writes two files:

- `trial.csv`: one row per plate sample: `t_ptp_ns, t, plate, fx, fy, fz, mx, my, mz, cop_x, cop_y`. `t_ptp_ns` is PTP time: whole nanoseconds since 1970-01-01 00:00:00 TAI, the count PTP and GigE Vision cameras use. `t` is FDT time in seconds. Units and signs as chapter 19; an empty `cop` cell where the centre of pressure is undefined.
- `trial.csv.json`: the time base (`method`: `pulse` or `host`), its numbers and warnings, every event and gap with its PTP time, the firmware, the rate and, on Linux with linuxptp, what `ptp4l` said at the start (grandmaster identity and offset).

The samples before the first pulse and after the last are placed by the line through the nearest pulses; `first_fdt_s` and `last_fdt_s` in the JSON say where the pulses begin and end. Start the recording a second or two before the movement and stop it a second or two after.

### How the pulse map works

Each accepted rising edge is a pair (FDT time, PTP time). The host clock chooses which PTP second a pulse marks: an edge belongs to the whole second nearest the host's estimate, so the host must be within a quarter of the period; the JSON reports how far it was (`host_offset_ms`) and warns above that. Edges that lie at no whole second (static on the jack, a bounce) and edges farther than 0.5 ms from the line through their neighbours are rejected and counted. Each pulse's PTP time is then smoothed with a line through it and up to five pulses on each side, which averages the edge jitter down; a sample's PTP time is the straight line between the two smoothed pulses around it. Over eleven seconds the FDT's crystal does not bend measurably; over minutes it can, by temperature, and the pulse-by-pulse map follows that.

In Python:

```python
from movetrics_fdt.ptp import PtpRecorder, make_host_clock, record_ptp

recorder = PtpRecorder(clock=make_host_clock("utc"))           # TAI = UTC + 37 s
await fdt.set_sync_mode(SyncMode.EVENT_FRAMES, debounce_ticks=1)
await fdt.set_rate(2000, 0)                                     # 0: the FDT's low-pass off
await fdt.start_stream()
path, ptp_map = await record_ptp(fdt.samples(), recorder, "trial.csv", seconds=60)
print(ptp_map.quality())
```

`pulse_map(edges, coarse)` is usable on its own for edge times from any source, and `PtpRecorder.push(item)` with `finish()` for a program that writes its own files.

## 3. Host route

Without a cable, `ptp-record` without `--pps` maps the FDT's stamps onto the computer's clock with the clock map of chapter 22 (the least-delayed sample of each second, a line through the whole recording) and reads that clock as PTP time. That is right only as far as the computer follows PTP:

- **Linux**: `ptp4l` keeps the network card's clock on the grandmaster and `phc2sys` steers the system clock from it. `movetrics-fdt ptp-status` prints what `ptp4l` reports through `pmc` (grandmaster, offset of the card's clock); the offset of the system clock is `phc2sys`'s to report. `--host-clock tai` reads `CLOCK_TAI`, refused when the kernel's TAI offset was never set; the default reads the wall clock (UTC) and adds `--utc-offset` (37 s).
- **Windows**: the Windows Time service has a PTP client. Its accuracy depends on the network card and switch; the SDK does not read its state.
- **macOS**: no PTP client is built in. Use the pulse route.

## 4. Constants the time base does not contain

A time base tells when the FDT's clock read a value, not when the force happened. Two delays lie between them, and both matter at the precision PTP offers.

1. **The FDT's low-pass filter.** The FDT filters each channel with a second-order Butterworth low-pass, 50 Hz by default (chapter 04, SET_FILTER). Such a filter delays slow signals by √2 / (2π × 50 Hz), about 4.5 ms (computed for the filter design, not measured), and fast ones by a different amount. `ptp-record` therefore records with the filter off (`set_rate(rate, 0)`): filter afterwards with a zero-lag (forward and backward) filter, as gait labs do with camera data too.
2. **The plate itself**: the sensors, the pad electronics and their analog filters. The resampler that places each pad's conversions on the frame's time is symmetric (chapter 05, section 4.8), so it adds no delay by design. The rest is unknown until measured: tap the plate with a conductive rod wired to SYNC IN, so the edge marks the moment of contact, and compare it with the force onset in the same recording.

The host route has a third: plate frames leave the FDT about 10 to 15 ms after their stamp, for the resampler (chapter 05, section 4.8, from code), and USB adds its shortest delay. The clock map cannot see a constant, so it ends up in every time. A recording with `--pps` measures it: the JSON's `host_minus_pulse_ms` is the error the host route would have had, and its mean is the `--latency-ms` to give recordings without the pulse on the same FDT, firmware, rate and computer.

## 5. What accuracy a lab needs

Cameras at 100 to 200 frames per second take a frame every 5 to 10 ms; plates at 1,000 to 2,000 samples per second take one every 0.5 to 1 ms. For forces and movement analysed together (inverse dynamics, the moment of foot contact), labs commonly aim for alignment within about 1 ms. The pulse route's time base is two orders of magnitude inside that (inferred); the filter of section 4 is not, which is why it is off. The host route reaches about 1 ms only after its constant is measured.

## 6. Not yet done

- No recording with a real FDT, pulse source or PTP network; every number above is simulated or inferred. Before a figure goes into a data sheet: the edge jitter with a pulse per second on a real FDT (`edge_jitter_rms_us`), the drift of a real FDT against PTP, the host route's constant on USB and on Bluetooth, and the plate's delay with the tap test of section 4.
- The simulator's `--pps` option (`movetrics-fdt simulate --profile sync --pps`) drives SYNC IN from the computer's clock in steps of its 1 ms loop, so its edges are up to a millisecond late and some are rejected: it shows the workflow, not the accuracy.
- Python only. TypeScript and MATLAB have the sync commands and `align()` (chapter 22), not this time base.
- LSL keeps its own clock (chapter 22); this chapter's time base is for files.
