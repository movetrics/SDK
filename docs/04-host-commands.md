# 04. Host commands

Public edition of the SDK specification. Statements are marked code (read in the firmware), measured (seen on a device) or vector (covered by the test vectors).

This chapter specifies the host command set of the controller at firmware 1.2.8.0, from the parser to the reply encoders. Firmware 1.2.8.0 has not been run on hardware, so everything here is code unless a row says measured or vector.

For each of the 47 command codes in the firmware's command list, it gives the request payload, the reply, the effect on state, whether that effect survives a reset, the safety class, and whether the SDK clients implement it. It also gives the rules that decide whether a request reaches the command switch at all. It then sets out four findings where the firmware differs from what a host would assume: F1, F2, F4 and F5. The fifth finding, F3 (the stream rate), is in [05-measurement-stream.md](05-measurement-stream.md).

It does not define the request and reply envelope, the CRC or the end marker. They are in [03-host-link-framing.md](03-host-link-framing.md). The 24-byte stream frame is in [05-measurement-stream.md](05-measurement-stream.md), and the status and health records are in [06-status-health-versions.md](06-status-health-versions.md). The firmware-update state machine is not part of this edition.

## 1. Scope and reading rules

Frame bytes are numbered from zero as they arrive. Bytes 0 and 1 are the header `FE ED`. Byte 2 is the platform address `pa`. Byte 3 is the destination or subop `da`. Byte 4 is the command code. The payload starts at byte 5. The payload byte `pN` is frame byte `5+N`. A request of total length `n` has a payload of `n-9` bytes. Replies use the header `BE EF`.

Safety classes are used in the tables with these meanings.

- **Read-only**: the reply is the only effect from the host's point of view.
- **Configuration**: RAM state changes and is lost at reset.
- **Persistent write**: flash is written on the controller or on a pad.
- **Destructive**: the controller resets, the main loop stops, the pads lose power, or a flash sector is erased without a backup.
- **Firmware update**: firmware slots are erased or written.

The bench commands 0x60, 0x61 and 0x63 change RAM state only, so they are in the Configuration class (Table 3.5).

The column "SDK" says either **implemented**, meaning the SDK clients send and parse this command, or **documented only** followed by the reason the SDK does not expose it. The implemented set is exactly 0x01, 0x05, 0x22, 0x23 and 0x26.

Rows marked **do not send** are dangerous or internal. A general host client must never send them. This edition gives no operating detail for them.

## 2. Dispatch and parse rules

Steps 1 to 10 of Table 2.1 run before the command switch, in this order. Step 11 runs inside the case labels, so it comes after step 12 selects the case.

**Table 2.1 Checks applied to every request, in order**

| Step | Check | Result on failure | Evidence |
|---|---|---|---|
| 1 | Resync: when bytes 0 and 1 are not `FE ED` and at least nine bytes are present, the parser searches from byte 1 for `FE ED`, which must have nine bytes from its position onward | Parsing continues from the first match | code |
| 2 | At least nine bytes after resync | Silent drop | code |
| 3 | Header is `FE ED` | Silent drop | code |
| 4 | CRC-16/CCITT-FALSE over bytes 2 to n-5 equals the little-endian CRC at n-4 | NACK 9 (CRC), on the source port | vector |
| 5 | Bytes n-2 and n-1 are `04 04` | NACK 7 (unknown command), on the source port | code |
| 6 | Payload length: at least 3 bytes for 0x1C; at least 2 for 0x07, 0x26 and 0x53; at least 1 for 0x12, 0x14, 0x15, 0x31 and 0x34 | NACK 3 (invalid parameter) | code |
| 7 | Platform address below 3 for 0x14, 0x15, 0x52 and 0x53; destination below 3 for 0x52 and 0x53 | NACK 3 | code |
| 8 | Accepted: command, `pa`, `da` and payload length are latched | For command byte 0x00 the platform, destination and length fields are still stored and the stored command becomes 0; no command case matches 0x00 | code |
| 9 | A latched command zeroes the keep-alive counter, before the next guard | Not applicable | code |
| 10 | Pad firmware job running and the command is in the pad-disturbing list | NACK 8 (ineffective command) | code |
| 11 | Firmware update running: 0x01 and 0x11 NACK 8; 0x1B NACK 8; 0x62 NACK 3 while streaming or updating | As stated | code |
| 12 | Switch on the command code | No case: NACK 7 | code |

