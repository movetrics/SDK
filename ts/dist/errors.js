// Typed errors. Each carries a short machine-readable code.
export class ReplyFormatError extends Error {
    code;
    constructor(code, message) {
        super(message);
        this.name = 'ReplyFormatError';
        this.code = code;
    }
}
export class FrameEncodeError extends Error {
    code;
    frame;
    constructor(code, message, frame = new Uint8Array(0)) {
        super(message);
        this.name = 'FrameEncodeError';
        this.code = code;
        this.frame = frame;
    }
}
// The controller answered with a NACK (BE EF pa cmd 15 err_lo err_hi crc 04 04).
// Error codes are in the firmware.
export class FdtNackError extends Error {
    command;
    platformAddress;
    errorCode;
    constructor(command, platformAddress, errorCode, errorName) {
        super(`controller NACK ${errorCode} (${errorName}) to command 0x${command.toString(16).padStart(2, '0')}`);
        this.name = 'FdtNackError';
        this.command = command;
        this.platformAddress = platformAddress;
        this.errorCode = errorCode;
    }
}
export class FdtTimeoutError extends Error {
    command;
    constructor(command, timeoutMs) {
        super(`no reply to command 0x${command.toString(16).padStart(2, '0')} within ${timeoutMs} ms`);
        this.name = 'FdtTimeoutError';
        this.command = command;
    }
}
export class FdtRefusedError extends Error {
    code;
    constructor(code, message) {
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
