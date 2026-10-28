// Typed errors. Each carries a short machine-readable code.

// Reply framing and layout errors (reply bytes that do not decode).
export type ReplyErrorCode =
  | 'bad_length'
  | 'bad_header'
  | 'bad_command'
  | 'bad_end_marker'
  | 'crc_mismatch'
  | 'bad_platform_order';

export class ReplyFormatError extends Error {
  readonly code: ReplyErrorCode;

  constructor(code: ReplyErrorCode, message: string) {
    super(message);
    this.name = 'ReplyFormatError';
    this.code = code;
  }
}

// Request frames the client refuses to build. 'early_04_04_delimiter' means the
// controller's RX splitter would end the message before its real end
// (doc 03 section 3.3). 'not_implemented' means the command is one the client does not
// send (commands.ts NOT_IMPLEMENTED). The frame that would have been sent is in `frame`.
export type FrameEncodeCode = 'early_04_04_delimiter' | 'not_implemented' | 'too_long' | 'bad_field';

export class FrameEncodeError extends Error {
  readonly code: FrameEncodeCode;
  readonly frame: Uint8Array;

  constructor(code: FrameEncodeCode, message: string, frame: Uint8Array = new Uint8Array(0)) {
    super(message);
    this.name = 'FrameEncodeError';
    this.code = code;
    this.frame = frame;
  }
}

// The controller answered with a NACK (BE EF pa cmd 15 err_lo err_hi crc 04 04).
// Error codes are in the firmware.
export class FdtNackError extends Error {
  readonly command: number;
  readonly platformAddress: number;
  readonly errorCode: number;

  constructor(command: number, platformAddress: number, errorCode: number, errorName: string) {
    super(`controller NACK ${errorCode} (${errorName}) to command 0x${command.toString(16).padStart(2, '0')}`);
    this.name = 'FdtNackError';
    this.command = command;
    this.platformAddress = platformAddress;
    this.errorCode = errorCode;
  }
}

export class FdtTimeoutError extends Error {
  readonly command: number;

  constructor(command: number, timeoutMs: number) {
    super(`no reply to command 0x${command.toString(16).padStart(2, '0')} within ${timeoutMs} ms`);
    this.name = 'FdtTimeoutError';
    this.command = command;
  }
}

// A call the client refuses because the state of the controller or its firmware rules it out.
// 'streaming': the stream is running (set rate and sync mode need it stopped). 'firmware': GET_FW_VERSION
// names firmware that is too old for SET_FILTER. 'no_sync_modes': the firmware answered NACK 7 to
// SET_SYNC_MODE. The message says what to do.
export type RefusalCode = 'streaming' | 'firmware' | 'no_sync_modes';

export class FdtRefusedError extends Error {
  readonly code: RefusalCode;

  constructor(code: RefusalCode, message: string) {
    super(message);
    this.name = 'FdtRefusedError';
    this.code = code;
  }
}

export class FdtClosedError extends Error {
  constructor(message = 'the client is closed') {
    super(message);
    this.name = 'FdtClosedError';
  }
}
