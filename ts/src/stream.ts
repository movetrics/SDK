// The 24-byte stream frame (T_Frame, the firmware):
//   0-1    BE EF header (RSP_HEADER_MARKER, hp.h:14)
//   2      platform address
//   3      command code, always 0x01
//   4-7    timeStamp, uint32 little-endian
//   8-19   forceX, forceY, forceZ, momentX, momentY, momentZ, int16 little-endian each
//   20-21  CRC-16/CCITT-FALSE over bytes 2 to 19, low byte first
//   22-23  04 04
// Stream frames are sent once per sample and platform. START_STREAM first sends two
// placeholder frames with timeStamp 0 (the firmware). The stream values
// are wire integers. Their physical units are not verified (vectors/README.md, not covered 11).
//
// The event frame (DRAFT, 28 Oct 2026; python/movetrics_fdt/stream.py) uses the same
// envelope with address 0xFD and command 0x0E. The controller sends one only when a host sets the
// EVENT_FRAMES bit of SET_SYNC_MODE, so firmware without sync modes never sends one.
//   0-1    BE EF header
//   2      0xFD (EVENT_ADDRESS)
//   3      0x0E (EVENT_COMMAND)
//   4-7    timeStamp, uint32 little-endian (0.1 ms ticks)
//   8      eventType, uint8 (1 to 10, see EVENT_NAMES)
//   9      source, uint8 (sync input or output index, 0 = the first; the plate number for saturation)
//   10-13  count, uint32 little-endian (edge counter since START)
//   14-15  offsetUs, int16 little-endian (microseconds from the stamp's tick to the edge)
//   16-17  detail, uint16 little-endian (type-specific)
//   18     mode, uint8 (the SET_SYNC_MODE mode in force)
//   19     0
//   20-21  CRC-16 over bytes 2 to 19
//   22-23  04 04
// The event time is stamp / 10000 + offsetUs / 1e6 seconds.

import { at, dataView } from './bytes.ts';
import { crc16CcittFalse } from './crc.ts';
import { FrameEncodeError, ReplyFormatError, type ReplyErrorCode } from './errors.ts';
import { ReplyScanner } from './frames.ts';

export const STREAM_FRAME_LENGTH = 24; // the firmware
export const STREAM_COMMAND = 0x01; // the firmware
export const EVENT_ADDRESS = 0xfd; // DRAFT: plate address of an event frame
export const EVENT_COMMAND = 0x0e; // DRAFT: command byte of an event frame

// Event types 1 to 8 (contracts/vocabulary.v1.json "events"). Types 100 and 101 are host-made and never
// come from the controller.
export const EVENT_NAMES: Readonly<Record<number, string>> = {
  1: 'sync_in_rise',
  2: 'sync_in_fall',
  3: 'sync_out_rise',
  4: 'sync_out_fall',
  5: 'stream_armed',
  6: 'stream_started_by_trigger',
  7: 'saturation',
  8: 'frames_dropped',
  9: 'saturation_end',
  10: 'arm_expired',
};

// The name of an event type. Unknown types are named unknown_N, as in the Python client.
export function eventName(eventType: number): string {
  return EVENT_NAMES[eventType] ?? `unknown_${eventType}`;
}

// A sync event from the controller (DRAFT layout). It is an edge or a state change at timeStamp, offset by
// offsetUs microseconds.
export interface EventFrame {
  readonly timeStamp: number;
  readonly eventType: number;
  readonly source: number;
  readonly count: number;
  readonly offsetUs: number;
  readonly detail: number;
  readonly mode: number;
}

// One item of the device stream, in arrival order: a stream frame or an event frame.
export type StreamItem =
  | { readonly kind: 'frame'; readonly frame: StreamFrame }
  | { readonly kind: 'event'; readonly event: EventFrame };