The pad-disturbing list is 0x06, 0x1A, 0x31, 0x25, 0x19, 0x52, 0x53, 0x1B and 0x62. Its guard applies only while a pad firmware job owns the pad bus. It does not apply while streaming (finding F5).

Replies are written to the port that carried the request. The controller sets the active port to the source port before parsing, so a NACK for a malformed request goes back to the port it came from. A request that latches nothing restores the previously active port, so a bad frame on one port does not take over the stream from the other.

Requests from both ports are queued in a 16-slot ring that is full at 15 commands. A request that finds the queue full is counted and dropped with no reply. The receive splitter ends a message at the first two consecutive `04` bytes. [03-host-link-framing.md](03-host-link-framing.md) describes the hazard that this creates for CRC bytes.

Reply encoders use the request's `pa` for most replies, with these exceptions.

- GET_CURRENT_CONFIG and the firmware update reply always carry `pa` 0.
- GET_STATUS ignores the request's `pa` and sends one record per address.
- SET_TARE replies carry the target, which is 0xFF for a broadcast.
- SET_SERIAL_PARAM with `da` 0 sends its ACK with `pa` 0, not the request's `pa`, because the ACK encoder receives `da`.

A reply that finds the TX ring full waits up to 50 ms for it to drain, then is dropped and counted. The ring is 4096 bytes per host port. Stream frames are not retried: a frame that finds the ring full is dropped at once.

Commands that send no reply on success are 0x01 and 0x11, 0x06, 0x14, 0x15, 0x26, 0x37 and 0x38, and command 0x00 (Section 3.7). A host must not wait for an ACK from these.

## 3. Command table

The 38 dispatched case labels are grouped below by function. Each row gives the request payload as payload offsets, the reply, the effect, the safety class and the SDK value. Replies are listed with their total byte count. Their layouts are in [03-host-link-framing.md](03-host-link-framing.md) and [06-status-health-versions.md](06-status-health-versions.md).

### 3.1 Stream and session

**Table 3.1 Stream and session commands**

| Code and name | Class | Request payload | Reply | Effect | SDK | Evidence |
|---|---|---|---|---|---|---|
| 0x01 START_STREAM | Configuration | None. `pa` and `da` are not checked, so a START frame with `pa` 0xFF is accepted | None. No ACK (F2) | Refused with NACK 8 while a firmware update is running. Runs a platform redetection on every START: when fewer than two plates are known it sweeps again and, within the first 8 s of uptime, waits for the missing plate. It tares every detected plate that has had no tare attempt since boot (Section 3.8). Sends two placeholder frames with stamp 0, one for each plate address 1 and 2, whether or not the plate exists. Clears the means and the queued pad samples and sets the stream flag. | implemented | vector |
| 0x11 SET_CALIBRATION | Configuration | As 0x01 | As 0x01 | Same case label as 0x01, so it starts the stream as well (F2). | documented only: alias of 0x01 | code |
| 0x05 STOP_STREAM | Configuration | None | ACK | Clears the stream flag. The timestamp returns to zero on the next TIM2 tick. | implemented | vector |
| 0x16 END_CALIBRATION | Configuration | None | ACK | Same case label as 0x05. | documented only: alias of 0x05 | code |
| 0x06 GET_FRAME | Read-only (pad link counters change) | None | None | Polls each pad of plates 1 and 2 once with a blocking transaction of up to 600 us. The readings update, which the stream reads later. Refused with NACK 8 during a pad firmware job. A code comment records that extra polls add repeats and raise pad noise. | documented only: no reply, and the stream already polls the pads | code |
| 0x26 KEEP_ALIVE | Configuration | p0 and p1: interval in seconds, u16 little-endian. NACK 3 when the payload is shorter than two bytes | None | Sets the keep-alive interval and zeroes the counter. Interval 0 turns the sleep off in 1.2.8.0. The default is 600 s. The value is RAM only: the saved configuration holds baud rates and factors only. Section 6.3 gives the rule. | implemented | vector |

### 3.2 Identification, status and queries

**Table 3.2 Identification, status and query commands**

