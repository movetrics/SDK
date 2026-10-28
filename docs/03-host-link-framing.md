# 03. Host link framing: request, reply and stream frames

Public edition of the SDK specification. Statements are marked code (read in the firmware), measured (seen on a device) or vector (covered by the test vectors).

This chapter describes controller firmware 1.2.8.0. Byte sequences and CRC values were recomputed with CRC-16/CCITT-FALSE in Python, and the worked examples say so. Nothing here was run on a device. Firmware 1.2.8.0 has not been run on hardware. Its host framing code is the same as in 1.2.6.5.

Every host request and every reply uses one envelope: a two-byte header, a platform and a pad address, a command code, an optional payload, a CRC-16/CCITT-FALSE over bytes 2 to n-5, and the end marker `04 04`. Requests start with `FE ED`. Replies start with `BE EF`. The 24-byte stream frame is a reply with command 0x01.

The end marker has no escaping. A CRC byte of 0x04 can therefore close a frame early. The controller then drops a zero-payload request silently and answers NACK 9 to one with a payload. The controller's parser, the bootloader and the reference phone client's decoder each resynchronise in a different way. Section 3.12 compares them.

Firmware-update frames avoid the hazard with base64 payloads and `.` salt bytes. The generic frame has no salt.

This chapter does not cover the command table or the stream timing. They are in [04-host-commands.md](04-host-commands.md) and [05-measurement-stream.md](05-measurement-stream.md). The firmware-update sequence is not part of this edition.

## 3.1 Frame layouts

All multi-byte fields are little-endian. The CRC is always the two bytes before `04 04`, and it covers bytes 2 to n-5 of the frame.

| Frame | Length | Byte layout | Evidence |
|---|---|---|---|
| Request | 9 + payload | `FE ED pa da cmd [payload] crc_lo crc_hi 04 04` | vector |
| ACK reply | 9 | `BE EF pa cmd 06 crc_lo crc_hi 04 04` | vector |
| NACK reply | 11 | `BE EF pa cmd 15 err_lo err_hi crc_lo crc_hi 04 04` | code |
| Stream frame (also the START reply) | 24 | `BE EF pa 01 ts[4] fx fy fz mx my mz crc_lo crc_hi 04 04` | vector |
| GET_CURRENT_CONFIG reply | 24 | `BE EF 00 1A t1 ... t16 crc_lo crc_hi 04 04` | code |
| GET_STATUS record (one per platform, plus one general) | 86 | `BE EF pa 22 errorFlags[4] temp serial[20] ssid[30] ip[4] mask[4] gw[4] cache[4] calX calY calZ soc crc_lo crc_hi 04 04` | vector |
| Firmware-update reply | 18 | `BE EF 00 40 subop status value1[4] value2[4] crc_lo crc_hi 04 04` | code |

In the stream frame, `fx fy fz mx my mz` are six 2-byte values. The other reply sizes are in section 3.6. The sizes in this table and in 3.6 are the packed struct sizes, recomputed in Python from the field lists.

## 3.2 The CRC

Evidence: code and vector.

The CRC is CRC-16/CCITT-FALSE: initial value 0xFFFF, polynomial 0x1021, no reflection and no final XOR. Its check value over the ASCII string `123456789` is 0x29B1, which is the standard value for this variant.

The CRC is stored low byte first. Replies compute it the same way, over the bytes from the platform address up to the CRC field.

The reference phone client has its own copy of the routine, and the bootloader has another. Both use the same parameters.

## 3.3 The end marker and the 0x04 hazard

Evidence: code. The scan below is arithmetic over the CRC definition and has not been run against a controller.

Every frame ends in `04 04`, and nothing is escaped. The receive splitter closes a message on the first pair of `04` bytes it sees, wherever that pair is. This holds even inside the payload or the CRC.

A CRC high byte of 0x04 therefore closes the message one byte early, at the CRC high byte and the first end byte. The last `04` then starts the next message. A CRC low byte of 0x04 does no harm on its own, because the pair is not complete until the high byte is also 04.

