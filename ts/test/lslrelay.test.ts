import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { LSL_RELAY_URL, LslRelay, LslRelayError, type WebSocketEventLike, type WebSocketLike } from '../src/lslrelay.ts';
import type { Event, Gap, Sample } from '../src/vocabulary.ts';

// Plays the relay's side of the socket: the tests open it, answer hello and close it.
class FakeSocket implements WebSocketLike {
  bufferedAmount = 0;
  readonly sent: unknown[] = [];
  closedWith: [number | undefined, string | undefined] | null = null;
  readonly #listeners = new Map<string, ((event: WebSocketEventLike) => void)[]>();

  addEventListener(type: string, listener: (event: WebSocketEventLike) => void): void {
    this.#listeners.set(type, [...(this.#listeners.get(type) ?? []), listener]);
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(code?: number, reason?: string): void {
    this.closedWith = [code, reason];
  }

  emit(type: string, event: WebSocketEventLike = {}): void {
    for (const listener of this.#listeners.get(type) ?? []) listener(event);
  }

  ready(streams: string[] = ['Movetrics FDT plate 1', 'Movetrics FDT markers']): void {
    this.emit('message', { data: JSON.stringify({ type: 'ready', streams }) });
  }
}

function sample(t: number, plate = 1, fz = 700, cop: [number, number] = [0.0057, -0.0043]): Sample {
  return {
    kind: 'sample', t, plate, fx: 1, fy: 2, fz, mx: 3, my: -4, mz: 0.5, cop_x: cop[0], cop_y: cop[1],
    stamp: Math.round(t * 10000), raw: [1, -2, fz, -3, -4, 0],
  };
}

// Opens a relay on a fake socket that answers at once.
async function opened(options: Partial<Parameters<typeof LslRelay.open>[0]> = {}): Promise<{ relay: LslRelay; socket: FakeSocket }> {
  const socket = new FakeSocket();
  const opening = LslRelay.open({ rateHz: 1000, plates: [1], firmware: '1.2.8.20', socket: () => socket, ...options });
  socket.emit('open');
  socket.ready();
  return { relay: await opening, socket };
}

const tick = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

describe('LslRelay', () => {
  test('says hello on open and learns the stream names from ready', async () => {
    let usedUrl = '';
    const socket = new FakeSocket();
    const opening = LslRelay.open({ rateHz: 2000, firmware: '1.2.8.20', device: 'B', socket: (url) => ((usedUrl = url), socket) });
    socket.emit('open');
    assert.deepEqual(socket.sent, [{ type: 'hello', version: 1, rate_hz: 2000, plates: [1, 2], firmware: '1.2.8.20', device: 'B' }]);
    socket.ready(['Movetrics FDT B plate 1', 'Movetrics FDT B plate 2', 'Movetrics FDT B markers']);
    const relay = await opening;
    assert.equal(usedUrl, LSL_RELAY_URL);
    assert.deepEqual(relay.streams, ['Movetrics FDT B plate 1', 'Movetrics FDT B plate 2', 'Movetrics FDT B markers']);
  });

  test('batches items, and sends a missing centre of pressure as null', async () => {
    const { relay, socket } = await opened({ flushMs: 5 });
    const event: Event = { kind: 'event', t: 1.25, type: 1, name: 'sync_in_rise', source: 1, count: 3, detail: 0, stamp: 12500, offset_us: 40 };
    const gap: Gap = { kind: 'gap', plate: 1, start_t: 2, end_t: 2.01, missing: 9 };
    relay.push(sample(1));
    relay.push(sample(1.001, 1, 20, [Number.NaN, Number.NaN]));
    relay.push(event);
    relay.push(gap);
    assert.equal(socket.sent.length, 1); // only hello so far: the batch waits flushMs
    await tick(20);
    assert.equal(socket.sent.length, 2);
    assert.deepEqual(socket.sent[1], {
      type: 'items',
      items: [
        { kind: 'sample', t: 1, plate: 1, fx: 1, fy: 2, fz: 700, mx: 3, my: -4, mz: 0.5, cop_x: 0.0057, cop_y: -0.0043, stamp: 10000 },
        { kind: 'sample', t: 1.001, plate: 1, fx: 1, fy: 2, fz: 20, mx: 3, my: -4, mz: 0.5, cop_x: null, cop_y: null, stamp: 10010 },
        { kind: 'event', t: 1.25, name: 'sync_in_rise', type: 1, source: 1, count: 3, detail: 0, stamp: 12500, offset_us: 40 },
        { kind: 'gap', plate: 1, start_t: 2, end_t: 2.01, missing: 9 },
      ],
    });
    relay.close();
  });

  test('a full batch goes out at once, and a mark sends the queue first', async () => {
    const { relay, socket } = await opened({ maxBatch: 3, flushMs: 1000 });
    for (let k = 1; k <= 4; k++) relay.push(sample(k / 1000));
    assert.equal(socket.sent.length, 2);
    assert.equal((socket.sent[1] as { items: unknown[] }).items.length, 3);
    relay.mark('jump 3');
    assert.deepEqual(socket.sent.slice(2).map((m) => (m as { type: string }).type), ['items', 'mark']);
    assert.deepEqual(socket.sent[3], { type: 'mark', text: 'jump 3' });
    relay.close();
    assert.deepEqual(socket.closedWith, [1000, 'done']);
    assert.throws(() => relay.push(sample(1)), LslRelayError);
  });

  test('bad options are refused before anything connects', async () => {
    let connected = false;
    const socket = (): WebSocketLike => ((connected = true), new FakeSocket());
    for (const options of [{ rateHz: 0 }, { rateHz: 1000, plates: [1, 1] }, { rateHz: 1000, plates: [5] },
                           { rateHz: 1000, device: 'B/2' }, { rateHz: 1000, firmware: '' }]) {
      await assert.rejects(LslRelay.open({ ...options, socket }), LslRelayError);
    }
    assert.equal(connected, false);
  });

  test('a busy or refusing relay makes open() fail with its reason', async () => {
    const busy = new FakeSocket();
    const opening = LslRelay.open({ rateHz: 1000, socket: () => busy });
    busy.emit('open');
    busy.emit('close', { code: 1013, reason: 'another page is already streaming to this relay' });
    await assert.rejects(opening, (error: LslRelayError) => error.code === 1013 && error.message.includes('another page'));

    const absent = new FakeSocket();
    const unreachable = LslRelay.open({ rateHz: 1000, socket: () => absent });
    absent.emit('close', { code: 1006, reason: '' });
    await assert.rejects(unreachable, /is movetrics-fdt lsl-relay running/);

    const silent = new FakeSocket();
    await assert.rejects(LslRelay.open({ rateHz: 1000, openTimeoutMs: 20, socket: () => silent }), /did not answer within 20 ms/);
    assert.deepEqual(silent.closedWith, [1000, 'giving up']);
  });

  test('when the relay closes the connection, push() says why and closed resolves', async () => {
    const { relay, socket } = await opened();
    socket.emit('close', { code: 1007, reason: 'item 0: plate 3 was not announced in hello' });
    assert.deepEqual(await relay.closed, { code: 1007, reason: 'item 0: plate 3 was not announced in hello' });
    assert.throws(() => relay.push(sample(1)), (error: LslRelayError) => error.code === 1007 && error.message.includes('plate 3'));
  });

  test('a relay that does not keep up closes the connection instead of filling memory', async () => {
    const { relay, socket } = await opened({ maxBufferedBytes: 1000 });
    socket.bufferedAmount = 5000;
    assert.throws(() => relay.push(sample(1)), /not keeping up/);
    assert.deepEqual(socket.closedWith, [1000, 'relay not keeping up']);
    assert.throws(() => relay.push(sample(1.001)), LslRelayError);
  });
});