| Code and name | Class | Request payload | Reply | Effect | SDK | Evidence |
|---|---|---|---|---|---|---|
| 0x08 GET_SAMPLING_RATE | Read-only | None | 10 bytes; `sampleRate` u16 little-endian at bytes 4 and 5. The value at boot is 2048 | Reports the stored `sample_rate` only. The stream rate is the filter SPS (Section 8). | documented only: query that does not describe the stream rate | code |
| 0x13 GET_CHANNEL_MASK | Read-only | None | 9 bytes; `channelMask` at byte 4. The value at boot is 0xFF | Reports the stored mask. | documented only: query outside the first SDK surface | code |
| 0x18 SET_LAYOUT | Read-only (the name does not match the behaviour) | None | 32 bytes: twelve int16 limits at bytes 4 to 27: forceX +/-2000, forceY +/-2000, forceZ 0 to 8000, moments +/-720. Units are not named in the code. | Sends the limits and changes nothing. | documented only: layout query outside the first SDK surface | code |
| 0x1A GET_CURRENT_CONFIG | Read-only (detected plate types can update) | None | 24 bytes, `pa` 0: `platform_type` of plate 1 at byte 4 and of plate 2 at byte 5 | Runs a blocking transaction to each pad first. Then, within the first 8 s of uptime, it waits for a plate that has not answered before it replies (Section 3.8). A pad answer updates the plate type. Refused with NACK 8 during a pad firmware job. | documented only: identification query outside the first SDK surface | code |
| 0x21 RUN_SELF_TEST | Read-only | None | ACK | Sends the ACK and runs no test. The self-test error code 4 is defined and never sent by this code. | documented only: the command runs no test | code |
| 0x22 GET_STATUS | Read-only | None. The request `pa` is ignored | One 86-byte record for address 0, then one for each plate whose type is not PLATFORM_NONE | Layout and error bits are in [06-status-health-versions.md](06-status-health-versions.md). | implemented | vector |
| 0x23 GET_FW_VERSION | Read-only | None | 38 bytes: `stm32FW` text "1.2.8.0" at byte 4 (15 bytes), `esp32FW` text "000.000.000" at byte 19 (15 bytes). The synthetic transport-test build reports "1.2.8.0-SYN" | In the bootloader the same request gets `BOOT-1.0.0.3`. Other non-0x40 requests are ignored there. | implemented | vector |
| 0x24 GET_SERIAL_NUMBER | Read-only | None | 28 bytes: a 19-character ID at bytes 4 to 22, then NUL. The ID is the base64 of the 12-byte unique ID of the microcontroller (read from address 0x1FFF7A10), 16 characters, followed by three `0` characters | Read-only. | documented only: identification query outside the first SDK surface | code |
| 0x27 GET_PAD_HEALTH | Read-only | None | 120 bytes: link and tare health per pad, and filter fields. Layout is in [06-status-health-versions.md](06-status-health-versions.md). | Read-only. | documented only: no vector for the 120-byte reply | code |

### 3.3 Configuration in RAM

**Table 3.3 Configuration commands (RAM state)**

