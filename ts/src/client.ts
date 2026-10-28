// FdtClient: the host side of the FDT link over any Transport. It sends the seven commands
// in IMPLEMENTED_CODES (commands.ts) and nothing else. Requests run one at a time, so a
// reply is always matched to the request that caused it, by its command code.

import { COMMANDS, NACK_ERROR_NAMES } from './commands.ts';
import { FdtClosedError, FdtNackError, FdtRefusedError, FdtTimeoutError } from './errors.ts';
import { BROADCAST_ADDRESS, encodeHostFrame, ReplyScanner, type ReplyKind, type ScannedReply } from './frames.ts';
import { parseFirmwareVersion, parseStatus, type FirmwareVersion, type Status } from './status.ts';
import {
  parseEventFrame,
  parseStreamFrame,
  parseSyncModeReply,
  type EventFrame,
  type StreamFrame,
  type StreamItem,
  type SyncModeState,
} from './stream.ts';
import { AsyncQueue, type Transport } from './transport.ts';
import { SampleConverter, type Event, type Gap, type Sample } from './vocabulary.ts';

// Time limits in milliseconds. The firmware sends no timing rule for the host, so these
// are client policy. The notes say what each limit guards against.
export interface ClientTimeouts {
  // ACK, NACK, GET_FW_VERSION reply, and the first GET_STATUS record.
  readonly reply: number;
  // The whole GET_STATUS reply, from the request to the last record.
  readonly status: number;
  // Silence that ends a GET_STATUS reply. The reply carries no record count.
  readonly statusQuiet: number;
  // How long START_STREAM waits for a NACK. START has no success reply (docs/04-host-commands.md section 2).
  readonly settle: number;
}

export const DEFAULT_TIMEOUTS: Readonly<ClientTimeouts> = {
  reply: 1000,
  status: 3000,
  statusQuiet: 150,
  settle: 250,
};

export const DEFAULT_FRAME_BACKLOG = 4096;

// The stream rate is clamped to 50..2000 frames per second per plate (the firmware). 2000 is
// clean over USB on 1.2.8.1+ (bench, 10 Oct 2026); the default after every reset is 500 (1,000 from firmware 1.2.8.8) with a 50 Hz low-pass.
export const MIN_RATE_HZ = 50;
export const MAX_RATE_HZ = 2000;
export const DEFAULT_CUTOFF_HZ = 50;
// The bench tools leave 100 ms between SET_FILTER and START (tools/bench/stream_check.py); the filter is rebuilt then.
const SET_RATE_SETTLE_MS = 100;
// SET_FILTER means cutoff and rate only on Movetrics firmware from 1.2.8.0 (doc 17, SET_FILTER section).
const MIN_SET_FILTER_FIRMWARE: readonly number[] = [1, 2, 8, 0];
const FIRMWARE_VERSION_RE = /^(\d+)\.(\d+)\.(\d+)\.(\d+)/;
// NACK 7: the firmware has no case for the command (ERR_UNKNOWN_COMMAND, the firmware).
const NACK_UNKNOWN_COMMAND = 7;
// NACK 8: the stream is running or armed, so the sync mode cannot change (DRAFT).
const NACK_STREAM_RUNNING = 8;

// Bits of SET_SYNC_MODE (DRAFT; python/movetrics_fdt/client.py SyncMode). Combine them with |.
// 0 is the behaviour of firmware without sync modes.
export const SyncMode = {
  OFF: 0x00,
  START_ON_RISE: 0x01, // arm: START waits for a rising edge on SYNC IN
  STOP_ON_FALL: 0x02, // stop the stream on a falling edge on SYNC IN
  MASTER_OUT: 0x04, // SYNC OUT high while streaming
  EVENT_FRAMES: 0x08, // send an event frame (address 0xFD, code 0x0E) for every edge
  PULSE_TRAIN: 0x10, // SYNC OUT pulses every pulse period while streaming
  SATURATION_EVENTS: 0x20, // event type 7 when a plate value leaves the int16 range
} as const;

