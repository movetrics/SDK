# movetrics-fdt-sdk

The TypeScript client of the [Movetrics SDK](https://github.com/movetrics/sdk): live force data from a Movetrics FDT in the browser (Web Serial over USB, Web Bluetooth through the FDT's bridge) and in Node 22, in the same names and units as every other Movetrics client. No runtime dependencies. Version 0.3.0, Apache 2.0. Docs: [developers.movetrics.com](https://developers.movetrics.com).

The browser transports are written and unit-tested against fake ports, but have not yet run against an FDT: treat a first browser run as a test.

## Install and build

```sh
cd ts
npm install        # typescript 5.9.3 and @types/node 22.20.5 (dev only)
npm test           # node:test, runs the .ts sources directly (Node 22.18 or later)
npm run typecheck  # tsc --noEmit, strict, erasableSyntaxOnly
npm run build      # emits dist/ (ES modules and .d.ts), committed with the sources
```

The tests ran on Node 22.22.0. `dist/` holds the built output. Its declaration files import
`./*.js`, because the build rewrites the `.ts` specifiers in `dist/*.d.ts` after `tsc` runs.

Import check, from `ts/`:

```sh
node -e "import('./dist/index.js').then((m) => console.log(Object.keys(m).length, 'exports'))"
```

## Use

```ts
import { FdtClient, WebSerialTransport } from 'movetrics-fdt-sdk';

const port = await navigator.serial.requestPort(); // from a user gesture
const client = new FdtClient(await WebSerialTransport.open(port));

const version = await client.getFwVersion();   // { stm32FW, esp32FW, ... }
const status = await client.getStatus();       // { general, platforms, lengthClass }
await client.startStream();
setInterval(() => client.keepAlive(600), 30_000); // the Movetrics Android app does the same

for await (const frame of client.frames()) {
  console.log(frame.platformAddress, frame.timeStamp, frame.forceX, frame.momentZ);
}

await client.stopStream();
await client.close();
```

Bluetooth: `WebBluetoothTransport.open({ notify, write })` takes the bridge's TX characteristic
(`notify`) and RX characteristic (`write`). The UUIDs are exported as `BLE_SERVICE_UUID`,
`BLE_RX_UUID`, `BLE_TX_UUID` and `BLE_STATUS_UUID`, and the advertised name as `BLE_DEVICE_NAME`.
The bridge accepts one client at a time. The page in `../examples/web` shows both paths.

Rate, sync modes and the shared vocabulary (version 0.3.0):

```ts
await client.getFwVersion();                 // setRate refuses unless this is Movetrics 1.2.8.0 or later
await client.setRate(500, 50);               // 50 to 2000 frames per second; cutoff 0 (off) or 1 to 255 Hz
await client.setSyncMode(SyncMode.EVENT_FRAMES | SyncMode.START_ON_RISE); // DRAFT, needs sync-mode firmware
await client.startStream();
for await (const item of client.samples()) {   // Sample, Event or Gap, in SI units and the plate frame
  if (item.kind === 'sample') console.log(item.t, item.plate, item.fz, item.cop_x);
}
```

`setRate` and `setSyncMode` refuse while the stream runs (`FdtRefusedError`, code `streaming`). `setRate` refuses
firmware older than 1.2.8.0 (code `firmware`). A NACK 7 to `setSyncMode` means the firmware has no sync modes
(code `no_sync_modes`). `items()` gives stream frames and event frames in the order they arrived, `frames()` only
the stream frames, and `events()` only the event frames. Use one of them per client, because each item goes to one
consumer. `vocabulary.v1.json` names and units are in `../docs/19-vocabulary-and-units.md`. The vocabulary
`Event` uses `source` (the sync input or plate), and its time is `stamp / 10000 + offsetUs / 1e6`.

## Commands

The client sends eight commands and nothing else. A client test checks the frames written in a
session against `IMPLEMENTED_CODES`.

| Method | Command | Address (pa/da) | Reply |
| --- | --- | --- | --- |
| `getFwVersion()` | GET_FW_VERSION 0x23 | 00/00 | 38-byte version record |
| `getStatus()` | GET_STATUS 0x22 | 00/00 | general record, then one per detected pad |
| `startStream()` | START_STREAM 0x01 | FF/FF | no reply on success; a NACK within 250 ms rejects |
| `stopStream()` | STOP_STREAM 0x05 | FF/00 | ACK |
| `keepAlive(seconds)` | KEEP_ALIVE 0x26 | 00/00 | none. Seconds from 1 to 65535; 0 is refused |
| `setRate(fps, cutoffHz = 50)` | SET_FILTER 0x1C (Movetrics 1.2.8+ only) | 00/00 | ACK; 100 ms settle after it |
| `setSyncMode(mode, periodMs, widthMs, debounce, armMin)` | SET_SYNC_MODE 0x28 (DRAFT) | 00/00 | ACK. Six payload bytes; 0 = firmware default |
| `getSyncMode()` | GET_SYNC_MODE 0x29 (DRAFT) | 00/00 | 26-byte state; `null` on NACK 7 (no sync modes) |

Not implemented, with the reason for each, in `src/commands.ts` (`NOT_IMPLEMENTED`):

- Setters and pad writes outside the reviewed set: 0x07, 0x12, 0x14, 0x15, 0x31, 0x34, 0x53, 0x55.
- Tare: 0x1B (SET_TARE). A tare re-zeroes the plates; zeroing is done in Movetrics Studio or the Movetrics app.
- Flash writes: 0x19 (SAVE_CALIBRATION). Calibration data: 0x52 (PADS_GET_FACTORY_GF).
- Pad health (0x27): its layout is in `docs/06-status-health-versions.md` section 7. No vector covers its reply, so the client does not send it.
- Firmware update (0x40), controller reset (0x25), analog test (0x39), debug (0x60 to 0x62).
- Queries outside the first surface (0x08, 0x13, 0x17, 0x18, 0x1A, 0x24) and undispatched codes.

Commands with a fixed meaning that matter when a host talks to this firmware:

- Never send 0x25 as a tare. The firmware runs 0x25 as a controller reset.
- KEEP_ALIVE interval 0 turns the sleep timer off, so `keepAlive(0)` throws `RangeError`.

## Replies and errors

- Replies are read by length, command byte and CRC. They are not read by delimiter. A reply that
  contains `04 04` in its data is not cut short.
- Requests run one at a time. A reply is matched to its request by command byte.
- A NACK rejects with `FdtNackError`, which carries the error code and its name
 . A timeout rejects with `FdtTimeoutError`. A closed client or link
  rejects with `FdtClosedError`.
- `encodeHostFrame` refuses a request that the controller's RX splitter would cut short, a frame
  with `04 04` before its end (`docs/03-host-link-framing.md`, section 3.3). Such a request is a
  `FrameEncodeError` with `code === 'early_04_04_delimiter'`. Example: GET_STATUS to FF/FF.
- `encodeHostFrame` also refuses a command in `NOT_IMPLEMENTED`, with `FrameEncodeError` code
  `not_implemented`. The client never sends one.
- START_STREAM has no success reply (`docs/04-host-commands.md`, section 2). The firmware then
  sends two placeholder frames with timeStamp 0. The vectors
  record stream indexes 0 and 1 as these placeholders (`vectors/README.md`, notes).
- In the first 8 s after a controller restart, START first waits for a plate that has not answered
  yet, so the placeholders and the first
  frames can arrive seconds late. `timeouts.settle` only waits for a NACK and does not cover this.
- A GET_STATUS reply carries no record count, so the client reads until the line is quiet for
  150 ms, or until 3 s have passed. The records are then parsed as one reply.
- `frames()` gives raw wire integers. `samples()` turns them into SI units and the plate frame ([chapter 19](https://github.com/movetrics/sdk/blob/main/docs/19-vocabulary-and-units.md)).

## Timing limits (client policy)

The firmware defines no host timing. These limits are chosen here and can be changed with
`new FdtClient(transport, { timeouts, frameBacklog })`.

| Option | Default | Used for |
| --- | --- | --- |
| `timeouts.reply` | 1000 ms | ACK, NACK, version reply, first status record |
| `timeouts.status` | 3000 ms | the whole GET_STATUS reply |
| `timeouts.statusQuiet` | 150 ms | silence that ends a GET_STATUS reply |
| `timeouts.settle` | 250 ms | how long START_STREAM waits for a NACK |
| `frameBacklog` | 4096 frames | stream frames kept for `frames()`; the oldest are dropped and counted in `droppedFrames` |

## Coverage by the vectors

`test/vectors.test.ts` runs the byte-level cases in `../vectors`. Every case is checked, and no anchor is skipped.

| File | Cases | Checked | Anchors checked |
| --- | ---: | ---: | ---: |
| `crc16.json` | 6 | 6 | 2 |
| `host_frames.json` | 24 | 24 | 9 |
| `stream_frames.json` | 13 | 13 | 6 |
| `status.json` | 6 | 6 | 1 |
| `ota_frames.json` | 4 | 4 | 2 |
| total | 53 | 53 | 20 |

Deliberate deviation. An earlier FDT reference parser rejects the 86-byte status record and the three-record
reply (`status.json`, `reference_parser: "reject"`). This client accepts them, because the FDT has sent that
layout since firmware 1.2.6.5. The vectors test asserts both sides of that decision. The 85-byte record
is accepted by both.

## Tests

`npm test` runs 202 tests. They cover the vector cases above, the sync jack golden vectors
(`../python/tests/fixtures/sync_events.json`, 11 event frames and 2 GET_SYNC_MODE replies, decoded, and
the event frames re-encoded byte for byte), the event frame and the set-rate and sync-mode requests, the vocabulary
(placeholders, signs, CoP, gaps, the learnt period, the wrap, combine); the CRC; host framing, the
RX splitter and the reply scanner, including every chunk boundary in the three-record reply;
the stream and status layouts; the client's request matching, GET_STATUS collection, START
settling, the stream backlog and the close paths; and the two transports, with fake port and
characteristics. No test opens a serial port, scans for BLE devices or contacts hardware.

## Notes from the firmware

- The firmware parses 0x1B with `pa` 0 or FF as all plates and 1 or 2 as one plate. This client
  does not send 0x1B.
- USB serial lines: after open, `WebSerialTransport` clears both DTR and RTS with `port.setSignals`,
  where the browser allows it. A platform without `setSignals` still opens. If the call rejects, `open`
  fails and the port is closed. The Movetrics Android app never sets either line. Whether opening the
  port in a browser resets the FDT has not been checked on hardware.
- Keep-alive: the FDT sleeps when no command arrives within the interval (600 s up to firmware 1.2.8.8,
  300 s from 1.2.8.9, see [COMPATIBILITY.md](https://github.com/movetrics/sdk/blob/main/COMPATIBILITY.md)). It does not sleep while it streams.
  Call `keepAlive` on a timer while a session is open.
- The layouts of the status and version replies are in [chapter 06](https://github.com/movetrics/sdk/blob/main/docs/06-status-health-versions.md),
  sections 6 and 7.

## Layout

- `src/bytes.ts`, `src/crc.ts`: byte helpers and CRC-16/CCITT-FALSE.
- `src/frames.ts`: host request encoder, the controller's RX splitter, the host parser, and the
  reply scanner.
- `src/commands.ts`: command codes, safety classes, dispatch table, NACK names.
- `src/stream.ts`, `src/status.ts`: the 24-byte stream frame, the status records, the version reply.
- `src/client.ts`: `FdtClient`.
- `src/transport.ts`: the `Transport` interface and `AsyncQueue`.
- `src/webserial.ts`, `src/webbluetooth.ts`: the browser transports, written against structural
  interfaces so the package has no DOM or Node types.
- `src/errors.ts`, `src/index.ts`.
- `test/`: `*.test.ts` files, a fake transport and fakes for browser objects (`support.ts`), and a
  loader for `../vectors` (`vectors-data.ts`).

## Documents

- [`../docs/02-transports.md`](https://github.com/movetrics/sdk/blob/main/docs/02-transports.md): the USB and Bluetooth links.
- [`../docs/03-host-link-framing.md`](https://github.com/movetrics/sdk/blob/main/docs/03-host-link-framing.md): frame layouts, CRC, the `04 04` hazard.
- [`../docs/04-host-commands.md`](https://github.com/movetrics/sdk/blob/main/docs/04-host-commands.md): command table, reply rules, worked frames.
- [`../docs/19-vocabulary-and-units.md`](https://github.com/movetrics/sdk/blob/main/docs/19-vocabulary-and-units.md): names, units, signs, the centre of pressure.
