# 15. Conformance and testing

Public edition of the SDK specification. Statements are marked code (read in the firmware), measured (seen on a device) or vector (covered by the test vectors).

This chapter says how to decide whether an implementation of the host link conforms to the controller and to the SDK. The SDK clients are the Python package in [python/](../python/), the TypeScript client in [ts/](../ts/) and the MATLAB client in [matlab/](../matlab/), version 0.3.0.

The protocol chapters describe firmware 1.2.8.0. Later firmware keeps the same frames and adds the capabilities listed in [COMPATIBILITY.md](../COMPATIBILITY.md) (the stream rate, sleep, the sync modes). Conformance has four levels.

- L0 covers framing and CRC. L1 covers decoding of stream, status and version replies. Both run offline against the byte vectors in [vectors/](../vectors/).
- L2 covers the read-only commands and L3 the configuration commands. Both need a controller and the approval of whoever is responsible for it.

Firmware update is out of scope for conformance. Section 6 lists the commands to run, and Section 7 says what was checked and what was not.

## 1. Reading rules

A result is given only for a check named in Section 7. Commands in Section 6 are what to run. Pass and fail are used only for runs recorded in [CONFORMANCE.md](../CONFORMANCE.md). Every row there was run on simulated and recorded bytes. No row was run against a real controller.

## 2. Conformance levels

**Table 2.1 Conformance levels**

| Level | What it checks | Inputs | Needs a controller | Commands sent |
|---|---|---|---|---|
| L0 Framing and CRC | Request layout (`FE ED`, `pa`, `da`, command, payload, CRC, `04 04`), reply header and end marker, CRC-16/CCITT-FALSE, and the silent-drop and resync rules of [04-host-commands.md](04-host-commands.md) Section 2 | `crc16.json`, and the framing cases of `host_frames.json` | No | None |
| L1 Decoding | The 24-byte stream frame; GET_STATUS replies in the forms of [06-status-health-versions.md](06-status-health-versions.md) Section 6.5; the GET_FW_VERSION reply | `stream_frames.json`, `status.json`, and the version cases of `ota_frames.json` | No | None |
| L2 Read-only commands | GET_STATUS (0x22) and GET_FW_VERSION (0x23) sent to a controller, with each reply decoded by the L1 decoders | No vector file; the reply bytes are kept for comparison with L1 | Yes, with approval | 0x22 and 0x23 |
| L3 Configuration commands | START_STREAM (0x01), STOP_STREAM (0x05), KEEP_ALIVE (0x26), SET_FILTER (0x1C, the stream rate) and, on firmware that has them, SET_SYNC_MODE and GET_SYNC_MODE (0x28, 0x29) sent to a controller, with the conditions of Section 5 | No vector file for the commands; `sync_events.json` for the sync replies | Yes, with approval and the conditions of Section 5 | 0x01, 0x05, 0x1C, 0x26, 0x28 and 0x29 |

Out of scope: firmware update (0x40 and its sub-commands), the controller's internal pad bus and the pad bootloader (not part of the host protocol), and the BLE bridge firmware. [02-transports.md](02-transports.md) describes the bridge only as far as a host sees it.

The status and version decoders are at L1 because they decode bytes and send nothing. That placement is a choice of this chapter. The GET_STATUS length rule that L1 applies is in [06-status-health-versions.md](06-status-health-versions.md) Section 6.5.

## 3. Vector files

Table 3.1 gives the byte-level vector files in [vectors/](../vectors/) (schema `movetrics-fdt-vectors/1`), with their case counts. Each suite runs every case of every file. The client, status, stream and frame tests also select named cases from the same files.

A case is an anchor or derived. An anchor is external truth: a real capture or a published check value. A derived case is computed from layout constants in the firmware, or from a port of a firmware routine.

**Table 3.1 Vector files**