// True when a firmware version string such as "1.2.8.20" is at least the minimum. A string without four
// numeric parts is not a Movetrics version, so it is refused, as the Python client does.
function firmwareAtLeast(version: string, minimum: readonly number[]): boolean {
  const match = FIRMWARE_VERSION_RE.exec(version);
  if (match === null) return false;
  for (let i = 0; i < minimum.length; i++) {
    const part = Number(match[i + 1]);
    const floor = minimum[i] ?? 0;
    if (part !== floor) return part > floor;
  }
  return true;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => timers.setTimeout(resolve, ms));
}

export interface ClientOptions {
  readonly timeouts?: Partial<ClientTimeouts>;
  // Stream frames kept for frames() before the oldest are dropped. See droppedFrames.
  readonly frameBacklog?: number;
}

// Timers, without DOM or Node types. The same functions exist in browsers and in Node.
interface TimerHost {
  setTimeout(callback: () => void, ms: number): unknown;
  clearTimeout(id: unknown): void;
}
const timers = globalThis as unknown as TimerHost;

function noop(): void {
  return undefined;
}

// Stream frames from an item queue. Breaking out of the loop does not close the queue (see AsyncQueue).
async function* onlyFrames(items: AsyncIterable<StreamItem>): AsyncGenerator<StreamFrame> {
  for await (const item of items) {
    if (item.kind === 'frame') yield item.frame;
  }
}

// Event frames from an item queue.
async function* onlyEvents(items: AsyncIterable<StreamItem>): AsyncGenerator<EventFrame> {
  for await (const item of items) {
    if (item.kind === 'event') yield item.event;
  }
}

function mergeTimeouts(overrides: Partial<ClientTimeouts> | undefined): Record<keyof ClientTimeouts, number> {
  const merged: Record<keyof ClientTimeouts, number> = { ...DEFAULT_TIMEOUTS };
  for (const key of Object.keys(DEFAULT_TIMEOUTS) as (keyof ClientTimeouts)[]) {
    const value = overrides?.[key];
    if (value === undefined) continue;
    if (!Number.isFinite(value) || value <= 0) {
      throw new RangeError(`timeout ${key} must be a positive number of milliseconds, got ${value}`);
    }
    merged[key] = value;
  }
  return merged;
}

function nackError(reply: ScannedReply): FdtNackError {
  const code = reply.errorCode ?? 0;
  return new FdtNackError(reply.command, reply.platformAddress, code, NACK_ERROR_NAMES[code] ?? 'UNKNOWN_NACK_CODE');
}

// The one reply the client is waiting for.
interface Waiter {
  readonly command: number;
  accept(reply: ScannedReply): void;
  fail(error: unknown): void;
}

export class FdtClient {
  readonly #transport: Transport;
  readonly #timeouts: Record<keyof ClientTimeouts, number>;
  // Stream frames and event frames, in arrival order (see items()).
  readonly #items: AsyncQueue<StreamItem>;
  readonly #scanner = new ReplyScanner();
  readonly #reading: Promise<void>;
  #waiter: Waiter | null = null;
  #tail: Promise<void> = Promise.resolve();
  #closed = false;
  #ended = false;
  // True from a startStream() whose settle window passed without a NACK, until stopStream() is acknowledged.
  #streaming = false;
  // The rate set by the last setRate() that was acknowledged; samples() uses it.
  #rateHz: number | null = null;

  constructor(transport: Transport, options: ClientOptions = {}) {
    const backlog = options.frameBacklog ?? DEFAULT_FRAME_BACKLOG;
    if (!Number.isInteger(backlog) || backlog < 1) {
      throw new RangeError(`frameBacklog must be a positive integer, got ${backlog}`);
    }
    this.#transport = transport;
    this.#timeouts = mergeTimeouts(options.timeouts);
    this.#items = new AsyncQueue<StreamItem>(backlog);
    this.#reading = this.#readLoop();
  }

