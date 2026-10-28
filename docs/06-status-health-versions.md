# 06. Status, health and versions

Public edition of the SDK specification. Statements are marked code (read in the firmware), measured (seen on a device) or vector (covered by the test vectors).

This chapter specifies the four read-only replies that describe the controller at firmware 1.2.8.0: GET_STATUS (0x22), GET_PAD_HEALTH (0x27), GET_FW_VERSION (0x23) and GET_SERIAL_NUMBER (0x24). For each reply it gives the byte layout that the code builds, the meaning of its bits and fields, and the length rule for the 85-, 86- and 88-byte status variants.

Section 6 records what each known decoder does with each length, and Section 6.5 gives the rule that the SDK applies.

It does not define the request and reply envelope or the CRC ([03-host-link-framing.md](03-host-link-framing.md)). It does not cover the command switch and its guards ([04-host-commands.md](04-host-commands.md)) or the 24-byte stream frame ([05-measurement-stream.md](05-measurement-stream.md)). Points that the code does not settle are in Section 13, and the places where sources disagree are in Section 14.

## 1. Scope and reading rules

Byte numbers count from zero as the device sends them. The structs are packed, so every offset in this chapter is a wire offset.

The byte layouts are the C structs of the firmware. The safety class of the four requests is read-only, as [04-host-commands.md](04-host-commands.md) Section 1 defines it: each reply is built from RAM and no request starts traffic on the pad bus (Table 2.1).

The code builds controller application 1.2.8.0, controller bootloader 1.0.0.3 and pad application 2.8.0.0, whose channel-7 version value is 11. The four reply layouts are the same as in 1.2.6.5. What changed since then is how the pad bookkeeping behind errorFlags and GET_PAD_HEALTH is filled while a pad answers with queued samples (Sections 7.6 and 8.4), and the version texts (Section 9).

Controller 1.2.8.0 with pad 2.8.0.0 has not been run on hardware. The behaviour this chapter gives for those versions comes from the code and from host tests that simulate the pads. It is unverified on hardware (open point 16).

## 2. Requests and record order

**Table 2.1 The four requests**

| Request | Code | Payload | Reply bytes | Pad bus traffic | Evidence |
|---|---|---|---|---|---|
| GET_STATUS | 0x22 | None. The request `pa` is ignored | k records of one length, k = 1 + N (Table 2.2): 86 bytes per record in the controller form, 85 in the legacy form (Section 6.1) | None | vector |
| GET_FW_VERSION | 0x23 | None | 38 | None | vector |
| GET_SERIAL_NUMBER | 0x24 | None | 28 | None | code |
| GET_PAD_HEALTH | 0x27 | None | 120 | None | code |

None of the four codes is in the pad-disturbing list ([04-host-commands.md](04-host-commands.md), Table 2.1), so a pad firmware job does not refuse them. The only checks that apply are the generic checks of that table. Each builder reads RAM, and the serial builder also reads the fixed address of the microcontroller's unique ID.

The GET_STATUS builder ignores the request's `pa`. It sends the record for address 0 first, then one record for each of addresses 1 and 2 whose `platform_type` is not PLATFORM_NONE. PLATFORM_NONE is 0, PLATFORM_SINGLE is 1 and PLATFORM_DOUBLE is 2. No record is sent for an address above 2.

Each record is a separate write. A record that finds the TX ring full is dropped on its own, as [04-host-commands.md](04-host-commands.md) Section 2 describes. A host therefore finds each record by its own header and CRC and does not count on the record count.

**Reply length.** A GET_STATUS reply is k records, with k = 1 + N, where N is the number of addresses 1 and 2 whose type is not PLATFORM_NONE. So k is 1, 2 or 3, and all records of one reply have the same length.

The controller form has 86 bytes per record, so the reply is 86 x k bytes. The legacy form has 85 bytes per record, so its reply is 85 x k bytes. The legacy k = 1 case has a capture and two vectors. The legacy k = 2 and k = 3 cases are unverified (open point 15). For k from 1 to 3 the two forms never give the same total: 85, 170 and 255 against 86, 172 and 258. The total length therefore gives both the form and k.

**Table 2.2 GET_STATUS reply length by the number of detected plates**

| Detected plates N | Records k = 1 + N | Controller form, 86 x k | Legacy form, 85 x k |
|---|---|---|---|
| 0 | 1: address 0 | 86 | 85, one capture and two vectors |
| 1 | 2: address 0, then the one detected address | 172 | 170, unverified (open point 15) |
| 2 | 3: addresses 0, 1 and 2 | 258 | 255, unverified (open point 15) |

The controller's own transport test covers N = 1 only. No test covers N = 2 for firmware. A phone-client bench log summarises one device reply of 258 bytes as three 86-byte records, each with a valid CRC, and gives no bytes. The log labels the device `1.1-UART4-b3`. No capture holds the bytes of a multi-record reply. The vectors hold a derived three-record reply of 258 bytes.

