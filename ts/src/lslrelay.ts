// Local relay client: sends what FdtClient.samples() yields to the SDK's Lab Streaming Layer relay
// (`movetrics-fdt lsl-relay`, docs/22-lsl-and-sync.md), which publishes it with the same streams, units and clock
// mapping as the Python LslBridge. A browser cannot publish LSL itself: it cannot open the sockets LSL uses.
//
//   const relay = await LslRelay.open({ rateHz: 2000, plates: [1, 2], firmware: version.stm32 });
//   for await (const item of client.samples()) relay.push(item);
//
// Wire format (JSON text, one message per batch): hello, then {"type": "items", "items": [...]} and {"type": "mark"}.
// The relay stamps each message when it arrives and maps the FDT's own clock onto LSL's from those arrivals, so
// items are sent as they come (at most flushMs late), never held back.

import type { Event, Gap, Sample } from './vocabulary.ts';

export const LSL_RELAY_URL = 'ws://127.0.0.1:7812';
export const LSL_RELAY_PROTOCOL_VERSION = 1;

const DEVICE_LABEL = /^[A-Za-z0-9_-]+$/;

// Timers, without DOM or Node types (as in client.ts). The same functions exist in browsers and in Node.
interface TimerHost {
  setTimeout(callback: () => void, ms: number): unknown;
  clearTimeout(id: unknown): void;
}
const timers = globalThis as unknown as TimerHost;

// The part of the WebSocket API this client uses. The browser's WebSocket and Node's global WebSocket fit.
export interface WebSocketLike {
  readonly bufferedAmount: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  addEventListener(type: 'open' | 'message' | 'close' | 'error', listener: (event: WebSocketEventLike) => void): void;
}

export interface WebSocketEventLike {
  readonly data?: unknown;
  readonly code?: number;
  readonly reason?: string;
}

export interface LslRelayOptions {
  // Frames per second per plate, as set with setRate().
  readonly rateHz: number;
  // Default [1, 2].
  readonly plates?: readonly number[];
  // The STM32 firmware version; it goes into the stream description.
  readonly firmware?: string;
  // A label when more than one FDT streams on the network: "Movetrics FDT B plate 1". The relay's --device wins.
  readonly device?: string;
  // Default LSL_RELAY_URL.
  readonly url?: string;
  // Items wait at most this long before they go out together (default 10 ms).
  readonly flushMs?: number;
  // A batch goes out as soon as it holds this many items (default 200).
  readonly maxBatch?: number;
  // How long to wait for the relay's ready (default 5000 ms).
  readonly openTimeoutMs?: number;
  // Above this many unsent bytes the relay is not keeping up: the connection is closed and push() throws (default 8 MiB).
  readonly maxBufferedBytes?: number;
  // How to open the socket. Default: the global WebSocket (every browser, Node 22 and later).
  readonly socket?: (url: string) => WebSocketLike;
}

export interface LslRelayClosed {
  readonly code: number;
  readonly reason: string;
}

export class LslRelayError extends Error {
  // The WebSocket close code when the relay closed the connection, else null.
  readonly code: number | null;

  constructor(message: string, code: number | null = null) {
    super(message);
    this.name = 'LslRelayError';
    this.code = code;
  }
}

type Wire = Record<string, number | string | null>;

interface Connection {
  end: LslRelayClosed | null;
}

export class LslRelay {
  // The LSL stream names the relay publishes, from its ready message (what to tick in LabRecorder).
  readonly streams: readonly string[];
  // Resolves when the connection ends, by close() or by the relay (its code and reason say why).
  readonly closed: Promise<LslRelayClosed>;
  readonly #socket: WebSocketLike;
  readonly #connection: Connection;
  readonly #flushMs: number;
  readonly #maxBatch: number;
  readonly #maxBufferedBytes: number;
  #pending: Wire[] = [];
  #timer: unknown = null;
  #closing = false;

  private constructor(socket: WebSocketLike, connection: Connection, closed: Promise<LslRelayClosed>,
                      streams: readonly string[], options: LslRelayOptions) {
    this.#socket = socket;
    this.#connection = connection;
    this.closed = closed;
    this.streams = streams;
    this.#flushMs = options.flushMs ?? 10;
    this.#maxBatch = options.maxBatch ?? 200;
    this.#maxBufferedBytes = options.maxBufferedBytes ?? 8 * 1024 * 1024;
  }

  // Connects, says hello and waits for ready. Bad options are refused before anything connects.
  static async open(options: LslRelayOptions): Promise<LslRelay> {
    const hello = helloMessage(options);
    const url = options.url ?? LSL_RELAY_URL;
    const timeoutMs = options.openTimeoutMs ?? 5000;
    const socket = (options.socket ?? globalSocket)(url);
    const connection: Connection = { end: null };
    let markClosed: (end: LslRelayClosed) => void = () => {};
    const closed = new Promise<LslRelayClosed>((resolve) => {
      markClosed = resolve;
    });
    socket.addEventListener('close', (event) => {
      if (connection.end !== null) return;
      connection.end = { code: typeof event.code === 'number' ? event.code : 1006, reason: typeof event.reason === 'string' ? event.reason : '' };
      markClosed(connection.end);
    });
    const streams = await new Promise<readonly string[]>((resolve, reject) => {
      let settled = false;
      const finish = (result: readonly string[] | LslRelayError): void => {
        if (settled) return;
        settled = true;
        timers.clearTimeout(timer);
        if (Array.isArray(result)) {
          resolve(result);
        } else {
          if (connection.end === null) socket.close(1000, 'giving up');
          reject(result);
        }
      };
      const timer = timers.setTimeout(() => finish(new LslRelayError(`the relay at ${url} did not answer within ${timeoutMs} ms`)), timeoutMs);
      socket.addEventListener('open', () => socket.send(JSON.stringify(hello)));
      socket.addEventListener('message', (event) => {
        const reply = parseObject(event.data);
        const names = reply?.['streams'];
        if (reply?.['type'] === 'ready' && Array.isArray(names)) finish(names.map(String));
        else finish(new LslRelayError('the relay did not answer hello with ready'));
      });
      socket.addEventListener('close', (event) => finish(closeError(url, event)));
    });
    return new LslRelay(socket, connection, closed, streams, options);
  }

