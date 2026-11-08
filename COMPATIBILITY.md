# Firmware capability table

Generated from `contracts/firmware-capabilities.v1.json` (contract `movetrics.firmware-capabilities/1.0.0`, updated 2026-11-08). Do not edit by hand.

Each row is a firmware version. A capability holds from the version in its row until a later entry with the same name. Versions before 1.2.8.0 or versions that cannot be read give `unknown`.

Evidence words:

- `measured`: seen on an FDT on the bench
- `code`: read in the firmware source, not seen on a device

| Firmware from | `stream_rate_command` | `default_stream_rate_hz` | `zero_while_streaming_refuses_unsteady` | `battery_percent` | `sleep_after_last_command_s` | `start_waits_for_pads_after_sleep_ms` | `wake_only_on_host_command` | `studio_exam_start_after_sleep` | `sync_modes` | `stream_values_clip_int16` | `analog_outputs_clip` | `platforms_max` | `four_plate_stream_rate_max_hz` | `first_frame_after_reset_four_plates_ms` | `pad_clip_flag` | `watchdog_every_boot` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| before 1.2.8.0 (or unreadable) | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown |
| 1.2.8.0 | true (code) | 500 (code) | false (code) | false (code) | 600 (code) | 0 (code) | false (code) | false (code) | false (code) | false (code) | false (code) | 2 (code) | null (code) | null (code) | false (code) | false (code) |
| 1.2.8.5 | true (code) | 1000 (measured) | false (code) | false (code) | 600 (code) | 0 (code) | false (code) | false (code) | false (code) | false (code) | false (code) | 2 (code) | null (code) | null (code) | false (code) | false (code) |
| 1.2.8.6 | true (code) | 1000 (measured) | true (measured) | false (code) | 600 (code) | 0 (code) | false (code) | false (code) | false (code) | false (code) | false (code) | 2 (code) | null (code) | null (code) | false (code) | false (code) |
| 1.2.8.7 | true (code) | 1000 (measured) | true (measured) | true (measured) | 600 (code) | 0 (code) | false (code) | false (code) | false (code) | false (code) | false (code) | 2 (code) | null (code) | null (code) | false (code) | false (code) |
| 1.2.8.9 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 0 (code) | false (code) | false (code) | false (code) | false (code) | false (code) | 2 (code) | null (code) | null (code) | false (code) | false (code) |
| 1.2.8.10 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | false (code) | false (code) | false (code) | false (code) | false (code) | 2 (code) | null (code) | null (code) | false (code) | false (code) |
| 1.2.8.12 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | false (code) | false (code) | false (code) | false (code) | 2 (code) | null (code) | null (code) | false (code) | false (code) |
| 1.2.8.14 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | true (measured) | false (code) | false (code) | false (code) | 2 (code) | null (code) | null (code) | false (code) | false (code) |
| 1.2.8.21 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | true (measured) | false (code) | false (code) | true (code) | 2 (code) | null (code) | null (code) | false (code) | false (code) |
| 1.2.8.24 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | true (measured) | true (code) | true (code) | true (code) | 2 (code) | null (code) | null (code) | false (code) | false (code) |
| 1.2.8.26 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | true (measured) | true (code) | true (code) | true (code) | 2 (code) | null (code) | null (code) | true (code) | false (code) |
| 1.2.8.27 | true (code) | 1000 (measured) | true (measured) | true (measured) | 300 (measured) | 6000 (measured) | true (measured) | true (measured) | true (code) | true (code) | true (code) | 4 (measured) | 1000 (measured) | 2410 (measured) | true (code) | true (code) |

Shared numbers: two different builds carry 1.2.8.24 and 1.2.8.25, a sync build (the rows above) and a four-platform build without sync. On those two numbers probe GET_SYNC_MODE (NACK 7 means no sync) and count the plate addresses in the stream instead of trusting the version. 1.2.8.27 has both.

Side branch: firmware 1.2.9.0 is read as 1.2.8.8 until the version is renumbered.
