import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { bytesOf, FakeTransport } from './support.ts';
import { vectorCase } from './vectors-data.ts';
import { crc16CcittFalse } from '../src/crc.ts';
import { FdtClient, SyncMode, type ClientOptions } from '../src/client.ts';
import { FdtNackError, FdtRefusedError, FdtTimeoutError, FrameEncodeError } from '../src/errors.ts';
import { encodeEventFrame, encodeStreamFrame, type EventFrame, type StreamFrame } from '../src/stream.ts';

// Short limits, so the timing tests run quickly.
const FAST: ClientOptions = {
  timeouts: { reply: 60, status: 400, statusQuiet: 30, settle: 20 },
};

// Builds one device reply from the bytes after BE EF: [pa, command, ...], adding the CRC and 04 04.
function reply(body: readonly number[]): Uint8Array {
  const crc = crc16CcittFalse(Uint8Array.from(body));
  return Uint8Array.from([0xbe, 0xef, ...body, crc & 0xff, crc >> 8, 0x04, 0x04]);
}

const ACK = (command: number): Uint8Array => reply([0x00, command, 0x06]);
const NACK = (command: number, error: number): Uint8Array => reply([0x00, command, 0x15, error & 0xff, error >> 8]);

// GET_FW_VERSION reply with a chosen STM32 version string (at most 15 characters).
function firmwareReply(stm32FW: string): Uint8Array {
  const body = Array.from(bytesOf(vectorCase('ota-anchor-identification-fw-version-reply').frame_hex ?? '').subarray(2, 34));
  for (let i = 0; i < 15; i++) body[2 + i] = i < stm32FW.length ? stm32FW.charCodeAt(i) : 0;
  return reply(body);
}

const PROBE = 'feed0000239dd80404'; // GET_FW_VERSION to 00/00
const START = 'feedffff01'; // prefix of START_STREAM to FF/FF

// Command byte of a frame the transport received (FE ED pa da cmd).
function commandOf(frame: Uint8Array): number {
  return frame[4] ?? -1;
}

function clientFor(transport: FakeTransport): FdtClient {
  return new FdtClient(transport, FAST);
}

// A device that answers GET_FW_VERSION with `version` and every other command with `answer`.
function device(version: string, answer: (command: number) => Uint8Array[]): (frame: Uint8Array) => Uint8Array[] {
  return (frame) => (commandOf(frame) === 0x23 ? [firmwareReply(version)] : answer(commandOf(frame)));
}

