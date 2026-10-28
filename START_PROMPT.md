# Start prompt: build with an AI assistant

Copy the prompt below into Claude Code, Cursor, ChatGPT, Copilot or any coding assistant that can read the web or a folder. Replace the line in brackets with what you want, in your own words. You do not need to know the technical terms; the assistant asks what it needs.

---

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

---

## What happens next

The assistant reads the SDK's [AGENTS.md](AGENTS.md), which tells it how the plates, the FDT, Studio and the Cloud fit together, which part of the SDK fits your goal, and which rules keep your data right and your device safe. It then starts a simulated FDT on your computer, so you see your program working within minutes, with or without a plate.

When it says "tested on the simulator", that is the truth and not a disclaimer: plug in the FDT, make the one change it gives you, and run it again.

## Good first goals

- "Show me the live vertical force of each plate as a graph in the browser."
- "Every time someone jumps, print the flight time and the jump height."
- "Turn this folder of Studio CSV exports into one table with the peak force per trial."
- "Record the plates in LabRecorder next to my EMG."
- "Pull my athletes' jump heights from Movetrics Cloud into a chart by week."
