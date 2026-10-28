// Runs the byte-level vectors in sdk/vectors against this client. Every case in the vector
// files is either checked here or listed below with the reason it is out of scope. No
// anchor is out of scope, and no case is skipped. Deliberate deviations from the pinned
// reference parser are marked "DEVIATION" and explained in ts/README.md.

import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { bytesOf, toHex } from './support.ts';
import { PUBLIC_REPOSITORY, VECTOR_FILE_NAMES, loadVectors, type VectorCase, type VectorFile } from './vectors-data.ts';
import { crc16CcittFalse } from '../src/crc.ts';
import { IMPLEMENTED_CODES } from '../src/commands.ts';
import { FrameEncodeError } from '../src/errors.ts';
import {
  HostRxSplitter,
  ReplyScanner,
  buildHostFrame,
  encodeHostFrame,
  parseHostMessage,
  type HostRequest,
} from '../src/frames.ts';
import { decodeStreamFrame, encodeStreamFrame, parseStreamFrame, type StreamFrame } from '../src/stream.ts';
import { parseFirmwareVersion, parseStatus, parseStatusRecord } from '../src/status.ts';

const FILE_NAMES = VECTOR_FILE_NAMES;

// Whole files that the host link never carries. Their cases are counted as out of scope.
const OUT_OF_SCOPE_FILES: Readonly<Record<string, string>> = {
  'pad_bus.json': 'RS-485 frames between the controller and the pads. The host link never carries them (docs/07-pad-bus.md).',
  'boot_frames.json':
    'Pad bootloader frames (07 b0 and 08 b0). The host link never carries them (docs/08-pad-firmware-and-bootloader.md).',
};

// Single cases in scope files that are out of scope, with the reason.
const OUT_OF_SCOPE_CASES: Readonly<Record<string, string>> = {
  'ota-derived-request-status-s': 'FIRMWARE_UPDATE (0x40) is not implemented (commands.ts NOT_IMPLEMENTED).',
  'ota-derived-request-data-salted': 'FIRMWARE_UPDATE (0x40) is not implemented (commands.ts NOT_IMPLEMENTED).',
  'ota-derived-reply-ok': 'The 18-byte FIRMWARE_UPDATE reply (0x40) is not implemented.',
  'ota-derived-reply-param-error': 'The 18-byte FIRMWARE_UPDATE reply (0x40) is not implemented.',
};

type Check = (vector: VectorCase) => void;

function must<T>(value: T | undefined, what: string): T {
  if (value === undefined) throw new Error(`vector field ${what} is missing`);
  return value;
}

function hexByte(hex: string | undefined, what: string): number {
  const value = Number.parseInt(must(hex, what), 16);
  if (Number.isNaN(value)) throw new Error(`vector field ${what} is not a hex byte`);
  return value;
}

function byteHex(value: number): string {
  return value.toString(16).padStart(2, '0');
}

// Reads the named fields of an object. platform_address maps to platformAddress, the other names match.
function projectFields(record: object, keys: readonly string[]): Record<string, unknown> {
  const source = record as unknown as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const key of keys) out[key] = source[key === 'platform_address' ? 'platformAddress' : key];
  return out;
}

// ---- crc16.json ----------------------------------------------------------------------

function checkCrc(vector: VectorCase): void {
  const input = bytesOf(vector.input_hex ?? '');
  const crc = crc16CcittFalse(input);
  assert.equal(crc.toString(16).padStart(4, '0'), vector.crc_hex);
  if (vector.stored_hex !== undefined) {
    assert.equal(toHex(Uint8Array.of(crc & 0xff, crc >> 8)), vector.stored_hex);
  }
  if (vector.frame_hex !== undefined) {
    assert.equal(
      toHex(buildHostFrame({ address: input[0] ?? 0, destination: input[1] ?? 0, command: input[2] ?? 0 })),
      vector.frame_hex,
    );
  }
}

// ---- host_frames.json ----------------------------------------------------------------

function checkHostAnchor(vector: VectorCase): void {
  const parsed = parseHostMessage(bytesOf(must(vector.frame_hex, 'frame_hex')));
  if (!parsed.valid) throw new Error(`${vector.id} does not parse as a host message`);
  const expect = must(vector.expect, 'expect');
  assert.equal(expect.valid, true);
  assert.equal(byteHex(parsed.command), expect.command);
  assert.equal(toHex(parsed.payload), expect.payload_hex);
}