Three cases follow from the code.

- Zero payload. `FE ED FF 01 21 8D 04 04 04` is a request to platform FF, pad 01, command 0x21 (RUN_SELF_TEST), with CRC 0x048D. The splitter hands over the 8 bytes `FE ED FF 01 21 8D 04 04`. The parser returns at once because it needs at least 9 bytes. The request is dropped without a NACK, and the leftover `04` is held as the start of the next message.
- Payload. `FE ED 00 00 12 2C 3F 04 04 04` is SET_CHANNEL_MASK with payload 0x2C and CRC 0x043F. The splitter hands over a 9-byte message. The parser reads its CRC from the payload byte and the CRC low byte, so the check fails. The controller answers `BE EF 00 12 15 09 00 C8 F5 04 04`, which is NACK 9. The request was valid.
- Replies. A reader that splits replies on `04 04` cuts a reply whose CRC high byte is 0x04. A decoder that reads each reply by its header and length is not affected (section 3.12).

The hazard is not rare. Take the 47 documented opcodes, the platform and pad addresses 00, 01, 02 and FF, and da 00 to 04 and FF. Five zero-payload requests then have a CRC high byte of 0x04:

- pa 00, da 04, 0x22
- pa 02, da 04, 0x53
- pa FF, da 01, 0x21
- pa FF, da 03, 0x14
- pa FF, da FF, 0x22

Any other address pair has about the same one-in-256 chance per opcode. The opcode 0x63, new in 1.2.7.0, adds no such request.

The five frames of a minimal client have no 04 byte in their CRC. The CRCs are:

| Frame | CRC |
|---|---|
| KEEP_ALIVE with 600 s | 0x823E |
| START | 0x1021 |
| STOP (to platform FF) | 0x535A |
| GET_STATUS | 0xC8BC |
| SET_TARE to the broadcast platform, no payload: `FE ED FF 00 1B A5 A0 04 04` | 0xA0A5 |

The BLE bridge sends the same STOP frame when a session ends.

## 3.4 What the controller does with a message

Evidence: code.

1. The receive path keeps bytes until it sees `04 04`. Each UART has its own splitter and DMA cursor. A message longer than the 320-byte builder sets an overflow flag and is not delivered.
2. A delivered message is queued with its port. The queue has 16 slots, of which 15 can hold a command, because one slot must stay empty to tell full from empty. A command that finds the queue full is dropped and counted. A burst larger than 15 commands loses commands.
3. The main loop takes the oldest message, records its port as the active port, and parses it.
4. The parser does the following, in order.
   - If the message is at least 9 bytes and does not start with `FE ED`, it searches from byte 1 for the first `FE ED` and drops the bytes before it. This is the only resynchronisation in the controller.
   - A message shorter than 9 bytes, or one without a header, returns with no reply.
   - A CRC mismatch gets NACK 9.
   - End bytes that are not `04 04` get NACK 7. The splitter only closes messages on `04 04`, so this branch is not reached from the splitter. That is a reading of the code, not a run.
   - A payload shorter than the command needs, or an index out of range, gets NACK 3. The minimum payloads are: SET_FILTER 3 bytes; SET_SAMPLING_RATE, KEEP_ALIVE and PADS_SAVE_FACTORY_GF 2 bytes; SET_CHANNEL_MASK, INCREASE_VALUE, DECREASE_VALUE, ANALOG_ENABLE and SET_SERIAL_PARAM 1 byte. The debug commands 0x60 to 0x63 are not in this list. Each checks its own payload and answers NACK 3.
   - A valid command stores its addresses and its length, and its port becomes the active port.
5. Execution first refuses a pad-disturbing command during a pad update with NACK 8. It then dispatches on the opcode. Every accepted command resets the sleep counter.

