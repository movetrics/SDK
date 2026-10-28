import { type Transport } from './transport.js';
export interface SerialOpenOptions {
    readonly baudRate: number;
    readonly dataBits?: 7 | 8;
    readonly stopBits?: 1 | 2;
    readonly parity?: 'none' | 'even' | 'odd';
    readonly flowControl?: 'none' | 'hardware';
}
export declare const SERIAL_OPTIONS: Readonly<SerialOpenOptions>;
export interface SerialSignals {
    readonly dataTerminalReady?: boolean;
    readonly requestToSend?: boolean;
    readonly break?: boolean;
}
export interface SerialReaderLike {
    read(): Promise<{
        readonly done: boolean;
        readonly value?: Uint8Array | undefined;
    }>;
    cancel(reason?: unknown): Promise<void>;
    releaseLock(): void;
}
export interface SerialWriterLike {
    write(chunk: Uint8Array): Promise<void>;
    releaseLock(): void;
}
export interface SerialPortLike {
    open(options: SerialOpenOptions): Promise<void>;
    setSignals?(signals: SerialSignals): Promise<void>;
    close(): Promise<void>;
    readonly readable: {
        getReader(): SerialReaderLike;
    } | null;
    readonly writable: {
        getWriter(): SerialWriterLike;
    } | null;
}
export declare class WebSerialTransport implements Transport {
    #private;
    readonly chunks: AsyncIterable<Uint8Array>;
    private constructor();
    static open(port: SerialPortLike): Promise<WebSerialTransport>;
    write(data: Uint8Array): Promise<void>;
    close(): Promise<void>;
}
