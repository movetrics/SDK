import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { bytesOf, toHex } from './support.ts';
import { crc16CcittFalse } from '../src/crc.ts';
import { FrameEncodeError, ReplyFormatError } from '../src/errors.ts';
import { ReplyScanner } from '../src/frames.ts';
import {
  EVENT_NAMES,
  StreamDecoder,
  encodeEventFrame,
  encodeStreamFrame,
  eventName,
  parseEventFrame,
  parseSyncModeReply,
  type EventFrame,
  type StreamFrame,
} from '../src/stream.ts';

// Hex from the Python reference (independent computation from the 28 Oct layout): EventFrame(timeStamp=12345,
// type 1, source 0, count 7, offset 0, detail 0, mode 0).
const EVENT_HEX = 'beeffd0e39300000010007000000000000000000005a0404';

const EVENT: EventFrame = { timeStamp: 12345, eventType: 1, source: 0, count: 7, offsetUs: 0, detail: 0, mode: 0 };
const STREAM: StreamFrame = {
  platformAddress: 2,
  commandCode: 1,
  timeStamp: 123456,
  forceX: -1,
  forceY: 2,
  forceZ: -3,
  momentX: 4,
  momentY: -5,
  momentZ: 32767,
};

// Re-computes the CRC of a frame whose body was changed (bytes 2 to 19 for a 24-byte frame).
function withCrc(bytes: Uint8Array): Uint8Array {
  const out = Uint8Array.from(bytes);
  const crc = crc16CcittFalse(out.subarray(2, 20));
  out[20] = crc & 0xff;
  out[21] = crc >> 8;
  return out;
}

// One 26-byte GET_SYNC_MODE reply, built from its body (bytes 2 to 21) with CRC and 04 04.
function syncModeReply(body: readonly number[]): Uint8Array {
  const crc = crc16CcittFalse(Uint8Array.from(body));
  return Uint8Array.from([0xbe, 0xef, ...body, crc & 0xff, crc >> 8, 0x04, 0x04]);
}