describe('FdtClient.setRate', () => {
  test('sends the version probe, then SET_FILTER with cutoff and rate, and waits for the ACK', async () => {
    const transport = new FakeTransport();
    transport.respond = device('001.002.008.020', (command) => [ACK(command)]);
    const client = clientFor(transport);
    try {
      await client.setRate(500, 50);
      // The SET_FILTER bytes are the Python client's encode_host_frame(0x1c, 0, 0, bytes((50,)) + pack('<H', 500)).
      assert.deepEqual(transport.written, [PROBE, 'feed00001c32f401643e0404']);
    } finally {
      await client.close();
    }
  });

  test('the cutoff defaults to 50 Hz, and 0 means no low-pass', async () => {
    const transport = new FakeTransport();
    transport.respond = device('001.002.008.020', (command) => [ACK(command)]);
    const client = clientFor(transport);
    try {
      await client.setRate(500);
      await client.setRate(2000, 0);
      assert.deepEqual(transport.written, [
        PROBE,
        'feed00001c32f401643e0404',
        PROBE,
        'feed00001c00d007453f0404',
      ]);
    } finally {
      await client.close();
    }
  });

  test('values out of range are refused before anything is sent', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      const refused: Array<[number, number?]> = [[49], [2001], [500.5], [100, 50], [500, 256], [500, -1], [500, 1.5]];
      for (const [rate, cutoff] of refused) {
        await assert.rejects(client.setRate(rate, cutoff), RangeError, `rate ${rate} cutoff ${cutoff}`);
      }
      assert.deepEqual(transport.written, []);
    } finally {
      await client.close();
    }
  });

  test('a rate whose bytes form 04 04 (1028) is refused by the frame encoder before the probe', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      await assert.rejects(
        client.setRate(1028),
        (error: unknown) => error instanceof FrameEncodeError && error.code === 'early_04_04_delimiter',
      );
      assert.deepEqual(transport.written, []);
    } finally {
      await client.close();
    }
  });

  test('refuses while the stream runs, and allows the call again after stopStream', async () => {
    const transport = new FakeTransport();
    transport.respond = (frame) => {
      const command = commandOf(frame);
      if (command === 0x01) return [];
      if (command === 0x05) return [ACK(0x05)];
      return device('001.002.008.020', (c) => [ACK(c)])(frame);
    };
    const client = clientFor(transport);
    try {
      await client.startStream();
      assert.equal(client.streaming, true);
      await assert.rejects(
        client.setRate(500),
        (error: unknown) => error instanceof FdtRefusedError && error.code === 'streaming',
      );
      assert.equal(transport.written.length, 1, 'only START was sent');
      assert.ok(transport.written[0]?.startsWith(START));
      await client.stopStream();
      assert.equal(client.streaming, false);
      await client.setRate(500);
    } finally {
      await client.close();
    }
  });

  test('refuses firmware older than 1.2.8.0 after the probe, and firmware without four version parts', async () => {
    for (const version of ['001.002.007.099', '001.002.003']) {
      const transport = new FakeTransport();
      transport.respond = device(version, (command) => [ACK(command)]);
      const client = clientFor(transport);
      try {
        await assert.rejects(
          client.setRate(500),
          (error: unknown) => error instanceof FdtRefusedError && error.code === 'firmware',
          version,
        );
        assert.deepEqual(transport.written, [PROBE], `${version}: only the probe was sent`);
      } finally {
        await client.close();
      }
    }
  });

  test('a NACK to SET_FILTER is raised with its error code', async () => {
    const transport = new FakeTransport();
    transport.respond = device('001.002.008.020', (command) => [NACK(command, 3)]);
    const client = clientFor(transport);
    try {
      await assert.rejects(
        client.setRate(500),
        (error: unknown) => error instanceof FdtNackError && error.command === 0x1c && error.errorCode === 3,
      );
    } finally {
      await client.close();
    }
  });

  test('no ACK to SET_FILTER within the reply limit is a timeout', async () => {
    const transport = new FakeTransport();
    transport.respond = (frame) => (commandOf(frame) === 0x23 ? [firmwareReply('001.002.008.020')] : []);
    const client = clientFor(transport);
    try {
      await assert.rejects(
        client.setRate(500),
        (error: unknown) => error instanceof FdtTimeoutError && error.command === 0x1c,
      );
    } finally {
      await client.close();
    }
  });

  test('waits 100 ms after the ACK before it resolves', async () => {
    const transport = new FakeTransport();
    transport.respond = device('001.002.008.020', (command) => [ACK(command)]);
    const client = clientFor(transport);
    try {
      const started = Date.now();
      await client.setRate(500);
      assert.ok(Date.now() - started >= 90, `resolved after ${Date.now() - started} ms`);
    } finally {
      await client.close();
    }
  });
});