  // Queues one item; it goes out within flushMs, or at once when the batch is full.
  push(item: Sample | Event | Gap): void {
    this.#checkOpen();
    this.#pending.push(toWire(item));
    if (this.#socket.bufferedAmount > this.#maxBufferedBytes) {
      this.#closing = true;
      this.#socket.close(1000, 'relay not keeping up');
      throw new LslRelayError(`the relay is not keeping up: more than ${this.#maxBufferedBytes} bytes are waiting to be sent`);
    }
    if (this.#pending.length >= this.#maxBatch) this.flush();
    else if (this.#timer === null) this.#timer = timers.setTimeout(() => this.flush(), this.#flushMs);
  }

  // A free-text marker at the relay's current time (trial names, "jump 3"). Queued items go first.
  mark(text: string): void {
    this.#checkOpen();
    if (text.length === 0 || text.length > 256) throw new LslRelayError('a mark needs text of 1 to 256 characters');
    this.flush();
    this.#socket.send(JSON.stringify({ type: 'mark', text }));
  }

  // Sends the queued items now.
  flush(): void {
    if (this.#timer !== null) {
      timers.clearTimeout(this.#timer);
      this.#timer = null;
    }
    if (this.#pending.length === 0 || this.#connection.end !== null) return;
    const items = this.#pending;
    this.#pending = [];
    this.#socket.send(JSON.stringify({ type: 'items', items }));
  }

  // Sends what is queued and closes; the relay then takes the streams off the network.
  close(): void {
    if (this.#closing || this.#connection.end !== null) return;
    this.flush();
    this.#closing = true;
    this.#socket.close(1000, 'done');
  }

  #checkOpen(): void {
    const end = this.#connection.end;
    if (end !== null) {
      throw new LslRelayError(`the relay closed the connection (${end.code}${end.reason ? `: ${end.reason}` : ''})`, end.code);
    }
    if (this.#closing) throw new LslRelayError('this LslRelay is closed');
  }
}

function helloMessage(options: LslRelayOptions): Record<string, unknown> {
  const rate = options.rateHz;
  if (!Number.isFinite(rate) || rate <= 0 || rate > 100_000) throw new LslRelayError('rateHz must be above 0 and at most 100000');
  const plates = options.plates ?? [1, 2];
  if (plates.length === 0 || new Set(plates).size !== plates.length || !plates.every((p) => Number.isInteger(p) && p >= 1 && p <= 4)) {
    throw new LslRelayError('plates must be distinct plate numbers from 1 to 4');
  }
  const firmware = options.firmware ?? 'unknown';
  if (firmware.length === 0 || firmware.length > 64) throw new LslRelayError('firmware must be 1 to 64 characters');
  if (options.device !== undefined && !DEVICE_LABEL.test(options.device)) {
    throw new LslRelayError("device must be letters, digits, '-' or '_'");
  }
  if ((options.flushMs ?? 10) < 0 || (options.maxBatch ?? 200) < 1) throw new LslRelayError('flushMs must be 0 or more and maxBatch at least 1');
  return { type: 'hello', version: LSL_RELAY_PROTOCOL_VERSION, rate_hz: rate, plates: [...plates], firmware, device: options.device ?? null };
}

function toWire(item: Sample | Event | Gap): Wire {
  switch (item.kind) {
    case 'sample':
      return {
        kind: 'sample', t: item.t, plate: item.plate, fx: item.fx, fy: item.fy, fz: item.fz, mx: item.mx, my: item.my, mz: item.mz,
        // JSON has no NaN: the centre of pressure below 50 N travels as null and is NaN again on LSL.
        cop_x: Number.isFinite(item.cop_x) ? item.cop_x : null,
        cop_y: Number.isFinite(item.cop_y) ? item.cop_y : null,
        stamp: item.stamp,
      };
    case 'event':
      return {
        kind: 'event', t: item.t, name: item.name, type: item.type, source: item.source, count: item.count,
        detail: item.detail, stamp: item.stamp, offset_us: item.offset_us,
      };
    case 'gap':
      return { kind: 'gap', plate: item.plate, start_t: item.start_t, end_t: item.end_t, missing: item.missing };
  }
}

function parseObject(data: unknown): Record<string, unknown> | null {
  if (typeof data !== 'string') return null;
  try {
    const value: unknown = JSON.parse(data);
    return typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function closeError(url: string, event: WebSocketEventLike): LslRelayError {
  const code = typeof event.code === 'number' ? event.code : 1006;
  if (code === 1006) {
    return new LslRelayError(`could not reach the relay at ${url}: is movetrics-fdt lsl-relay running, and does it accept this page's origin?`, code);
  }
  return new LslRelayError(`the relay closed the connection (${code}${event.reason ? `: ${event.reason}` : ''})`, code);
}

function globalSocket(url: string): WebSocketLike {
  const Socket = (globalThis as { WebSocket?: new (url: string) => WebSocketLike }).WebSocket;
  if (Socket === undefined) throw new LslRelayError('no WebSocket in this runtime: pass options.socket');
  return new Socket(url);
}
