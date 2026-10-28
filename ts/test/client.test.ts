import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { bytesOf, FakeTransport, tick, toHex } from './support.ts';
import { vectorCase } from './vectors-data.ts';
import { crc16CcittFalse } from '../src/crc.ts';
import { COMMANDS, IMPLEMENTED_CODES } from '../src/commands.ts';
import { FdtClient, type ClientOptions } from '../src/client.ts';
import { FdtClosedError, FdtNackError, FdtTimeoutError } from '../src/errors.ts';
import { encodeStreamFrame, type StreamFrame } from '../src/stream.ts';

// Short limits, so the timing tests run quickly.
const FAST: ClientOptions = {
  timeouts: { reply: 60, status: 400, statusQuiet: 30, settle: 20 },
};

function clientFor(transport: FakeTransport, options: ClientOptions = FAST): FdtClient {
  return new FdtClient(transport, options);
}

// Builds one device reply from the bytes after BE EF: [pa, command, ...], adding the CRC and 04 04.
function reply(body: readonly number[]): Uint8Array {
  const crc = crc16CcittFalse(Uint8Array.from(body));
  return Uint8Array.from([0xbe, 0xef, ...body, crc & 0xff, crc >> 8, 0x04, 0x04]);
}

const FW_REPLY = bytesOf(vectorCase('ota-anchor-identification-fw-version-reply').frame_hex ?? '');
const STATUS_RECORDS = bytesOf(vectorCase('status-derived-86x3-reply').frame_hex ?? '');
const ONE_STATUS = bytesOf(vectorCase('status-derived-86-general-record').frame_hex ?? '');
const STATUS_PLATFORM_2 = bytesOf(vectorCase('status-derived-86-platform-2-record').frame_hex ?? '');
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

// The command byte of a written frame (FE ED pa da cmd, so hex characters 8 and 9).
function commandOf(hex: string): number {
  return Number.parseInt(hex.slice(8, 10), 16);
}

