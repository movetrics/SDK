# 02. Transports: how a host reaches the controller

Public edition of the SDK specification. Statements are marked code (read in the firmware), measured (seen on a device) or vector (covered by the test vectors).

This chapter describes controller firmware 1.2.8.0 and bridge firmware 1.3.1.0. The controller's host port code is the same as in 1.2.6.5. Firmware 1.2.8.0 has not been run on hardware. Everything below that concerns it is code, not measured. Facts that no source shows are marked unverified.

Every host reaches the controller over one of two byte pipes. Both run at 1,500,000 baud by default, 8N1, with no flow control (code).

- USB: the FTDI FT232R on the controller's USART3.
- Bluetooth LE: the ESP32-S3 bridge on the controller's UART4.

The controller treats the two ports alike, with two exceptions a client must know. First, a reply and the stream go to the port of the last accepted command. Second, SET_SERIAL_PARAM does not check its source port.

The bridge is a transparent byte relay. It forwards bytes only while one phone is subscribed to its notify characteristic. At other times it discards controller output.

A phone client that is known to work uses the connect sequence in section 2.6. Use it as the reference for a new BLE client. Browser transports are unverified (section 2.11).

The frame layout is in [03-host-link-framing.md](03-host-link-framing.md) and is not repeated here.

## 2.1 The transports at a glance

| Transport | Path to the controller | Host settings | Controller port | Status | Evidence |
|---|---|---|---|---|---|
| USB | USB-C, FTDI FT232R (VID 0x0403, PID 0x6001) | 1,500,000 baud by default, 8N1, no flow control | USART3 | Works on Windows (reported). A phone client implements it. macOS and Linux have no record (section 2.10). | code |
| BLE | Phone over BLE to the ESP32-S3 bridge, advertised as `Movetrics-BLE`, then UART4 | Nordic UART service; bridge side 1,500,000 baud, 8N1; commands written with response | UART4 | Implemented in a phone client. The acceptance record names older builds. | code |
| Browser | Web Serial (USB) or Web Bluetooth (BLE) | Not known | Same ports | Unverified (section 2.11). | code |

## 2.2 The controller's two host ports

Evidence: code.

Both host ports are set up once, at start-up. Both use 8 data bits, one stop bit, no parity and no hardware flow control.

USART3 takes its rate from a RAM value, the USB baud rate. The value starts at 1,500,000. At boot it is replaced by the saved value when a save exists. UART4 always uses 1,500,000.

SET_SERIAL_PARAM (0x31) with destination 0 sets only that RAM value. It does not reconfigure USART3. USART3 is set up once at start-up, so the running rate changes only at the next boot.

Any flash write of the configuration stores the current RAM value. Two commands make that write:

- 0x19 (SAVE_CALIBRATION) saves without a restart.
- 0x25 (CONTROLLER_RESET) with destination 0 saves and then restarts the controller.

Every later boot uses the saved value. No selector restores 1,500,000. The rate table has six entries: 115,200, 230,400, 460,800, 1,000,000, 2,000,000 and 4,000,000. None of them is 1,500,000.

A power cycle discards a value that no flash write has stored. A later save of any kind stores it. An earlier rate change then becomes permanent at that save.

A client that opens USB at a fixed 1,500,000 baud cannot reach the controller once a different USB rate is saved. No command restores 1,500,000, and no recovery procedure is known (unverified). BLE is not affected, because UART4 always uses the default rate.

GET_STATUS puts the rate in its serial string as `<rate>,8,n,1`. On UART4 that string always carries 1,500,000. On USART3 it carries the RAM value. That value can differ from the running rate until the next boot. A client must not take the USB rate from this string alone.

## 2.3 Which port a reply and the stream use

Evidence: code, and the controller's own transport test (vector-level behaviour, simulated).

The controller takes the oldest queued command, records the port it arrived on, and parses it. If the command is not accepted, the previous port is restored. A bad command therefore gets its NACK on its own port and leaves the stream where it was.

The transport test checks this. A bad CRC on the USB port is NACKed on USB while the stream stays on BLE. A truncated KEEP_ALIVE is handled the same way.

An accepted command moves the stream and all replies to its own port. Every transmit uses the active port at the moment it is queued. The stream follows whichever port sent the last accepted command, until the next one arrives.

Two clients on the two ports share one stream. The client that sent the most recent accepted command receives the samples and the replies. A client must not hold a second link open while another one streams.

SET_SERIAL_PARAM has no source-port check. A command from UART4 can therefore set the USB rate, under the save and boot rules in section 2.2.

## 2.4 USB: the FTDI port and a working open sequence

Evidence: code (a phone client). The steps below are a recipe that is known to work in that client. They are not a requirement of the controller.