GET_STATUS reports the plates that are detected when the request arrives. A plate becomes detected when one of its pads sends a config reply, a frame reply or a GET_SAMPLES answer. The GET_STATUS handler only builds the reply, so it neither probes the pad bus nor waits for a plate.

Only a config query (0x1A), START and SET_CALIBRATION (0x11, which shares the START handler) wait for a plate that has not answered yet, and only while the uptime is below 8 s. Outside a stream the controller probes an undetected plate once a second.

A status reply sent soon after a restart can therefore hold fewer records than there are plates, and a later reply can hold more. [04-host-commands.md](04-host-commands.md) Section 3.8 describes the wait in 0x1A and START.

## 3. The status record (86 bytes)

**Table 3.1 GET_STATUS record in controller 1.2.8.0**

| Bytes | Size | Field | Type and wire order | Content in 1.2.8.0 | Evidence |
|---|---|---|---|---|---|
| 0-1 | 2 | header | uint16, `BE EF` on the wire | Reply marker 0xEFBE | vector |
| 2 | 1 | platform_address | uint8 | 0 for the general record, 1 or 2 for a plate | vector |
| 3 | 1 | commandCode | uint8 | 0x22 | vector |
| 4-7 | 4 | errorFlags | uint32, little-endian | Section 4 | code |
| 8 | 1 | temperature | int8 | Always 0. No code assigns it | code |
| 9-28 | 20 | serialParams | char[20] | Text `baud,8,n,1`, NUL-terminated | vector |
| 29-58 | 30 | wifiSSID | char[30] | Always zero | code |
| 59-62 | 4 | wifiIP | uint8[4] | Always zero | code |
| 63-66 | 4 | wifiMask | uint8[4] | Always zero | code |
| 67-70 | 4 | wifiGW | uint8[4] | Always zero | code |
| 71-74 | 4 | cacheFrames | uint32, little-endian | Always zero | code |
| 75-76 | 2 | calibrationFactorX | uint16, little-endian | Factor X of the plate; zero in the general record | vector |
| 77-78 | 2 | calibrationFactorY | uint16, little-endian | Factor Y of the plate; zero in the general record | code |
| 79-80 | 2 | calibrationFactorZ | uint16, little-endian | Factor Z of the plate; zero in the general record | vector |
| 81 | 1 | batterySOC | uint8 | 255 in this firmware (Section 5) | vector |
| 82-83 | 2 | crc | uint16, little-endian | CRC over bytes 2 to 81 | vector |
| 84-85 | 2 | eot1, eot2 | `04 04` | End marker | vector |

The CRC is the CRC-16/CCITT-FALSE that [03-host-link-framing.md](03-host-link-framing.md) defines.

The record is zeroed before its fields are set. Any field the code never assigns is therefore zero on the wire.

The serialParams text is `1500000,8,n,1` when the request arrived on UART4, because the code then reports the default rate. On the other ports it reports the host rate held in RAM. The value is set by 0x31, and a later flash write stores it, as [04-host-commands.md](04-host-commands.md) Table 3.3 describes. The calibration factors are the values that scale each force and moment ([05-measurement-stream.md](05-measurement-stream.md) Section 3.1).

**Table 3.2 Two derived records** (computed from Table 3.1 and the CRC routine. No capture contains these bytes.)

| Record | Wire bytes (hex) | CRC, bytes 82-83 | Inputs |
|---|---|---|---|
| General record, serialParams as the UART4 path writes it | `beef00220000000000313530303030302c382c6e2c310000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000ff80530404` | 0x5380 | No plate, factors zero, battery 255 |
| Plate 1 record, factor X 35 and factor Z 43 | `beef01220000000000313530303030302c382c6e2c310000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000230000002b00fff4cc0404` | 0xccf4 | The factors are 35 and 43. The controller's transport test asserts some of these bytes: the address, the command, byte 81, the serial text and, for plate 1, bytes 75 and 79. It does not assert the whole record |

## 4. errorFlags

Evidence: code.

Each plate record carries the flags of its own pads in errorFlags. Pads 1 and 2 are the only pads in the loop.

**Table 4.1 errorFlags bits in a plate record**

| Bit for pad 1 | Bit for pad 2 | Set when | Pad flag |
|---|---|---|---|
| 0 | 1 | Streaming, and the pad has no reply, or its last reply is more than 50 ms old | 0x01 NOT_ANSWERING |
| 4 | 5 | The last tare got fewer than 20 of its 40 replies | 0x02 TARE_FAILED |
| 8 | 9 | The latest tare did not fail, and the last successful tare had noise above 60 counts | 0x04 NOISY |
| 12 | 13 | The pad needs a tare after a restart and has not been tared since | 0x08 RESTARTED |
| 16 | 17 | Pad firmware 6 or later and bit 10 of its health word set, or a rate fault measured while the pad answers with queued samples (Section 8.4); and the pad answers | 0x20 CLOCK_FAULT |