| Code and name | Class | Request payload | Reply | Effect | SDK | Evidence |
|---|---|---|---|---|---|---|
| 0x07 SET_SAMPLING_RATE | Configuration (stored only) | p0 and p1: u16 little-endian. NACK 3 when shorter than two bytes | ACK | Stores `sample_rate`. Only the GET_SAMPLING_RATE reply reads it. The stream rate does not change. | documented only: the stored value has no effect on the stream | code |
| 0x12 SET_CHANNEL_MASK | Configuration (stored only) | p0: mask byte. NACK 3 when there is no payload | ACK | Stores the mask. No other code reads it: the only uses are the store and the GET_CHANNEL_MASK reply. | documented only: no effect on acquisition | code |
| 0x14 INCREASE_VALUE | Configuration | p0: axis, 1 X, 2 Y, 3 Z. NACK 3 when `pa` is 3 or above | None. No ACK | Adds one to the calibration factor of that axis, clamped to 200. Writes a line to USART2 at 115200 baud, which is the debug port and not a host port. Factors are saved only by 0x19 or by a reset with changes (Section 3.4). Any other axis byte changes nothing and still prints. | documented only: silent RAM step with no reply to confirm | code |
| 0x15 DECREASE_VALUE | Configuration | As 0x14 | None. No ACK | Subtracts one, clamped to a minimum of 1. | documented only: as 0x14 | code |
| 0x1B SET_TARE | Configuration | None. `pa` 0 or 0xFF selects all plates, and 1 or 2 selects one plate | ACK with the target as `pa`. NACK 1 when the addressed plate does not exist. NACK 2 when a pad gave fewer than 20 of its 40 samples, which fails the plate | Averages 40 samples per pad at 5 ms spacing, after a warm-up of up to 4 s. The warm-up starts again whenever a cold-booted pad gets its soft reset, so it can last longer than 4 s. Resets the filter state and clears the means and the queued pad samples. Allowed while streaming. A phone client sends it as a broadcast with `pa` 0xFF, only while live and not recording. Refused with NACK 8 during a firmware update or a pad firmware job. A tare re-zeroes the plates, so send it only when the plates are unloaded. | documented only: no vector | code |
| 0x1C SET_FILTER | Configuration | p0: cutoff in hertz, u8; 0 bypasses the filter. p1 and p2: sample rate (SPS), u16 little-endian. NACK 3 when shorter than three bytes | ACK, or NACK 3 when the cutoff is not below half the rate or the rate is not positive | Sets a second-order Butterworth low-pass for the cutoff and the rate. The rate also sets the stream rate per plate. A new rate restarts the frame grid and rebuilds the resampling kernel at the next pass ([05-measurement-stream.md](05-measurement-stream.md), section 7.5). The grid and the resampler came with 1.2.8.0, which has not been run on hardware. Bypass resets the filter state. Default 50 Hz at 500 sps. RAM only. | documented only: no vector, and what 0x1C does can depend on the firmware line | code |
| 0x31 SET_SERIAL_PARAM | Configuration; the new rate reaches the port only after a boot, and only if a flash write ran after the command | See below. | ACK | **Do not send with destination 0:** it changes the USB baud rate at a later boot, and a client that opens USB at 1,500,000 baud is then locked out (see [02-transports.md](02-transports.md), section 2.2). With any non-zero `da`: ACK with the request's `pa`, then the command is forwarded to that address. The pad has no 0x31 case, so nothing happens there. Refused with NACK 8 during a pad firmware job. | documented only: the link rate changes at a later boot, and only when stored | code |
| 0x33 SERVER_AP_ENABLE | Configuration (no effect) | None | ACK | Acknowledged and ignored. | documented only: no effect | code |
| 0x35 SERVER_BT_ENABLE | Configuration (no effect) | None | ACK | Acknowledged and ignored. | documented only: no effect | code |
| 0x36 SERVER_USB_ENABLE | Configuration (no effect) | None | ACK | Acknowledged and ignored. | documented only: no effect | code |
| 0x34 ANALOG_ENABLE | Configuration | p0: 0 disables and 1 enables the analogue outputs. Other values change nothing. NACK 3 when there is no payload | ACK | Sets the analogue-output enable flag, which defaults to true. While streaming, the outputs are updated at most about 500 times per second per plate ([05-measurement-stream.md](05-measurement-stream.md), section 4.10). This cap came with 1.2.7.0, which has not been run on hardware. | documented only: analogue output switch | code |
| 0x37 PRINTOUT_ENABLE | Configuration | None | None | Sets the printout flag. The periodic printout runs only while streaming, and writes to USART2. | documented only: debug output, not a host reply | code |
| 0x38 PRINTOUT_DISABLE | Configuration | None | None | Clears the printout flag. | documented only: debug output | code |

For 0x31, the payload is p0, a baud code. Codes outside the range the firmware accepts get NACK 3, as does a request with no payload. This edition does not list the codes, because the command must not be sent with destination 0.

### 3.4 Calibration, flash and reset

**Table 3.4 Calibration, flash and reset commands**

| Code and name | Class | Reply | Why it is dangerous | SDK | Evidence |
|---|---|---|---|---|---|
| 0x19 SAVE_CALIBRATION | Persistent write | ACK, sent before the write | **Do not send:** writes the controller's flash (baud rates and calibration factors) and is not refused while streaming (F5). A flash sector erase stalls interrupts. | documented only: the SDK does not write flash | code |
| 0x25 CONTROLLER_RESET | Destructive (reset). Persistent write when values changed | ACK, sent before the reset | **Do not send:** with `da` 0 it saves the configuration and resets the controller, which ends the stream. With any other `da` it forwards a reset to that address, and a `da` of 0xFF resets every pad on the platform the frame names. It is not refused while streaming (F5). | documented only: resets the controller and ends the stream | code |
| 0x52 PADS_GET_FACTORY_GF | Read-only on the host side (sends a pad command) | 16 bytes: plate, pad, then the 8 factory gain bytes held in RAM | The plate is the `pa` byte and the pad is the `da` byte. Both must be below 3. The controller sends 0x52 to the pad, waits 100 ms, then replies with whatever its RAM copy holds, so the reply can be older than the pad's answer (open point 4). Refused with NACK 8 during a pad firmware job. | documented only: calibration data | code |
| 0x53 PADS_SAVE_FACTORY_GF | Persistent write on the pad | ACK | **Do not send:** it can erase and rewrite a pad's factory-gain flash page with no backup and no read-back. The ACK does not show that the pad's write happened (F5). | documented only: pad flash write without backup | code |