Opcodes with no case in the dispatch switch get NACK 7. In 1.2.8.0 these are 0x02, 0x03, 0x04, 0x17, 0x32, 0x50, 0x51, 0x54 and 0x55.

## 3.5 Error codes

Evidence: code. The NACK frame carries the code as two little-endian bytes.

| Code | Name | Sent when (examples from the code) |
|---|---|---|
| 1 | ERR_PLATFORM_NOT_EXIST | SET_TARE names a platform with no plate |
| 2 | ERR_PLATFORM_NO_RESPONSE | SET_TARE finds no response from the plates |
| 3 | ERR_INVALID_PARAMETER | A payload or index fails the parser checks; SET_SERIAL_PARAM outside 1 to 6; SET_FILTER refused; DEBUG_ADC_CLOCK_DRIVE or DEBUG_POLL_TIMING out of range; the pad-sample debug command 0x63 without its byte or with a value above 1 |
| 7 | ERR_UNKNOWN_COMMAND | An opcode with no dispatch case |
| 8 | ERR_UNEFFECTIVE_COMMAND | A pad-disturbing command during a pad update; START or SET_CALIBRATION during a firmware update; SET_TARE during a firmware update |
| 9 | ERR_CRC | A request CRC does not match |

## 3.6 Reply kinds and reply rules

Evidence: code.

| Kind | Frame | Commands |
|---|---|---|
| ACK | 9 bytes, ack 0x06 | STOP_STREAM 0x05 and END_CALIBRATION 0x16; SET_SAMPLING_RATE 0x07; SET_CHANNEL_MASK 0x12; RUN_SELF_TEST 0x21 (sends the ACK and runs no test); CONTROLLER_RESET 0x25; SET_FILTER 0x1C; SET_TARE 0x1B; ANALOG_TEST 0x39; SAVE_CALIBRATION 0x19; SET_SERIAL_PARAM 0x31; SERVER_AP_ENABLE 0x33; ANALOG_ENABLE 0x34; SERVER_BT_ENABLE 0x35; SERVER_USB_ENABLE 0x36; PADS_SAVE_FACTORY_GF 0x53; DEBUG_ADC_CLOCK_DRIVE 0x60; DEBUG_POLL_TIMING 0x61; DEBUG_PADS_RESTART 0x62; the pad-sample debug command 0x63 |
| Data | see the table below | GET_CURRENT_CONFIG 0x1A; GET_SAMPLING_RATE 0x08; GET_CHANNEL_MASK 0x13; GET_STATUS 0x22; GET_SERIAL_NUMBER 0x24; GET_FW_VERSION 0x23; GET_PAD_HEALTH 0x27; SET_LAYOUT 0x18 |
| Stream-type | 24 bytes, cmd 0x01 | START 0x01, and SET_CALIBRATION 0x11 through the same case |
| NACK | 11 bytes | Any error in section 3.5 |
| None | nothing from the controller | KEEP_ALIVE 0x26; GET_FRAME 0x06; INCREASE_VALUE 0x14 and DECREASE_VALUE 0x15 (no reply to a request that passes the checks in section 3.4; the controller writes a debug line to its USART2 debug port, not a frame); PRINTOUT_ENABLE 0x37 and PRINTOUT_DISABLE 0x38 |
| Firmware update | 18 bytes | FIRMWARE_UPDATE 0x40 (do not send; section 3.11) |
| Factory gain | 16 bytes, no command byte | PADS_GET_FACTORY_GF 0x52 |

Sizes of the data replies, from the packed structs:

| Reply | Bytes |
|---|---|
| GET_CURRENT_CONFIG 0x1A | 24 bytes |
| GET_SAMPLING_RATE 0x08 | 10 bytes |
| GET_CHANNEL_MASK 0x13 | 9 bytes |
| GET_STATUS 0x22 | 86 bytes per record |
| GET_SERIAL_NUMBER 0x24 | 28 bytes |
| GET_FW_VERSION 0x23 | 38 bytes |
| GET_PAD_HEALTH 0x27 | 120 bytes |
| SET_LAYOUT 0x18 | 32 bytes |