describe('FdtClient requests', () => {
  test('getFwVersion sends the version probe to 00/00 and reads the 38-byte reply', async () => {
    const transport = new FakeTransport();
    transport.respond = () => [FW_REPLY];
    const client = clientFor(transport);
    try {
      const version = await client.getFwVersion();
      assert.deepEqual(version, { platformAddress: 0, commandCode: 0x23, stm32FW: '001.002.003', esp32FW: '002.005.001' });
      assert.deepEqual(transport.written, ['feed0000239dd80404']);
    } finally {
      await client.close();
    }
  });

  test('getStatus reads the three records of a discovery reply', async () => {
    const transport = new FakeTransport();
    transport.respond = () => [STATUS_RECORDS];
    const client = clientFor(transport);
    try {
      const status = await client.getStatus();
      assert.equal(status.lengthClass, '86x3');
      assert.equal(status.general.batterySOC, 87);
      assert.deepEqual(
        status.platforms.map((record) => record.platformAddress),
        [1, 2],
      );
      assert.deepEqual(transport.written, ['feed000022bcc80404']);
    } finally {
      await client.close();
    }
  });

  test('getStatus keeps reading records that arrive within the quiet period', async () => {
    const transport = new FakeTransport();
    const first = ONE_STATUS;
    const second = STATUS_PLATFORM_2;
    transport.respond = () => {
      setTimeout(() => transport.push(second), 10);
      return [first];
    };
    const client = clientFor(transport);
    try {
      const status = await client.getStatus();
      assert.equal(status.lengthClass, '86x2');
    } finally {
      await client.close();
    }
  });

  test('getStatus ends at the quiet period, and a later record is not added to the reply', async () => {
    const transport = new FakeTransport();
    transport.respond = () => {
      setTimeout(() => transport.push(STATUS_PLATFORM_2), 150);
      return [ONE_STATUS];
    };
    const client = clientFor(transport);
    try {
      const status = await client.getStatus();
      assert.equal(status.lengthClass, '86');
      assert.deepEqual(status.platforms, []);
    } finally {
      await client.close();
    }
  });

  test('getStatus with no reply rejects with a timeout for 0x22', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      await assert.rejects(client.getStatus(), (error: unknown) => {
        assert.ok(error instanceof FdtTimeoutError);
        assert.equal(error.command, 0x22);
        return true;
      });
    } finally {
      await client.close();
    }
  });

  test('a NACK to a request is raised with its error name', async () => {
    const transport = new FakeTransport();
    transport.respond = () => [reply([0x00, 0x23, 0x15, 0x01, 0x00])];
    const client = clientFor(transport);
    try {
      await assert.rejects(client.getFwVersion(), (error: unknown) => {
        assert.ok(error instanceof FdtNackError);
        assert.equal(error.errorCode, 1);
        assert.equal(error.message, 'controller NACK 1 (ERR_PLATFORM_NOT_EXIST) to command 0x23');
        return true;
      });
    } finally {
      await client.close();
    }
  });

  test('a stream frame that arrives during a request goes to frames() and the reply still resolves', async () => {
    const transport = new FakeTransport();
    transport.respond = () => [encodeStreamFrame(SAMPLE), FW_REPLY];
    const client = clientFor(transport);
    try {
      const version = await client.getFwVersion();
      assert.equal(version.stm32FW, '001.002.003');
      const iterator = client.frames()[Symbol.asyncIterator]();
      assert.deepEqual(await iterator.next(), { value: SAMPLE, done: false });
    } finally {
      await client.close();
    }
  });

  test('a write that fails rejects the request with the write error', async () => {
    const transport = new FakeTransport();
    transport.writeError = new Error('bus busy');
    const client = clientFor(transport);
    try {
      await assert.rejects(client.getFwVersion(), /bus busy/);
    } finally {
      await client.close();
    }
  });

  test('requests run one at a time, in call order, and each gets its own reply', async () => {
    const transport = new FakeTransport();
    transport.respond = (frame) => (commandOf(toHex(frame)) === 0x23 ? [FW_REPLY] : [STATUS_RECORDS]);
    const client = clientFor(transport);
    try {
      const [version, status] = await Promise.all([client.getFwVersion(), client.getStatus()]);
      assert.equal(version.esp32FW, '002.005.001');
      assert.equal(status.lengthClass, '86x3');
      assert.deepEqual(
        transport.written.map((hex) => commandOf(hex)),
        [0x23, 0x22],
      );
    } finally {
      await client.close();
    }
  });
});

describe('FdtClient commands without a success reply', () => {
  test('startStream sends START to FF/FF and resolves when no NACK follows', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      await client.startStream();
      assert.deepEqual(transport.written, ['feedffff0121100404']);
    } finally {
      await client.close();
    }
  });

  test('startStream rejects with a NACK that arrives in the settle window', async () => {
    const transport = new FakeTransport();
    transport.respond = () => [reply([0xff, 0x01, 0x15, 0x08, 0x00])];
    const client = clientFor(transport);
    try {
      await assert.rejects(client.startStream(), (error: unknown) => {
        assert.ok(error instanceof FdtNackError);
        assert.equal(error.errorCode, 8);
        assert.equal(error.command, 0x01);
        return true;
      });
    } finally {
      await client.close();
    }
  });

  test('keepAlive sends the interval as uint16 little-endian and does not wait', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      await client.keepAlive(600);
      assert.deepEqual(transport.written, ['feed00002658023e820404']);
    } finally {
      await client.close();
    }
  });

  test('keepAlive refuses 0, which would turn the sleep off, and values out of range', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      await assert.rejects(client.keepAlive(0), RangeError);
      await assert.rejects(client.keepAlive(65536), RangeError);
      await assert.rejects(client.keepAlive(1.5), RangeError);
      assert.deepEqual(transport.written, []);
    } finally {
      await client.close();
    }
  });
});

describe('FdtClient stop', () => {
  test('stopStream sends STOP to FF/00 and resolves on the ACK', async () => {
    const transport = new FakeTransport();
    transport.respond = () => [reply([0xff, 0x05, 0x06])];
    const client = clientFor(transport);
    try {
      await client.stopStream();
      assert.deepEqual(transport.written, ['feedff00055a530404']);
    } finally {
      await client.close();
    }
  });});