### 3.5 Debug and bench

**Table 3.5 Debug and bench commands**

| Code and name | Class | Reply | Why it is dangerous | SDK | Evidence |
|---|---|---|---|---|---|
| 0x39 ANALOG_TEST | Destructive | ACK, then no reply ever (F1) | **Do not send:** never returns. The controller stops answering until it is reset. | documented only | code |
| 0x60 DEBUG_ADC_CLOCK_DRIVE | Configuration (RAM) | ACK | **Do not send:** a bench experiment that changes the pads' ADC clock output. In 1.2.6.5 the one-byte form set the divider to 1, which switched the pads to 8 MHz until reset. | documented only | code |
| 0x61 DEBUG_POLL_TIMING | Configuration (RAM) | ACK | **Do not send:** a bench experiment that changes the pad poll timing. The defaults are 700 us. | documented only | code |
| 0x62 DEBUG_PADS_RESTART | Destructive (pad power or pad reset) | ACK when the pads answer and tare; NACK 2 otherwise | **Do not send:** it switches the pad power off or resets every pad, then detects plates and tares. It is refused with NACK 3 while streaming or updating, and with NACK 8 during a pad firmware job. | documented only | code |
| 0x63 (pad-sample mode switch) | Configuration (RAM) | ACK | **Do not send:** a bench experiment that switches the pad polling between GET_FRAME and queued samples, RAM only. The state after a reset is queued samples on. It does not check whether a stream is running and has no guard. The effect on the stream is in [05-measurement-stream.md](05-measurement-stream.md), section 4.8. Not run on hardware. | documented only | code |

The codes 0x64 and 0x65 are not in the 1.2.8.0 command list and get NACK 7. Treat the whole range 0x60 to 0x65 as debug codes that must not be sent.

### 3.6 Firmware update

**Table 3.6 Firmware update command**

| Code and name | Class | Reply | Why it is dangerous | SDK | Evidence |
|---|---|---|---|---|---|
| 0x40 FIRMWARE_UPDATE | Firmware update | 18 bytes, `pa` 0: subop, status, `value1` u32, `value2` u32 ([03-host-link-framing.md](03-host-link-framing.md), section 3.11) | **Do not send:** it erases and writes firmware slots. A payload that is not valid base64 gets status 2 in this reply, not a NACK. The sequence is not part of this edition. | documented only: out of conformance scope | code |

### 3.7 Undispatched codes and 0x00

The command list names nine codes that the switch does not handle. Each gets NACK 7 through the default case. The list has 47 codes, of which 38 are dispatched.

**Table 3.7 Undispatched codes and 0x00**

| Code and name | Reply | SDK | Evidence |
|---|---|---|---|
| 0x02 START_ACQ | NACK 7 | not implemented: the firmware refuses it | code |
| 0x03 STOP_ACQ | NACK 7 | not implemented: the firmware refuses it | code |
| 0x04 CLEAR_CACHE | NACK 7 | not implemented: the firmware refuses it | code |
| 0x17 GET_CALIBRATION | NACK 7 | not implemented: the firmware refuses it | code |
| 0x32 SET_WIFI_SSID | NACK 7 | not implemented: the firmware has no Wi-Fi | code |
| 0x50 PADS_CALIBRATION_START | NACK 7 | not implemented: the firmware refuses it | code |
| 0x51 PADS_CALIBRATION_STOP | NACK 7 | not implemented: the firmware refuses it | code |
| 0x54 PADS_GET_CF | NACK 7. Not dispatched on the host side. The pad has a handler, which the host cannot reach | not implemented | code |
| 0x55 PADS_SAVE_CF | NACK 7. Not dispatched on the host side. The pad has a handler that saves flash, which the host cannot reach | not implemented | code |
| 0x00 | No reply. A request with code 0x00 stores its fields and matches no command case | documented only: nothing to implement | code |
| Any other code | NACK 7 | not implemented | code |

