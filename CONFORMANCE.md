# Conformance matrix

Written by `tools/conformance.py` on 2026-10-28. A client conforms to a file when its tests read the file and pass. "not wired" means the client's tests do not read that file yet: it may still decode those bytes, but nothing checks it against the shared vectors.

| Client | Suite | Result |
|---|---|---|
| Python | ran here | passed (Ran 250 tests in 11.673s OK (skipped=1)) |
| TypeScript | ran here | passed (202 pass, 0 fail) |
| MATLAB (Octave) | ran here | passed (61 checks) |
| Kotlin (Android fdt-core) | - | not run: android checkout not given (--android) |

| File | Python | TypeScript | MATLAB (Octave) | Kotlin (Android fdt-core) |
|---|---|---|---|---|
| `crc16.json` | pass | pass | pass | not wired |
| `host_frames.json` | pass | pass | not wired | not wired |
| `ota_frames.json` | pass | pass | not wired | not wired |
| `status.json` | pass | pass | not wired | not wired |
| `stream_frames.json` | pass | pass | pass | not wired |
| `sync_events.json` | pass | pass | pass | not wired |
| `vocabulary.json` | pass | pass | pass | not wired |
| `k5_c3d_cop.json` | pass | not wired | not wired | not wired |

Simulated and recorded bytes only; no row here was run against a real FDT.
