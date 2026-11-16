---
title: Work with NOKOV XINGYING
description: An FDT file for every XINGYING take, XINGYING started from your program, and the FDT's analog outputs as a XINGYING force plate.
---

Three ways to use the FDT next to NOKOV's XINGYING motion capture software. Written from XINGYING's manual (4.7, English and Chinese) and run with the SDK's simulator; **none has run with XINGYING yet**. [Full details, status and limits](../../reference/24-nokov/).

## An FDT file for every take

Switch on Remote Trigger in XINGYING (data broadcast panel, section Capture-Trigger, port 7061). On the computer with the FDT:

```sh
pip install "movetrics-fdt[serial] @ git+https://github.com/movetrics/sdk#subdirectory=python"
movetrics-fdt nokov-record --serial COM3 --rate 2000 --out D:\fdt-takes
```

Each time XINGYING records, you get `<take>.csv` (or `.c3d` with `--format c3d`) named like XINGYING's take, plus `<take>.nokov.json` with the trigger messages and the cut times. The cut is made in FDT time and aligns takes, not samples. Add `--lsl` to publish the FDT on Lab Streaming Layer at the same time, with each trigger as a marker.

## Start and stop XINGYING from your program

Switch on Remote Control (section Capture-Remote, port 7060), then:

```sh
movetrics-fdt nokov-control start --host 192.168.1.20 --name jump01 --database-path "D:\NOKOV\project"
movetrics-fdt nokov-control stop --host 192.168.1.20 --name jump01
```

## The plates inside XINGYING

An FDT with the analog board can feed XINGYING through an NI USB-6218 or USB-6225, so the plates show in XINGYING's 3D view and C3D export. This prints the wiring, the calibration matrix to type in and the known-load check to run before use:

```sh
movetrics-fdt nokov-analog-setup --firmware 1.2.8.22
```

The values follow from the FDT's analog scale; how XINGYING expects some of them (plate type, moment unit, axes) is not settled by its manual, which is why the check comes first. With digital EMG inside XINGYING (Noraxon over its SDK, for example), XINGYING does not accept analog plates: use the take files or [LSL](../emg-and-cameras/) instead.