Each group is four bits wide, but only the bits for pads 1 and 2 are ever set. No other bit is set in a plate record. The BOOTING flag (0x10) is not mapped into errorFlags, and neither is the PRESENT flag (0x80).

**Table 4.2 errorFlags in the general record (address 0)**

Bit 0 is set when any present pad of any plate has NOT_ANSWERING, TARE_FAILED, NOISY, RESTARTED or CLOCK_FAULT. BOOTING is not part of that test. No other bit is set. The general record has no plate or pad number, so bit 0 means "some pad has a problem" in the general record and "pad 1 is not answering" in a plate record.

Three rules follow from the code:

- NOT_ANSWERING is judged only while a stream runs. With no stream, the bit is never set, even for a pad that has never answered.
- A pad that is outside its plate's type has no flags at all.
- An older code comment describes only three of the five groups. The code sets all five.

## 5. batterySOC

Evidence: code and vector.

The battery byte is 255 in this firmware, which means "not measured".

- The only firmware assignment is its initialiser. The status builder reads it.
- A code comment says that the board revision has no battery sense input wired to the firmware.
- The struct comment gives the range 0 to 100 for a measured value. This firmware never produces such a value.
- A client that reads the battery should take it only from the general record of an 86-byte status reply. It should read 255 as "not measured" and any other value up to 100 as a percentage.

## 6. Status length variants

### 6.1 The three layouts in the sources

**Table 6.1 Layouts of the status record**

| Layout | Record length | Battery byte | CRC and end marker | Fields that differ from layout A | Evidence |
|---|---|---|---|---|---|
| A, controller 1.2.8.0 | 86 | Byte 81 | CRC 82-83, EOT 84-85 | None. This is Table 3.1 | vector |
| B, earlier reference firmware and a 2026-09-25 capture | 85 | None | CRC 81-82, EOT 83-84 | None. Bytes 0 to 80 have the same offsets as in A | vector |
| C, an 88-byte appendix described in protocol notes | 88 | Byte 83 | CRC 84-85, EOT 86-87 | SSID 29-60 (32 bytes); IP 61-64; mask 65-68; gateway 69-72; cacheFrames 73-76; factors 77-82 | code |

Layout C is not produced by any firmware or capture that the SDK knows. The controller struct is 86 bytes, the earlier reference struct is 85 bytes, and the phone client tables hold 86 and 85. Static analysis of one host application (Studio 0.24.0) says it expects 88 bytes.

### 6.2 What each decoder does

**Table 6.2 Decoder behaviour by status length**

| Decoder | 85-byte record | 86-byte record | 88-byte record |
|---|---|---|---|
| Earlier Python reference, stream parser | Accepted as soon as 85 bytes are buffered and the CRC at 81-82 is valid | Rejected. The 85-byte candidate fails, so the first byte is dropped as an invalid candidate. `status.json` in vectors/ records the reference parser as reject | Rejected in the same way |
| Earlier Python reference, frame decoder | Decoded as `status` | Not decoded. Any length other than 85 is `unknown` | Not decoded |
| Phone client, frame decoder | Decoded once 86 bytes are buffered and the 86-byte candidate is invalid. Until then the decoder waits | Decoded when its CRC and end marker are valid | Rejected. The 86-byte candidate fails the CRC, and one byte is dropped |
| Phone client, stream decoder | Held until 86 bytes are buffered or the stream ends, then decoded (Section 6.3) | Decoded when its CRC is valid | Rejected as an invalid candidate |
| Phone client, battery reader | Ignored | Read at byte 81, when byte 2 is 0 | Ignored |
| Phone client, pad health reader | errorFlags read at bytes 4 to 7, when byte 2 is 1 or 2 | Read in the same way | Ignored |
| One host application (static analysis) | Waits for three more bytes | Not expected | Expected |

A phone-client unit test builds both 86-byte and 85-byte records and checks that the stream decoder returns both replies between stream frames. That test was not run for this edition (open point 6).

### 6.3 The hold on an 85-byte record in the phone client's decoders

The phone client's decoders do not accept an 85-byte record at once. They wait for 86 bytes to be buffered, or for the stream to end, and then check the 85-byte candidate. In both decoders the hold ends with the next byte that arrives.

On a running stream the next byte starts the next stream frame, so the hold is short. On a link with no further data, an 85-byte record stays buffered until more bytes arrive or the session ends. The earlier Python reference parser has no such hold, because its expected length is 85.

### 6.4 The CRC position separates the layouts

The three layouts place the CRC at different offsets: 81-82 in B, 82-83 in A and 84-85 in C (Table 6.1). Each decoder above tests the candidate length whose end marker and CRC are in place.

The protocol notes state that a CRC does not select between two layouts that share a header and command when one of them has a CRC-valid prefix. They give a synthetic 88-byte example. No capture contains that case (open point 5).

### 6.5 The rule the SDK applies