| File | Cases | Anchors | Derived | Level | Content |
|---|---|---|---|---|---|
| `crc16.json` | 6 | 2 | 4 | L0 | CRC-16/CCITT-FALSE values, including the check value of `123456789` |
| `host_frames.json` | 24 | 9 | 15 | L0 | Encodes of START, STOP, KEEP_ALIVE, GET_STATUS and GET_FW_VERSION; an encode of GET_CURRENT_CONFIG that the Python suite skips, and the refusal of GET_STATUS to FF/FF; decodes of replies and of bad CRC, truncated, bad header and split end-marker input |
| `stream_frames.json` | 13 | 6 | 7 | L1 | 24-byte stream frames, encode and decode |
| `status.json` | 6 | 1 | 5 | L1 | GET_STATUS: the 85-byte anchor, the 85-byte derived record, three 86-byte derived records, and the three-record reply of 258 bytes |
| `ota_frames.json` | 4 | 2 | 2 | L1 | The version probe and the 38-byte version reply (anchors), the bootloader version reply, which carries `BOOT-1.0.0.3` as the bootloader sends it, and the bridge STOP frame |
| Total | 53 | 20 | 33 | | |

A second kind of file, `vocabulary.json` (schema `movetrics-fdt-vocabulary-vectors/1`), maps frames to the samples, gaps and events a client must make of them. It is generated by [tools/gen_vocabulary_vectors.py](../tools/gen_vocabulary_vectors.py) from [contracts/](../contracts/). [19-vocabulary-and-units.md](19-vocabulary-and-units.md) describes the vocabulary.

**Captures.** Two recordings from earlier firmware are the sources of the anchors. One holds 19,057 stream frames in 457,368 bytes. The other is a 194-byte identification capture, and it is the source of the anchors in `status.json` and `ota_frames.json`. Neither is included in vectors/. No client test reads the stream capture (open point 3).

## 4. Codes outside L2 and L3

Table 4.1 lists the codes that neither level covers. The Python encoder encodes only 0x01, 0x05, 0x1C, 0x22, 0x23, 0x26, 0x28 and 0x29, and it refuses every code in Table 4.1 with `UnsupportedCommandError`. The TypeScript command table holds the same eight codes; the MATLAB toolbox sends a subset of them.

A run that sends any code in Table 4.1 is not a conformance run. Code 0x63 entered the firmware after the encoder run of Section 7. Both command tables list it as refused, and that run did not include it (open point 11).

Rows marked **do not send** are dangerous or internal. A general host client must never send them.

**Table 4.1 Codes outside L2 and L3**

