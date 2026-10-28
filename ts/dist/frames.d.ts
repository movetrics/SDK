export declare const EOT = 4;
export declare const ACK_CODE = 6;
export declare const NACK_CODE = 21;
export declare const BROADCAST_ADDRESS = 255;
export declare const HOST_MESSAGE_MAX = 320;
export declare const REQUEST_MIN_LENGTH = 9;
export declare const ACK_LENGTH = 9;
export declare const NACK_LENGTH = 11;
export interface HostRequest {
    readonly address: number;
    readonly destination: number;
    readonly command: number;
    readonly payload?: Uint8Array | undefined;
}
export declare function buildHostFrame(request: HostRequest): Uint8Array;
export declare function earlyDelimiterAt(frame: Uint8Array): number;
export declare function encodeHostFrame(request: HostRequest): Uint8Array;
export declare class HostRxSplitter {
    #private;
    push(bytes: Uint8Array): Uint8Array[];
}
export type HostFrameReason = 'shorter_than_9_bytes' | 'bad_header' | 'crc_mismatch' | 'bad_end_marker';
export type DeviceReply = {
    readonly reply: 'command_reply';
} | {
    readonly reply: 'none';
    readonly reason: string;
} | {
    readonly nack_code: number;
};
export type HostParseResult = {
    readonly valid: false;
    readonly reason: HostFrameReason;
    readonly device_reply: DeviceReply;
    readonly dispatched: false;
} | {
    readonly valid: true;
    readonly command: number;
    readonly address: number;
    readonly destination: number;
    readonly payload: Uint8Array;
    readonly device_reply: DeviceReply;
    readonly dispatched: boolean;
};
export declare function parseHostMessage(message: Uint8Array): HostParseResult;
export type ReplyKind = 'stream' | 'event' | 'sync_mode' | 'ack' | 'nack' | 'status' | 'firmware_version';
export interface ScannedReply {
    readonly kind: ReplyKind;
    readonly command: number;
    readonly platformAddress: number;
    readonly errorCode: number | null;
    readonly bytes: Uint8Array;
}
export declare class ReplyScanner {
    #private;
    push(chunk: Uint8Array): ScannedReply[];
}