The SDK accepts a GET_STATUS reply of 85 x k or 86 x k bytes, with k = 1 to 3 (Table 2.2), and rejects any other length. The total length gives the form and k.

Each record of the reply is checked on its own for header, command, end marker and CRC. The position rule is checked on the whole reply: the first record must be the general record (address 0), and any platform records must follow in increasing order with addresses 1 and 2 only. The rule holds for a reply of one record too, so a lone platform record is refused. The controller sends in this order.

The CRC is at bytes 81-82 in the 85-byte form and at bytes 82-83 in the 86-byte form. The earlier Python reference decoder rejects the 86-byte form (Table 6.2), and the phone client's decoders accept it.

The 85 x 1 form has a capture and two vectors. The 85 x 2 and 85 x 3 forms are accepted under this rule and are unverified (open point 15).

## 7. GET_PAD_HEALTH (0x27)

### 7.1 Record layout

Evidence: code. No vector covers the 120-byte reply.

**Table 7.1 GET_PAD_HEALTH record, 120 bytes**

| Bytes | Size | Field | Content |
|---|---|---|---|
| 0-1 | 2 | header | `BE EF` |
| 2 | 1 | platform_address | Request `pa`, echoed |
| 3 | 1 | commandCode | 0x27 |
| 4-99 | 96 | pad[2][2] | Four 24-byte entries, Table 7.2. The index is `[plate - 1][pad - 1]` |
| 100-103 | 4 | stale_frames[0] | Plate 1: frames sent while no pad of the plate had new data for the frame (Section 7.6) |
| 104-107 | 4 | stale_frames[1] | Plate 2: the same count |
| 108-111 | 4 | rs485_skipped_bytes | Bytes that the controller's pad-bus receive scan passed over without decoding a message |
| 112-113 | 2 | filter_cutoff_dhz | Filter cutoff in units of 0.1 Hz; 0 when the filter is off |
| 114-115 | 2 | filter_sps | Filter sample rate in samples per second |
| 116-117 | 2 | crc | CRC over bytes 2 to 115 |
| 118-119 | 2 | eot1, eot2 | `04 04` |

The size is fixed by a static assert in the firmware. The reply is written from a zeroed struct.

### 7.2 The four entries

**Table 7.2 `T_PadHealth` entry, 24 bytes.** Entry bases are 4 for pad [0][0], 28 for [0][1], 52 for [1][0] and 76 for [1][1].

| Offset in entry | Size | Field | Content |
|---|---|---|---|
| 0-3 | 4 | polls | Polls sent to the pad: GET_FRAME polls, and GET_SAMPLES requests while the pad answers with queued samples (Section 7.6) |
| 4-7 | 4 | replies | CRC-valid replies from the pad: frames, configs and GET_SAMPLES answers |
| 8-9 | 2 | ms_since_reply | Milliseconds since the last reply, saturating at 0xFFFE. 0xFFFF when the pad has never replied |
| 10-11 | 2 | tare_samples | Replies that the last tare averaged. Written by a failed tare as well |
| 12-13 | 2 | tare_noise_counts | Worst force-channel standard deviation of the last successful tare. A failed tare leaves the earlier value |
| 14 | 1 | flags | Pad flags, Table 7.3 |
| 15-18 | 4 | changed | Frame replies whose eight channels differ from the previous reply. For a pad on queued samples, each answer adds the number of new conversions it carries (Section 7.6) |
| 19-20 | 2 | cold_boots | Cold boots counted for the pad. Section 7.4 lists the sources |
| 21-22 | 2 | soft_resets | Soft resets the controller sent to the pad. Section 7.4 lists the sources |
| 23 | 1 | pad_fw | Pad firmware version field, Section 8 |

### 7.3 Pad flags

**Table 7.3 Pad flags (entry byte 14)**

| Value | Name | Set when |
|---|---|---|
| 0x01 | PAD_HEALTH_NOT_ANSWERING | Streaming, and the pad has no reply or its last reply is more than 50 ms old |
| 0x02 | PAD_HEALTH_TARE_FAILED | The last tare got fewer than 20 of its 40 replies |
| 0x04 | PAD_HEALTH_NOISY | The latest tare did not fail, and the last successful tare had noise above 60 counts |
| 0x08 | PAD_HEALTH_RESTARTED | The pad needs a tare. A cold boot, a lost link or a soft reset sets it, and a successful tare clears it |
| 0x10 | PAD_HEALTH_BOOTING | The pad is not in its running state, or a reset is pending |
| 0x20 | PAD_HEALTH_CLOCK_FAULT | Pad firmware 6 or later and bit 10 of channel 7 set, or a rate fault measured while the pad answers with queued samples (Section 8.4); and the pad answers |
| 0x80 | PAD_HEALTH_PRESENT | The plate type includes this pad number |

A pad outside its plate's type returns 0. The header describes 0x20 as an ADC clock fault for pad v2.3 and later. For pad v2.7, bit 10 also means held bursts in the last second. The controller also sets the flag from its own check of the conversion period of a pad on queued samples (Section 8.4).