| Code | Name | Class in [04-host-commands.md](04-host-commands.md) | Reason it is excluded |
|---|---|---|---|
| 0x19 | SAVE_CALIBRATION | Persistent write | **Do not send:** writes flash, and is not refused while streaming (04 Section 6.4) |
| 0x1B | SET_TARE | Configuration | No vector. A tare re-zeroes the plates, so it needs the approval of whoever runs the plates |
| 0x25 | CONTROLLER_RESET | Destructive | **Do not send:** resets the controller and ends the stream (04 Section 6.4) |
| 0x27 | GET_PAD_HEALTH | Read-only | No vector for the 120-byte reply |
| 0x31 | SET_SERIAL_PARAM | Configuration; applied at a later boot, and only when stored | **Do not send with destination 0:** changes the link rate at a later boot |
| 0x39 | ANALOG_TEST | Destructive | **Do not send:** never returns (04 Section 6.1) |
| 0x40 | FIRMWARE_UPDATE | Firmware update | **Do not send:** out of scope (Section 2) |
| 0x53 | PADS_SAVE_FACTORY_GF | Persistent write on a pad | **Do not send:** pad flash write with no backup (04 Section 6.4) |
| 0x60 and 0x61 | DEBUG_ADC_CLOCK_DRIVE, DEBUG_POLL_TIMING | Configuration (RAM) | **Do not send:** bench experiments that change the pad clock or poll timing (04 Table 3.5) |
| 0x62 | DEBUG_PADS_RESTART | Destructive | **Do not send:** switches the pad power off or resets the pads (04 Table 3.5) |
| 0x63 | pad-sample mode switch (debug) | Configuration (RAM) | **Do not send:** bench experiment that switches the pad polling between GET_FRAME and queued samples, RAM only and with no guard (04 Table 3.5) |
| 0x08, 0x13, 0x1A, 0x21, 0x24 | GET_SAMPLING_RATE, GET_CHANNEL_MASK, GET_CURRENT_CONFIG, RUN_SELF_TEST, GET_SERIAL_NUMBER | Read-only | Outside the first SDK surface (04 Table 3.2) |
| 0x02, 0x03, 0x04 | START_ACQ, STOP_ACQ, CLEAR_CACHE | Not dispatched | The firmware has no case for it and answers NACK 7 (04 Section 3.7) |
| 0x06 | GET_FRAME | Read-only | No reply. It polls the pads, which the stream already does (04 Table 3.1) |
| 0x07 | SET_SAMPLING_RATE | Configuration | Stores a value with no effect on the stream. No vector |
| 0x11 | SET_CALIBRATION | Configuration | Alias of START_STREAM in the firmware (04 Table 3.1, F2) |
| 0x12 | SET_CHANNEL_MASK | Configuration | Stores a mask with no effect on acquisition. No vector |
| 0x14, 0x15 | INCREASE_VALUE, DECREASE_VALUE | Configuration | Silent RAM step with no reply. No vector |
| 0x16 | END_CALIBRATION | Configuration | Alias of STOP_STREAM in the firmware (04 Table 3.1) |
| 0x17, 0x32, 0x50, 0x51 | GET_CALIBRATION, SET_WIFI_SSID, PADS_CALIBRATION_START, PADS_CALIBRATION_STOP | Not dispatched | The firmware has no case for it and answers NACK 7 (04 Section 3.7) |
| 0x18 | SET_LAYOUT | Read-only | Outside the first SDK surface (04 Table 3.2). No reply vector |
| 0x33, 0x35, 0x36 | SERVER_AP_ENABLE, SERVER_BT_ENABLE, SERVER_USB_ENABLE | Configuration | ACK only, no effect (04 Table 3.3) |
| 0x34 | ANALOG_ENABLE | Configuration | Analogue output switch. No vector ([23-analog-outputs.md](23-analog-outputs.md)) |
| 0x37, 0x38 | PRINTOUT_ENABLE, PRINTOUT_DISABLE | Configuration | Debug output on USART2, no host reply (04 Table 3.3) |
| 0x52 | PADS_GET_FACTORY_GF | Read-only | Calibration data. No vector (04 Table 3.4) |
| 0x54 | PADS_GET_CF | Not dispatched | Not dispatched on the host side (04 Section 3.7) |
| 0x55 | PADS_SAVE_CF | Not dispatched | Not dispatched on the host side. It is a pad flash save |

## 5. Conditions for L2 and L3 runs

A hardware run needs all of the following conditions.

1. Whoever is responsible for the controller approves each run in advance. The approval names the controller, the port or bridge, and the commands the run will send.
2. A run sends only the commands listed for its level in Table 2.1, and no code in Table 4.1.
3. L2 sends only read-only codes. L3 ends with STOP_STREAM after its START_STREAM.
4. KEEP_ALIVE is sent only with a non-zero interval. A new driver must not send 0x26 with an interval of 0, because that turns the sleep off ([03-host-link-framing.md](03-host-link-framing.md), section 3.9).
5. The run keeps the request and reply bytes of every exchange, so that the L1 decoders can check them later.
6. Only one host commands the controller at a time ([02-transports.md](02-transports.md), section 2.3).

## 6. Commands to run

The offline commands need no hardware. The Python transport tests replace pyserial and bleak with fakes, and the TypeScript transport tests use a fake serial port.

- Offline, Python (L0 and L1): `cd python && python3 -m unittest discover -s tests -t .`. The `-t .` is required: without it, three discovery imports fail. The form `python3 -m unittest discover -s python/tests -v`, run from the repository root, fails with `ModuleNotFoundError: No module named 'movetrics_fdt'`.
- Offline, TypeScript (L0 and L1): `cd ts && npm test`, which runs `node --test "test/**/*.test.ts"`. The package needs Node 22.18 or later. The form `node --test ts/test/`, run from the root, fails with `Cannot find module`.
- The whole matrix: `python3 tools/conformance.py` runs every client's suite and writes [CONFORMANCE.md](../CONFORMANCE.md) with `--write`. A client conforms to a file only when its tests read that file and pass.
- L2 and L3: no command is defined. A run needs the approval in Section 5, with the port or bridge named in that approval (open point 1).

The Python README numbers its levels 1 to 3 as byte, behaviour and hardware. This chapter uses L0 to L3, with the status and version decoders at L1.

