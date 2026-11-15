# 23. Analog outputs

FDTs with the analog interface board put each plate's forces, moments and centre of pressure on sixteen ±10 V outputs, A1 to A16, for systems that record voltages: an EMG amplifier's auxiliary inputs, a DAQ card, a motion capture system's analog board. This chapter gives the scale and what the voltages mean. Source: Nur Engineering, *Movetrics FDT analog outputs: scale per channel*, 27 October 2026, for FDT firmware 1.2.8.22, checked against the firmware source. Machine-readable: `contracts/analog-outputs.v1.json`; in Python, `movetrics_fdt.analog`.

## 23.1 Scale

0 V is zero load. Value = volts × units per V.

| Plate 1 | Plate 2 | Signal | Full scale at ±10 V | mV per unit | Units per V |
|---|---|---|---:|---:|---:|
| A1 | A9 | Fz | ±8,000 N | 1.25 | 800 |
| A2 | A10 | Fx | ±2,000 N | 5.00 | 200 |
| A3 | A11 | Fy | ±2,000 N | 5.00 | 200 |
| A4 | A12 | Mz | ±720 N·m | 13.89 | 72 |
| A5 | A13 | Mx | ±720 N·m | 13.89 | 72 |
| A6 | A14 | My | ±720 N·m | 13.89 | 72 |
| A7 | A15 | CoP x | ±15 cm | 666.7 | 1.5 |
| A8 | A16 | CoP y | ±30 cm | 333.3 | 3 |

On an F1-3D S plate, which has one Fx and one Fy load cell, Mz (A4, A12) is not measured: the FDT derives it as 0.02 m × Fx, as it does for the digital `mz`. A twin-pad F1-3D measures Mz.

## 23.2 Signs

Fz is positive for a load pressing on the plate. The other channels carry the sign of the same value in the FDT's digital frame (the wire signs of chapter 05). Studio, and therefore the shared vocabulary (chapter 19), shows Fy and Mx with the opposite sign, so **A3, A5, A11 and A13 are the reverse of `fy` and `mx`**. `movetrics_fdt.analog.to_vocabulary()` flips them. The maker's sheet does not state the sign or origin of the CoP outputs; check them with a known off-centre load before relying on them.

## 23.3 What the voltages can and cannot give you

- **Resolution.** The outputs are made from the stream's whole numbers (N, N·m, cm), so they move in steps of one unit: 1.25 mV for Fz, 5 mV for Fx and Fy, 13.9 mV for a moment, and **1 cm for the centre of pressure**. For CoP at millimetre level, compute it from the forces and moments (`plate_cop`, chapter 19) or use the digital stream.
- **CoP threshold.** The CoP outputs read 0 V while Fz is below 30 N. The digital vocabulary uses 50 N.
- **Clipping.** A value past full scale stays at the end of the range; it does not wrap. On the measured unit +10 V was reached at 99.4 % of full scale (about 7,950 N Fz) because of its zero offset. Treat anything within 1 % of ±10 V as clipped (`analog.clipped()`).
- **Update rate.** The outputs change only while the FDT streams (after START from Studio, the app or any host); they sit at 0 V after power-up and hold the last value after STOP. Start your recorder after the stream runs, not before. Each plate is updated at most 500 times per second: every frame at 500 frames/s, every second frame at 1,000 frames/s (chapter 05 section 4.10). Sampling them faster does not add information.
- **Filtering and delay.** The values are the FDT's filtered values (50 Hz low-pass by default, set by the host), followed by a first-order low-pass at about 220 Hz in the output stage (33 kΩ, 22 nF, from the schematic, not measured). They lag the force by the frame latency of chapter 13 (about 12 ms at 500 frames/s), so an analog channel recorded next to EMG is **not** a time reference. For alignment use the sync jack or LSL (chapter 22).
- **Zero.** 0 V means the plate was zeroed: at power-up, at reset and on the Zero command. There is no separate analog zero. Movetrics Studio restarts the FDT when a test starts and waits about 3 s before it streams (measured, October 2026); during that time the outputs read 0 V and the FDT takes its zero, so **keep the plates empty while Studio starts a test**. Analog data are only comparable between sessions that used the same stream rate and filter, because both set how often and how smoothly the outputs move; Studio uses the FDT's defaults (1,000 frames/s and 50 Hz on firmware 1.2.8.5 and later).
- **Sleep.** After the last host command the FDT switches the pads off and sleeps: 5 minutes on firmware 1.2.8.9 and later, 10 minutes before (chapter 03, section 3.9). A host's KEEP_ALIVE sets another time. A running stream never sleeps.

## 23.4 Electrical

16-bit DAC, 0.305 mV per code. 50 Ω series resistor per output: a load of 10 kΩ or more keeps the divider error under 0.5 %. Gain set by 4.7 kΩ and 33 kΩ resistors of 1 %, so up to ±1.8 % worst case. On the measured unit a meter agreed with the digital values within 1 % at 164 N Fz and 24.6 N·m Mx, and zero read close to 0 mV on all outputs (27 October 2026, plates empty).

**Zero offset is per unit.** That unit's outputs read about 58 mV low at rest; firmware 1.2.8.22 adds +190 codes (+58 mV) to every output to cancel it. The value was measured on that one board and is compiled into the firmware, so another FDT can read tens of mV off zero at rest, up or down. Each output stage can also add an offset of its own of up to about 24 mV (inferred from the parts, not measured). Record a few seconds with the plates empty and the stream running, and subtract each channel's mean; at 1.25 mV per N, 58 mV is 46 N of Fz.

## 23.5 Firmware

The scale, channel order and clipping hold for firmware 1.2.8.21 and later with analog outputs (code, read in the 1.2.8.22 source on 28 Oct 2026; the maker's sheet names 1.2.8.22, the firmware it was measured on). 1.2.8.22 adds the zero trim of section 23.4, which fits one unit only. **Before 1.2.8.21**, which includes the released 1.2.8.2, the moment outputs of a double plate were 100 times too large (full scale 7.2 N·m) and values past full scale wrapped around to the other sign; ask the FDT for its version (GET_FW_VERSION) before you rely on the moment channels. ANALOG_ENABLE (0x34) switches the outputs on or off (chapter 04); they are on by default. The digital-only FDT variant has no analog board.

Status: maker's document plus one metered unit (measured, 27 October 2026). Not checked by this SDK on hardware.