### 7.4 Where the counters are incremented

Evidence: code. None of this was observed on hardware (open point 7).

`cold_boots` and `soft_resets` are the counters that a host most often needs to interpret, so their sources are listed here.

- `cold_boots` is incremented when a pad replies with all-zero channels while it runs, when a pad answers again after the link was lost, at the wake from the keep-alive sleep, by a 0x62 power-off, and when the pad firmware update code powers the pads on.
- `soft_resets` is incremented by the start-up broadcast reset, by the recovery of a cold-booted pad, by a 0x25 that names a pad, by a 0x62 mode 1 broadcast, and by a pad firmware update restart.

The header comment for `cold_boots` says the count covers restarts "the pad did on its own". The sources above include restarts that the controller causes itself.

### 7.5 Tests

No test is known to call the GET_PAD_HEALTH builder. The only size check is the static assert (open point 9).

### 7.6 Counters while a pad answers with queued samples

Evidence: code and simulation. Not run on hardware (open point 16).

While a stream runs, the controller asks a pad for its queued conversions with GET_SAMPLES instead of a single frame when the pad reports version 11 or higher, is running, has no reset pending and has a `missed_in_row` count below three. The pad-sample debug command 0x63 switches this off and on in RAM ([04-host-commands.md](04-host-commands.md) Table 3.5). The fields of an entry then count as follows.

- polls: each GET_SAMPLES request counts as a poll, as each stream GET_FRAME poll does. The same function keeps `missed_in_row`, the number of polls in a row without a reply. It counts a poll as missed only when the next poll of that pad is sent, so a pad that stops answering gets four GET_SAMPLES requests before the controller asks it with GET_FRAME.
- replies, ms_since_reply and NOT_ANSWERING: a CRC-valid GET_SAMPLES answer for a valid pad address and plate type counts as a reply, also when it carries no new conversion.
- changed: each answer adds the number of conversions in it that the controller had not received before. Conversions that the pad marked as repeated are included. The field then counts conversions, not replies with new readings. The count is expected to follow the nominal conversion rate of about 1,953 per second. This is not measured.
- pad_fw and CLOCK_FAULT: they come from the health word of the answer, which the pad fills with its channel-7 word. The rate check can add CLOCK_FAULT (Section 8.4).
- cold_boots: the controller does not look for all-zero readings in a GET_SAMPLES answer. A restarting pad stops answering GET_SAMPLES until its ADC runs, and the GET_FRAME polls after a few misses find its all-zero readings, which count a cold boot as before. The lost-link check that counts a cold boot also runs for a GET_SAMPLES answer. A pad is asked with GET_SAMPLES only while its `missed_in_row` count is below three, and a lost link takes five, so the first answer after a lost link is a frame reply, and that reply counts the cold boot. This is read from the code and has not been observed.
- stale_frames: a frame counts as stale when no pad of its plate had new data for it. For a pad on GET_FRAME polling, that means no reply with readings since the previous frame. For a pad on queued samples, it means that the resampler found no conversion near the frame's time. A frame value made from some of the conversions, because others were missing, does not count as stale. The counters are only ever incremented.
- rs485_skipped_bytes: the receive scan decodes a GET_SAMPLES answer by its own header, 0xBEE5, so its bytes are not counted as skipped.
- The queue and the resampler keep further counters for each pad: conversions received, lost and repeated, time-base restarts, and frame values made from all, some or none of the conversions they need. No reply in this chapter carries them.

Host tests check the poll count of a GET_SAMPLES request, the reply and changed counts, `pad_fw` 11 from the answer's health word, and the rate fault in `clock_fault`. No test builds a GET_PAD_HEALTH or GET_STATUS reply from these counters (open point 9).

## 8. The pad health word and pad_fw

### 8.1 What the pad puts in channel 7

Evidence: code.

The pad builds channel 7 as a 16-bit word with these fields:

- bits 15 to 12: the pad firmware version;
- bit 11: set when the ADC is not configured;
- bit 10: signal fault;
- bits 9 and 8: ADC re-initialisations, two bits;
- bits 7 to 0: dropped ADC frames, impulses and held bursts, as a wrapping count.

The version value of this firmware is 11. The pad application image header also carries the string "2.8.0.0". The 4-bit channel-7 value is a separate field. Pad application 2.8.0.0 raised it from 10 to 11. None of the replies in this chapter (0x22, 0x23 or 0x27) carries the string (open point 14).

**Table 8.1 Version values named in the pad firmware header**

| Field value | Name in the header |
|---|---|
| 2 | v2 |
| 4 | v2.1 |
| 5 | v2.2 |
| 6 | v2.3 |
| 7 | v2.4 |
| 8 | v2.5 |
| 9 | v2.6 |
| 10 | v2.7 |
| 11 | v2.8 (GET_SAMPLES) |
| 3, 12 to 14 | Not named (open point 8) |