function checkHostEncode(vector: VectorCase): void {
  const request: HostRequest = {
    address: hexByte(vector.address_hex, 'address_hex'),
    destination: hexByte(vector.destination_hex, 'destination_hex'),
    command: hexByte(vector.command, 'command'),
    payload: bytesOf(vector.payload_hex ?? ''),
  };
  if (vector.expect_frame_hex === null) {
    assert.throws(
      () => encodeHostFrame(request),
      (error: unknown) => {
        assert.ok(error instanceof FrameEncodeError);
        assert.equal(error.code, vector.expect_error);
        assert.equal(toHex(error.frame), vector.would_be_frame_hex);
        return true;
      },
    );
    return;
  }
  // The builder gives the bytes for any command. The encoder must give them for a command
  // the client sends, and must refuse a command in NOT_IMPLEMENTED (not_implemented).
  assert.equal(toHex(buildHostFrame(request)), vector.expect_frame_hex);
  if (IMPLEMENTED_CODES.has(request.command)) {
    assert.equal(toHex(encodeHostFrame(request)), vector.expect_frame_hex);
    return;
  }
  assert.throws(
    () => encodeHostFrame(request),
    (error: unknown) => {
      assert.ok(error instanceof FrameEncodeError);
      assert.equal(error.code, 'not_implemented');
      return true;
    },
  );
}

function checkHostDecode(vector: VectorCase): void {
  const messages = new HostRxSplitter().push(bytesOf(must(vector.frame_hex, 'frame_hex'))).map(toHex);
  assert.deepEqual(messages, vector.rx_messages_hex);
  const expect = must(vector.expect, 'expect');
  for (const message of messages) {
    const parsed = parseHostMessage(bytesOf(message));
    assert.equal(parsed.valid, expect.valid, vector.id);
    assert.deepEqual(parsed.device_reply, expect.device_reply, vector.id);
    assert.equal(parsed.dispatched, expect.dispatched, vector.id);
    if (parsed.valid && expect.command !== undefined) {
      assert.equal(byteHex(parsed.command), expect.command, vector.id);
      assert.equal(toHex(parsed.payload), expect.payload_hex, vector.id);
    }
  }
}

// ---- stream_frames.json --------------------------------------------------------------

function streamFrameFrom(fields: Readonly<Record<string, unknown>>): StreamFrame {
  const num = (name: string): number => {
    const value = fields[name];
    if (typeof value !== 'number') throw new Error(`stream field ${name} is not a number`);
    return value;
  };
  return {
    platformAddress: num('platform_address'),
    commandCode: num('commandCode'),
    timeStamp: num('timeStamp'),
    forceX: num('forceX'),
    forceY: num('forceY'),
    forceZ: num('forceZ'),
    momentX: num('momentX'),
    momentY: num('momentY'),
    momentZ: num('momentZ'),
  };
}

function checkStream(vector: VectorCase): void {
  const expect = must(vector.expect, 'expect');
  if (expect.valid === false) {
    assert.deepEqual(decodeStreamFrame(bytesOf(must(vector.frame_hex, 'frame_hex'))), {
      valid: false,
      reason: expect.reason,
    });
    return;
  }
  if (vector.expect_frame_hex !== undefined && vector.expect_frame_hex !== null) {
    const frame = streamFrameFrom(must(expect.fields, 'expect.fields'));
    assert.equal(toHex(encodeStreamFrame(frame)), vector.expect_frame_hex);
    assert.deepEqual(projectFields(parseStreamFrame(bytesOf(vector.expect_frame_hex)), Object.keys(must(expect.fields, 'fields'))), expect.fields);
    return;
  }
  const decoded = decodeStreamFrame(bytesOf(must(vector.frame_hex, 'frame_hex')));
  if (!decoded.valid) throw new Error(`${vector.id} does not decode`);
  if (vector.kind === 'anchor') {
    assert.equal(byteHex(decoded.frame.commandCode), expect.command);
    return;
  }
  assert.deepEqual(projectFields(decoded.frame, Object.keys(must(expect.fields, 'expect.fields'))), expect.fields);
}

// ---- status.json ---------------------------------------------------------------------

function checkStatus(vector: VectorCase): void {
  const expect = must(vector.expect, 'expect');
  const bytes = bytesOf(must(vector.frame_hex, 'frame_hex'));
  const scanned = new ReplyScanner().push(bytes);
  assert.ok(scanned.every((reply) => reply.kind === 'status'), vector.id);

  if (vector.records !== undefined) {
    // The three-record reply: one object per record, with the same field names.
    const replies = scanned.map((reply) => reply.bytes);
    assert.equal(replies.length, vector.records.length, vector.id);
    replies.forEach((record, index) => {
      const expected = must(vector.records?.[index], 'records');
      assert.deepEqual(projectFields(parseStatusRecord(record), Object.keys(expected)), expected, `${vector.id} record ${index}`);
    });
    const status = parseStatus(replies);
    assert.equal(status.lengthClass, vector.expect_length_class, vector.id);
    // DEVIATION: the pinned FDT parser rejects this reply. The discovery firmware sends it (hp.cpp:585-593).
    assert.equal(expect.reference_parser, 'reject');
    return;
  }

  const expectedFields = must(vector.fields, 'fields');
  const record = parseStatusRecord(bytes);
  assert.deepEqual(projectFields(record, Object.keys(expectedFields)), expectedFields, vector.id);
  assert.equal(vector.expect_length_class, bytes.length === 85 ? '85' : '86', vector.id);
  assert.equal(scanned.length, 1, vector.id);
  assert.equal(expect.valid, true, vector.id);
  if (expect.reference_parser === 'accept') {
    assert.equal(expect.reference_kind, 'status', vector.id);
  } else {
    // DEVIATION: the pinned FDT parser rejects the 86-byte record and reports kind "unknown".
    // This client reads it as the discovery 86-byte record (hp.h:111-131, batterySOC at 81).
    assert.equal(expect.reference_parser, 'reject', vector.id);
    assert.equal(expect.reference_kind, 'unknown', vector.id);
    assert.equal(bytes.length, 86, vector.id);
    assert.equal(scanned[0]?.kind, 'status', vector.id);
  }
}