describe('FdtClient.setSyncMode and getSyncMode', () => {
  test('SET_SYNC_MODE sends six payload bytes and resolves on the ACK', async () => {
    const transport = new FakeTransport();
    transport.respond = (frame) => [ACK(commandOf(frame))];
    const client = clientFor(transport);
    try {
      // mode 0x18, period 1000 ms (e8 03), width, debounce and arm timeout 0 (firmware defaults).
      await client.setSyncMode(0x18);
      assert.deepEqual(transport.written, ['feed00002818e80300000012500404']);
    } finally {
      await client.close();
    }
  });

  test('SyncMode bits are the six named values, plus OFF', () => {
    assert.deepEqual(SyncMode, {
      OFF: 0x00,
      START_ON_RISE: 0x01,
      STOP_ON_FALL: 0x02,
      MASTER_OUT: 0x04,
      EVENT_FRAMES: 0x08,
      PULSE_TRAIN: 0x10,
      SATURATION_EVENTS: 0x20,
    });
  });

  test('NACK 7 means the firmware has no sync modes', async () => {
    const transport = new FakeTransport();
    transport.respond = (frame) => [NACK(commandOf(frame), 7)];
    const client = clientFor(transport);
    try {
      await assert.rejects(
        client.setSyncMode(SyncMode.START_ON_RISE),
        (error: unknown) =>
          error instanceof FdtRefusedError &&
          error.code === 'no_sync_modes' &&
          /no sync modes/.test(error.message),
      );
    } finally {
      await client.close();
    }
  });

  test('NACK 8 (stream running or armed) and NACK 3 (bad parameters) are refused with their codes', async () => {
    const busy = new FakeTransport();
    busy.respond = (frame) => [NACK(commandOf(frame), 8)];
    const busyClient = clientFor(busy);
    try {
      await assert.rejects(
        busyClient.setSyncMode(0x01),
        (error: unknown) => error instanceof FdtRefusedError && error.code === 'streaming',
      );
    } finally {
      await busyClient.close();
    }

    const bad = new FakeTransport();
    bad.respond = (frame) => [NACK(commandOf(frame), 3)];
    const badClient = clientFor(bad);
    try {
      await assert.rejects(
        badClient.setSyncMode(SyncMode.MASTER_OUT | SyncMode.PULSE_TRAIN),
        (error: unknown) => error instanceof FdtNackError && error.errorCode === 3,
      );
    } finally {
      await badClient.close();
    }
  });

  test('no reply is a timeout, and invalid values are refused before anything is sent', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      await assert.rejects(client.setSyncMode(0x01), (error: unknown) => error instanceof FdtTimeoutError);
      const invalid: Array<[number, number?]> = [[256], [-1], [1, 65536], [1, 1.5]];
      for (const [mode, period] of invalid) {
        await assert.rejects(client.setSyncMode(mode, period), RangeError, `mode ${mode} period ${period}`);
      }
    } finally {
      await client.close();
    }
  });

  test('a period whose bytes form 04 04 (1028) is refused by the frame encoder', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      await assert.rejects(
        client.setSyncMode(0x18, 1028),
        (error: unknown) => error instanceof FrameEncodeError && error.code === 'early_04_04_delimiter',
      );
      assert.deepEqual(transport.written, []);
    } finally {
      await client.close();
    }
  });

  test('getSyncMode returns null on NACK 7, the capability probe', async () => {
    const transport = new FakeTransport();
    transport.respond = (frame) => [NACK(commandOf(frame), 7)];
    const client = clientFor(transport);
    try {
      assert.equal(await client.getSyncMode(), null);
      assert.deepEqual(transport.written, ['feed000029d7790404']);
    } finally {
      await client.close();
    }
  });

  test('getSyncMode parses the 26-byte reply', async () => {
    // Body after BE EF: pa, 0x29, then bytes 4 to 21 of the reply. Byte 4 is the mode (0x18), 5-6 the period
    // (1000 ms, e8 03), 7 the width (2), 8 debounce (0), 9 arm timeout (5), 10 state (0x09 = armed + sync in high),
    // 11 contract (1), 12-15 edges in, 16-19 edges out, 20-21 overflows: all zero except those named here.
    const body = [0x00, 0x29, 0x18, 0xe8, 0x03, 0x02, 0x00, 0x05, 0x09, 0x01, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
    const state = reply(body);
    const transport = new FakeTransport();
    transport.respond = () => [state];
    const client = clientFor(transport);
    try {
      const parsed = await client.getSyncMode();
      assert.equal(parsed?.mode, 0x18);
      assert.equal(parsed?.pulsePeriodMs, 1000);
      assert.equal(parsed?.armed, true);
      assert.equal(parsed?.syncInHigh, true);
      assert.equal(parsed?.streaming, false);
    } finally {
      await client.close();
    }
  });
});