### 8.2 What the host keeps

Evidence: code.

The controller passes the health word of each reply to a health routine. For a frame reply the word is channel 7. For a GET_SAMPLES answer it is the answer's health field, which the pad fills with its channel-7 word.

The routine takes the version nibble and keeps it only when it is 2 to 14. Otherwise `pad_fw` is 0. It sets CLOCK_FAULT when `pad_fw` is 6 or higher and bit 10 is set.

A code comment says that older pad firmware has a sensor reading in channel 7, and that a reading starting with 0xF is a small negative value, not a version. A value such as 0xFFFE gives the nibble 15, which the controller rejects. The 1.2.6.5 firmware applied this rule to frame replies only.

The raw health word is not sent to the host. A host sees only `pad_fw` (byte 23 of each entry) and the CLOCK_FAULT flag.

### 8.3 Test words

Evidence: code (host test, simulated).

A host test checks four words. 0x6400 gives `pad_fw` 6 with CLOCK_FAULT. 0x2000 gives `pad_fw` 2 without it. 0xA400 gives `pad_fw` 10 with it. 0xFFFE gives `pad_fw` 0 without it. A GET_SAMPLES answer with the health word 0xB005 gives `pad_fw` 11.

### 8.4 Version 11 and the rate check

Evidence: code and simulation. Not run on hardware.

- `pad_fw` also selects how the pad is polled. A pad with `pad_fw` 11 or higher is asked for queued samples while it runs normally, so byte 23 of a GET_PAD_HEALTH entry tells a host which pads can use them (Section 7.6). A pad that leaves four requests in a row without an answer is asked with GET_FRAME again, because a miss is counted only when the next request is sent.
- While a pad answers with queued samples, the controller measures the period of its conversions over windows of 1 s. From the third window on, it sets `rate_fault` when the measured period differs from the nominal one by more than 300 ppm, and clears it otherwise. The nominal period is 2048 ADC clocks, 512 us at the default ADC clock of 4 MHz.
- Each answer sets `clock_fault` from its health word and then also when `rate_fault` is set. The flag reaches errorFlags bits 16 and 17 and GET_PAD_HEALTH flag 0x20 in the usual way (Table 4.1, Table 7.3). A frame reply from the same pad sets it from the health word alone again. The header comments still describe the flag as a fault that the pad's ADC detects.
- Simulated pads from 2,000 ppm fast to 500 ppm slow set `rate_fault` exactly when the offset is above 300 ppm. This has not been run on hardware (open point 16).

## 9. Version reply (GET_FW_VERSION, 0x23)

### 9.1 Controller 1.2.8.0

**Table 9.1 GET_FW_VERSION reply, 38 bytes**

| Bytes | Field | Content | Evidence |
|---|---|---|---|
| 0-1 | header | `BE EF` | vector |
| 2 | platform_address | Request `pa`, echoed | vector |
| 3 | commandCode | 0x23 | vector |
| 4-18 | stm32FW | The controller version text "1.2.8.0", NUL-terminated | code |
| 19-33 | esp32FW | "000.000.000", the placeholder. The code says the controller cannot see the bridge version | code |
| 34-35 | crc | CRC over bytes 2 to 33 | vector |
| 36-37 | eot1, eot2 | `04 04` | vector |

The release build sends "1.2.8.0", and the host test checks that text on the UART4 path. The synthetic build sends "1.2.8.0-SYN". No capture of a 1.2.8.0 reply exists, because that image has not been run on hardware (open point 16). The longest text the 15-byte field can hold is 14 characters, because the last byte is forced to NUL.

### 9.2 Version constants

**Table 9.2 Version constants and their use**

| Constant | Value | Use |
|---|---|---|
| Application version number | 1.2.8.0, which is 0x01020800 | Image header number and the running version for OTA |
| Application version text | "1.2.8.0", or "1.2.8.0-SYN" in the synthetic build | GET_FW_VERSION stm32FW field, and the image header string |
| Release string | "Movetrics Discovery 001.002.003 + UART4 + OTA 1.2.8.0" | Not used. The only occurrence is the definition |
| Unknown bridge version | "000.000.000" | GET_FW_VERSION esp32FW field |
| Bootloader version | 1.0.0.3, which is 0x01000003 | Returned as the bootloader's running version and written to the hand-off record. Its 0x23 reply uses the literal in Table 9.3 |

The release string contains "001.002.003", which a 2026-09-25 capture sends as its stm32FW value (Section 11). The 1.2.8.0 firmware does not send that string (Section 14).

### 9.3 Bootloader reply

**Table 9.3 Bootloader reply to 0x23, 38 bytes**

| Bytes | Content |
|---|---|
| 0-1 | `BE EF` |
| 2 | `pa` 0, always. The application echoes the request `pa` instead |
| 3 | 0x23 |
| 4-15 | "BOOT-1.0.0.3", 12 characters. The rest of the 15-byte field is zero |
| 19-29 | "000.000.000", 11 characters. The rest of the field is zero |
| 34-35 | CRC over bytes 2 to 33 |
| 36-37 | `04 04` |