The rules a client can rely on:

- Every reply starts with `BE EF`. Most replies echo the request's platform address. The configuration reply and the firmware-update reply use address 0. Each GET_STATUS record carries its own address: 0 for the general record, and 1 or 2 for a plate.
- Most replies echo the command code. The factory-gain reply does not: its fourth byte is the pad address.
- A NACK replaces the normal reply for that command.
- START and SET_CALIBRATION send no ACK. Each sends one stream-type frame for platform slot 1 and one for slot 2, with timestamp 0, and then enables the stream. The pa byte of each frame is the plate's stored address. It is 0 until that plate has answered its configuration, so the frames need not carry addresses 1 and 2.
- Both commands first run a platform redetection. If fewer than two plates are known, it sweeps for them. Within 8 s of start-up, it waits for a plate that has not answered yet. It then tares each detected plate that has had no tare attempt since boot.
- A config query (0x1A) also waits for a missing plate within 8 s of start-up before it replies. A client that sends 0x1A or START soon after the controller starts must allow for that wait in its reply timeout ([04-host-commands.md](04-host-commands.md), section 3.8).
- KEEP_ALIVE sends no reply. A host cannot tell from a reply that the controller received it.
- A reply goes to the port of the last accepted command, and waits up to 50 ms for transmit room (sections 2.3 and 2.8 of [02-transports.md](02-transports.md)).

## 3.7 The stream frame

The stream frame is the 24-byte reply in section 3.1. Its fields are these.

- `pa` is the platform's number. It is 0 until the plate has answered its configuration (code).
- `cmd` is 0x01.
- `ts` is the frame time, an unsigned 32-bit count. TIM2 ticks every SystemCoreClock / 10,000 cycles, that is at 10 kHz, so one tick is 0.1 ms. The count restarts at 0 with each stream (code). [05-measurement-stream.md](05-measurement-stream.md) gives the stamp rules. In short, in every build except the synthetic test image, once a pad of a plate is on queued samples in a stream, that plate's frames are stamped with their own time on the frame grid until the stream stops. Any other frame is stamped with the mean time at which its pad replies were polled, as before 1.2.8. Neither is the time the frame was sent. Each platform's stamps stay strictly increasing.
- The six channels are signed 16-bit values in the order forceX, forceY, forceZ, momentX, momentY, momentZ. The values are scaled by the platform factors and a constant of 98/100000, then converted to int16 with a plain cast and no saturation. The unit is not stated in the code or in any record (open point).

The frame has no quality, gap or health field. The health bits are in the GET_STATUS `errorFlags` and in GET_PAD_HEALTH ([06-status-health-versions.md](06-status-health-versions.md)). 
Outside the synthetic test image, the frames of each plate lie on one grid at the filter's design rate per plate, which defaults to 500 per second in 1.2.8.0 (1,000 from 1.2.8.8). Frame m is for TIM2 tick m x 10,000 / rate, rounded. A frame is sent a fixed latency after its time, so that its pad data is in. The latency is zero while 0x63 has queued samples switched off. The main loop sends at most one frame per pass. After a stall, the older due frames are skipped, so at most two frames go out back to back.

A plate with no new pad data for a frame is counted in `stale_frames`, and its frame is still sent with the held values. A code comment records about 626 frames per second per plate for the free-running rate that the pacing replaced. A bench record gives 500.1 frames per second per plate on firmware 1.2.3.3 (measured, not the 1.2.8.0 build). The grid of 1.2.8.0 has not been run on hardware. Stream rate and timing are covered in [05-measurement-stream.md](05-measurement-stream.md).

Example, from the transport test. A START frame for platform 1 with forceX -123, forceZ 456 and timestamp 123456, with the other channels at zero, is 24 bytes with a valid CRC:

