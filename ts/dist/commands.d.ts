export type SafetyClass = 'read-only' | 'configuration' | 'persistent-write' | 'destructive' | 'firmware-update';
export interface CommandInfo {
    readonly code: number;
    readonly name: string;
    readonly safety: SafetyClass;
}
export declare const COMMANDS: {
    readonly START_STREAM: {
        readonly code: 1;
        readonly name: "START_STREAM";
        readonly safety: "configuration";
    };
    readonly STOP_STREAM: {
        readonly code: 5;
        readonly name: "STOP_STREAM";
        readonly safety: "configuration";
    };
    readonly GET_STATUS: {
        readonly code: 34;
        readonly name: "GET_STATUS";
        readonly safety: "read-only";
    };
    readonly GET_FW_VERSION: {
        readonly code: 35;
        readonly name: "GET_FW_VERSION";
        readonly safety: "read-only";
    };
    readonly KEEP_ALIVE: {
        readonly code: 38;
        readonly name: "KEEP_ALIVE";
        readonly safety: "configuration";
    };
    readonly SET_FILTER: {
        readonly code: 28;
        readonly name: "SET_FILTER";
        readonly safety: "configuration";
    };
    readonly SET_SYNC_MODE: {
        readonly code: 40;
        readonly name: "SET_SYNC_MODE";
        readonly safety: "configuration";
    };
    readonly GET_SYNC_MODE: {
        readonly code: 41;
        readonly name: "GET_SYNC_MODE";
        readonly safety: "read-only";
    };
};
export declare const IMPLEMENTED_CODES: ReadonlySet<number>;
export declare const FIRMWARE_COMMAND_NAMES: Readonly<Record<number, string>>;
export interface NotImplementedCommand {
    readonly code: number;
    readonly name: string;
    readonly reason: string;
}
export declare const NOT_IMPLEMENTED: readonly NotImplementedCommand[];
export declare const NOT_IMPLEMENTED_CODES: ReadonlySet<number>;
export declare const FIRMWARE_DISPATCH: ReadonlySet<number>;
export declare const NO_REPLY_ON_SUCCESS: ReadonlySet<number>;
export declare const NACK_ERROR_NAMES: Readonly<Record<number, string>>;
