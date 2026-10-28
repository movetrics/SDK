# Firmware capability table

Generated from `contracts/firmware-capabilities.v1.json` (contract `movetrics.firmware-capabilities/1.0.0`, updated 2026-10-28). Do not edit by hand.

Each row is a firmware version. A capability holds from the version in its row until a later entry with the same name. Versions before 1.2.8.0 or versions that cannot be read give `unknown`.

Evidence words:

- `measured`: seen on an FDT on the bench
- `code`: read in the firmware source, not seen on a device

| Firmware from | `stream_rate_command` | `default_stream_rate_hz` | `zero_while_streaming_refuses_unsteady` | `battery_percent` | `sleep_after_last_command_s` | `start_waits_for_pads_after_sleep_ms` | `wake_only_on_host_command` | `studio_exam_start_after_sleep` | `analog_outputs_clip` | `analog_outputs_offset` | `sync_modes` | `stream_values_clip_int16` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| before 1.2.8.0 (or unreadable) | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown |
| 1.2.8.0 | true (code) | 500 (code) | false (code) | false (code) | 600 (code) | 0 (code) | false (code) | false (code) | unknown | unknown | false (code) | false (code) |
| 1.2.8.5 | true (code) | 1000 (measured) | false (code) | false (code) | 600 (code) | 0 (code) | false (code) | false (code) | unknown | unknown | false (code) | false (code) |
| 1.2.8.6 | true (code) | 1000 (measured) | true (measured) | false (code) | 600 (code) | 0 (code) | false (code) | false (code) | unknown | unknown | false (code) | false (code) |
| 1.2.8.7 | true (code) | 1000 (measured) | true (measured) | true (measured) | 600 (code) | 0 (code) | false (code) | false (code) | unknown | unknown | false (code) | false (code) |
| 1.2.8.9 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 0 (code) | false (code) | false (code) | unknown | unknown | false (code) | false (code) |
| 1.2.8.10 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | false (code) | false (code) | unknown | unknown | false (code) | false (code) |
| 1.2.8.12 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | false (code) | unknown | unknown | false (code) | false (code) |
| 1.2.8.14 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | true (measured) | unknown | unknown | false (code) | false (code) |
| 1.2.8.21 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | true (measured) | true (code) | unknown | false (code) | false (code) |
| 1.2.8.22 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | true (measured) | true (code) | true (measured) | false (code) | false (code) |
| 1.2.8.24 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | true (measured) | true (code) | true (measured) | true (code) | true (code) |

Side branch: firmware 1.2.9.0 is read as 1.2.8.8 until the version is renumbered.
