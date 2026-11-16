import type { Event, Gap, Sample } from './vocabulary.js';
export declare const LSL_RELAY_URL = "ws://127.0.0.1:7812";
export declare const LSL_RELAY_PROTOCOL_VERSION = 1;
export interface WebSocketLike {
    readonly bufferedAmount: number;
    send(data: string): void;
    close(code?: number, reason?: string): void;
    addEventListener(type: 'open' | 'message' | 'close' | 'error', listener: (event: WebSocketEventLike) => void): void;
}
export interface WebSocketEventLike {
    readonly data?: unknown;
    readonly code?: number;
    readonly reason?: string;
}
export interface LslRelayOptions {
    readonly rateHz: number;
    readonly plates?: readonly number[];
    readonly firmware?: string;
    readonly device?: string;
    readonly url?: string;
    readonly flushMs?: number;
    readonly maxBatch?: number;
    readonly openTimeoutMs?: number;
    readonly maxBufferedBytes?: number;
    readonly socket?: (url: string) => WebSocketLike;
}
export interface LslRelayClosed {
    readonly code: number;
    readonly reason: string;
}
export declare class LslRelayError extends Error {
    readonly code: number | null;
    constructor(message: string, code?: number | null);
}
export declare class LslRelay {
    #private;
    readonly streams: readonly string[];
    readonly closed: Promise<LslRelayClosed>;
    private constructor();
    static open(options: LslRelayOptions): Promise<LslRelay>;
    push(item: Sample | Event | Gap): void;
    mark(text: string): void;
    flush(): void;
    close(): void;
}
