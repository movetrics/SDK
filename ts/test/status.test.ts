import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { bytesOf } from './support.ts';
import { vectorCase } from './vectors-data.ts';
import { crc16CcittFalse } from '../src/crc.ts';
import { ReplyFormatError, type ReplyErrorCode } from '../src/errors.ts';
import { parseFirmwareVersion, parseStatus, parseStatusRecord } from '../src/status.ts';

function codeOf(action: () => unknown): ReplyErrorCode | 'ok' {
  try {
    action();
    return 'ok';
  } catch (error) {
    if (error instanceof ReplyFormatError) return error.code;
    throw error;
  }
}

// A copy of a record with one byte changed and the CRC recomputed, so only that byte differs.
function edited(hex: string, index: number, value: number): Uint8Array {
  const bytes = bytesOf(hex);
  bytes[index] = value;
  const n = bytes.length;
  const crc = crc16CcittFalse(bytes.subarray(2, n - 4));
  bytes[n - 4] = crc & 0xff;
  bytes[n - 3] = crc >> 8;
  return bytes;
}

const GENERAL_86 = vectorCase('status-derived-86-general-record').frame_hex ?? '';
const PAD1_86 = vectorCase('status-derived-86-platform-1-record').frame_hex ?? '';
const PAD2_86 = vectorCase('status-derived-86-platform-2-record').frame_hex ?? '';

describe('parseStatusRecord', () => {
  test('the 85-byte identification reply has no battery byte and keeps its text fields', () => {
    const record = parseStatusRecord(bytesOf(vectorCase('status-anchor-identification-85').frame_hex ?? ''));
    assert.equal(record.platformAddress, 0);
    assert.equal(record.serialParams, '123');
    assert.equal(record.wifiSSID, '123');
    assert.deepEqual(record.wifiIP, [1, 2, 3, 4]);
    assert.equal(record.batterySOC, null);
  });

  test('the 86-byte general record reads batterySOC at offset 81', () => {
    const record = parseStatusRecord(bytesOf(GENERAL_86));
    assert.equal(record.batterySOC, 87);
    assert.equal(record.serialParams, '1500000,8,n,1');
    assert.equal(record.wifiSSID, '');
  });

  test('the 86-byte pad record reads its calibration factors and its error flags', () => {
    const record = parseStatusRecord(bytesOf(PAD1_86));
    assert.equal(record.platformAddress, 1);
    assert.equal(record.errorFlags, 1);
    assert.deepEqual(
      [record.calibrationFactorX, record.calibrationFactorY, record.calibrationFactorZ, record.batterySOC],
      [291, 1110, 1929, 255],
    );
  });

  test('a changed byte inside the record fails the CRC, and a bad length is refused', () => {
    const flipped = bytesOf(GENERAL_86);
    flipped[10] = (flipped[10] ?? 0) ^ 0x01;
    assert.equal(codeOf(() => parseStatusRecord(flipped)), 'crc_mismatch');
    assert.equal(codeOf(() => parseStatusRecord(bytesOf(GENERAL_86).subarray(0, 84))), 'bad_length');
  });

  test('a record with a different command byte is refused', () => {
    assert.equal(codeOf(() => parseStatusRecord(edited(GENERAL_86, 3, 0x23))), 'bad_command');
  });
});

describe('parseStatus', () => {
  test('three records give the general record and two platform records, class 86x3', () => {
    const records = [GENERAL_86, PAD1_86, PAD2_86].map((hex) => bytesOf(hex));
    const status = parseStatus(records);
    assert.equal(status.lengthClass, '86x3');
    assert.equal(status.general.platformAddress, 0);
    assert.deepEqual(
      status.platforms.map((record) => record.platformAddress),
      [1, 2],
    );
    assert.equal(status.platforms[1]?.batterySOC, 100);
  });

  test('a single 85-byte record is class 85', () => {
    const status = parseStatus([bytesOf(vectorCase('status-derived-85-discovery-record').frame_hex ?? '')]);
    assert.equal(status.lengthClass, '85');
    assert.deepEqual(status.platforms, []);
  });

  test('a general record and one platform record is class 86x2, and a platform may be skipped', () => {
    const status = parseStatus([bytesOf(GENERAL_86), bytesOf(PAD2_86)]);
    assert.equal(status.lengthClass, '86x2');
    assert.deepEqual(
      status.platforms.map((record) => record.platformAddress),
      [2],
    );
  });

  test('the order and the mix of lengths are checked', () => {
    assert.equal(codeOf(() => parseStatus([bytesOf(PAD1_86), bytesOf(GENERAL_86)])), 'bad_platform_order');
    assert.equal(codeOf(() => parseStatus([bytesOf(GENERAL_86), bytesOf(PAD2_86), bytesOf(PAD1_86)])), 'bad_platform_order');
    assert.equal(codeOf(() => parseStatus([bytesOf(GENERAL_86), bytesOf(vectorCase('status-derived-85-discovery-record').frame_hex ?? '')])), 'bad_length');
    assert.equal(codeOf(() => parseStatus([])), 'bad_length');
    assert.equal(codeOf(() => parseStatus([bytesOf(GENERAL_86), bytesOf(PAD1_86), bytesOf(PAD2_86), bytesOf(PAD2_86)])), 'bad_length');
  });
});

describe('parseFirmwareVersion', () => {
  test('the identification capture reply reads STM32 and ESP32 fields', () => {
    const version = parseFirmwareVersion(bytesOf(vectorCase('ota-anchor-identification-fw-version-reply').frame_hex ?? ''));
    assert.deepEqual(version, { platformAddress: 0, commandCode: 0x23, stm32FW: '001.002.003', esp32FW: '002.005.001' });
  });

  test('the bootloader reply reads its own version text', () => {
    const version = parseFirmwareVersion(bytesOf(vectorCase('ota-derived-bootloader-version-reply').frame_hex ?? ''));
    assert.deepEqual(version, { platformAddress: 0, commandCode: 0x23, stm32FW: 'BOOT-1.0.0.3', esp32FW: '000.000.000' });
  });

  test('a reply of another length is refused', () => {
    const reply = bytesOf(vectorCase('ota-anchor-identification-fw-version-reply').frame_hex ?? '');
    assert.equal(codeOf(() => parseFirmwareVersion(reply.subarray(0, 37))), 'bad_length');
  });
});
