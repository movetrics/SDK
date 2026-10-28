import { type FirmwareVersion, type Status } from './status.js';
import { type EventFrame, type StreamFrame, type StreamItem, type SyncModeState } from './stream.js';
import { type Transport } from './transport.js';
import { type Event, type Gap, type Sample } from './vocabulary.js';
export interface ClientTimeouts {
    readonly reply: number;
    readonly status: number;
    readonly statusQuiet: number;
    readonly settle: number;
}
export declare const DEFAULT_TIMEOUTS: Readonly<ClientTimeouts>;
export declare const DEFAULT_FRAME_BACKLOG = 4096;
export declare const MIN_RATE_HZ = 50;
export declare const MAX_RATE_HZ = 2000;
export declare const DEFAULT_CUTOFF_HZ = 50;
export declare const SyncMode: {
    readonly OFF: 0;
    readonly START_ON_RISE: 1;
    readonly STOP_ON_FALL: 2;
    readonly MASTER_OUT: 4;
    readonly EVENT_FRAMES: 8;
    readonly PULSE_TRAIN: 16;
    readonly SATURATION_EVENTS: 32;
};
export interface ClientOptions {
    readonly timeouts?: Partial<ClientTimeouts>;
    readonly frameBacklog?: number;
}
export declare class FdtClient {
    #private;
    constructor(transport: Transport, options?: ClientOptions);
    get streaming(): boolean;
    getFwVersion(): Promise<FirmwareVersion>;
    getStatus(): Promise<Status>;
    startStream(): Promise<void>;
    stopStream(): Promise<void>;
    setRate(framesPerSecond: number, cutoffHz?: number): Promise<void>;
    setSyncMode(mode: number, pulsePeriodMs?: number, pulseWidthMs?: number, debounce?: number, armTimeoutMin?: number): Promise<void>;
    getSyncMode(): Promise<SyncModeState | null>;
    keepAlive(seconds: number): Promise<void>;
    frames(): AsyncIterable<StreamFrame>;
    events(): AsyncIterable<EventFrame>;
    items(): AsyncIterable<StreamItem>;
    samples(rateHz?: number | null): AsyncIterable<Sample | Event | Gap>;
    get droppedFrames(): number;
    close(): Promise<void>;
}