The bootloader answers 0x23 when the frame's CRC is valid. For commands other than 0x23 and 0x40 it sends no reply, and 0x40 goes to the firmware-update handler. The literal is not generated from the bootloader version constant. Both name 1.0.0.3, and a comment above the literal still names 1.0.0.1. No capture of the BOOT-1.0.0.3 reply is known.

### 9.4 Reading the field

A client should find a 38-byte reply that starts with `BE EF 00 23`, check its CRC over bytes 2 to 33, and return the 15-byte STM32 field up to the first NUL. It should accept the bootloader's "BOOT-" text as a version too. The earlier Python reference decodes both fields as text and marks the reply as hard-coded in its reference firmware.

## 10. Serial reply (GET_SERIAL_NUMBER, 0x24)

**Table 10.1 GET_SERIAL_NUMBER reply, 28 bytes**

| Bytes | Field | Content | Evidence |
|---|---|---|---|
| 0-1 | header | `BE EF` | code |
| 2 | platform_address | Request `pa`, echoed | code |
| 3 | commandCode | 0x24 | code |
| 4-23 | serialID | 19 characters and a NUL, in a 20-byte field | code |
| 24-25 | crc | CRC over bytes 2 to 23 | code |
| 26-27 | eot1, eot2 | `04 04` | code |

The serial ID is built from the STM32 unique device ID. The controller reads 12 bytes at 0x1FFF7A10, encodes them as base64, keeps the first 16 characters, and then writes "000" and the NUL. The 16 characters of a 12-byte input need no base64 padding. A 2026-09-25 capture returns an ID of this form, ending in `000` (measured).

No test is known to check the length or the content of the 0x24 reply (open point 11).

## 11. The identification sequence of 2026-09-25

Evidence: measured, on a capture from an earlier controller image that is not identified. The capture is not included in vectors/ and is the source of the anchors in `status.json` and `ota_frames.json`.

The capture holds six identification queries. The six replies total 194 bytes.

**Table 11.1 The six queries and their replies**

| # | Query | Code | Reply bytes | Reply checks, recomputed | SDK |
|---|---|---|---|---|---|
| 1 | GET_SAMPLING_RATE | 0x08 | 10 | CRC and end marker valid. Raw value 2048 | Not exposed ([04-host-commands.md](04-host-commands.md) Table 3.2) |
| 2 | GET_CHANNEL_MASK | 0x13 | 9 | CRC and end marker valid. Mask 0xFF | Not exposed |
| 3 | GET_CURRENT_CONFIG | 0x1A | 24 | CRC and end marker valid. Plate types 2 and 2 | Not exposed |
| 4 | GET_STATUS | 0x22 | 85 | CRC and end marker valid at the 85-byte positions, 81-82 and 83-84. Placeholder fields (Section 6, layout B) | Exposed (implemented) |
| 5 | GET_FW_VERSION | 0x23 | 38 | CRC and end marker valid. Text "001.002.003" and "002.005.001" | Exposed (implemented) |
| 6 | GET_SERIAL_NUMBER | 0x24 | 28 | CRC and end marker valid | Not exposed |

The version text of reply 5 is the text that an earlier reference firmware hard-codes. The 1.2.8.0 firmware cannot produce it, because its stm32FW field is its own version text. The status in reply 4 carries the placeholders "123" (serial parameters and SSID) and 1.2.3.4 (IP, mask and gateway), which 1.2.8.0 no longer sends. Its calibration factors at bytes 75 to 80 are zero. The image that produced this capture is not identified (open point 2).

The SDK exposes 0x22 and 0x23 from this sequence. The 0x27 reply is specified in Section 7 but is not in this sequence and has no vector, so the SDK does not expose it.

## 12. Checks made for this chapter

- The identification capture was parsed again. It holds six replies, 194 bytes in total. The CRC and end-marker checks pass at the lengths in Table 11.1.
- The derived records in Table 3.2 were computed with the CRC routine. The routine returns 0x29B1 for the ASCII string `123456789`, the published check value of CRC-16/CCITT-FALSE, and 0xFFFF for an empty input, which follows from the initial value. The derived records are not captures.
- The earlier Python reference decoders were run over the six cases in `status.json` (see [15-conformance-and-testing.md](15-conformance-and-testing.md)). The stream parser returned one status message for each 85-byte case and none for the 86-byte cases or the three-record case, with one invalid candidate for each 86-byte record. The frame decoder returned `status` for the 85-byte cases and `unknown` for the 86-byte cases. On each 86-byte record, the frame check passes at 86 bytes and fails on the first 85.
- The reply layouts of 1.2.8.0 were compared with those of 1.2.6.5, and none of the files that build them changed. The pad bookkeeping, the stale-frame count, the pad version and the version constants were read again for 1.2.8.0 (Sections 7.6, 8 and 9).

