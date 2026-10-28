import { type ReplyErrorCode } from './errors.js';
export declare const STREAM_FRAME_LENGTH = 24;
export declare const STREAM_COMMAND = 1;
export declare const EVENT_ADDRESS = 253;
export declare const EVENT_COMMAND = 14;
export declare const EVENT_NAMES: Readonly<Record<number, string>>;
export declare function eventName(eventType: number): string;
export interface EventFrame {
    readonly timeStamp: number;
    readonly eventType: number;
    readonly source: number;
    readonly count: number;
    readonly offsetUs: number;
    readonly detail: number;
    readonly mode: number;
}
export type StreamItem = {
    readonly kind: 'frame';
    readonly frame: StreamFrame;
} | {
    readonly kind: 'event';
    readonly event: EventFrame;
};
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
export type StreamDecodeResult = {
    readonly valid: true;
    readonly frame: StreamFrame;
} | {
    readonly valid: false;
    readonly reason: ReplyErrorCode;
};
export declare function parseStreamFrame(bytes: Uint8Array): StreamFrame;
export declare function decodeStreamFrame(bytes: Uint8Array): StreamDecodeResult;
export declare function encodeStreamFrame(frame: StreamFrame): Uint8Array;
export declare const SYNC_MODE_COMMAND = 41;
export declare const SYNC_MODE_REPLY_LENGTH = 26;
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
export declare function parseSyncModeReply(bytes: Uint8Array): SyncModeState;
export declare function parseEventFrame(bytes: Uint8Array): EventFrame;
export declare function encodeEventFrame(event: EventFrame): Uint8Array;
export declare class StreamDecoder {
    #private;
    push(chunk: Uint8Array): StreamFrame[];
    pushItems(chunk: Uint8Array): StreamItem[];
}
