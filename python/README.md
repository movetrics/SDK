# movetrics-fdt

The Python package of the [Movetrics SDK](https://github.com/movetrics/sdk): live force data from a Movetrics FDT over USB or Bluetooth, Movetrics Studio files, CSV, C3D and OpenSim files, Lab Streaming Layer, clock alignment for sync, a simulated FDT, and the Movetrics Cloud read API. Every sample comes out in the same names and units: `t` in seconds from the FDT's clock, forces in N, moments in N·m, centre of pressure in m.

Version 0.3.0. Docs: [developers.movetrics.com](https://developers.movetrics.com). Licence: Apache 2.0.

## Install

Python 3.10 or newer. The core uses only the standard library; each connection or file format is an extra:

```sh
pip install "movetrics-fdt[serial] @ git+https://github.com/movetrics/sdk#subdirectory=python"
```

| Extra | Adds | For |
|---|---|---|
| `serial` | pyserial | the FDT on a USB cable |
| `ble` | bleak (0.21 to below 1) | the FDT over Bluetooth |
| `c3d` | ezc3d, numpy | reading and writing C3D |
| `lsl` | pylsl | Lab Streaming Layer |

Combine them as `movetrics-fdt[serial,c3d,lsl]`. Without an extra, the call that needs it raises an `ImportError` that names the extra to install.

## One minute, no FDT needed

```sh
movetrics-fdt simulate --tcp 7800 --signal cmj       # prints READY 127.0.0.1:7800
```

```python
import asyncio
from movetrics_fdt import FdtClient, TcpTransport, Sample, Gap

async def main():
    async with FdtClient(TcpTransport("127.0.0.1", 7800)) as fdt:   # a real FDT: SerialTransport("COM3")
        await fdt.set_rate(2000)                                     # samples per second per plate
        await fdt.start_stream()
        async for item in fdt.samples():
            if isinstance(item, Sample) and item.plate == 1 and item.stamp % 1000 == 0:   # every 0.1 s
                print(f"t={item.t:6.2f} s  fz={item.fz:7.1f} N  cop_x={item.cop_x * 1000:6.1f} mm")
            elif isinstance(item, Gap):
                print(f"plate {item.plate}: {item.missing} samples missing")
            if getattr(item, "t", 0) > 4:
                break
        await fdt.stop_stream()

asyncio.run(main())
```

The simulator speaks the FDT's real protocol. `--signal stand|cmj|empty`, `--bodyweight 750`, `--replay exam-channels.csv` (a Studio export), `--drop-every 500` (lose frames, to test your gap handling), `--clock-ppm 30`, `--sync-pulse-s 1`, `--profile sync` (firmware with the sync modes), `--pty /tmp/fdt` (a serial-like device on Linux and macOS).

## What is in the package

| You want to | Use |
|---|---|
| Stream live | `FdtClient` with `SerialTransport(port)`, `BleTransport("Movetrics-BLE")` or `TcpTransport(host, port)`; `samples()` yields `Sample`, `Event` and `Gap` |
| Read Studio exports | `read_studio_csv(path)`, `read_studio_c3d(path)`, `read_studio_details(path)` |
| Write files for other tools | `Recording.from_samples(items, rate_hz)` or `Recording.from_studio(...)`, then `write_csv`, `write_c3d`, `write_mot` (in `movetrics_fdt.writers`) |
| Record next to EMG, EEG or cameras | `movetrics_fdt.lsl.LslBridge(rate_hz, plates)`: `bridge.push(item)` for each item of `samples()` |
| Align two clocks with sync pulses | `movetrics_fdt.sync`: `edge_times`, `align`, `merge` (two FDTs into one timeline) |
| Read results and recordings from Movetrics Cloud | `CloudClient(os.environ["MOVETRICS_TOKEN"])`: `results()`, `recordings()`, `samples(recording_id)` |
| Turn recorded analog voltages into values | `movetrics_fdt.analog.to_vocabulary("A1", volts)` |
| Compute the centre of pressure yourself | `plate_cop(fx, fy, fz, mx, my)`, `combine({1: s1, 2: s2})` |

Complete programs are in [`examples/python/`](https://github.com/movetrics/sdk/blob/main/examples/python/): a stream reader, a CSV recorder, an LSL outlet, a Bluetooth status check and a Cloud results reader.

## The FdtClient

| Call | Command sent | Result |
|---|---|---|
| `await fdt.get_firmware_version()` | GET_FW_VERSION 0x23 | `FirmwareVersionReply` with `stm32FW` and `esp32FW` |
| `await fdt.get_status()` | GET_STATUS 0x22 | `Status`, one record per address |
| `await fdt.set_rate(fps, cutoff_hz=50)` | SET_FILTER 0x1C | 50 to 2,000 frames per second per plate; lost on every FDT reset, so call it after each connect |
| `await fdt.start_stream()` | START_STREAM 0x01 | no reply on success; a NACK within `start_check` raises `NackError` |
| `await fdt.stop_stream()` | STOP_STREAM 0x05 | ACK |
| `await fdt.keep_alive(300)` | KEEP_ALIVE 0x26 | sets how long the FDT waits for a command before it sleeps; 0 is refused |
| `await fdt.get_sync_mode()` | GET_SYNC_MODE 0x29 | the sync state, or `None` when the FDT has no sync modes (use it as the probe) |
| `await fdt.set_sync_mode(SyncMode.START_ON_RISE, ...)` | SET_SYNC_MODE 0x28 | start or stop on the SYNC IN jack, SYNC OUT pulses; firmware 1.2.8.24 and later |
| `fdt.samples(rate_hz=None)` | (stream) | `Sample`, `Event`, `Gap` in SI units and FDT time |
| `fdt.frames()`, `fdt.records()` | (stream) | the raw wire frames, and the frames with the sync event frames |

Use one stream iterator per client; each item goes to one consumer. `async with FdtClient(...)` opens the link and, on exit, stops a stream it started and closes the link.

Errors are subclasses of `FdtError`: `FrameError`, `UnsupportedCommandError`, `NackError` (with `error_name`), `ReplyTimeoutError`, `TransportError`.

### Commands the client will not send

The FDT also accepts commands that update firmware, write calibration, reset the controller, re-zero the plates or change how the plates inside are polled. The client sends the eight commands above and nothing else. The other 41 codes it knows are in `NOT_IMPLEMENTED` in `movetrics_fdt/commands.py`, each with its reason, and asking for one raises `UnsupportedCommandError` before a byte is written. Zeroing the plates and firmware updates are done in Movetrics Studio or the Movetrics app.

## Data rules

- **Samples.** `Sample` has `t`, `plate`, `fx fy fz` (N), `mx my mz` (N·m), `cop_x cop_y` (m from the plate centre, NaN below 50 N), the FDT `stamp` (0.1 ms ticks) and the six `raw` wire integers. The signs follow Movetrics Studio's files. [Chapter 19](https://github.com/movetrics/sdk/blob/main/docs/19-vocabulary-and-units.md) defines all of it.
- **Time** comes from the stamp in each frame, never from the computer's clock, so USB and Bluetooth jitter do not move a sample.
- **Placeholders.** After START, each plate sends one frame with stamp 0 before it measures. `samples()` drops it.
- **Gaps** are reported, never filled. A `Gap` has `plate`, `start_t`, `end_t` and `missing`.
- **Status replies** are a general record followed by one record per plate, 85 or 86 bytes each; the parser decides by length and CRC, never by version string, and refuses mixed or out-of-order records.
- **The stream and replies share one byte stream.** Frames are found by header, command byte, length, end marker and CRC; the `04 04` end marker is never used alone to cut the stream, because it can occur inside data.

## Bluetooth

Connect, check the bridge's RX, TX and status characteristics, read the status line and require `mode=UART`, subscribe to TX, and only then write ([chapter 02](https://github.com/movetrics/sdk/blob/main/docs/02-transports.md), section 2.6). Writes use write-with-response, split to the negotiated MTU minus 3 bytes. The bridge accepts one client; when a session that sent commands ends, the bridge sends STOP to the FDT. The transport exposes the bridge's status line as `transport.bridge_status`.

## Tests

```sh
cd python
python3 -m unittest discover -s tests -t .          # the -t . is required
```

No hardware and no extras needed; a test that needs a missing extra is skipped with the reason. They run the shared byte vectors in [`../vectors`](https://github.com/movetrics/sdk/blob/main/vectors/), the vocabulary vectors, the sync and C3D golden files, the simulator over TCP and a pseudo-terminal, the file writers against real Studio exports, and the transports against fake pyserial and bleak modules.

## What has been run

| Part | How |
|---|---|
| Decoding, vocabulary, CoP, files | shared vectors and real Studio exports (measured) |
| 2,000 samples per second, two plates, no loss | the simulator over a pseudo-terminal (simulated) |
| `set_rate` and the stream on a real FDT | the firmware team's own tool, not yet this client |
| Bluetooth, Windows, macOS, Linux serial | fakes only; not yet with a device |

## Layout

`movetrics_fdt/`: `client.py` (FdtClient), `transport.py`, `serial_transport.py`, `ble_transport.py`, `tcp_transport.py`, `frames.py` and `crc.py` (framing), `commands.py`, `stream.py` and `status.py` (wire layouts), `vocabulary.py` (samples, CoP), `files.py` (Studio readers), `writers.py`, `lsl.py`, `sync.py`, `analog.py`, `cloud.py`, `simulator.py` and `simulator_io.py`, `__main__.py` (the `movetrics-fdt` command). `tests/`: the suites and their fixtures.
