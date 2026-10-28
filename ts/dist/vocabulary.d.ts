import { type StreamItem } from './stream.js';
export declare const TICKS_PER_SECOND = 10000;
export declare const STAMP_MODULUS: number;
export declare const MOMENT_REFERENCE_DEPTH_M = 0.03;
export declare const COP_MIN_FZ_N = 50;
export declare const STREAM_SIGN: readonly [1, -1, 1, -1, 1, 1];
export interface Sample {
    readonly kind: 'sample';
    readonly t: number;
    readonly plate: number;
    readonly fx: number;
    readonly fy: number;
    readonly fz: number;
    readonly mx: number;
    readonly my: number;
    readonly mz: number;
    readonly cop_x: number;
    readonly cop_y: number;
    readonly stamp: number;
    readonly raw: readonly [number, number, number, number, number, number];
}
export interface Event {
    readonly kind: 'event';
    readonly t: number;
    readonly type: number;
    readonly name: string;
    readonly source: number;
    readonly count: number;
    readonly detail: number;
    readonly stamp: number;
    readonly offset_us: number;
}
export interface Gap {
    readonly kind: 'gap';
    readonly plate: number;
    readonly start_t: number;
    readonly end_t: number;
    readonly missing: number;
}
export type VocabularyItem = Sample | Event | Gap;
export interface SampleConverterOptions {
    readonly copMinFzN?: number;
}
export declare function plateCop(fx: number, fy: number, fz: number, mx: number, my: number, minFzN?: number, depthM?: number): readonly [number, number];
export declare class SampleConverter {
    #private;
    readonly gaps: Gap[];
    constructor(rateHz?: number | null, options?: SampleConverterOptions);
    get placeholders(): number;
    push(item: StreamItem): VocabularyItem[];
    convert(items: Iterable<StreamItem>): Generator<VocabularyItem>;
}
export interface CombinedWrench {
    readonly fx: number;
    readonly fy: number;
    readonly fz: number;
    readonly mx: number;
    readonly my: number;
    readonly mz: number;
    readonly cop_x: number;
    readonly cop_y: number;
}
export declare function combine(samples: ReadonlyMap<number, Sample>, copMinFzN?: number): CombinedWrench;