### 3.8 Commands that wait for a late plate (1.2.6.6 and later)

Evidence: code, with one measured bench run of 1.2.6.6.

In 1.2.6.6 and later, two command cases can hold the main loop until 8 s after a controller boot while a plate does not answer.

- GET_CURRENT_CONFIG (0x1A) sends its config transaction to each pad and then waits for late plates before it replies.
- START (0x01) and SET_CALIBRATION (0x11) run a platform redetection before the placeholders. When fewer than two plates are known, it runs a detection sweep of up to three rounds and then waits for late plates. It then tares every detected plate that has not been tared since boot, whether or not a plate was missing. A failed tare counts as tried.

The wait repeats a one-round detection sweep, with a watchdog refresh, while fewer than two plates are known and the uptime is below 8000 ms. A detection sweep continues until every plate has answered, up to its maximum rounds. After 8 s of uptime nothing waits, so a setup with one plate is delayed only right after a power-on or a reset.

The reason: right after a controller restart a plate's pads can need seconds to answer. A config query or a START then left that plate out, with its START frame sent as platform 0.

A host that talks to the controller right after a boot or a reset has to allow for this.

1. A GET_CURRENT_CONFIG or START sent within 8 s of a boot, while a plate is missing, can take until 8 s of uptime to complete. No other command is handled meanwhile, because the wait runs inside the command case.
2. START can tare a plate before the stream starts, and a load on the plate then becomes its zero. A bench run of 1.2.6.6 recorded the first frame 1.30 to 1.31 s after START in a sequence that began with a controller reset, because the plates were tared before streaming (measured).
3. A plate still missing after the wait gets a placeholder with `pa` 0 (Section 6.2).

In 1.2.6.5 the detection sweep stopped at the first plate found, START gave a missing plate one sweep, and nothing waited. A host then sometimes saw a frame from platform 0 and no data from one plate.

The 1.2.6.6 bench run recorded GET_CURRENT_CONFIG answering in 0.02 s without a reset and in 0.31 s after a host application's reset sequence. In those runs plate 2 answered within 3 s, so the late-plate wait itself did not have to act (measured). The wait has not been seen acting on hardware, and 1.2.8.0 keeps this code and has not been run on hardware (open point 11).

## 4. Worked frames

Each frame below was computed from the layout in Section 2 and the CRC in [03-host-link-framing.md](03-host-link-framing.md). The KEEP_ALIVE, START and broadcast SET_TARE request frames match the bytes a known-good phone client writes, and the version probe matches the one in chapter 03. The SET_TARE and SET_FILTER frames belong to commands that have no vector.

**Table 4.1 Worked frames**

