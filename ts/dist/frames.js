// Host request frames (FE ED pa da cmd [payload] crc_lo crc_hi 04 04), the host
// frame reader that mirrors the controller's parser, and the reply scanner that finds
// BE EF replies by length and CRC. Layouts: docs/03-host-link-framing.md section 3.1.
// Parser: the firmware. RX splitter: the firmware.
import { at, concatBytes } from "./bytes.js";
import { crc16CcittFalse } from "./crc.js";
import { FrameEncodeError } from "./errors.js";
import { FIRMWARE_DISPATCH, NOT_IMPLEMENTED, NOT_IMPLEMENTED_CODES, NO_REPLY_ON_SUCCESS } from "./commands.js";
export const EOT = 0x04; // the firmware
export const ACK_CODE = 0x06; // the firmware
export const NACK_CODE = 0x15; // the firmware
export const BROADCAST_ADDRESS = 0xff; // the firmware
export const HOST_MESSAGE_MAX = 320; // the firmware (HP_BUFFER_SIZE 256 + 64)
export const REQUEST_MIN_LENGTH = 9; // the firmware
export const ACK_LENGTH = 9; // the firmware
export const NACK_LENGTH = 11; // the firmware
function checkByte(name, value) {
    if (!Number.isInteger(value) || value < 0 || value > 0xff) {
        throw new FrameEncodeError('bad_field', `${name} must be a byte, got ${value}`);
    }
}
// Builds the frame without the delimiter check. Used to report what would be sent.
export function buildHostFrame(request) {
    checkByte('address', request.address);
    checkByte('destination', request.destination);
    checkByte('command', request.command);
    const payload = request.payload ?? new Uint8Array(0);
    const length = REQUEST_MIN_LENGTH + payload.length;
    if (length > HOST_MESSAGE_MAX) {
        throw new FrameEncodeError('too_long', `request of ${length} bytes exceeds the ${HOST_MESSAGE_MAX}-byte limit`);
    }
    const frame = new Uint8Array(length);
    frame[0] = 0xfe;
    frame[1] = 0xed;
    frame[2] = request.address;
    frame[3] = request.destination;
    frame[4] = request.command;
    frame.set(payload, 5);
    // CRC covers bytes 2 to n-5, stored low byte first.
    const crc = crc16CcittFalse(frame.subarray(2, length - 4));
    frame[length - 4] = crc & 0xff;
    frame[length - 3] = crc >> 8;
    frame[length - 2] = EOT;
    frame[length - 1] = EOT;
    return frame;
}
// Index of the byte that completes an early 04 04 pair, or -1. The controller's RX
// splitter closes a message at the first 04 04 it sees (the firmware),
// so a frame whose CRC high byte or payload holds 04 followed by 04 is cut short.
export function earlyDelimiterAt(frame) {
    for (let i = 1; i <= frame.length - 2; i++) {
        if (at(frame, i - 1) === EOT && at(frame, i) === EOT)
            return i;
    }
    return -1;
}
// Builds a request that the controller can receive as built. Throws
// FrameEncodeError('not_implemented') for a command in NOT_IMPLEMENTED, which this client
// never sends. Throws FrameEncodeError('early_04_04_delimiter') for a frame the splitter
// would cut (docs/03-host-link-framing.md section 3.3).
export function encodeHostFrame(request) {
    const frame = buildHostFrame(request);
    if (NOT_IMPLEMENTED_CODES.has(request.command)) {
        const entry = NOT_IMPLEMENTED.find((command) => command.code === request.command);
        throw new FrameEncodeError('not_implemented', `command 0x${request.command.toString(16).padStart(2, '0')} (${entry?.name ?? 'unknown'}) is not implemented: ${entry?.reason ?? ''}`, frame);
    }
    if (earlyDelimiterAt(frame) >= 0) {
        throw new FrameEncodeError('early_04_04_delimiter', 'the frame contains 04 04 before its end, so the controller would cut it short', frame);
    }
    return frame;
}
// ---- Host message reader (controller side) ---------------------------------------
// Splits a byte stream into the messages the controller's RX splitter delivers. A
// message ends at the first pair of 04 bytes; a message longer than HOST_MESSAGE_MAX
// is dropped (the firmware).
export class HostRxSplitter {
    #message = [];
    #overflow = false;
    #previous = 0;
    push(bytes) {
        const out = [];
        for (const byte of bytes) {
            if (this.#message.length < HOST_MESSAGE_MAX)
                this.#message.push(byte);
            else
                this.#overflow = true;
            if (this.#previous === EOT && byte === EOT) {
                if (!this.#overflow)
                    out.push(Uint8Array.from(this.#message));
                this.#message = [];
                this.#overflow = false;
                this.#previous = 0;
            }
            else {
                this.#previous = byte;
            }
        }
        return out;
    }
}
// Reads one delivered message the way hp_parse_command does (the firmware):
// resynchronise at the first FE ED, then the length, the header, the CRC, the end
// marker, the payload minimums and the dispatch table. Device state (pad job, firmware
// update) is not modelled.
export function parseHostMessage(message) {
    let buf = message;
    if (buf.length >= REQUEST_MIN_LENGTH && !(at(buf, 0) === 0xfe && at(buf, 1) === 0xed)) {
        for (let i = 1; i + REQUEST_MIN_LENGTH <= buf.length; i++) {
            if (at(buf, i) === 0xfe && at(buf, i + 1) === 0xed) {
                buf = buf.subarray(i);
                break;
            }
        }
    }
    if (buf.length < REQUEST_MIN_LENGTH) {
        return invalid('shorter_than_9_bytes', { reply: 'none', reason: 'shorter_than_9_bytes' });
    }
    if (at(buf, 0) !== 0xfe || at(buf, 1) !== 0xed) {
        return invalid('bad_header', { reply: 'none', reason: 'bad_header' });
    }
    const n = buf.length;
    const address = at(buf, 2);
    const destination = at(buf, 3);
    const command = at(buf, 4);
    const stored = at(buf, n - 4) | (at(buf, n - 3) << 8);
    if (crc16CcittFalse(buf.subarray(2, n - 4)) !== stored) {
        return invalid('crc_mismatch', { nack_code: 9 });
    }
    if (at(buf, n - 2) !== EOT || at(buf, n - 1) !== EOT) {
        return invalid('bad_end_marker', { nack_code: 7 });
    }
    const payload = buf.slice(5, n - 4);
    const base = { valid: true, command, address, destination, payload };
    if (command === 0x00) {
        return { ...base, device_reply: { reply: 'none', reason: 'no_command' }, dispatched: false };
    }
    // Minimum payloads (the firmware): NACK 3 when short or out of range.
    const len = payload.length;
    const needsThree = command === 0x1c;
    const needsTwo = command === 0x07 || command === 0x26 || command === 0x53;
    const needsOne = command === 0x12 || command === 0x14 || command === 0x15 || command === 0x31 || command === 0x34;
    const indexesPad = command === 0x52 || command === 0x53;
    const badIndex = ((command === 0x14 || command === 0x15 || indexesPad) && address >= 3) || (indexesPad && destination >= 3);
    if ((needsThree && len < 3) || (needsTwo && len < 2) || (needsOne && len < 1) || badIndex) {
        return { ...base, device_reply: { nack_code: 3 }, dispatched: false };
    }
    if (!FIRMWARE_DISPATCH.has(command)) {
        return { ...base, device_reply: { nack_code: 7 }, dispatched: false };
    }
    const reply = NO_REPLY_ON_SUCCESS.has(command)
        ? { reply: 'none', reason: 'no_reply_on_success' }
        : { reply: 'command_reply' };
    return { ...base, device_reply: reply, dispatched: true };
}
function invalid(reason, deviceReply) {
    return { valid: false, reason, device_reply: deviceReply, dispatched: false };
}
// Lengths that a reply starting at BE EF can have, given its command byte (offset 3)
// and its byte 4. Byte 4 is the ACK or NACK marker for those reply kinds, so it is only
// a hint: each candidate is confirmed by its end marker and CRC.
function candidatesFor(command, byte4) {
    const list = [];
    if (command === 0x01)
        list.push({ length: 24, kind: 'stream' });
    if (command === 0x0e)
        list.push({ length: 24, kind: 'event' });
    if (command === 0x29)
        list.push({ length: 26, kind: 'sync_mode' });
    if (command === 0x22)
        list.push({ length: 86, kind: 'status' }, { length: 85, kind: 'status' });
    if (command === 0x23)
        list.push({ length: 38, kind: 'firmware_version' });
    if (byte4 === ACK_CODE)
        list.push({ length: ACK_LENGTH, kind: 'ack' });
    if (byte4 === NACK_CODE)
        list.push({ length: NACK_LENGTH, kind: 'nack' });
    return list;
}
// True when `frame` is exactly one reply of `kind`: end marker, CRC over bytes 2 to n-5,
// and the fields that the kind requires.
function isWholeReply(frame, kind) {
    const n = frame.length;
    if (at(frame, n - 2) !== EOT || at(frame, n - 1) !== EOT)
        return false;
    const stored = at(frame, n - 4) | (at(frame, n - 3) << 8);
    if (crc16CcittFalse(frame.subarray(2, n - 4)) !== stored)
        return false;
    const command = at(frame, 3);
    switch (kind) {
        case 'stream':
            return n === 24 && command === 0x01;
        case 'event':
            return n === 24 && command === 0x0e && at(frame, 2) === 0xfd;
        case 'sync_mode':
            return n === 26 && command === 0x29;
        case 'ack':
            return n === ACK_LENGTH && at(frame, 4) === ACK_CODE;
        case 'nack':
            return n === NACK_LENGTH && at(frame, 4) === NACK_CODE;
        case 'status':
            return (n === 86 || n === 85) && command === 0x22;
        case 'firmware_version':
            return n === 38 && command === 0x23;
        default:
            return false;
    }
}
function findHeader(buf, from) {
    for (let i = from; i + 1 < buf.length; i++) {
        if (at(buf, i) === 0xbe && at(buf, i + 1) === 0xef)
            return i;
    }
    return -1;
}
// Finds complete replies in a device byte stream. It resynchronises on BE EF, uses
// the command code and the ACK/NACK marker to choose candidate lengths, and accepts a
// candidate only when its end marker and CRC are correct. Stream frames and other
// replies can interleave freely, and chunk boundaries can fall anywhere.
export class ReplyScanner {
    #pending = new Uint8Array(0);
    push(chunk) {
        const buf = concatBytes([this.#pending, chunk]);
        const out = [];
        let start = 0;
        for (;;) {
            const header = findHeader(buf, start);
            if (header < 0) {
                // A lone BE at the end may be the first byte of a header; keep it.
                start = buf.length > 0 && at(buf, buf.length - 1) === 0xbe ? buf.length - 1 : buf.length;
                break;
            }
            start = header;
            if (buf.length - start < 5)
                break;
            const candidates = candidatesFor(at(buf, start + 3), at(buf, start + 4));
            let found = null;
            let incomplete = false;
            for (const candidate of candidates) {
                if (buf.length - start < candidate.length) {
                    incomplete = true;
                    continue;
                }
                if (isWholeReply(buf.subarray(start, start + candidate.length), candidate.kind)) {
                    found = candidate;
                    break;
                }
            }
            if (found) {
                const frame = buf.slice(start, start + found.length);
                out.push({
                    kind: found.kind,
                    command: at(frame, 3),
                    platformAddress: at(frame, 2),
                    errorCode: found.kind === 'nack' ? at(frame, 5) | (at(frame, 6) << 8) : null,
                    bytes: frame,
                });
                start += found.length;
                continue;
            }
            // A longer candidate may still complete: wait for more bytes.
            if (incomplete)
                break;
            start += 1;
        }
        this.#pending = buf.slice(start);
        return out;
    }
}
