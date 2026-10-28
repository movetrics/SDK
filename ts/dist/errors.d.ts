export type ReplyErrorCode = 'bad_length' | 'bad_header' | 'bad_command' | 'bad_end_marker' | 'crc_mismatch' | 'bad_platform_order';
export declare class ReplyFormatError extends Error {
    readonly code: ReplyErrorCode;
    constructor(code: ReplyErrorCode, message: string);
}
export type FrameEncodeCode = 'early_04_04_delimiter' | 'not_implemented' | 'too_long' | 'bad_field';
export declare class FrameEncodeError extends Error {
    readonly code: FrameEncodeCode;
    readonly frame: Uint8Array;
    constructor(code: FrameEncodeCode, message: string, frame?: Uint8Array);
}
export declare class FdtNackError extends Error {
    readonly command: number;
    readonly platformAddress: number;
    readonly errorCode: number;
    constructor(command: number, platformAddress: number, errorCode: number, errorName: string);
}
export declare class FdtTimeoutError extends Error {
    readonly command: number;
    constructor(command: number, timeoutMs: number);
}
export type RefusalCode = 'streaming' | 'firmware' | 'no_sync_modes';
export declare class FdtRefusedError extends Error {
    readonly code: RefusalCode;
    constructor(code: RefusalCode, message: string);
}
export declare class FdtClosedError extends Error {
    constructor(message?: string);
}
