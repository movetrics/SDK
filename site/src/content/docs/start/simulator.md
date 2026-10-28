---
title: Build without an FDT
description: A virtual FDT that speaks the real protocol, for development and tests.
---

```sh
movetrics-fdt simulate --tcp 7800                       # 127.0.0.1:7800
movetrics-fdt simulate --pty /tmp/fdt                   # a serial-like device (macOS, Linux)
movetrics-fdt simulate --tcp 7800 --replay exam-channels.csv   # replay a Studio export, gaps included
```

Your program cannot tell it from an FDT on the byte level: the same frames and checksums, the same pacing, sleep after 5 minutes without a command and the 4.6 s wake-up of the plates, the same refusals. It can also misbehave on purpose so you can test your error handling: drop frames, stall, drift its clock, overload the plates.

With `--signal cmj`, a virtual person of 750 N jumps every 6 seconds. This is what your program receives, both plates added:

![The simulated jump: standing at 750 N, a dip, a push-off to about 1,800 N, 0.45 s in the air, a landing spike](/diagrams/cmj.svg)

Full options: [the simulator reference](../../reference/20-simulator/).

It never replaces a check on a real FDT: it does what the firmware is documented to do.