// ---- ota_frames.json (the in-scope cases) ----------------------------------------------

function checkVersionProbe(vector: VectorCase): void {
  const expect = must(vector.expect, 'expect');
  assert.equal(toHex(encodeHostFrame({ address: 0, destination: 0, command: 0x23 })), vector.frame_hex);
  const parsed = parseHostMessage(bytesOf(must(vector.frame_hex, 'frame_hex')));
  if (!parsed.valid) throw new Error(`${vector.id} does not parse`);
  assert.equal(byteHex(parsed.command), expect.command);
  assert.equal(toHex(parsed.payload), expect.payload_hex);
}

function checkFirmwareReply(vector: VectorCase): void {
  const bytes = bytesOf(must(vector.frame_hex, 'frame_hex'));
  const version = parseFirmwareVersion(bytes);
  const fields = must(vector.fields, 'fields');
  assert.deepEqual(projectFields(version, Object.keys(fields)), fields, vector.id);
  if (vector.expect?.reference_kind !== undefined) {
    const scanned = new ReplyScanner().push(bytes);
    assert.deepEqual(
      scanned.map((reply) => reply.kind),
      [vector.expect.reference_kind],
      vector.id,
    );
  }
}

function checkBridgeStop(vector: VectorCase): void {
  assert.equal(toHex(encodeHostFrame({ address: 0xff, destination: 0x00, command: 0x05 })), vector.frame_hex);
}

const OTA_CHECKS: Readonly<Record<string, Check>> = {
  'ota-anchor-version-probe': checkVersionProbe,
  'ota-anchor-identification-fw-version-reply': checkFirmwareReply,
  'ota-derived-bootloader-version-reply': checkFirmwareReply,
  'ota-derived-bridge-stop': checkBridgeStop,
};

function checkFor(file: string, vector: VectorCase): Check | null {
  switch (file) {
    case 'crc16.json':
      return checkCrc;
    case 'host_frames.json':
      if (vector.id.startsWith('host-anchor-')) return checkHostAnchor;
      if (vector.id.startsWith('host-encode-')) return checkHostEncode;
      if (vector.id.startsWith('host-decode-')) return checkHostDecode;
      return null;
    case 'stream_frames.json':
      return checkStream;
    case 'status.json':
      return checkStatus;
    case 'ota_frames.json':
      return OTA_CHECKS[vector.id] ?? null;
    default:
      return null;
  }
}

const FILES: readonly VectorFile[] = FILE_NAMES.map((name) => loadVectors(name));

// Registers one test per checked case. Out-of-scope cases get no test, and the coverage test below counts them.
for (const file of FILES) {
  describe(file.file, () => {
    for (const vector of file.cases) {
      const check = OUT_OF_SCOPE_FILES[file.file] === undefined ? checkFor(file.file, vector) : null;
      if (check !== null && OUT_OF_SCOPE_CASES[vector.id] === undefined) {
        test(`${vector.kind} ${vector.id}`, () => check(vector));
      }
    }
  });
}

describe('coverage of the vector files', () => {
  test('every case is checked or listed as out of scope, with no anchor left out', () => {
    let checked = 0;
    let anchorsChecked = 0;
    let outOfScope = 0;
    const knownIds = new Set<string>();
    for (const file of FILES) {
      for (const vector of file.cases) {
        knownIds.add(vector.id);
        const fileOut = OUT_OF_SCOPE_FILES[file.file] !== undefined;
        const check = fileOut ? null : checkFor(file.file, vector);
        const reason = OUT_OF_SCOPE_CASES[vector.id];
        if (fileOut || reason !== undefined) {
          assert.equal(check, null, `${vector.id} is out of scope but has a check`);
          outOfScope++;
        } else {
          assert.notEqual(check, null, `${vector.id} has neither a check nor an out-of-scope reason`);
          checked++;
          if (vector.kind === 'anchor') anchorsChecked++;
        }
      }
    }
    // The public repository leaves the firmware-update cases out of ota_frames.json, so their ids are absent there.
    for (const id of PUBLIC_REPOSITORY ? [] : Object.keys(OUT_OF_SCOPE_CASES)) {
      assert.ok(knownIds.has(id), `out-of-scope id ${id} is not in the vector files`);
    }
    assert.equal(checked, 53);
    assert.equal(outOfScope, PUBLIC_REPOSITORY ? 0 : 24);
    assert.equal(anchorsChecked, 20);
  });
});
