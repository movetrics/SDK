# Contributing

This repository holds the host SDK for the Movetrics Force Data Terminal (FDT): the host protocol, the Python, TypeScript and MATLAB clients, the simulator, the byte test vectors and the documentation. Device firmware, bootloader and signing code are not in this repository.

## Before you open a pull request

- Open an issue first for any change to the frame format, the command codes, the timing or the stream. Movetrics Studio and the apps rely on those.
- Keep one behaviour change in one pull request, with a test for it.
- Use LF line endings in every file.
- The pull request description says what a reader sees before and after the change.

## Tests that must pass

Run all three suites from the repository root. Continuous integration runs them on every push to `main` and every pull request (`.github/workflows/ci.yml`).

```sh
(cd python && python3 -m unittest discover -s tests -t . -v)
(cd ts && npm ci && npm test && npm run typecheck && npm run build)
(cd matlab && octave --no-gui --no-window-system --eval "run('tests/run_tests.m')")
```

The Python client needs Python 3.10 or later. The TypeScript client needs Node 22.18 or later. The MATLAB tests run in GNU Octave; the toolbox is also written for MATLAB, which has not been used to run these tests.

## Byte vectors

The files in `vectors/` are generated. Do not edit them by hand. When a vector must change, change the generator and regenerate the files. The generator that writes the byte vectors is not yet part of this repository, so for now open an issue that gives the change and the expected bytes, and a maintainer regenerates the files.

## Claims in the documentation

Say what was run. A result from a device names the device, the firmware version and the command or capture. A fact read from the firmware source is labelled as read from the code, not as seen on a device. A result from a simulator is labelled as simulated.

## Sign-off (DCO)

Sign off each commit with `git commit -s`. The `Signed-off-by:` line accepts the Developer Certificate of Origin (https://developercertificate.org).

## Licence

Contributions are accepted under the Apache License, Version 2.0 (see `LICENSE`).

## Security

Report security problems privately, as described in `SECURITY.md`.
