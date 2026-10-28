export type RecordLength = 85 | 86;
export type LengthClass = '85' | '86' | '85x2' | '86x2' | '85x3' | '86x3';
export interface StatusRecord {
    readonly platformAddress: number;
    readonly commandCode: number;
    readonly errorFlags: number;
    readonly temperature: number;
    readonly serialParams: string;
    readonly wifiSSID: string;
    readonly wifiIP: readonly [number, number, number, number];
    readonly wifiMask: readonly [number, number, number, number];
    readonly wifiGW: readonly [number, number, number, number];
    readonly cacheFrames: number;
    readonly calibrationFactorX: number;
    readonly calibrationFactorY: number;
    readonly calibrationFactorZ: number;
    readonly batterySOC: number | null;
}
export interface Status {
    readonly lengthClass: LengthClass;
    readonly general: StatusRecord;
    readonly platforms: readonly StatusRecord[];
}
export interface FirmwareVersion {
    readonly platformAddress: number;
    readonly commandCode: number;
    readonly stm32FW: string;
    readonly esp32FW: string;
}
export declare function parseStatusRecord(bytes: Uint8Array): StatusRecord;
export declare function parseStatus(records: readonly Uint8Array[]): Status;
export declare function parseFirmwareVersion(bytes: Uint8Array): FirmwareVersion;