describe('FdtClient items, events and samples', () => {
  const EVENT: EventFrame = { timeStamp: 12345, eventType: 1, source: 0, count: 7, offsetUs: 0, detail: 0, mode: 0 };
  const A: StreamFrame = {
    platformAddress: 1,
    commandCode: 1,
    timeStamp: 100000,
    forceX: 100,
    forceY: 20,
    forceZ: 400,
    momentX: 30,
    momentY: -40,
    momentZ: 5,
  };
  const B: StreamFrame = { ...A, platformAddress: 2, timeStamp: 100020 };

  // Pushes bytes into the client's transport in 7-byte chunks, so the frames are split across reads.
  function pushChunked(transport: FakeTransport, bytes: Uint8Array): void {
    for (let i = 0; i < bytes.length; i += 7) transport.push(bytes.subarray(i, i + 7));
  }

  test('items() delivers stream frames and event frames in the order the controller sent them', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      const stream = new Uint8Array([...encodeStreamFrame(A), ...encodeEventFrame(EVENT), ...encodeStreamFrame(B)]);
      pushChunked(transport, stream);
      const seen = [];
      for await (const item of client.items()) {
        seen.push(item);
        if (seen.length === 3) break;
      }
      assert.deepEqual(seen, [
        { kind: 'frame', frame: A },
        { kind: 'event', event: EVENT },
        { kind: 'frame', frame: B },
      ]);
    } finally {
      await client.close();
    }
  });

  test('frames() skips event frames, and events() skips stream frames', async () => {
    const onlyFrames = new FakeTransport();
    const frameClient = clientFor(onlyFrames);
    const onlyEvents = new FakeTransport();
    const eventClient = clientFor(onlyEvents);
    try {
      const stream = new Uint8Array([...encodeStreamFrame(A), ...encodeEventFrame(EVENT), ...encodeStreamFrame(B)]);
      pushChunked(onlyFrames, stream);
      const frames: StreamFrame[] = [];
      for await (const frame of frameClient.frames()) {
        frames.push(frame);
        if (frames.length === 2) break;
      }
      assert.deepEqual(frames, [A, B]);

      pushChunked(onlyEvents, stream);
      const events: EventFrame[] = [];
      for await (const event of eventClient.events()) {
        events.push(event);
        break;
      }
      assert.deepEqual(events, [EVENT]);
    } finally {
      await frameClient.close();
      await eventClient.close();
    }
  });

  test('samples() yields Samples, gaps and events in the vocabulary, with the placeholder dropped', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      const placeholder: StreamFrame = { ...A, timeStamp: 0 };
      const second: StreamFrame = { ...A, timeStamp: 70 };
      const first: StreamFrame = { ...A, timeStamp: 20 };
      const event: EventFrame = { ...EVENT, timeStamp: 80 };
      const bytes = new Uint8Array([
        ...encodeStreamFrame(placeholder),
        ...encodeStreamFrame(first),
        ...encodeStreamFrame(second),
        ...encodeEventFrame(event),
      ]);
      pushChunked(transport, bytes);
      const kinds: string[] = [];
      for await (const item of client.samples(500)) {
        kinds.push(item.kind);
        if (item.kind === 'gap') assert.equal(item.missing, 1, 'a step of 2.5 periods rounds half to even: 2 - 1 = 1');
        if (item.kind === 'event') assert.equal(item.t, 0.008);
        if (kinds.length === 4) break;
      }
      assert.deepEqual(kinds, ['sample', 'gap', 'sample', 'event']);
    } finally {
      await client.close();
    }
  });
});