The Python status parser accepts 85 x k and 86 x k bytes for k = 1 to 3, checks the record order, refuses a reply that mixes the two lengths, and refuses any other length. The TypeScript status parser meets the same length rule ([06-status-health-versions.md](06-status-health-versions.md), section 6.5).

## 7. Checks made

Evidence: simulated and recorded bytes only.

The latest results of the offline suites are in [CONFORMANCE.md](../CONFORMANCE.md). The checks made for this chapter were:

- The Python suite, in the form of Section 6, passed. Its skips are all vector cases.
- The Python encoder encodes 0x01, 0x05, 0x1C, 0x22, 0x23, 0x26, 0x28 and 0x29. It refuses each of the other 41 codes it knows with `UnsupportedCommandError`.
- The TypeScript suite, in the form of Section 6, passed.
- The vector totals of Table 3.1 (53 cases, 20 anchors, 33 derived) are checked by the Python vector test against the files, and passed.
- The stream capture of Section 3 was decoded by the earlier Python reference parser: 19,057 sample messages, 0 invalid candidates, 0 discarded bytes, 0 bytes left over.
- The identification capture was decoded with the reference frame check: six replies of 10, 9, 24, 85, 38 and 28 bytes, 194 bytes in all, each with a valid CRC and end marker.

Not checked with this SDK version: L2 and L3 on a controller, the BLE bridge, and browser runs of Web Serial and Web Bluetooth. The stream rate of 2,000 frames per second per plate was measured on a controller with the firmware team's own tool, not with these clients.

## 8. Open points

All of these are unverified.

1. No L2 or L3 run has been made. The port or bridge, the approval and the command list for a run are not set.
2. The safety rules for hardware runs are not repeated here. Section 5 lists only the conditions this chapter can state.
3. No client test reads the stream capture. The earlier reference parser decodes all of it.
4. No vector file covers the GET_PAD_HEALTH reply, SET_FILTER (the clients' own tests check its bytes against the frame the firmware team's tool sends), SET_TARE (no case with 0x1B in any vector file), or the 85 x 2 and 85 x 3 status forms ([06-status-health-versions.md](06-status-health-versions.md), open point 15).
5. The generator that rebuilds the byte-level vector files from the firmware sources is not part of this repository, so they cannot be compared with their sources from here.
6. The tests use fakes. No serial port, BLE adapter or browser was used.
7. Only Python 3.13 and Node 22 were used, here and in the repository's CI. The other versions in the stated ranges (Python 3.10 and later, Node 22.18 and later) were not run.
8. The stream timing is not checked by any vector or SDK test.
9. Frames on an exact grid. In 1.2.8.0, frame m of every platform is for TIM2 tick m x 10,000 / rate, rounded, and becomes due the frame latency after that tick, with no burst after a stall. A frame carries its grid tick once any pad of its plate has used queued samples in the stream. No vector or SDK test checks the spacing or the order of stream timestamps. The firmware host tests do not compile the pacing code and model the grid in a bus simulation. The grid has not run on hardware.
10. The late-plate wait after a controller restart. Within 8 s of uptime, START and GET_CURRENT_CONFIG wait for a plate that does not answer yet, and START tares each plate that has had no tare attempt since boot before it sends its reply. No vector or SDK test covers a START reply that comes seconds late. The Python `start_stream` returns once it has watched its check period for a NACK. On hardware, 1.2.6.6 ran on a bench, and in its recorded runs the wait did not have to act (measured).
11. Command 0x63, the pad-sample debug command, is new in 1.2.7.0. It sets a RAM flag and answers NACK 3 when the parameter is missing or above 1. Both clients refuse it, no vector covers it, the encoder run of Section 7 predates it, and it has not run on hardware. It is limited to bench experiments.

## 9. Known pitfalls

- The command `python3 -m unittest discover -s python/tests -v` from the repository root fails (Section 6).
- The command `node --test ts/test/` fails (Section 6).
- Node 22 alone is not enough for the TypeScript tests. The package needs 22.18 or later.
- SET_FILTER (0x1C) lives in RAM: a controller reset restores the default rate, so a client sends it after every connect and leaves 100 ms before START ([04-host-commands.md](04-host-commands.md) Table 3.3).
