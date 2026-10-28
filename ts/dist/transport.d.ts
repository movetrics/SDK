export interface Transport {
    write(data: Uint8Array): Promise<void>;
    readonly chunks: AsyncIterable<Uint8Array>;
    close(): Promise<void>;
}
export declare class AsyncQueue<T> implements AsyncIterable<T> {
    #private;
    constructor(maxBacklog?: number);
    get dropped(): number;
    get closed(): boolean;
    push(item: T): void;
    close(error?: unknown): void;
    [Symbol.asyncIterator](): AsyncIterator<T>;
}