describe('FdtClient stream frames', () => {
  test('frames() yields the stream frames in order', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    try {
      transport.push(Uint8Array.from([...encodeStreamFrame(SAMPLE), ...encodeStreamFrame({ ...SAMPLE, timeStamp: 1 })]));
      const seen: StreamFrame[] = [];
      for await (const frame of client.frames()) {
        seen.push(frame);
        if (seen.length === 2) break;
      }
      assert.deepEqual(seen, [SAMPLE, { ...SAMPLE, timeStamp: 1 }]);
    } finally {
      await client.close();
    }
  });

  test('a full backlog drops the oldest frame and counts it', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport, { ...FAST, frameBacklog: 2 });
    try {
      const frames = [0, 1, 2].map((timeStamp) => encodeStreamFrame({ ...SAMPLE, timeStamp }));
      transport.push(Uint8Array.from(frames.flatMap((frame) => [...frame])));
      await tick();
      assert.equal(client.droppedFrames, 1);
      const seen: number[] = [];
      for await (const frame of client.frames()) {
        seen.push(frame.timeStamp);
        if (seen.length === 2) break;
      }
      assert.deepEqual(seen, [1, 2]);
    } finally {
      await client.close();
    }
  });
});

describe('FdtClient lifetime', () => {
  test('close rejects a pending request, ends frames(), and closes the transport', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    const pending = client.getStatus();
    await tick();
    await client.close();
    await assert.rejects(pending, FdtClosedError);
    assert.equal(transport.closeCalls, 1);
    const drained: StreamFrame[] = [];
    for await (const frame of client.frames()) drained.push(frame);
    assert.deepEqual(drained, []);
    await assert.rejects(client.getFwVersion(), FdtClosedError);
  });

  test('when the transport ends, a pending request rejects and later requests fail at once', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport, { timeouts: { reply: 5000 } });
    const pending = client.getFwVersion();
    await tick();
    transport.end();
    await assert.rejects(pending, (error: unknown) => {
      assert.ok(error instanceof FdtClosedError);
      assert.equal(error.message, 'the transport closed');
      return true;
    });
    await assert.rejects(client.getFwVersion(), FdtClosedError);
    await client.close();
  });

  test('a transport error ends frames() with that error', async () => {
    const transport = new FakeTransport();
    const client = clientFor(transport);
    transport.end(new Error('unplugged'));
    await assert.rejects(async () => {
      for await (const _frame of client.frames()) {
        // Nothing arrives after the error.
      }
    }, /unplugged/);
    await client.close();
  });

  test('the timeout options must be positive numbers', () => {
    assert.throws(() => new FdtClient(new FakeTransport(), { timeouts: { reply: 0 } }), RangeError);
    assert.throws(() => new FdtClient(new FakeTransport(), { frameBacklog: 0 }), RangeError);
  });

  test('every frame written during a session is one of the implemented commands', async () => {
    const transport = new FakeTransport();
    transport.respond = (frame) => {
      const command = commandOf(toHex(frame));
      if (command === COMMANDS.GET_FW_VERSION.code) return [FW_REPLY];
      if (command === COMMANDS.GET_STATUS.code) return [STATUS_RECORDS];
      if (command === COMMANDS.STOP_STREAM.code) return [reply([0xff, 0x05, 0x06])];
      return [];
    };
    const client = clientFor(transport);
    try {
      await client.getFwVersion();
      await client.getStatus();
      await client.startStream();
      await client.keepAlive(600);
      await client.stopStream();
      assert.ok(transport.written.length === 5);
      for (const hex of transport.written) assert.ok(IMPLEMENTED_CODES.has(commandOf(hex)), hex);
    } finally {
      await client.close();
    }
  });
});

describe('FdtClient command set', () => {
  test('the client implements eight commands: START_STREAM, STOP_STREAM, GET_STATUS, GET_FW_VERSION, KEEP_ALIVE, SET_FILTER, SET_SYNC_MODE (draft) and GET_SYNC_MODE (draft)', () => {
    assert.deepEqual([...IMPLEMENTED_CODES].sort((a, b) => a - b), [0x01, 0x05, 0x1c, 0x22, 0x23, 0x26, 0x28, 0x29]);
  });
});