export interface StreamFrame {
  readonly platformAddress: number;
  readonly commandCode: number;
  readonly timeStamp: number;
  readonly forceX: number;
  readonly forceY: number;
  readonly forceZ: number;
  readonly momentX: number;
  readonly momentY: number;
  readonly momentZ: number;
}

export type StreamDecodeResult =
  | { readonly valid: true; readonly frame: StreamFrame }
  | { readonly valid: false; readonly reason: ReplyErrorCode };

// Checks the 24-byte envelope shared by stream and event frames, in the order length, header, CRC,
// end marker. Throws ReplyFormatError when a check fails.
function checkEnvelope(bytes: Uint8Array, name: string): void {
  if (bytes.length !== STREAM_FRAME_LENGTH) {
    throw new ReplyFormatError('bad_length', `${name} is 24 bytes, got ${bytes.length}`);
  }
  if (at(bytes, 0) !== 0xbe || at(bytes, 1) !== 0xef) {
    throw new ReplyFormatError('bad_header', `${name} starts with BE EF`);
  }
  const stored = at(bytes, 20) | (at(bytes, 21) << 8);
  if (crc16CcittFalse(bytes.subarray(2, 20)) !== stored) {
    throw new ReplyFormatError('crc_mismatch', `${name} CRC does not match bytes 2 to 19`);
  }
  if (at(bytes, 22) !== 0x04 || at(bytes, 23) !== 0x04) {
    throw new ReplyFormatError('bad_end_marker', `${name} ends with 04 04`);
  }
}

// Reads one complete 24-byte stream frame. Throws ReplyFormatError when a check fails.
// The checks run in the order length, header, CRC, end marker, command.
export function parseStreamFrame(bytes: Uint8Array): StreamFrame {
  checkEnvelope(bytes, 'a stream frame');
  if (at(bytes, 3) !== STREAM_COMMAND) {
    throw new ReplyFormatError('bad_command', `a stream frame carries command 0x01, got 0x${at(bytes, 3).toString(16)}`);
  }
  const view = dataView(bytes);
  return {
    platformAddress: at(bytes, 2),
    commandCode: at(bytes, 3),
    timeStamp: view.getUint32(4, true),
    forceX: view.getInt16(8, true),
    forceY: view.getInt16(10, true),
    forceZ: view.getInt16(12, true),
    momentX: view.getInt16(14, true),
    momentY: view.getInt16(16, true),
    momentZ: view.getInt16(18, true),
  };
}

// Same checks as parseStreamFrame, reported as a value instead of a throw.
export function decodeStreamFrame(bytes: Uint8Array): StreamDecodeResult {
  try {
    return { valid: true, frame: parseStreamFrame(bytes) };
  } catch (error) {
    if (error instanceof ReplyFormatError) return { valid: false, reason: error.code };
    throw error;
  }
}

function checkRange(name: string, value: number, min: number, max: number): void {
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new FrameEncodeError('bad_field', `${name} must be an integer from ${min} to ${max}, got ${value}`);
  }
}

// Builds a stream frame from its fields. The commandCode must be 0x01. The CRC is
// computed as the device computes it. The frame is not checked for 04 04 bytes, because
// the 04 04 rule applies to host requests, not to device replies (docs/03 section 3.3).
export function encodeStreamFrame(frame: StreamFrame): Uint8Array {
  checkRange('platformAddress', frame.platformAddress, 0, 0xff);
  if (frame.commandCode !== STREAM_COMMAND) {
    throw new FrameEncodeError('bad_field', `a stream frame carries command 0x01, got ${frame.commandCode}`);
  }
  checkRange('timeStamp', frame.timeStamp, 0, 0xffffffff);
  checkRange('forceX', frame.forceX, -0x8000, 0x7fff);
  checkRange('forceY', frame.forceY, -0x8000, 0x7fff);
  checkRange('forceZ', frame.forceZ, -0x8000, 0x7fff);
  checkRange('momentX', frame.momentX, -0x8000, 0x7fff);
  checkRange('momentY', frame.momentY, -0x8000, 0x7fff);
  checkRange('momentZ', frame.momentZ, -0x8000, 0x7fff);

  const out = new Uint8Array(STREAM_FRAME_LENGTH);
  const view = dataView(out);
  out[0] = 0xbe;
  out[1] = 0xef;
  out[2] = frame.platformAddress;
  out[3] = STREAM_COMMAND;
  view.setUint32(4, frame.timeStamp, true);
  view.setInt16(8, frame.forceX, true);
  view.setInt16(10, frame.forceY, true);
  view.setInt16(12, frame.forceZ, true);
  view.setInt16(14, frame.momentX, true);
  view.setInt16(16, frame.momentY, true);
  view.setInt16(18, frame.momentZ, true);
  const crc = crc16CcittFalse(out.subarray(2, 20));
  out[20] = crc & 0xff;
  out[21] = crc >> 8;
  out[22] = 0x04;
  out[23] = 0x04;
  return out;
}