`BE EF 01 01 40 E2 01 00 85 FF 00 00 C8 01 00 00 00 00 00 00 06 4C 04 04`

The CRC over bytes 2 to 19 is 0x4C06, which matches the bytes `06 4C` (worked example, recomputed in Python).

## 3.8 Worked examples

Evidence: vector for A and B (KEEP_ALIVE, STOP), otherwise recomputed in Python. Each CRC matches the bytes on the wire.

Example A, KEEP_ALIVE with 600 seconds. The request is 11 bytes:

`FE ED 00 00 26 58 02 3E 82 04 04`

The CRC covers `00 00 26 58 02` and is 0x823E. The payload `58 02` is 600 as a little-endian 16-bit value. The controller sets the sleep interval to 600 s and clears the counter, and it sends no reply. The request needs at least 11 bytes. A phone client that is known to work sends this frame every 30 s (section 3.10).

Example B, STOP and its ACK. The request is for platform 0 and pad 0:

`FE ED 00 00 05 39 9C 04 04`

Its CRC covers `00 00 05` and is 0x9C39. The reply is:

`BE EF 00 05 06 AF 53 04 04`

Its CRC covers `00 05 06` and is 0x53AF. The ACK is sent first, and the stream is then disabled. A phone client and the bridge send the same command to the broadcast platform address, as `FE ED FF 00 05 5A 53 04 04` with CRC 0x535A. Its ACK echoes address FF.

Example C, the zero-payload hazard, is in section 3.3. Its bytes are `FE ED FF 01 21 8D 04 04 04`, and the controller drops it silently.

## 3.9 KEEP_ALIVE is a sleep timer, not a watchdog

Evidence: code. This section describes firmware 1.2.8.0. Earlier builds may differ.

KEEP_ALIVE sets the sleep interval in seconds. The default is 600 s. The timer counts 10,000 ticks per second, and the controller sleeps when no host has been heard for longer than the interval.

In 1.2.8.0, any accepted command counts as a host being heard. A stream never sleeps. An interval of 0 turns sleep off.

When the timer fires, the controller switches the pads off, stops USART1 and TIM2, and enters sleep. On wake it switches the pads on and marks them for a cold boot. Nothing resets the controller when a host goes quiet. The sleep only powers the pads down.

## 3.10 A known-good client cadence

Evidence: code (a phone client that is known to work).

While samples arrive, the phone client writes the KEEP_ALIVE frame every 30 s and a GET_STATUS request every 10 s. The first status query comes 3 s after the stream starts.

The client writes a broadcast SET_TARE (0x1B) only when the operator asks for it while the stream is live and nothing is recorded. It takes a 9-byte ACK as success, and it queries the status again as soon as the reply arrives. The controller runs the tare inside the command, so the stream pauses while it runs.

Before START, the client writes the KEEP_ALIVE frame first and then waits a short interval before it writes START.

Whether a connected phone that sends nothing keeps the controller awake is not covered by these code paths (unverified).

## 3.11 Firmware-update frames

Evidence: code. Do not send firmware-update frames from a general host client. This section gives only the framing.

Firmware-update requests use command 0x40 and carry the sub-operation in the destination byte. The layout is:

`FE ED 00 <subop> 40 <base64 payload> <'.' x k> <crc16 LE> 04 04`

The base64 alphabet contains no 04, so the payload cannot close the frame early. The host appends `.` bytes (0x2E) until neither CRC byte is 0x04. The decoder strips trailing `.` and `=` before it decodes.

Generic requests have no salt. Their payload bytes are passed on as they arrive. A client must not add `.` bytes to a generic request.

The firmware-update reply is 18 bytes: `BE EF 00 40 <subop> <status> <value1 u32 LE> <value2 u32 LE> <crc16 LE> 04 04`. The CRC covers bytes 2 to 13. The bootloader builds the same reply.

## 3.12 Resynchronisation: three parsers compared

Evidence: code.

