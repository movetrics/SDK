# 00. Overview

Public edition of the SDK specification. Statements are marked code (read in the firmware), measured (seen on a device) or vector (covered by the test vectors).

## What the SDK is

The Movetrics SDK lets you talk to a Movetrics Force Data Terminal (FDT) from your own software. It is released under the Apache-2.0 licence. It contains:

- the protocol specification, in these chapters;
- byte test vectors that any client can run offline ([../vectors/](../vectors/));
- reference clients in Python ([../python/](../python/)), TypeScript ([../ts/](../ts/)) and MATLAB ([../matlab/](../matlab/));
- a simulator, a virtual FDT that speaks the real host protocol ([20-simulator.md](20-simulator.md));
- file writers for CSV, C3D and OpenSim ([21-writing-files.md](21-writing-files.md));
- Lab Streaming Layer (LSL) and sync helpers ([22-lsl-and-sync.md](22-lsl-and-sync.md)).

## The hardware in a few lines

- The FDT controller gathers the measurements of one or two F1-3D force plates. Each plate is 35 x 60 cm.
- It streams one 24-byte frame per plate and per sample. Each frame holds three forces, three moments and a 32-bit time stamp. The default rate is 1,000 frames per second per plate from firmware 1.2.8.8 (500 before); a host can set 50 to 2,000.
- USB: a USB-C cable to an FTDI FT232R, at 1,500,000 baud, 8 data bits, no parity, one stop bit (8N1), no flow control.
- Bluetooth LE: a bridge on the controller relays the same bytes over a Nordic UART service.

Both links carry the same frames. [02-transports.md](02-transports.md) has the details.

## Where to start

1. Read [../README.md](../README.md) for installation and the quick start.
2. Read [19-vocabulary-and-units.md](19-vocabulary-and-units.md) for the names, units and frames that every client shares.
3. Read [20-simulator.md](20-simulator.md) to build and test a client without hardware.
4. Read chapters 03 to 06 when you need the exact bytes.

## Chapters in this repository

| Chapter | Content |
|---|---|
| [00-overview.md](00-overview.md) | This page |
| [02-transports.md](02-transports.md) | USB and Bluetooth LE: ports, bridge, connect sequence, platform notes |
| [03-host-link-framing.md](03-host-link-framing.md) | Request, reply and stream frames, CRC, the `04 04` end marker, error codes |
| [04-host-commands.md](04-host-commands.md) | Every command code, its payload, reply, effect and hazards |
| [05-measurement-stream.md](05-measurement-stream.md) | The 24-byte stream frame, rate, pacing, time stamps, placeholders |
| [06-status-health-versions.md](06-status-health-versions.md) | Status, pad health, version and serial replies |
| [15-conformance-and-testing.md](15-conformance-and-testing.md) | Conformance levels, test vectors, what to run |
| [18-export-formats.md](18-export-formats.md) | The files and streams a Movetrics system produces |
| [19-vocabulary-and-units.md](19-vocabulary-and-units.md) | Shared names, units and frames |
| [20-simulator.md](20-simulator.md) | The virtual FDT |
| [21-writing-files.md](21-writing-files.md) | Writing CSV, C3D and OpenSim files |
| [22-lsl-and-sync.md](22-lsl-and-sync.md) | LSL and sync pulses |
| [23-analog-outputs.md](23-analog-outputs.md) | The analog outputs |

Other parts of the system, such as the controller's internal pad bus, the pad and controller firmware update, and the flash and calibration procedures, are not part of the host protocol. This repository does not document them.

## The honesty rule

Every statement says where it comes from:

- **code**: read in the firmware source;
- **measured**: seen on a device, in a capture or on a bench;
- **vector**: covered by the test vectors in [../vectors/](../vectors/);
- **simulated**: produced by a host test or by the simulator, not by a device.

Anything without a source is marked unverified. The specification describes controller firmware 1.2.8.0, which was checked by reading its code and by simulation tests. It has not been run on hardware. Conformance results are in [../CONFORMANCE.md](../CONFORMANCE.md). Every row there was run on simulated and recorded bytes, and none against a real controller.

Do not send commands marked "do not send" in [04-host-commands.md](04-host-commands.md). They erase flash, reset the controller or start a firmware update.