// GET_SYNC_MODE (0x29, DRAFT) reply, 26 bytes: BE EF pa 29, then the fields below, CRC over bytes 2 to 21,
// then 04 04. Byte 4 is the mode; 5-6 the pulse period (ms, uint16); 7 the pulse width (ms); 8 debounce (0.1 ms);
// 9 arm timeout (minutes); 10 state bits; 11 contract; 12-15 edges in (uint32); 16-19 edges out (uint32);
// 20-21 overflows (uint16). A NACK 7 instead means the firmware has no sync modes (the capability probe).
export const SYNC_MODE_COMMAND = 0x29;
export const SYNC_MODE_REPLY_LENGTH = 26;

export interface SyncModeState {
  readonly mode: number;
  readonly pulsePeriodMs: number;
  readonly pulseWidthMs: number;
  readonly debounce: number;
  readonly armTimeoutMin: number;
  readonly armed: boolean;
  readonly restored: boolean;
  readonly backupOk: boolean;
  readonly syncInHigh: boolean;
  readonly syncOutHigh: boolean;
  readonly streaming: boolean;
  readonly contract: number;
  readonly edgesIn: number;
  readonly edgesOut: number;
  readonly overflows: number;
}

// Reads one complete 26-byte GET_SYNC_MODE reply. Throws ReplyFormatError when a check fails.
export function parseSyncModeReply(bytes: Uint8Array): SyncModeState {
  if (bytes.length !== SYNC_MODE_REPLY_LENGTH) {
    throw new ReplyFormatError('bad_length', `a sync mode reply is 26 bytes, got ${bytes.length}`);
  }
  if (at(bytes, 0) !== 0xbe || at(bytes, 1) !== 0xef) {
    throw new ReplyFormatError('bad_header', 'a sync mode reply starts with BE EF');
  }
  const stored = at(bytes, 22) | (at(bytes, 23) << 8);
  if (crc16CcittFalse(bytes.subarray(2, 22)) !== stored) {
    throw new ReplyFormatError('crc_mismatch', 'sync mode reply CRC does not match bytes 2 to 21');
  }
  if (at(bytes, 24) !== 0x04 || at(bytes, 25) !== 0x04) {
    throw new ReplyFormatError('bad_end_marker', 'a sync mode reply ends with 04 04');
  }
  if (at(bytes, 3) !== SYNC_MODE_COMMAND) {
    throw new ReplyFormatError('bad_command', `a sync mode reply carries command 0x29, got 0x${at(bytes, 3).toString(16)}`);
  }
  const view = dataView(bytes);
  const state = at(bytes, 10);
  return {
    mode: at(bytes, 4),
    pulsePeriodMs: view.getUint16(5, true),
    pulseWidthMs: at(bytes, 7),
    debounce: at(bytes, 8),
    armTimeoutMin: at(bytes, 9),
    armed: (state & 0x01) !== 0,
    restored: (state & 0x02) !== 0,
    backupOk: (state & 0x04) !== 0,
    syncInHigh: (state & 0x08) !== 0,
    syncOutHigh: (state & 0x10) !== 0,
    streaming: (state & 0x20) !== 0,
    contract: at(bytes, 11),
    edgesIn: view.getUint32(12, true),
    edgesOut: view.getUint32(16, true),
    overflows: view.getUint16(20, true),
  };
}