  // True from a startStream() that passed its settle window until stopStream() is acknowledged.
  get streaming(): boolean {
    return this.#streaming;
  }

  // GET_FW_VERSION (0x23) to 00/00.
  async getFwVersion(): Promise<FirmwareVersion> {
    return this.#exclusive(async () => {
      const command = COMMANDS.GET_FW_VERSION.code;
      const reply = await this.#send(
        encodeHostFrame({ address: 0x00, destination: 0x00, command }),
        this.#awaitReply(command, this.#timeouts.reply, ['firmware_version', 'nack']),
      );
      if (reply.kind === 'nack') throw nackError(reply);
      return parseFirmwareVersion(reply.bytes);
    });
  }

  // GET_STATUS (0x22) to 00/00. Reads the general record and every platform record.
  async getStatus(): Promise<Status> {
    return this.#exclusive(async () => {
      const command = COMMANDS.GET_STATUS.code;
      const records = await this.#send(
        encodeHostFrame({ address: 0x00, destination: 0x00, command }),
        this.#collectStatus(),
      );
      return parseStatus(records.map((record) => record.bytes));
    });
  }

  // START_STREAM (0x01) to FF/FF. Resolves when no NACK arrives within the settle window.
  async startStream(): Promise<void> {
    return this.#exclusive(async () => {
      const command = COMMANDS.START_STREAM.code;
      const frame = encodeHostFrame({ address: BROADCAST_ADDRESS, destination: BROADCAST_ADDRESS, command });
      let reply: ScannedReply;
      try {
        reply = await this.#send(frame, this.#awaitReply(command, this.#timeouts.settle, ['nack']));
      } catch (error) {
        if (error instanceof FdtTimeoutError) {
          this.#streaming = true;
          return;
        }
        throw error;
      }
      throw nackError(reply);
    });
  }

  // STOP_STREAM (0x05) to FF/00. Resolves on the ACK.
  async stopStream(): Promise<void> {
    return this.#exclusive(async () => {
      const command = COMMANDS.STOP_STREAM.code;
      const reply = await this.#send(
        encodeHostFrame({ address: BROADCAST_ADDRESS, destination: 0x00, command }),
        this.#awaitReply(command, this.#timeouts.reply, ['ack', 'nack']),
      );
      if (reply.kind === 'nack') throw nackError(reply);
      this.#streaming = false;
    });
  }

  // SET_FILTER (0x1C) to 00/00: the low-pass cutoff in Hz and the stream rate per plate. Call it with the stream
  // stopped. The controller keeps both in RAM only, so a reset restores 500 frames per second and 50 Hz: set the
  // rate after every connect. It returns 100 ms after the ACK, so startStream() may follow at once.
  //
  // framesPerSecond: 50 to 2000. cutoffHz: 0 for no low-pass (raw, tare-corrected data), or 1 to 255 and below
  // half the rate. First it asks GET_FW_VERSION and refuses (FdtRefusedError, nothing sent after the probe)
  // unless the controller runs Movetrics firmware 1.2.8.0 or later, because other firmware reads 0x1C differently.
  // Throws FrameEncodeError for a rate whose bytes form 04 04 (1028), which the controller would split.
  async setRate(framesPerSecond: number, cutoffHz: number = DEFAULT_CUTOFF_HZ): Promise<void> {
    if (!Number.isInteger(framesPerSecond) || framesPerSecond < MIN_RATE_HZ || framesPerSecond > MAX_RATE_HZ) {
      throw new RangeError(`framesPerSecond must be ${MIN_RATE_HZ}..${MAX_RATE_HZ}, got ${framesPerSecond}`);
    }
    if (
      !Number.isInteger(cutoffHz) ||
      cutoffHz < 0 ||
      cutoffHz > 255 ||
      (cutoffHz !== 0 && cutoffHz * 2 >= framesPerSecond)
    ) {
      throw new RangeError(`cutoffHz must be 0 (off) or 1..255 and below half the rate, got ${cutoffHz}`);
    }
    if (this.#streaming) {
      throw new FdtRefusedError('streaming', 'stop the stream before setRate(); the controller rebuilds its filter between streams');
    }
    const frame = encodeHostFrame({
      address: 0x00,
      destination: 0x00,
      command: COMMANDS.SET_FILTER.code,
      payload: Uint8Array.of(cutoffHz, framesPerSecond & 0xff, framesPerSecond >> 8),
    });
    const version = await this.getFwVersion();
    if (!firmwareAtLeast(version.stm32FW, MIN_SET_FILTER_FIRMWARE)) {
      throw new FdtRefusedError(
        'firmware',
        `setRate needs Movetrics firmware 1.2.8.0 or later; the controller reports '${version.stm32FW}'`,
      );
    }
    await this.#exclusive(async () => {
      const command = COMMANDS.SET_FILTER.code;
      const reply = await this.#send(frame, this.#awaitReply(command, this.#timeouts.reply, ['ack', 'nack']));
      if (reply.kind === 'nack') throw nackError(reply);
      this.#rateHz = framesPerSecond;
      await delay(SET_RATE_SETTLE_MS);
    });
  }

  // SET_SYNC_MODE (0x28, DRAFT) to 00/00. Sends all six payload bytes: the mode bits (see SyncMode), the pulse
  // period in ms, the pulse width in ms, the debounce in 0.1 ms and the arm timeout in minutes. A 0 in any of the
  // last four means the firmware default, so the defaults here are 0. Call it with the stream stopped.
  // Errors: NACK 7 (no sync modes) raises FdtRefusedError 'no_sync_modes'; NACK 8 (stream running or armed) raises
  // FdtRefusedError 'streaming'; NACK 3 (bad parameters, for example MASTER_OUT with PULSE_TRAIN) raises FdtNackError.
  async setSyncMode(
    mode: number,
    pulsePeriodMs: number = 1000,
    pulseWidthMs: number = 0,
    debounce: number = 0,
    armTimeoutMin: number = 0,
  ): Promise<void> {
    if (!Number.isInteger(mode) || mode < 0 || mode > 0xff) {
      throw new RangeError(`mode must be 0..255, got ${mode}`);
    }
    if (!Number.isInteger(pulsePeriodMs) || pulsePeriodMs < 0 || pulsePeriodMs > 0xffff) {
      throw new RangeError(`pulsePeriodMs must be 0..65535 (0 = firmware default), got ${pulsePeriodMs}`);
    }
    for (const [name, value] of [
      ['pulseWidthMs', pulseWidthMs],
      ['debounce', debounce],
      ['armTimeoutMin', armTimeoutMin],
    ] as const) {
      if (!Number.isInteger(value) || value < 0 || value > 0xff) {
        throw new RangeError(`${name} must be 0..255 (0 = firmware default), got ${value}`);
      }
    }
    if (this.#streaming) {
      throw new FdtRefusedError('streaming', 'stop the stream before setSyncMode()');
    }
    const frame = encodeHostFrame({
      address: 0x00,
      destination: 0x00,
      command: COMMANDS.SET_SYNC_MODE.code,
      payload: Uint8Array.of(
        mode,
        pulsePeriodMs & 0xff,
        pulsePeriodMs >> 8,
        pulseWidthMs,
        debounce,
        armTimeoutMin,
      ),
    });
    return this.#exclusive(async () => {
      const command = COMMANDS.SET_SYNC_MODE.code;
      const reply = await this.#send(frame, this.#awaitReply(command, this.#timeouts.reply, ['ack', 'nack']));
      if (reply.kind === 'ack') return;
      if (reply.errorCode === NACK_UNKNOWN_COMMAND) {
        throw new FdtRefusedError(
          'no_sync_modes',
          "this FDT firmware has no sync modes (SET_SYNC_MODE answered NACK 7, 'unknown command'); " +
            'update to a firmware with sync modes, see docs/04',
        );
      }
      if (reply.errorCode === NACK_STREAM_RUNNING) {
        throw new FdtRefusedError('streaming', 'the FDT stream is running or armed; stop it before setSyncMode()');
      }
      throw nackError(reply);
    });
  }

  // GET_SYNC_MODE (0x29, DRAFT) to 00/00: the sync mode state. Returns null when the firmware answers NACK 7,
  // which is the capability probe: firmware without sync modes has no GET_SYNC_MODE either. Other NACKs raise
  // FdtNackError.
  async getSyncMode(): Promise<SyncModeState | null> {
    return this.#exclusive(async () => {
      const command = COMMANDS.GET_SYNC_MODE.code;
      const reply = await this.#send(
        encodeHostFrame({ address: 0x00, destination: 0x00, command }),
        this.#awaitReply(command, this.#timeouts.reply, ['sync_mode', 'nack']),
      );
      if (reply.kind === 'nack') {
        if (reply.errorCode === NACK_UNKNOWN_COMMAND) return null;
        throw nackError(reply);
      }
      return parseSyncModeReply(reply.bytes);
    });
  }

  // KEEP_ALIVE (0x26) to 00/00 with the interval in seconds, a uint16. The firmware sends
  // no reply on success. Its default interval is 600 s, and it sleeps when no command
  // arrives in time. Interval 0 turns the sleep off, so this client refuses it (doc 17).
  async keepAlive(seconds: number): Promise<void> {
    if (!Number.isInteger(seconds) || seconds < 1 || seconds > 0xffff) {
      throw new RangeError(`keepAlive takes whole seconds from 1 to 65535, got ${seconds}`);
    }
    return this.#exclusive(async () => {
      const payload = Uint8Array.of(seconds & 0xff, seconds >> 8);
      const frame = encodeHostFrame({
        address: 0x00,
        destination: 0x00,
        command: COMMANDS.KEEP_ALIVE.code,
        payload,
      });
      await this.#transport.write(frame);
    });
  }

  // Stream frames in arrival order. Event frames are skipped here; items() and events() deliver them. Each
  // item goes to one consumer, so use one of these per client. When the backlog is full the oldest item is
  // dropped (see droppedFrames).
  frames(): AsyncIterable<StreamFrame> {
    return onlyFrames(this.#items);
  }

  // Event frames (sync edges, trigger start, saturation) in arrival order. Stream frames are skipped here.
  events(): AsyncIterable<EventFrame> {
    return onlyEvents(this.#items);
  }

  // Stream frames and event frames together, in the order the controller sent them. Use this when the
  // order of frames and events matters. Each item goes to one consumer.
  items(): AsyncIterable<StreamItem> {
    return this.#items;
  }

  // The stream in the shared vocabulary (docs/19): Samples in SI units and the plate frame, sync Events, and
  // a Gap before the first sample after any hole. Placeholders are dropped. rateHz defaults to the rate of the
  // last acknowledged setRate(); without a rate the period is learnt from the stream. Start a new samples()
  // after each START, because the stamp restarts at 0.
  samples(rateHz: number | null = null): AsyncIterable<Sample | Event | Gap> {
    const converter = new SampleConverter(rateHz || this.#rateHz);
    return (async function* (items: AsyncQueue<StreamItem>) {
      for await (const item of items) yield* converter.push(item);
    })(this.#items);
  }

  // Stream frames and event frames dropped because the consumer did not keep up with the backlog.
  get droppedFrames(): number {
    return this.#items.dropped;
  }

  async close(): Promise<void> {
    if (this.#closed) return;
    this.#closed = true;
    this.#waiter?.fail(new FdtClosedError());
    this.#items.close();
    await this.#transport.close();
  }

  async #readLoop(): Promise<void> {
    try {
      for await (const chunk of this.#transport.chunks) {
        for (const reply of this.#scanner.push(chunk)) this.#dispatch(reply);
      }
    } catch (error) {
      this.#ended = true;
      this.#waiter?.fail(error);
      this.#items.close(error);
      return;
    }
    this.#ended = true;
    this.#waiter?.fail(new FdtClosedError('the transport closed'));
    this.#items.close();
  }

  // Stream and event frames go to the item queue in arrival order. Other replies go to the waiter.
  #dispatch(reply: ScannedReply): void {
    if (reply.kind === 'stream') {
      this.#items.push({ kind: 'frame', frame: parseStreamFrame(reply.bytes) });
      return;
    }
    if (reply.kind === 'event') {
      this.#items.push({ kind: 'event', event: parseEventFrame(reply.bytes) });
      return;
    }
    this.#waiter?.accept(reply);
  }

  // Runs one request at a time, in the order the calls were made.
  #exclusive<T>(task: () => Promise<T>): Promise<T> {
    const run = this.#tail.then(() => {
      if (this.#closed) throw new FdtClosedError();
      if (this.#ended) throw new FdtClosedError('the transport closed');
      return task();
    });
    this.#tail = run.then(noop, noop);
    return run;
  }

  // Registers the waiter and returns the promise. Must run before the frame is written,
  // so a reply that arrives during the write is not lost.
  #awaitReply(command: number, timeoutMs: number, kinds: readonly ReplyKind[]): Promise<ScannedReply> {
    return new Promise<ScannedReply>((resolve, reject) => {
      const timer = timers.setTimeout(() => {
        this.#waiter = null;
        reject(new FdtTimeoutError(command, timeoutMs));
      }, timeoutMs);
      this.#waiter = {
        command,
        accept: (reply) => {
          if (reply.command !== command || !kinds.includes(reply.kind)) return;
          timers.clearTimeout(timer);
          this.#waiter = null;
          resolve(reply);
        },
        fail: (error) => {
          timers.clearTimeout(timer);
          this.#waiter = null;
          reject(error);
        },
      };
    });
  }

  // Collects GET_STATUS records. The first record must come within the reply limit. After
  // that, the reply ends at the quiet limit, or at the overall limit with the records seen so far.
  #collectStatus(): Promise<ScannedReply[]> {
    const command = COMMANDS.GET_STATUS.code;
    const { reply: firstLimit, statusQuiet, status: overallLimit } = this.#timeouts;
    return new Promise<ScannedReply[]>((resolve, reject) => {
      const records: ScannedReply[] = [];
      let firstTimer: unknown = null;
      let quietTimer: unknown = null;
      let overallTimer: unknown = null;

      const stop = (): void => {
        this.#waiter = null;
        timers.clearTimeout(firstTimer);
        timers.clearTimeout(quietTimer);
        timers.clearTimeout(overallTimer);
      };
      const finish = (): void => {
        stop();
        resolve(records);
      };
      const fail = (error: unknown): void => {
        stop();
        reject(error);
      };

      firstTimer = timers.setTimeout(() => fail(new FdtTimeoutError(command, firstLimit)), firstLimit);
      overallTimer = timers.setTimeout(() => {
        if (records.length > 0) finish();
        else fail(new FdtTimeoutError(command, overallLimit));
      }, overallLimit);
      this.#waiter = {
        command,
        accept: (incoming) => {
          if (incoming.command !== command) return;
          if (incoming.kind === 'nack') {
            fail(nackError(incoming));
            return;
          }
          if (incoming.kind !== 'status') return;
          records.push(incoming);
          timers.clearTimeout(firstTimer);
          firstTimer = null;
          timers.clearTimeout(quietTimer);
          quietTimer = timers.setTimeout(finish, statusQuiet);
        },
        fail,
      };
    });
  }

  // Sends one frame, after the reply waiter is registered. A failed write rejects the reply.
  async #send<T>(frame: Uint8Array, pending: Promise<T>): Promise<T> {
    pending.catch(noop);
    try {
      await this.#transport.write(frame);
    } catch (error) {
      this.#waiter?.fail(error);
    }
    return pending;
  }
}
