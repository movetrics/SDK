export declare function at(bytes: Uint8Array, index: number): number;
export declare function concatBytes(parts: readonly Uint8Array[]): Uint8Array;
export declare function toHex(bytes: Uint8Array): string;
export declare function fromHex(hex: string): Uint8Array;
export declare function dataView(bytes: Uint8Array): DataView;
export declare function asciiField(bytes: Uint8Array, start: number, width: number): string;