// Reads one complete 24-byte event frame (DRAFT layout). Throws ReplyFormatError when a check fails.
// The checks run in the order length, header, CRC, end marker, then address and command.
export function parseEventFrame(bytes: Uint8Array): EventFrame {
  checkEnvelope(bytes, 'an event frame');
  if (at(bytes, 2) !== EVENT_ADDRESS || at(bytes, 3) !== EVENT_COMMAND) {
    throw new ReplyFormatError(
      'bad_command',
      `an event frame has address 0xFD and command 0x0E, got 0x${at(bytes, 2).toString(16)} 0x${at(bytes, 3).toString(16)}`,
    );
  }
  const view = dataView(bytes);
  return {
    timeStamp: view.getUint32(4, true),
    eventType: at(bytes, 8),
    source: at(bytes, 9),
    count: view.getUint32(10, true),
    offsetUs: view.getInt16(14, true),
    detail: view.getUint16(16, true),
    mode: at(bytes, 18),
  };
}

// Builds the 24 wire bytes of an event frame. Used by the tests and by simulators. Like encodeStreamFrame,
// it does not check for 04 04 bytes, because that rule applies to host requests only.
export function encodeEventFrame(event: EventFrame): Uint8Array {
  checkRange('timeStamp', event.timeStamp, 0, 0xffffffff);
  checkRange('eventType', event.eventType, 0, 0xff);
  checkRange('source', event.source, 0, 0xff);
  checkRange('count', event.count, 0, 0xffffffff);
  checkRange('offsetUs', event.offsetUs, -0x8000, 0x7fff);
  checkRange('detail', event.detail, 0, 0xffff);
  checkRange('mode', event.mode, 0, 0xff);

  const out = new Uint8Array(STREAM_FRAME_LENGTH); // byte 19 stays zero (reserved)
  const view = dataView(out);
  out[0] = 0xbe;
  out[1] = 0xef;
  out[2] = EVENT_ADDRESS;
  out[3] = EVENT_COMMAND;
  view.setUint32(4, event.timeStamp, true);
  out[8] = event.eventType;
  out[9] = event.source;
  view.setUint32(10, event.count, true);
  view.setInt16(14, event.offsetUs, true);
  view.setUint16(16, event.detail, true);
  out[18] = event.mode;
  const crc = crc16CcittFalse(out.subarray(2, 20));
  out[20] = crc & 0xff;
  out[21] = crc >> 8;
  out[22] = 0x04;
  out[23] = 0x04;
  return out;
}

// Pulls the stream frames out of a device byte stream. Other replies in the same stream
// (ACK, NACK, GET_STATUS, GET_FW_VERSION) are skipped. Chunk boundaries can fall anywhere.
export class StreamDecoder {
  readonly #scanner = new ReplyScanner();

  // Stream frames only. Event frames in the same bytes are skipped; use pushItems to keep them.
  push(chunk: Uint8Array): StreamFrame[] {
    const frames: StreamFrame[] = [];
    for (const item of this.pushItems(chunk)) {
      if (item.kind === 'frame') frames.push(item.frame);
    }
    return frames;
  }

  // Stream frames and event frames, in the order they arrived. Event frames are never returned by push.
  pushItems(chunk: Uint8Array): StreamItem[] {
    const items: StreamItem[] = [];
    for (const reply of this.#scanner.push(chunk)) {
      if (reply.kind === 'stream') items.push({ kind: 'frame', frame: parseStreamFrame(reply.bytes) });
      else if (reply.kind === 'event') items.push({ kind: 'event', event: parseEventFrame(reply.bytes) });
    }
    return items;
  }
}
