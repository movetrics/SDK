import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { bytesOf, toHex } from './support.ts';
import { vectorCase } from './vectors-data.ts';
import { crc16CcittFalse } from '../src/crc.ts';
import { IMPLEMENTED_CODES, NOT_IMPLEMENTED, NOT_IMPLEMENTED_CODES } from '../src/commands.ts';
import { FrameEncodeError } from '../src/errors.ts';
import {
  HOST_MESSAGE_MAX,
  HostRxSplitter,
  ReplyScanner,
  buildHostFrame,
  earlyDelimiterAt,
  encodeHostFrame,
  parseHostMessage,
  type ScannedReply,
} from '../src/frames.ts';

describe('encodeHostFrame', () => {
  test('command 0x1B is refused as not implemented, and the worked frame of docs/04 table 4.1 is attached', () => {
    assert.throws(
      () => encodeHostFrame({ address: 0x01, destination: 0x00, command: 0x1b }),
      (error: unknown) => {
        assert.ok(error instanceof FrameEncodeError);
        assert.equal(error.code, 'not_implemented');
        assert.equal(toHex(error.frame), 'feed01001bf6580404');
        assert.match(error.message, /0x1b \(SET_TARE\) is not implemented: no vector covers 0x1B/);
        return true;
      },
    );
  });

  test('every NOT_IMPLEMENTED command is refused, and no implemented command is listed there', () => {
    for (const entry of NOT_IMPLEMENTED) {
      assert.throws(
        () => encodeHostFrame({ address: 0, destination: 0, command: entry.code }),
        (error: unknown) => {
          assert.ok(error instanceof FrameEncodeError, entry.name);
          assert.equal(error.code, 'not_implemented', entry.name);
          return true;
        },
      );
    }
    for (const command of IMPLEMENTED_CODES) assert.equal(NOT_IMPLEMENTED_CODES.has(command), false);
  });

  test('GET_STATUS to FF/FF is refused, and the refused frame is reported', () => {
    assert.throws(
      () => encodeHostFrame({ address: 0xff, destination: 0xff, command: 0x22 }),
      (error: unknown) => {
        assert.ok(error instanceof FrameEncodeError);
        assert.equal(error.code, 'early_04_04_delimiter');
        assert.equal(toHex(error.frame), 'feedffff2220040404');
        return true;
      },
    );
  });

  test('the early delimiter index points at the second 04 of the first pair', () => {
    assert.equal(earlyDelimiterAt(bytesOf('feedffff2220040404')), 7);
    assert.equal(earlyDelimiterAt(bytesOf('feed000022bcc80404')), -1);
  });

  test('bytes outside 0 to 255 are refused as bad fields', () => {
    assert.throws(() => buildHostFrame({ address: 256, destination: 0, command: 0x22 }), (error: unknown) => {
      assert.ok(error instanceof FrameEncodeError);
      assert.equal(error.code, 'bad_field');
      return true;
    });
  });

  test('a request longer than the 320-byte host limit is refused', () => {
    const payload = new Uint8Array(HOST_MESSAGE_MAX - 9 + 1);
    assert.throws(() => buildHostFrame({ address: 0, destination: 0, command: 0x26, payload }), (error: unknown) => {
      assert.ok(error instanceof FrameEncodeError);
      assert.equal(error.code, 'too_long');
      return true;
    });
  });
});

describe('HostRxSplitter', () => {
  test('delivers one message per 04 04 pair, the same whatever the chunking', () => {
    const stream = bytesOf('feed000022bcc80404' + 'feed0000239dd80404');
    const whole = new HostRxSplitter().push(stream).map(toHex);
    assert.deepEqual(whole, ['feed000022bcc80404', 'feed0000239dd80404']);

    const splitter = new HostRxSplitter();
    const bytewise: string[] = [];
    for (const byte of stream) {
      for (const message of splitter.push(Uint8Array.of(byte))) bytewise.push(toHex(message));
    }
    assert.deepEqual(bytewise, whole);
  });

  test('a message longer than 320 bytes is dropped, and the next message is delivered', () => {
    const splitter = new HostRxSplitter();
    const oversize = new Uint8Array(HOST_MESSAGE_MAX + 1).fill(0x11);
    assert.deepEqual(splitter.push(oversize), []);
    assert.deepEqual(splitter.push(bytesOf('0404')), []);
    assert.deepEqual(splitter.push(bytesOf('feed000022bcc80404')).map(toHex), ['feed000022bcc80404']);
  });
});

