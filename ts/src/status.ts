// GET_STATUS (0x22) and GET_FW_VERSION (0x23) replies.
//
// Status record (T_StatusResponse, the firmware, written by the firmware):
//   0-1    BE EF header
//   2      platform address: 0 for the general record, 1 or 2 for a pad platform
//   3      command code, 0x22
//   4-7    errorFlags, uint32 little-endian (bit layout in the firmware)
//   8      temperature, int8 (always 0 on this controller)
//   9-28   serialParams, 20 bytes of text, for example "1500000,8,n,1"
//   29-58  wifiSSID, 30 bytes of text (empty on this controller)
//   59-62  wifiIP, 63-66 wifiMask, 67-70 wifiGW (4 bytes each)
//   71-74  cacheFrames, uint32 little-endian (always 0 on this controller)
//   75-80  calibrationFactorX, Y, Z, uint16 little-endian each
//   81     batterySOC, 0 to 100 percent, 255 = not measured (hp.h:127). Discovery record only.
//   then   CRC-16 over bytes 2 to n-5, low byte first, then 04 04.
// The 85-byte class is the same record without batterySOC: its CRC is at 81-82.
//
// A GET_STATUS reply is one general record (address 0), then one record for each detected
// platform (addresses 1 and 2, in order), so it is 85 or 86 bytes times 1 to 3. The
// controller sends no record count. The client reads until the line goes quiet
// (docs/04-host-commands.md, GET_STATUS; the firmware).
//
// The status fields and the 86-byte form come from the discovery layout only. The FDT
// reference decoder rejects the 86-byte form (vectors/status.json, reference_parser "reject"),
// and the Android decoders accept it (docs/06-status-health-versions.md, Table 6.2).

import { asciiField, at, dataView } from './bytes.ts';
import { crc16CcittFalse } from './crc.ts';
import { ReplyFormatError } from './errors.ts';

export type RecordLength = 85 | 86;
export type LengthClass = '85' | '86' | '85x2' | '86x2' | '85x3' | '86x3';

export interface StatusRecord {
  readonly platformAddress: number;
  readonly commandCode: number;
  readonly errorFlags: number;
  readonly temperature: number;
  readonly serialParams: string;
  readonly wifiSSID: string;
  readonly wifiIP: readonly [number, number, number, number];
  readonly wifiMask: readonly [number, number, number, number];
  readonly wifiGW: readonly [number, number, number, number];
  readonly cacheFrames: number;
  readonly calibrationFactorX: number;
  readonly calibrationFactorY: number;
  readonly calibrationFactorZ: number;
  // Raw byte: 0 to 100 percent, 255 = not measured. Null when the record has no battery byte (85-byte class).
  readonly batterySOC: number | null;
}

export interface Status {
  readonly lengthClass: LengthClass;
  readonly general: StatusRecord;
  readonly platforms: readonly StatusRecord[];
}

export interface FirmwareVersion {
  readonly platformAddress: number;
  readonly commandCode: number;
  readonly stm32FW: string;
  readonly esp32FW: string;
}

// Layout check shared by the status record and the firmware version reply: BE EF header,
// CRC over bytes 2 to n-5 stored at n-4 (low byte first), then 04 04, then the command.
function checkFrame(bytes: Uint8Array, command: number, name: string): void {
  const n = bytes.length;
  if (at(bytes, 0) !== 0xbe || at(bytes, 1) !== 0xef) {
    throw new ReplyFormatError('bad_header', `${name} starts with BE EF`);
  }
  const stored = at(bytes, n - 4) | (at(bytes, n - 3) << 8);
  if (crc16CcittFalse(bytes.subarray(2, n - 4)) !== stored) {
    throw new ReplyFormatError('crc_mismatch', `${name} CRC does not match bytes 2 to ${n - 5}`);
  }
  if (at(bytes, n - 2) !== 0x04 || at(bytes, n - 1) !== 0x04) {
    throw new ReplyFormatError('bad_end_marker', `${name} does not end with 04 04`);
  }
  if (at(bytes, 3) !== command) {
    throw new ReplyFormatError('bad_command', `${name} carries command 0x${command.toString(16)}`);
  }
}