1. Accept the device only if its VID is 0x0403 and its PID is 0x6001.
2. Open the device through the platform's USB manager. Fail if no connection is returned.
3. Open the FTDI port so that DTR and RTS are left alone. The stock open of the common FTDI library toggles them. Claim interface 0. Require at least two endpoints. Read from endpoint 0 and write to endpoint 1. Send one vendor control transfer for the FTDI reset. The claim that the stock open toggles DTR and RTS comes from a code comment and is unverified.
4. Set 1,500,000 baud, 8 data bits, one stop bit, no parity, then no flow control. If any step fails, close the port and raise the error again.
5. Reads need a buffer of at least 16,384 bytes and a timeout of 1 to 1,000 ms. Writes time out after 1,200 ms.

A minimal client needs only five request frames: KEEP_ALIVE with 600 s, START, STOP, GET_STATUS and a broadcast SET_TARE (0x1B). [03-host-link-framing.md](03-host-link-framing.md) gives their bytes.

## 2.5 BLE: the bridge

Evidence: code.

The bridge is an ESP32-S3 running NimBLE. It relays bytes between one BLE client and UART4 without changing them.

| Item | UUID or value | Properties | Evidence |
|---|---|---|---|
| Service (advertised) | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | advertised with the device name | code |
| RX, commands to the controller | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | write with response | code |
| TX, controller output to the phone | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | notify | code |
| Status, read-only text | `52e528e4-f391-4f88-a43a-3d911f82e040` | read, up to 244 bytes | code |
| Device name | `Movetrics-BLE` | | code |

The bridge's behaviour:

- One client. A second connection is refused at once.
- The bridge asks the phone for a short connection interval, latency 0 and a longer supervision timeout. It also asks for a 251-byte data length and a 2M PHY. The phone decides.
- Commands are accepted only after the phone subscribes to TX. A write before that sets fault 1 and is discarded.
- Removing the subscription during a session also sets fault 1.
- Once a fault is set, further writes are refused. The bridge disconnects the phone and retries every 500 ms. A new connection clears the fault.
- Controller output is forwarded only while a phone is connected, subscribed and fault-free. Any other bytes are counted as discarded. The bridge flushes its UART input when a session starts.
- Command bytes leave the command ring only as far as the UART accepts them.
- A notification carries at most the MTU minus 3 bytes and at most 244 bytes. It is sent when a full packet is waiting, or 3 ms after the last send.
- Buffers: 4,096 bytes of commands, 32,768 bytes to the phone, and a 16,384-byte UART receive buffer.
- Notifications wait while NimBLE's buffer pool is nearly empty, so that incoming writes such as STOP can still be accepted.
- When a session that sent commands ends, the bridge writes the STOP frame to the controller. A phone that only connected does not stop a stream started over USB. Whether this STOP stops the stream on hardware has not been run (unverified).

The bridge sets these fault codes:

| Code | Name | Set when | Evidence |
|---|---|---|---|
| 1 | NOT_SUBSCRIBED | a write arrives before subscription, or the subscription ends during a session | code |
| 2 | COMMAND_OVERFLOW | the command ring is full, or an OTA write does not fit | code |
| 3 | DATA_OVERFLOW | the 32,768-byte buffer to the phone is full | code |
| 4 | UART_RX_ERROR | the UART reports a receive error during a session | code |
| 5 | BLE_STALLED | a notification is refused for 2,000 ms | code |
| 6 | NOTIFICATION_ERROR | the BLE stack reports a notify error other than a queue-full code | code |

The status line lists v, fw, mode, sub, mtu, lastFault, the byte counters, ota and trial. A client should keep the raw line. The reference phone client reads `mode=UART` from it and does not decode the fault codes.

## 2.6 BLE: a working connect sequence

Evidence: code (a phone client that is known to work).

1. Resolve the device address on the phone's Bluetooth adapter. Start a handler thread for the link.
2. Connect with autoConnect off, transport LE and the 1M PHY mask. Wait up to 20 s for the link to be ready. A timeout or failure closes the transport.
3. On a successful connection, request an MTU of 247.
4. On the MTU callback, request high connection priority and the 2M PHY, record the link parameters, and start service discovery. These are requests. The phone may refuse them. Keep the outcome.
5. Service discovery must find the RX, TX and status characteristics. If one is missing, the device is not a Movetrics bridge. Fail.
6. Enable notifications on TX and write the client characteristic configuration descriptor with the notify value.
7. When the descriptor write succeeds, mark the link as subscribed and read the status characteristic.
8. The status line must contain `mode=UART`, or the connection fails. Do not check the version string. An older bridge build reports `v=1.0`.
9. Release the ready signal. Refuse commands until the link is subscribed.

## 2.7 BLE: writes, retries and reads on the phone

Evidence: code (a phone client that is known to work).

