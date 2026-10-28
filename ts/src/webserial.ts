// Web Serial transport for the USB link. The adapter is an FTDI FT232R on USART3, at
// 1,500,000 baud, 8 data bits, one stop bit, no parity and no flow control
// (docs/02-transports.md, USB row; the firmware). The browser side is UNVERIFIED:
// no pinned repository uses Web Serial (docs/02-transports.md, U1).

import { AsyncQueue, type Transport } from './transport.ts';

export interface SerialOpenOptions {
  readonly baudRate: number;
  readonly dataBits?: 7 | 8;
  readonly stopBits?: 1 | 2;
  readonly parity?: 'none' | 'even' | 'odd';
  readonly flowControl?: 'none' | 'hardware';
}

// The options the USB link opens with. the firmware sets the default baud rate.
export const SERIAL_OPTIONS: Readonly<SerialOpenOptions> = {
  baudRate: 1500000,
  dataBits: 8,
  stopBits: 1,
  parity: 'none',
  flowControl: 'none',
};

// The part of a Web Serial SerialPort that the transport uses. Structural, so the SDK
// needs no DOM types, and tests can pass a fake.
// The output signals a Web Serial port can set (SerialPort.setSignals). Each one is optional.
export interface SerialSignals {
  readonly dataTerminalReady?: boolean;
  readonly requestToSend?: boolean;
  readonly break?: boolean;
}

export interface SerialReaderLike {
  read(): Promise<{ readonly done: boolean; readonly value?: Uint8Array | undefined }>;
  cancel(reason?: unknown): Promise<void>;
  releaseLock(): void;
}

export interface SerialWriterLike {
  write(chunk: Uint8Array): Promise<void>;
  releaseLock(): void;
}

export interface SerialPortLike {
  open(options: SerialOpenOptions): Promise<void>;
  // Web Serial's SerialPort.setSignals. Optional: a platform without it still opens.
  setSignals?(signals: SerialSignals): Promise<void>;
  close(): Promise<void>;
  readonly readable: { getReader(): SerialReaderLike } | null;
  readonly writable: { getWriter(): SerialWriterLike } | null;
}

export class WebSerialTransport implements Transport {
  readonly #port: SerialPortLike;
  readonly #reader: SerialReaderLike;
  readonly #writer: SerialWriterLike;
  readonly #input = new AsyncQueue<Uint8Array>();
  readonly #pump: Promise<void>;
  #closed = false;

  readonly chunks: AsyncIterable<Uint8Array> = this.#input;

  private constructor(port: SerialPortLike, reader: SerialReaderLike, writer: SerialWriterLike) {
    this.#port = port;
    this.#reader = reader;
    this.#writer = writer;
    this.#pump = this.#readAll();
  }

  // Opens the port with SERIAL_OPTIONS, clears DTR and RTS where the platform has setSignals,
  // and takes its streams. If the setSignals call rejects or a stream is missing, the port is
  // closed again and the error is raised.
  static async open(port: SerialPortLike): Promise<WebSerialTransport> {
    await port.open({ ...SERIAL_OPTIONS });
    try {
      if (typeof port.setSignals === 'function') {
        // The Android app's USB path never sets either line, source only:
        // android:app/src/main/java/com/movetrics/fdt/android/NoModemControlFtdiPort.java:9 and 16-26.
        // This call clears both lines, so neither is asserted. fdt:docs/architecture.md:44 (an
        // earlier SDK note, not firmware fact) says opening a port may affect modem lines and that
        // DTR/RTS choices are to be recorded. The first hardware run must check for reset-like
        // behaviour. The browser effect is UNVERIFIED.
        await port.setSignals({ dataTerminalReady: false, requestToSend: false });
      }
      const readable = port.readable;
      const writable = port.writable;
      if (readable === null || writable === null) {
        throw new Error('the serial port opened without its readable and writable streams');
      }
      return new WebSerialTransport(port, readable.getReader(), writable.getWriter());
    } catch (error) {
      await port.close().catch(() => undefined);
      throw error;
    }
  }

  async write(data: Uint8Array): Promise<void> {
    if (this.#closed) throw new Error('the serial port is closed');
    await this.#writer.write(data.slice());
  }

  async close(): Promise<void> {
    if (this.#closed) return;
    this.#closed = true;
    await this.#reader.cancel().catch(() => undefined);
    await this.#pump;
    this.#writer.releaseLock();
    await this.#port.close();
  }

  async #readAll(): Promise<void> {
    try {
      for (;;) {
        const result = await this.#reader.read();
        if (result.done) break;
        if (result.value !== undefined) this.#input.push(result.value.slice());
      }
      this.#input.close();
    } catch (error) {
      this.#input.close(error);
    }
    try {
      this.#reader.releaseLock();
    } catch {
      // The reader is already released.
    }
  }
}