describe('parseHostMessage', () => {
  test('command 00 is read and never answered', () => {
    const parsed = parseHostMessage(encodeHostFrame({ address: 0, destination: 0, command: 0x00 }));
    assert.ok(parsed.valid);
    assert.deepEqual(parsed.device_reply, { reply: 'none', reason: 'no_command' });
    assert.equal(parsed.dispatched, false);
  });

  test('KEEP_ALIVE with a valid payload is dispatched and gets no reply on success', () => {
    const parsed = parseHostMessage(bytesOf('feed00002658023e820404'));
    assert.ok(parsed.valid);
    assert.deepEqual(parsed.device_reply, { reply: 'none', reason: 'no_reply_on_success' });
    assert.equal(parsed.dispatched, true);
    assert.equal(toHex(parsed.payload), '5802');
  });

  test('a command outside the firmware dispatch table gets NACK 7', () => {
    const parsed = parseHostMessage(buildHostFrame({ address: 0, destination: 0, command: 0x02 }));
    assert.ok(parsed.valid);
    assert.deepEqual(parsed.device_reply, { nack_code: 7 });
    assert.equal(parsed.dispatched, false);
  });

  test('SET_FILTER (0x1C) with a 2-byte payload gets NACK 3, because it needs 3 bytes', () => {
    const frame = buildHostFrame({ address: 0, destination: 0, command: 0x1c, payload: Uint8Array.of(1, 2) });
    const parsed = parseHostMessage(frame);
    assert.ok(parsed.valid);
    assert.deepEqual(parsed.device_reply, { nack_code: 3 });
    assert.equal(parsed.dispatched, false);
  });
});

// errorFlags starts at offset 4, the byte where ACK and NACK markers are read. This copies
// a status record, sets that byte, and recomputes the CRC so the record stays valid.
function withErrorFlagsLowByte(hex: string, value: number): Uint8Array {
  const bytes = bytesOf(hex);
  bytes[4] = value;
  const crc = crc16CcittFalse(bytes.subarray(2, bytes.length - 4));
  bytes[bytes.length - 4] = crc & 0xff;
  bytes[bytes.length - 3] = crc >> 8;
  return bytes;
}

function scanAll(chunks: readonly string[]): ScannedReply[] {
  const scanner = new ReplyScanner();
  const out: ScannedReply[] = [];
  for (const chunk of chunks) out.push(...scanner.push(bytesOf(chunk)));
  return out;
}

describe('ReplyScanner', () => {
  test('finds an ACK and a NACK in one chunk', () => {
    const replies = scanAll(['beef0105069f640404' + 'beef02051502003b270404']);
    assert.deepEqual(
      replies.map((reply) => [reply.kind, reply.command, reply.platformAddress, reply.errorCode]),
      [
        ['ack', 0x05, 1, null],
        ['nack', 0x05, 2, 2],
      ],
    );
  });

  test('a broadcast ACK keeps FF as the platform address', () => {
    const [reply] = scanAll(['beefff0506cc9c0404']);
    assert.equal(reply?.kind, 'ack');
    assert.equal(reply?.platformAddress, 0xff);
  });

  test('the three-record GET_STATUS reply is found whatever the chunk boundaries', () => {
    const bytes = bytesOf(vectorCase('status-derived-86x3-reply').frame_hex ?? '');
    assert.equal(bytes.length, 258);
    for (let cut = 1; cut < bytes.length; cut++) {
      const scanner = new ReplyScanner();
      const found = [...scanner.push(bytes.subarray(0, cut)), ...scanner.push(bytes.subarray(cut))];
      assert.deepEqual(
        found.map((reply) => [reply.kind, reply.bytes.length]),
        [
          ['status', 86],
          ['status', 86],
          ['status', 86],
        ],
        `cut at ${cut}`,
      );
    }
  });

  test('a status record whose errorFlags low byte is 15 is not taken for a NACK', () => {
    const record = withErrorFlagsLowByte(vectorCase('status-derived-86-general-record').frame_hex ?? '', 0x15);
    const scanner = new ReplyScanner();
    assert.deepEqual(scanner.push(record.subarray(0, 40)), []);
    const complete = scanner.push(record.subarray(40));
    assert.deepEqual(
      complete.map((reply) => [reply.kind, reply.bytes.length]),
      [['status', 86]],
    );
  });

  test('stream frames, an ACK and garbage interleave without loss', () => {
    const stream = vectorCase('stream-derived-encode-platform-2-sample').expect_frame_hex ?? '';
    const replies = scanAll(['aa55', stream, 'beef0105069f640404', '00', stream]);
    assert.deepEqual(
      replies.map((reply) => reply.kind),
      ['stream', 'ack', 'stream'],
    );
  });

  test('a lone BE at the end of a chunk is kept for the next chunk', () => {
    const scanner = new ReplyScanner();
    assert.deepEqual(scanner.push(bytesOf('be')), []);
    const [reply] = scanner.push(bytesOf('ef0105069f640404'));
    assert.equal(reply?.kind, 'ack');
  });
});
