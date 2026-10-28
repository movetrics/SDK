import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { bytesOf, toHex } from './support.ts';
import { vectorCase } from './vectors-data.ts';
import { crc16CcittFalse } from '../src/crc.ts';
import { FrameEncodeError, ReplyFormatError } from '../src/errors.ts';
import {
  StreamDecoder,
  decodeStreamFrame,
  encodeStreamFrame,
  parseStreamFrame,
  type StreamFrame,
} from '../src/stream.ts';

const SAMPLE: StreamFrame = {
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

// Reason code of the parse, or 'valid'.
function reasonOf(bytes: Uint8Array): string {
  try {
    parseStreamFrame(bytes);
    return 'valid';
  } catch (error) {
    if (error instanceof ReplyFormatError) return error.code;
    throw error;
  }
}

describe('parseStreamFrame and encodeStreamFrame', () => {
  test('a sample encodes to the frame in the vector, and decodes back to itself', () => {
    const encoded = encodeStreamFrame(SAMPLE);
    assert.equal(toHex(encoded), vectorCase('stream-derived-encode-platform-2-sample').expect_frame_hex);
    assert.deepEqual(parseStreamFrame(encoded), SAMPLE);
  });

  test('the int16 and uint32 limits round-trip', () => {
    const extreme: StreamFrame = {
      platformAddress: 255,
      commandCode: 1,
      timeStamp: 0xffffffff,
      forceX: -32768,
      forceY: 32767,
      forceZ: -32768,
      momentX: 32767,
      momentY: -32768,
      momentZ: 0,
    };
    assert.deepEqual(parseStreamFrame(encodeStreamFrame(extreme)), extreme);
  });

  test('out-of-range fields are refused before anything is built', () => {
    const cases: Array<[Partial<StreamFrame>, string]> = [
      [{ platformAddress: 256 }, 'platformAddress'],
      [{ commandCode: 2 }, 'commandCode'],
      [{ timeStamp: 0x100000000 }, 'timeStamp'],
      [{ forceX: 32768 }, 'forceX'],
      [{ momentZ: -32769 }, 'momentZ'],
      [{ forceY: 1.5 }, 'forceY'],
    ];
    for (const [change, field] of cases) {
      assert.throws(
        () => encodeStreamFrame({ ...SAMPLE, ...change }),
        (error: unknown) => {
          assert.ok(error instanceof FrameEncodeError, field);
          assert.equal(error.code, 'bad_field', field);
          return true;
        },
      );
    }
  });

  test('a vector frame decodes to its named fields', () => {
    const frame = parseStreamFrame(bytesOf(vectorCase('stream-derived-decode-fdt-index-19056').frame_hex ?? ''));
    assert.deepEqual(frame, {
      platformAddress: 1,
      commandCode: 1,
      timeStamp: 200069,
      forceX: -34,
      forceY: 0,
      forceZ: 5,
      momentX: -1,
      momentY: 0,
      momentZ: 2,
    });
  });

  test('a wrong length, header, end marker or command gives the matching reason', () => {
    const good = bytesOf(vectorCase('stream-anchor-fdt-index-0').frame_hex ?? '');
    assert.equal(reasonOf(good.subarray(0, 23)), 'bad_length');
    assert.equal(reasonOf(Uint8Array.from([...good, 0])), 'bad_length');

    const badHeader = Uint8Array.from(good);
    badHeader[0] = 0xef;
    badHeader[1] = 0xbe;
    assert.equal(reasonOf(badHeader), 'bad_header');

    // The CRC covers bytes 2 to 19 only, so a changed end marker leaves it valid.
    const badEnd = Uint8Array.from(good);
    badEnd[23] = 0x05;
    assert.equal(reasonOf(badEnd), 'bad_end_marker');

    // A changed command byte is inside the CRC, so the CRC is recomputed for this case.
    const badCommand = encodeStreamFrame(SAMPLE);
    badCommand[3] = 0x22;
    badCommand[20] = 0;
    badCommand[21] = 0;
    const crc = crc16CcittFalse(badCommand.subarray(2, 20));
    badCommand[20] = crc & 0xff;
    badCommand[21] = crc >> 8;
    assert.equal(reasonOf(badCommand), 'bad_command');
  });

  test('decodeStreamFrame reports the reason as a value', () => {
    const good = bytesOf(vectorCase('stream-anchor-fdt-index-0').frame_hex ?? '');
    const flipped = Uint8Array.from(good);
    flipped[9] = (flipped[9] ?? 0) ^ 0x01;
    assert.deepEqual(decodeStreamFrame(flipped), { valid: false, reason: 'crc_mismatch' });
    assert.equal(decodeStreamFrame(good).valid, true);
  });
});

describe('StreamDecoder', () => {
  test('returns the stream frames from a mixed stream, whatever the chunk size', () => {
    const placeholder: StreamFrame = { ...SAMPLE, platformAddress: 1, timeStamp: 0 };
    const stream = new Uint8Array([
      ...encodeStreamFrame(placeholder),
      ...bytesOf('beef011b06e3440404'),
      ...encodeStreamFrame(SAMPLE),
    ]);

    const whole = new StreamDecoder().push(stream);
    assert.deepEqual(whole, [placeholder, SAMPLE]);

    const decoder = new StreamDecoder();
    const piecewise: StreamFrame[] = [];
    for (let i = 0; i < stream.length; i += 5) {
      piecewise.push(...decoder.push(stream.subarray(i, i + 5)));
    }
    assert.deepEqual(piecewise, whole);
  });

  test('a firmware version reply in the stream yields no stream frame', () => {
    const reply = bytesOf(vectorCase('ota-anchor-identification-fw-version-reply').frame_hex ?? '');
    assert.deepEqual(new StreamDecoder().push(reply), []);
  });
});
