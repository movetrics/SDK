// Test doubles shared by the test files. None of them touches a device or a browser.

import { fromHex, toHex } from '../src/bytes.ts';
import { AsyncQueue, type Transport } from '../src/transport.ts';
import type {
  SerialOpenOptions,
  SerialPortLike,
  SerialReaderLike,
  SerialSignals,
  SerialWriterLike,
} from '../src/webserial.ts';
import type { BleNotifyCharacteristic, BleWriteCharacteristic } from '../src/webbluetooth.ts';

export { fromHex, toHex };

export function bytesOf(hex: string): Uint8Array {
  return fromHex(hex);
}

// A Transport that records every write and replies through a script.
export class FakeTransport implements Transport {
  readonly written: string[] = [];
  readonly #input = new AsyncQueue<Uint8Array>();
  // Called with each frame written. Its return value is pushed to the input, in order.
  respond: ((frame: Uint8Array) => readonly Uint8Array[]) | null = null;
  writeError: Error | null = null;
  closeCalls = 0;

  readonly chunks: AsyncIterable<Uint8Array> = this.#input;

  write(data: Uint8Array): Promise<void> {
    this.written.push(toHex(data));
    if (this.writeError !== null) return Promise.reject(this.writeError);
    const replies = this.respond?.(data.slice()) ?? [];
    for (const reply of replies) this.#input.push(reply);
    return Promise.resolve();
  }

  // Pushes device bytes, given as hex or as bytes.
  push(bytes: string | Uint8Array): void {
    this.#input.push(typeof bytes === 'string' ? fromHex(bytes) : bytes);
  }

  // Ends the device side. With an error, the reader fails with it.
  end(error?: unknown): void {
    this.#input.close(error);
  }

  close(): Promise<void> {
    this.closeCalls++;
    this.#input.close();
    return Promise.resolve();
  }
}

export interface FakeSerialPortOptions {
  // false: the port has no setSignals method, as on a platform without it.
  readonly signals?: boolean;
  // When set, setSignals rejects with this error.
  readonly signalsError?: Error;
}

// A serial port with a scripted device side. The device queue is what the adapter receives.
export class FakeSerialPort implements SerialPortLike {
  readonly device = new AsyncQueue<Uint8Array>();
  readonly written: Uint8Array[] = [];
  // Each setSignals call, in order, with whether the port was open when the call was made.
  readonly signalCalls: { readonly signals: SerialSignals; readonly portOpen: boolean }[] = [];
  readonly setSignals?: (signals: SerialSignals) => Promise<void>;
  opened: SerialOpenOptions | null = null;
  openCalls = 0;
  closeCalls = 0;
  readerCancels = 0;
  readerReleases = 0;
  writerReleases = 0;
  failOpen: Error | null = null;
  withStreams = true;

  constructor(options: FakeSerialPortOptions = {}) {
    if (options.signals === false) return;
    this.setSignals = (signals: SerialSignals) => {
      this.signalCalls.push({ signals: { ...signals }, portOpen: this.opened !== null });
      if (options.signalsError !== undefined) return Promise.reject(options.signalsError);
      return Promise.resolve();
    };
  }

  open(options: SerialOpenOptions): Promise<void> {
    this.openCalls++;
    if (this.failOpen !== null) return Promise.reject(this.failOpen);
    this.opened = { ...options };
    return Promise.resolve();
  }

  close(): Promise<void> {
    this.closeCalls++;
    this.opened = null;
    return Promise.resolve();
  }

  get readable(): { getReader(): SerialReaderLike } | null {
    if (!this.withStreams || this.opened === null) return null;
    return { getReader: () => this.#reader() };
  }

  get writable(): { getWriter(): SerialWriterLike } | null {
    if (!this.withStreams || this.opened === null) return null;
    return { getWriter: () => this.#writer() };
  }

  #reader(): SerialReaderLike {
    const iterator = this.device[Symbol.asyncIterator]();
    return {
      read: async () => {
        const result = await iterator.next();
        return result.done === true ? { done: true } : { done: false, value: result.value };
      },
      cancel: () => {
        this.readerCancels++;
        this.device.close();
        return Promise.resolve();
      },
      releaseLock: () => {
        this.readerReleases++;
      },
    };
  }

  #writer(): SerialWriterLike {
    return {
      write: (chunk: Uint8Array) => {
        this.written.push(chunk.slice());
        return Promise.resolve();
      },
      releaseLock: () => {
        this.writerReleases++;
      },
    };
  }
}

// A notify (TX) characteristic. It keeps an ordered log of the calls it receives.
export class FakeNotifyCharacteristic implements BleNotifyCharacteristic {
  value: DataView | null = null;
  readonly log: string[] = [];
  failStart: Error | null = null;
  readonly #listeners = new Set<() => void>();

  startNotifications(): Promise<unknown> {
    this.log.push('startNotifications');
    if (this.failStart !== null) return Promise.reject(this.failStart);
    return Promise.resolve(this);
  }

  stopNotifications(): Promise<unknown> {
    this.log.push('stopNotifications');
    return Promise.resolve(this);
  }

  addEventListener(type: 'characteristicvaluechanged', listener: () => void): void {
    this.log.push(`add:${type}`);
    this.#listeners.add(listener);
  }

  removeEventListener(type: 'characteristicvaluechanged', listener: () => void): void {
    this.log.push(`remove:${type}`);
    this.#listeners.delete(listener);
  }

  get listenerCount(): number {
    return this.#listeners.size;
  }

  // Simulates a notification carrying `bytes`. The value is set before the listeners run,
  // as in the browser. The DataView wraps a copy, so the test can change `bytes` afterwards.
  notify(bytes: Uint8Array): void {
    const copy = bytes.slice();
    this.value = new DataView(copy.buffer);
    for (const listener of [...this.#listeners]) listener();
  }
}

// A write (RX) characteristic. It records each write and can hold writes open.
export class FakeWriteCharacteristic implements BleWriteCharacteristic {
  readonly written: string[] = [];
  inFlight = 0;
  maxInFlight = 0;
  // When set, each write waits for this promise before it completes.
  gate: Promise<void> | null = null;

  async writeValueWithResponse(value: Uint8Array): Promise<void> {
    this.inFlight++;
    this.maxInFlight = Math.max(this.maxInFlight, this.inFlight);
    this.written.push(toHex(value));
    try {
      if (this.gate !== null) await this.gate;
    } finally {
      this.inFlight--;
    }
  }
}

export function tick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}