| Parser | Starts a message at | Ends a message at | Bytes before a header |
|---|---|---|---|
| Controller, USB and BLE | Any `FE ED` found in the buffer | A `04 04` pair | Searched for and dropped |
| Bootloader, UART4 and USART3 | The first byte after the previous `04 04` | A `04 04` pair | The message is dropped without a reply |
| Reference phone client decoder, replies only | A `BE EF` found anywhere | The known length for the command, or 9 or 11 bytes for an ACK or NACK, or for a command with no known length the first length from 8 to 320 that passes the `04 04` and CRC check | Dropped up to the header. A known-length candidate that fails its check loses one byte |

The controller's search exists because junk before a header used to make the next command vanish silently.

The bootloader has no such search. It answers only GET_FW_VERSION (0x23) and FIRMWARE_UPDATE (0x40), and it returns no reply to any other command. A client that talks to the bootloader must send one of these two.

The reference phone client's decoder knows the reply lengths for a short list of commands:

- stream 24 (0x01)
- GET_SAMPLING_RATE 10 (0x08)
- GET_CHANNEL_MASK 9 (0x13)
- SET_LAYOUT 32 (0x18)
- GET_CURRENT_CONFIG 24 (0x1A)
- GET_STATUS 86 (0x22)
- GET_FW_VERSION 38 (0x23)
- GET_SERIAL_NUMBER 28 (0x24)

STOP (0x05) has no entry, so its reply is taken by the ACK rule. A 9-byte ACK (byte 4 is 0x06) or an 11-byte NACK (byte 4 is 0x15) is accepted for any command other than the stream, when it passes the check. A reply to a command with no known length, such as a firmware-update reply or GET_PAD_HEALTH, is taken at the first length from 8 to 320 that passes the check. A known-length candidate that fails its check loses one byte. A GET_STATUS of 85 bytes is accepted when the 86-byte candidate is not taken and the 85-byte check passes. The 85-byte form is for older firmware and is not a second format ([06-status-health-versions.md](06-status-health-versions.md), section 6).

A client that reads replies should check, in this order: the `BE EF` header; the echoed platform address and command code; the `04 04` end; and the CRC over bytes 2 to n-5.

A NACK 9 to a request is not always a line error. If the request's CRC high byte is 0x04, the controller produces this NACK for a frame that was built correctly (section 3.3). A client should compute the CRC before it sends, and treat a frame whose CRC high byte is 0x04 as one it cannot send as built.

## Open points

All of these are unverified.

- The stream's timing and pacing ([05-measurement-stream.md](05-measurement-stream.md)). The pacing code belongs to 1.2.8.0, which has not been run on hardware, and no host test compiles it. No timing was measured here.
- Whether the 0x04 hazard occurs on the wire. The scan in section 3.3 is arithmetic. No test is known to lose a frame this way.
- Whether a connected phone that writes nothing keeps the controller awake (section 3.10).
- That the NACK 7 branch for a bad end marker is unreachable from the splitter. This follows from reading the splitter and the parser.
- The timing of the bootloader's recovery window, and whether a host that is late still gets a reply. Only the code path was read.
- The physical unit and scale of the six channel values. The conversion to int16 is a plain cast.
- The paced rate and the first-frame timing on hardware. The 500.1 frames per second figure was recorded on firmware 1.2.3.3, not on 1.2.8.0.

## Known inconsistencies

- Debug command 0x60 (DEBUG_ADC_CLOCK_DRIVE) is a bench command and must not be sent. In 1.2.6.5 its one-byte form switched the pads to 8 MHz until reset. This changed in 1.2.7.0.
- The queue constant is 16, but only 15 commands can wait. Do not size a burst by the constant.
- SET_CALIBRATION (0x11) has its own name in the opcode list, but its case label is shared with START. It sends the stream-type frames and enables the stream, as START does.
- Some code calls the 86-byte status record "v26" and some calls it "v25". This edition names layouts by length.
