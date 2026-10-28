---
title: The SDK in two minutes
description: What the Movetrics SDK is, why it is open, and what a team can do with it on day one. No technical background needed.
---

A Movetrics force plate measures how a person pushes on the ground. Up to 2,000 times a second, each plate reports the force in three directions and the twisting moments around three axes; from those, the SDK computes the centre of pressure, the point under the feet where the push is centred. The FDT is the small box the plates plug into. It sends the stream to a computer or a phone over USB or Bluetooth, and recordings made with Movetrics Studio or the Movetrics app can be uploaded to the Movetrics Cloud.

**The SDK is the free, open toolkit that gets this data into whatever a clinic, a team or a lab already uses**: a spreadsheet, Python, MATLAB, motion-capture and EMG systems, OpenSim, its own app, or an AI assistant. It is published under the Apache 2.0 licence, so anyone may use it, change it and ship it in their own product, including commercially.

![Where the SDK sits: plates feed the FDT; live data reaches the SDK over USB-C or Bluetooth, recordings go through Studio or the app to Movetrics Cloud, analog voltages come back through the SDK](/diagrams/data-path.svg)

## Why it is open

Most force plates are closed systems: the data leaves through the maker's software, in the maker's format, on the maker's schedule. That is a reason labs hesitate to buy, and a reason integrators build around a plate instead of with it.

Opening the connection changes three things:

- **Buyers stop asking "can we get the data out?"** The answer is a link to this page.
- **Partners integrate without waiting for us.** An EMG maker, a camera system or a university can connect the plates in an afternoon, with test data that proves they got it right.
- **Our own products get better.** The Cloud and the Android app are moving onto the same names, units and test data as everyone else, so a mistake shows up in one shared test, not in a customer's data.

What stays Movetrics': the analysis engine that turns force into jump heights, balance scores and reports, and the Cloud that runs it. The SDK opens the raw measurement and the file formats. It can read engine results from the Cloud, with the method and version that produced each number, but it does not contain the engine.

## What a team can do on day one

| Who | What they get | Time to first data |
|---|---|---|
| Coach or clinician with Excel | Recordings and results refresh into a workbook with one click | about 5 minutes ([Excel](../excel/)) |
| Sports scientist with Python or MATLAB | A live stream or a recorded file as a table in SI units | about 5 minutes ([Python](../python/), [MATLAB](../matlab/)) |
| Lab with EMG, EEG or cameras | The plates appear in LabRecorder next to the other devices, with a sync signal for alignment | an hour ([EMG and cameras](../emg-and-cameras/)) |
| Biomechanist with OpenSim | C3D and OpenSim force files with the centre of pressure in the right place | minutes ([OpenSim](../opensim/)) |
| Developer building a product | A documented protocol, test data for every client, and a simulated FDT so work starts before hardware arrives | the same day, on the simulator ([Build with an AI assistant](../build-with-ai/)) |

Nobody needs an FDT to start. The SDK includes a simulator that behaves like one, with a person jumping on it, so a developer can build and test the whole application first and plug the real device in at the end.

## How far it has been tested

Plainly: the numbers that matter have been checked against references outside the SDK, and the hardware run with this exact version is still ahead. The centre of pressure computed by the SDK agrees with Movetrics Studio's own figures to about a third of a millimetre on real recordings (measured). The Python, TypeScript and MATLAB versions run the same shared test data, each the parts it uses, and all three pass. Streaming 2,000 samples per second per plate over USB without loss was measured on the FDT with the firmware team's tools; with this SDK it has been run on the simulator so far. [What has been tested, and how](../../concepts/tested/) lists every claim.

## What it costs

Nothing. No licence fee, no account needed for the live stream or for files. The Cloud API needs a Movetrics Cloud account and a personal access token that the user creates and can revoke.
