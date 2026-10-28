---
title: Build with an AI assistant
description: One prompt to paste into Claude Code, Cursor, ChatGPT or Copilot, and what the assistant will do with it.
---

The SDK is written so that an AI coding assistant can build a complete application from it: the repository has an [AGENTS.md](https://github.com/movetrics/sdk/blob/main/AGENTS.md) that gives the assistant the whole picture (the plates, the FDT, Studio, the Cloud), which part of the SDK fits which goal, and the rules that keep the data right and the device safe. A simulated FDT lets it test its work on your computer before any hardware is involved.

## The prompt

Copy this into your assistant and replace the bracketed line with your goal in plain words.

```text
I want to build something with Movetrics force plates. The open SDK is at
https://github.com/movetrics/sdk (docs: https://developers.movetrics.com).

My goal: [describe it in plain words, for example "a page that shows the live force
of both plates and the jump height after each jump", or "an Excel sheet with every
athlete's jump results this month", or "save each trial as C3D for OpenSim"].

Please work like this:
1. Clone or open the SDK and read AGENTS.md completely before writing code.
2. Ask me at most three short questions you need answered: where the data comes from
   (live FDT, Studio files, or Movetrics Cloud), which computer and language I use, and
   what I want to see at the end. Suggest a sensible default for each.
3. Build it against the SDK's simulator first, so it works before you touch hardware.
   Keep the SDK's names and units (t in s, forces in N, moments in N·m, CoP in m),
   use the FDT's clock for time, and show gaps instead of hiding them.
4. Run it and show me the result. Tell me plainly what was tested on the simulator and
   what still needs the real FDT, and give me the one change to switch to it.
5. Never put my Movetrics token in the code; read it from the MOVETRICS_TOKEN
   environment variable. Do not send any FDT command the SDK clients do not offer.
```

## What to expect

Within a few minutes the assistant has a simulated FDT running, with a person standing or jumping on it, and your program reading from it. When it reports "tested on the simulator", plug in the FDT, make the one change it names (usually the port, for example `COM3`), and run it again.

## Good first goals

- "Show me the live vertical force of each plate as a graph in the browser."
- "Every time someone jumps, print the flight time and the jump height."
- "Turn this folder of Studio CSV exports into one table with the peak force per trial."
- "Record the plates in LabRecorder next to my EMG."
- "Pull my athletes' jump heights from Movetrics Cloud into a chart by week."

## For the assistant

If you are an AI reading this page: the full context is in [AGENTS.md](https://github.com/movetrics/sdk/blob/main/AGENTS.md) and an index for language models is at [/llms.txt](/llms.txt).