| Example | Wire bytes (hex) | Field breakdown | CRC input (bytes 2 to n-5) | Evidence |
|---|---|---|---|---|
| KEEP_ALIVE, 600 s, request | `feed00002658023e820404` | FE ED; pa 00; da 00; cmd 26; p0 58, p1 02 (600, u16 little-endian); CRC 3E 82, that is 0x823E; EOT 04 04. No reply. | 00 00 26 58 02 | vector |
| SET_FILTER, 50 Hz at 500 sps, request | `feed00001c32f401643e0404` | cmd 1C; p0 32 (50 Hz); p1 F4, p2 01 (500, u16 little-endian); CRC 64 3E, that is 0x3E64 | 00 00 1C 32 F4 01 | code |
| SET_FILTER, 250 Hz at 500 sps, request (rejected) | `feed00001cfaf40132b10404` | p0 FA (250); the cutoff is not below half of 500, so the reply is NACK 3 | 00 00 1C FA F4 01 | code |
| SET_FILTER, 250 Hz at 500 sps, reply | `beef001c15030059b80404` | pa 00; cmd 1C; nack 15; error 03 00 (u16, 3); CRC 59 B8, that is 0xB859 | 00 1C 15 03 00 | code |
| SET_FILTER, 50 Hz at 500 sps, ACK | `beef001c0644ea0404` | pa 00; cmd 1C; ack 06; CRC 44 EA, that is 0xEA44 | 00 1C 06 | code |
| SET_TARE, plate 1, request | `feed01001bf6580404` | pa 01; da 00; cmd 1B; no payload; CRC F6 58, that is 0x58F6 | 01 00 1B | code |
| SET_TARE, plate 1, ACK | `beef011b06e3440404` | pa 01; cmd 1B; ack 06; CRC E3 44, that is 0x44E3 | 01 1B 06 | code |
| SET_TARE, plate 2, NACK 2 (no response) | `beef021b150200c69e0404` | pa 02; cmd 1B; nack 15; error 02 00; CRC C6 9E, that is 0x9EC6 | 02 1B 15 02 00 | code |
| SET_TARE, broadcast, request as a phone client writes it | `feedff001ba5a00404` | pa FF (all plates); da 00; cmd 1B; no payload; CRC A5 A0, that is 0xA0A5 | FF 00 1B | code |
| SET_TARE, broadcast, ACK | `beefff1b06b0bc0404` | pa FF; cmd 1B; ack 06; CRC B0 BC, that is 0xBCB0 | FF 1B 06 | code |
| GET_FW_VERSION (0x23), request | `feed0000239dd80404` | pa 00; da 00; cmd 23; no payload; CRC 9D D8, that is 0xD89D. The reply is 38 bytes (Table 3.2). | 00 00 23 | vector |
| GET_STATUS (0x22), request | `feed000022bcc80404` | pa 00; da 00; cmd 22; CRC BC C8, that is 0xC8BC | 00 00 22 | vector |
| START (0x01), request as a phone client writes it | `feedffff0121100404` | pa FF; da FF (broadcast); cmd 01; CRC 21 10, that is 0x1021. Accepted, not checked against `pa`. | FF FF 01 | vector |

The CRC routine gives 0x29B1 for the ASCII string `123456789`, the published check value for CRC-16/CCITT-FALSE.

The SET_TARE request names plate 1 in `pa`. A request whose `pa` is 3 to 254, or names a plate that was not detected, gets NACK 1 with that `pa`.

## 5. What a host does with silence

Five cases produce no reply, and a host has to treat them differently.

1. A frame that fails the length or header rules (Table 2.1, steps 2 and 3) is dropped without any reply. The host's request timeout is the only signal.
2. A command with code 0x00 is accepted by the parser, which stores its platform, destination and length fields. No command case matches it.
3. START and the other silent commands listed in Section 2 reply with nothing even when they succeed.
4. A reply that finds the TX ring full is dropped after 50 ms (Section 2).
5. A request that finds the command queue full is counted and dropped with no reply.

## 6. Findings

Findings F1, F2, F4 and F5 are defined here. Each was checked against the 1.2.8.0 code (code). The hardware behaviour that the code implies is listed in Section 7.

### 6.1 F1: ANALOG_TEST never returns

The firmware sends the ACK for 0x39 and then runs an endless loop with no watchdog refresh. Command parsing runs only from the main loop, so no later request is processed.

The only watchdog that the firmware arms is the independent watchdog that the trial boot starts, which a code comment puts at about 8 s. The application refreshes it from the main loop. After a firmware update the trial image runs under this watchdog, so a loop that stops refreshing it is reset about 8 s later. Outside a trial boot no watchdog runs, so the loop stays stopped until something resets the controller (open point 3). The host sees one ACK and then silence.

### 6.2 F2: START has no ACK and sends placeholders

START and SET_CALIBRATION share one case. The case sends no ACK. It sends two frames with timestamp 0, one each for plate addresses 1 and 2, whether or not those plates were detected.

The frame's `pa` byte is the plate's stored address, which the detection code sets only when it hears a plate. A placeholder for an undetected plate therefore has `pa` 0, and its force fields hold whatever the last calculation left in RAM.

Before the placeholders, START runs the platform redetection. When fewer than two plates are known, its detection sweep and the wait for a late plate can block the main loop for up to three sweep rounds and then until 8 s of uptime. It also blocks for a tare of any detected plate that has had no tare attempt since boot. Section 3.8 gives the rule.

A host cannot confirm START from a reply, so the first frames that follow it are the only sign that START worked. [05-measurement-stream.md](05-measurement-stream.md) covers the placeholder frames and how a host tells them from measurements.

### 6.3 F4: the keep-alive timer does not sleep while streaming

