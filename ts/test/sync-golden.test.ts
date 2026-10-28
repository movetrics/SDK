// Golden vectors from the firmware sync jack (FDT 1.2.8.24): every event frame and GET_SYNC_MODE reply in
// python/tests/fixtures/sync_events.json. Each event case decodes to its named fields and re-encodes to the
// same bytes. Each GET_SYNC_MODE case decodes to its named fields.

import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { fromHex, toHex } from './support.ts';
import { encodeEventFrame, parseEventFrame, parseSyncModeReply } from '../src/stream.ts';

interface GoldenCase {
  readonly id: string;
  readonly kind: string;
  readonly frame_hex: string;
  readonly fields: Record<string, number>;
}

const FIXTURE = fileURLToPath(new URL('../../python/tests/fixtures/sync_events.json', import.meta.url));
const cases = (JSON.parse(readFileSync(FIXTURE, 'utf8')) as { cases: GoldenCase[] }).cases;

describe('sync jack golden vectors (sync_events.json)', () => {
  test('the fixture has the 13 cases of the firmware, and each one has a frame', () => {
    assert.equal(cases.length, 13);
    for (const golden of cases) assert.ok(golden.frame_hex.length > 0, golden.id);
  });

  for (const golden of cases.filter((item) => item.frame_hex.length === 48)) {
    test(`${golden.id}: decodes to its fields and re-encodes to the same 24 bytes`, () => {
      const bytes = fromHex(golden.frame_hex);
      const event = parseEventFrame(bytes);
      const f = golden.fields;
      assert.deepEqual(event, {
        timeStamp: f['stamp'],
        eventType: f['type'],
        source: f['source'],
        count: f['counter'],
        offsetUs: f['offset_us'],
        detail: f['detail'],
        mode: f['mode'],
      });
      assert.equal(toHex(encodeEventFrame(event)), golden.frame_hex);
    });
  }

  for (const golden of cases.filter((item) => item.frame_hex.length === 52)) {
    test(`${golden.id}: GET_SYNC_MODE reply decodes to its fields`, () => {
      const state = parseSyncModeReply(fromHex(golden.frame_hex));
      const f = golden.fields;
      assert.equal(state.mode, f['mode']);
      assert.equal(state.pulsePeriodMs, f['pulse_period_ms']);
      assert.equal(state.pulseWidthMs, f['pulse_width_ms']);
      assert.equal(state.debounce, f['debounce_ticks']);
      assert.equal(state.armTimeoutMin, f['arm_timeout_min']);
      assert.equal(state.contract, f['contract']);
      assert.equal(state.edgesIn, f['edges_in']);
      assert.equal(state.edgesOut, f['edges_out']);
      assert.equal(state.overflows, f['overflows']);
      const bits = f['state'] ?? 0;
      assert.equal(state.armed, (bits & 0x01) !== 0);
      assert.equal(state.restored, (bits & 0x02) !== 0);
      assert.equal(state.backupOk, (bits & 0x04) !== 0);
      assert.equal(state.syncInHigh, (bits & 0x08) !== 0);
      assert.equal(state.syncOutHigh, (bits & 0x10) !== 0);
      assert.equal(state.streaming, (bits & 0x20) !== 0);
    });
  }
});