describe('event frames', () => {
  test('encodeEventFrame gives the Python reference bytes, and parseEventFrame reads them back', () => {
    const encoded = encodeEventFrame(EVENT);
    assert.equal(encoded.length, 24);
    assert.equal(toHex(encoded), EVENT_HEX);
    assert.deepEqual(parseEventFrame(encoded), EVENT);
  });

  test('every field sits at its byte of the 28 Oct layout', () => {
    const event: EventFrame = { timeStamp: 0x01020304, eventType: 7, source: 2, count: 0x0a0b0c0d, offsetUs: -250, detail: 0x1234, mode: 0x18 };
    const bytes = encodeEventFrame(event);
    assert.deepEqual([...bytes.subarray(0, 4)], [0xbe, 0xef, 0xfd, 0x0e]);
    assert.deepEqual([...bytes.subarray(4, 8)], [0x04, 0x03, 0x02, 0x01]); // stamp, u32 LE
    assert.equal(bytes[8], 7); // type
    assert.equal(bytes[9], 2); // source
    assert.deepEqual([...bytes.subarray(10, 14)], [0x0d, 0x0c, 0x0b, 0x0a]); // counter, u32 LE
    assert.deepEqual([...bytes.subarray(14, 16)], [0x06, 0xff]); // offset_us, int16 LE (-250)
    assert.deepEqual([...bytes.subarray(16, 18)], [0x34, 0x12]); // detail, u16 LE
    assert.equal(bytes[18], 0x18); // mode
    assert.equal(bytes[19], 0); // reserved, zero
    assert.deepEqual(parseEventFrame(bytes), event);
  });

  test('the event time is stamp/10000 plus offset_us/1e6 (checked in the vocabulary)', () => {
    assert.equal(EVENT_NAMES[9], 'saturation_end');
    assert.equal(EVENT_NAMES[10], 'arm_expired');
    assert.equal(eventName(10), 'arm_expired');
    assert.equal(eventName(42), 'unknown_42');
  });

  test('out-of-range fields are refused before anything is built', () => {
    const cases: Array<[Partial<EventFrame>, string]> = [
      [{ eventType: 256 }, 'eventType'],
      [{ source: -1 }, 'source'],
      [{ offsetUs: 32768 }, 'offsetUs'],
      [{ detail: 0x10000 }, 'detail'],
      [{ mode: 256 }, 'mode'],
      [{ timeStamp: 0x100000000 }, 'timeStamp'],
    ];
    for (const [change, field] of cases) {
      assert.throws(
        () => encodeEventFrame({ ...EVENT, ...change }),
        (error: unknown) => error instanceof FrameEncodeError && error.code === 'bad_field',
        field,
      );
    }
  });

  test('a stream frame is not an event frame, and an event frame is not a stream frame', () => {
    const stream = encodeStreamFrame(STREAM);
    assert.throws(
      () => parseEventFrame(stream),
      (error: unknown) => error instanceof ReplyFormatError && error.code === 'bad_command',
    );
    assert.equal(new ReplyScanner().push(encodeEventFrame(EVENT))[0]?.kind, 'event');
  });

  test('a bad CRC or a wrong end marker gives the matching reason', () => {
    const flipped = Uint8Array.from(encodeEventFrame(EVENT));
    flipped[9] = (flipped[9] ?? 0) ^ 0x01;
    assert.throws(
      () => parseEventFrame(flipped),
      (error: unknown) => error instanceof ReplyFormatError && error.code === 'crc_mismatch',
    );
    const badEnd = Uint8Array.from(encodeEventFrame(EVENT));
    badEnd[23] = 0x05;
    assert.throws(
      () => parseEventFrame(badEnd),
      (error: unknown) => error instanceof ReplyFormatError && error.code === 'bad_end_marker',
    );
  });

  test('pushItems keeps stream frames and event frames in order, whatever the chunk size', () => {
    const second: StreamFrame = { ...STREAM, timeStamp: 123500 };
    const bytes = new Uint8Array([
      ...encodeStreamFrame(STREAM),
      ...encodeEventFrame(EVENT),
      ...bytesOf('beef011b06e3440404'), // a reply that is not a frame (ACK-like), skipped
      ...encodeStreamFrame(second),
      ...encodeEventFrame({ ...EVENT, eventType: 6, timeStamp: 12350 }),
    ]);
    const expected = [
      { kind: 'frame', frame: STREAM },
      { kind: 'event', event: EVENT },
      { kind: 'frame', frame: second },
      { kind: 'event', event: { ...EVENT, eventType: 6, timeStamp: 12350 } },
    ];
    assert.deepEqual(new StreamDecoder().pushItems(bytes), expected);

    const decoder = new StreamDecoder();
    const piecewise = [];
    for (let i = 0; i < bytes.length; i += 5) piecewise.push(...decoder.pushItems(bytes.subarray(i, i + 5)));
    assert.deepEqual(piecewise, expected);
  });

  test('push returns stream frames only, so the existing API does not see events', () => {
    const bytes = new Uint8Array([...encodeEventFrame(EVENT), ...encodeStreamFrame(STREAM)]);
    assert.deepEqual(new StreamDecoder().push(bytes), [STREAM]);
  });

  test('an event frame with a bad CRC is not delivered, and does not stop the stream', () => {
    const bad = withCrc(encodeEventFrame(EVENT));
    bad[20] = (bad[20] ?? 0) ^ 0xff;
    const bytes = new Uint8Array([...bad, ...encodeStreamFrame(STREAM)]);
    assert.deepEqual(new StreamDecoder().pushItems(bytes), [{ kind: 'frame', frame: STREAM }]);
  });

  test('a 26-byte GET_SYNC_MODE reply is recognised, parsed and kept out of the stream', () => {
    const body = [0x00, 0x29, 0x18, 0xe8, 0x03, 0x00, 0x00, 0x00, 0x01, 0x00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
    const reply = syncModeReply(body);
    assert.equal(reply.length, 26);
    assert.equal(new ReplyScanner().push(reply)[0]?.kind, 'sync_mode');
    assert.deepEqual(new StreamDecoder().pushItems(new Uint8Array([...reply, ...encodeStreamFrame(STREAM)])), [
      { kind: 'frame', frame: STREAM },
    ]);
    const state = parseSyncModeReply(reply);
    assert.equal(state.mode, 0x18);
    assert.equal(state.pulsePeriodMs, 1000);
    assert.equal(state.armed, true);
  });
});