The keep-alive counter counts TIM2 update events. The counter is held at zero while the stream runs or when the interval is 0. Otherwise it counts, and when the count exceeds the interval times 10000 ticks it zeroes the counter and requests sleep. The main loop then refuses that sleep while streaming, so a stream never sleeps. A code comment records why: an earlier firmware cut pad power ten minutes into a recording when the host did not send KEEP_ALIVE.

Any latched host command zeroes the counter, and KEEP_ALIVE also sets the interval. The default interval is 600 s. The interval is RAM only, so a reset restores 600.

The sleep path turns the pad power off, disables USART1 and TIM2, and enters WFI, then restores all of them on wake. The code names no wake source. Whether host traffic wakes the controller is an open point (point 2).

A phone client that is known to work writes KEEP_ALIVE with interval 600 every 30 s while a session is open. A host that keeps a session open with KEEP_ALIVE therefore never reaches the sleep. A host that streams without KEEP_ALIVE is not put to sleep either, because the sleep is refused while streaming.

A stopped stream with no latched command for the full interval (600 s by default) is the only case in which the firmware sleeps on the keep-alive timer.

An earlier reference firmware behaves differently: its timer counts whether or not the device streams. This chapter describes 1.2.8.0 only.

### 6.4 F5: flash writes and pad saves are not refused while streaming

Only pad firmware updates block the commands in the pad-disturbing list (Table 2.1, step 10). SAVE_CALIBRATION (0x19) and CONTROLLER_RESET (0x25) are in that list, but the guard checks only for a pad firmware job, and nothing checks the stream flag. Both commands therefore run during a stream.

SAVE_CALIBRATION writes flash, and a code comment says a sector erase stalls interrupts. CONTROLLER_RESET writes flash when values changed and then resets the controller. A reset during a stream ends it, and the host sees the link drop.

On the pad side, PADS_SAVE_FACTORY_GF with a zero value erases the factory-gain flash page, writes the header word first, and then writes the data. It keeps no backup and reads nothing back. The reader checks only the header word, so a write interrupted after the header is accepted as valid. The controller does not wait for the pad to confirm the write.

## 7. Open points

All of these are unverified on hardware.

1. The keep-alive counter runs at 10 kHz only if TIM2 runs at 84 MHz. The PLL settings give 84 MHz SYSCLK and APB1 divided by two, and the timer clock rule for STM32F4 doubles the APB1 clock when its prescaler is not 1. The rate was not measured. (Code and vendor rule.)
2. The keep-alive sleep: the code names no wake source, and host UART interrupts are not disabled there. Whether a host byte wakes the controller, and whether the state is correct after wake, was not tested.
3. ANALOG_TEST (0x39) never returns and the device does not recover without a reset (Section 6.1). The hardware state after the command was not observed.
4. The 100 ms wait in PADS_GET_FACTORY_GF is enough for the pad to answer. The pad's reply time was not measured.
5. The duration of the flash erase that SAVE_CALIBRATION and CONTROLLER_RESET can trigger, and whether the 10 kHz timestamp loses ticks during the stall. Not measured.
6. After SET_SERIAL_PARAM and a reset that loads the saved value, the link comes back at the new rate. The path was not run on hardware.
7. The tare duration of 0.3 to 4 s is a code comment and is not measured here.
8. Extra pad polls from GET_FRAME raise pad noise, as a code comment states. The comment reports a bench measurement from 1.2.3, which was not repeated.
9. The pad-sample debug command (0x63) and the queued pad samples it switches. 1.2.8.0 was merged with simulation tests only. What a stream does when 0x63 changes during it was not observed.
10. The late-plate wait of Section 3.8 acting on hardware. See that section.

## 8. Known inconsistencies

- GET_SAMPLING_RATE reports 2048 at boot. A host that reads that value as the stream rate is wrong. The stream runs at the filter SPS, which is 500 by default in 1.2.8.0 and 1,000 from 1.2.8.8.
- On USART3, GET_STATUS reports the new baud rate as soon as SET_SERIAL_PARAM runs, while the port keeps the old rate until the next boot. Over UART4, GET_STATUS reports the default rate, not the stored one. The new rate survives that boot only if a flash write ran after the command.
- The SDK clients do not send SET_TARE (0x1B), although the 1.2.8.0 firmware accepts it while streaming. A tare re-zeroes the plates.