function ipOf(bytes: Uint8Array, start: number): readonly [number, number, number, number] {
  return [at(bytes, start), at(bytes, start + 1), at(bytes, start + 2), at(bytes, start + 3)];
}

// Reads one status record of 85 or 86 bytes.
export function parseStatusRecord(bytes: Uint8Array): StatusRecord {
  const n = bytes.length;
  if (n !== 85 && n !== 86) {
    throw new ReplyFormatError('bad_length', `a status record is 85 or 86 bytes, got ${n}`);
  }
  checkFrame(bytes, 0x22, 'a status record');
  const view = dataView(bytes);
  return {
    platformAddress: at(bytes, 2),
    commandCode: at(bytes, 3),
    errorFlags: view.getUint32(4, true),
    temperature: view.getInt8(8),
    serialParams: asciiField(bytes, 9, 20),
    wifiSSID: asciiField(bytes, 29, 30),
    wifiIP: ipOf(bytes, 59),
    wifiMask: ipOf(bytes, 63),
    wifiGW: ipOf(bytes, 67),
    cacheFrames: view.getUint32(71, true),
    calibrationFactorX: view.getUint16(75, true),
    calibrationFactorY: view.getUint16(77, true),
    calibrationFactorZ: view.getUint16(79, true),
    batterySOC: n === 86 ? at(bytes, 81) : null,
  };
}

const CLASS_NAMES: Record<RecordLength, readonly [LengthClass, LengthClass, LengthClass]> = {
  85: ['85', '85x2', '85x3'],
  86: ['86', '86x2', '86x3'],
};

// Reads a whole GET_STATUS reply, given as its records in the order they arrived. Every
// record must have the same length. The first record must be the general record (address
// 0), and the platform records must follow in increasing order with addresses 1 and 2.
export function parseStatus(records: readonly Uint8Array[]): Status {
  if (records.length < 1 || records.length > 3) {
    throw new ReplyFormatError('bad_length', `a GET_STATUS reply has 1 to 3 records, got ${records.length}`);
  }
  const length = records[0]?.length;
  if (length !== 85 && length !== 86) {
    throw new ReplyFormatError('bad_length', `a status record is 85 or 86 bytes, got ${length ?? 0}`);
  }
  for (const record of records) {
    if (record.length !== length) {
      throw new ReplyFormatError('bad_length', 'the records of one GET_STATUS reply differ in length');
    }
  }
  const parsed = records.map((record) => parseStatusRecord(record));
  const general = parsed[0];
  if (general === undefined || general.platformAddress !== 0) {
    throw new ReplyFormatError('bad_platform_order', 'the first status record must be the general record (address 0)');
  }
  const platforms = parsed.slice(1);
  let previous = 0;
  for (const record of platforms) {
    if (record.platformAddress <= previous || record.platformAddress > 2) {
      throw new ReplyFormatError('bad_platform_order', `status record for address ${record.platformAddress} is out of order`);
    }
    previous = record.platformAddress;
  }
  const classes = CLASS_NAMES[length];
  return {
    lengthClass: classes[records.length - 1] ?? classes[0],
    general,
    platforms,
  };
}

// Reads the 38-byte GET_FW_VERSION reply (T_FirmwareVersionResponse, the firmware):
// header, address, command 0x23, stm32FW at 4 (15 bytes), esp32FW at 19 (15 bytes), CRC
// over bytes 2 to 33 at 34-35, then 04 04. Each version field is text up to its first NUL.
export function parseFirmwareVersion(bytes: Uint8Array): FirmwareVersion {
  if (bytes.length !== 38) {
    throw new ReplyFormatError('bad_length', `a firmware version reply is 38 bytes, got ${bytes.length}`);
  }
  checkFrame(bytes, 0x23, 'a firmware version reply');
  return {
    platformAddress: at(bytes, 2),
    commandCode: at(bytes, 3),
    stm32FW: asciiField(bytes, 4, 15),
    esp32FW: asciiField(bytes, 19, 15),
  };
}