## 13. Open points

All of these are unverified on hardware unless stated.

1. No capture of controller 1.2.8.0 exists, and that image has not been run on hardware (point 16). The 86-byte layout, the record count, the errorFlags bits and the 120-byte health reply are verified by code and by static asserts only. `status.json` covers the 86-byte form at k = 1 and k = 3, and no vector or capture has k = 2 (172 bytes).
2. The image that produced the 2026-09-25 capture is not identified. Its status is 85 bytes, and its version text is "001.002.003" and "002.005.001". Neither identifies 1.2.8.0.
3. The per-build history of the status layout and the version label is not settled. A phone-client bench log labels a device `1.1-UART4-b3` and summarises three 86-byte records. An earlier report says that build sends 85 bytes. The two disagree.
4. Layout C (88 bytes) is in protocol notes and in static analysis of one host application. No firmware or capture produces it.
5. The CRC-valid prefix case in the protocol notes is synthetic. The rate at which an 85-byte record and an 86-byte candidate are confused in a real stream was not measured.
6. The phone-client unit test of the 85-byte hold was not run for this edition.
7. The increments of `cold_boots` and `soft_resets` (Section 7.4) are code paths only. Their values after a real power cycle, a keep-alive sleep or a pad restart were not observed.
8. Pad version values 3 and 12 to 14 are not named in the pad header. The controller keeps any value from 2 to 14. No known pad source sets a value other than 11.
9. No test sends or checks GET_PAD_HEALTH. Reference decoders find a 0x27 reply only by a generic CRC search, and one phone-client frame decoder discards it. No run covers any of these paths.
10. Two-plate GET_STATUS replies (258 bytes, Table 2.2) are not covered by a firmware test.
11. No test checks the length or the content of the 0x24 reply.
12. The range 0 to 100 for a measured battery value is found only in a struct comment and in a phone client. The firmware never produces such a value.
13. The phone client's pad health view was not observed for this edition.
14. The pad image header string "2.8.0.0" is said to be read by the pad bootloader and the controller. This was not traced, and no controller source names the constant.
15. The legacy 85-byte form with k = 2 or 3 (170 and 255 bytes). No known firmware sends more than one 85-byte record in a reply. The earlier reference firmware sends one 85-byte record per request. No vector and no capture has these lengths.
16. Controller application 1.2.8.0 and pad application 2.8.0.0 have not been run on hardware. The bookkeeping for a pad on queued samples (Section 7.6), `pad_fw` 11 and the rate check that sets CLOCK_FAULT (Section 8.4), the stale-frame count from the resampler, and the version text "1.2.8.0" are known from the code and from host tests only. No capture holds a GET_STATUS, GET_PAD_HEALTH or GET_FW_VERSION reply of that image.

## 14. Known inconsistencies

- An older code comment above the errorFlags loop lists three groups: bits 0-1, 4-5 and 8-9. The code sets five groups, which adds RESTARTED at bits 12-13 and CLOCK_FAULT at bits 16-17. Table 4.1 follows the code.
- Layout names. Some code calls the 86-byte record "v26" and some calls it "v25". A phone client names the 85-byte length `STATUS_LENGTH_V24` and the 86-byte length `STATUS_LENGTH_V25`. This chapter names layouts by length and does not use "v25" or "v26".
- The bootloader comment says "BOOT 1.0.0.1". The literal it sends is "BOOT-1.0.0.3".
- The field comment says `cold_boots` counts "restarts the pad did on its own (power loss, replug)". The code also counts restarts the controller causes: the keep-alive sleep wake, the 0x62 power-off and the pad firmware update power-on (Section 7.4).
- The header comment describes the 0x20 flag as an ADC clock fault for pad v2.3 and later. The pad source calls bit 10 a signal fault, which is a clock fault in v2.3 to v2.5 and "clock fault or held bursts" in v2.7. Table 7.3 gives both meanings.
- The struct comment gives batterySOC the values "0..100 %". The only assignment sets 255, which the code calls "not measured".
- The comment on `pad_fw` says 0 means "before v2". The controller also sets 0 for every version value outside 2 to 14.
- The release string reads "Movetrics Discovery 001.002.003 + UART4 + OTA 1.2.8.0". It is not used. The GET_FW_VERSION reply sends "1.2.8.0". An earlier reference firmware sends "001.002.003".
- Comments on the GET_PAD_HEALTH counters describe GET_FRAME polling only. For a pad on queued samples, GET_SAMPLES requests count as polls, answers count as replies, `changed` adds the new conversions of each answer, and a frame of a plate whose pads are on queued samples is stale only when the resampler finds no conversion near its time for any of them. Table 7.2 and Section 7.6 follow the code.
- The comments describe CLOCK_FAULT as a fault that the pad's ADC sees, for pad v2.3 and later. The controller also sets it when the conversion period it measures for a pad on queued samples is more than 300 ppm from nominal.