- Send commands as write-with-response to the RX characteristic, one at a time under a lock.
- Each write waits up to 2,000 ms for the write callback.
- Never retry START. Retry STOP and KEEP_ALIVE, every 100 ms for up to 3,000 ms, when the bridge rejects the write or the stack reports it busy. The reason is the bridge's full notification queue.
- Hazard: the reference client retries every command except START, so it also retries GET_STATUS and a broadcast SET_TARE, and it retries a write whose callback does not arrive within 2,000 ms. A tare can then run twice if the first write was delivered. A new client should retry only STOP and KEEP_ALIVE. This has not been run on hardware.
- Queue notifications in a 2,048-chunk queue. A full queue fails the link with "receive queue overflow". It must not drop data silently.
- A read returns zero bytes on timeout. It reports end of stream once the transport has failed or been closed.
- Read boundaries are whatever the notifications give. The frame decoder joins them. The decoded content is the same as over USB.
- Closing disconnects, closes the GATT handle and stops the thread.

## 2.8 The controller's transmit path, and what a host can see

Evidence: code.

- Each host port has its own transmit ring of 4,096 bytes. DMA drains the rings, at most 1,024 bytes per transfer. At 1.5 Mbaud, 4,096 bytes take about 27 ms to drain.
- A stream frame is dropped at once when its ring is full. A reply waits up to 50 ms for room and is dropped after that.
- The controller counts these drops, but no command reports them. They can be seen only with a debugger. The same holds for the queue overflow counter. A host sees a lost stream frame only as a gap in the frame timestamps.
- A DMA transfer error frees the transmitter by dropping the failed run.
- Each port has its own RX assembler and its own DMA cursor. Commands from either port go into one 16-slot queue and are parsed in the main loop. A command that finds the queue full is dropped and counted.

## 2.9 Throughput: measured figures

Evidence: measured, on other firmware.

One BLE result is recorded. A Mac as central carried about 15 kB/s of a 25 kB/s stream. The bridge's 32 KB buffer filled and discarded data. An Android phone carried the same stream with no loss: 85,453 frames per plate in 171 s. That is about 500 frames per second per plate. Two plates at 24 bytes per frame give about 24 kB/s, close to the 25 kB/s of the record.

No test has measured BLE throughput on firmware 1.2.8.0. Treat the figures as a record, not a guarantee (unverified).

## 2.10 Platform notes

| Platform | What is known | Status | Evidence |
|---|---|---|---|
| Windows | A connection at 1,500,000 baud, 8N1, no flow control is reported to work with the earlier Python reference package. That package lists FTDI candidates by VID 0x0403 without opening them. VID alone is not proof of an FDT. | Reported. The SDK's own Python client has not been recorded on Windows. | measured |
| macOS | USB operation was untested in the earlier investigation. A bench run of firmware 1.2.6.6 over USB from a Mac is recorded. A successful open alone is not a throughput test. | USB unverified for 1.2.8.0. | measured |
| Linux | No code and no record. | Unverified. | code |
| Android USB | Implemented (section 2.4). | Implemented in a phone client. | code |
| Android BLE | Implemented (sections 2.6 and 2.7). | Implemented in a phone client. The acceptance record names older builds. | code |

## 2.11 Browser transports (unverified)

Nothing in the SDK uses Web Serial or Web Bluetooth. Before any browser client is written, these points need a bench test. All of them are unverified:

- Whether the browser's serial API opens an FT232R at 1,500,000 baud.
- Whether browser notification delivery keeps the bridge's ordering and its 244-byte packets.
- Whether a page can run while a phone client is connected. The bridge accepts one client, so it cannot.
- Which user-gesture and secure-origin rules apply to the device picker. These are general browser rules.

## Open points

All of these are unverified.

- Browser APIs: support, baud rates, the device picker and origin rules (section 2.11).
- Linux, over USB or BLE (section 2.10).
- macOS over USB (section 2.10).
- Whether the phone clients' BLE and USB acceptance hold on controller 1.2.8.0 and bridge 1.3.1.0. The acceptance records name controller build `1.1-UART4-b3` and bridge v1.2. Controller 1.2.8.0 has not been run on hardware. Its host port code is the same as in 1.2.6.5.
- The DTR and RTS behaviour of the stock FTDI open. The claim comes from a code comment.
- BLE throughput on 1.2.8.0 (section 2.9).
- The link the phone actually gets: connection interval, PHY and priority. The requests are in section 2.6. The outcome is visible only on the phone.
- Whether STOP sent on session end stops the stream on hardware (section 2.5).

## Known inconsistencies

- The rate table has no 1,500,000 entry, but 1,500,000 is the default. Section 2.2 explains why no selector restores it.
- Reports about Mac use disagree: one record calls USB on a Mac untested, another records a bench run from a Mac (section 2.10).
