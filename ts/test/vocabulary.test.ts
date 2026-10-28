import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import {
  STREAM_SIGN,
  SampleConverter,
  combine,
  plateCop,
  type Gap,
  type Sample,
  type VocabularyItem,
} from '../src/vocabulary.ts';
import type { StreamFrame } from '../src/stream.ts';

// Values from the Python reference (python/movetrics_fdt/vocabulary.py). Both languages do the same IEEE
// double operations in the same order, so the printed values agree; the checks still allow 1e-12.
function near(actual: number, expected: number, message?: string): void {
  assert.ok(Math.abs(actual - expected) < 1e-12, `${message ?? ''} ${actual} vs ${expected}`);
}

function frame(platformAddress: number, timeStamp: number, raw: readonly number[] = [0, 0, 0, 0, 0, 0]): StreamFrame {
  const [forceX = 0, forceY = 0, forceZ = 0, momentX = 0, momentY = 0, momentZ = 0] = raw;
  return { platformAddress, commandCode: 1, timeStamp, forceX, forceY, forceZ, momentX, momentY, momentZ };
}

// Pushes frames at a fixed rate and returns everything the converter produced, in order.
function run(converter: SampleConverter, frames: readonly StreamFrame[]): VocabularyItem[] {
  return frames.flatMap((item) => converter.push({ kind: 'frame', frame: item }));
}

function sampleOf(plate: number, fx: number, fy: number, fz: number, mx: number, my: number, mz: number): Sample {
  const [cop_x, cop_y] = plateCop(fx, fy, fz, mx, my);
  return { kind: 'sample', t: 0, plate, fx, fy, fz, mx, my, mz, cop_x, cop_y, stamp: 0, raw: [0, 0, 0, 0, 0, 0] };
}

describe('SampleConverter', () => {
  test('the two placeholders after START are dropped and counted', () => {
    const converter = new SampleConverter(500);
    const out = run(converter, [frame(1, 0), frame(2, 0)]);
    assert.deepEqual(out, []);
    assert.equal(converter.placeholders, 2);
  });

  test('the sign map gives the Studio file signs, and the raw integers stay in wire order', () => {
    assert.deepEqual([...STREAM_SIGN], [1, -1, 1, -1, 1, 1]);
    const converter = new SampleConverter(500);
    const [sample] = run(converter, [frame(1, 100000, [100, 20, 400, 30, -40, 5])]);
    assert.equal(sample?.kind, 'sample');
    if (sample?.kind !== 'sample') return;
    assert.equal(sample.t, 10);
    assert.equal(sample.plate, 1);
    assert.equal(sample.stamp, 100000);
    assert.deepEqual([sample.fx, sample.fy, sample.fz, sample.mx, sample.my, sample.mz], [100, -20, 400, -30, -40, 5]);
    assert.deepEqual(sample.raw, [100, 20, 400, 30, -40, 5]);
  });

  test('a signed zero from a negated wire zero is reported as +0, as in Python', () => {
    const converter = new SampleConverter(500);
    const [sample] = run(converter, [frame(1, 100000, [0, 0, 0, 0, 0, 0])]);
    assert.equal(sample?.kind === 'sample' && Object.is(sample.fy, 0), true);
    assert.equal(sample?.kind === 'sample' && Object.is(sample.mx, 0), true);
  });

  test('centre of pressure from the moment and force, with d = 0.030 m (Python value 0.0925, 0.0735)', () => {
    const converter = new SampleConverter(500);
    const [sample] = run(converter, [frame(1, 100000, [100, 20, 400, 30, -40, 5])]);
    assert.equal(sample?.kind, 'sample');
    if (sample?.kind !== 'sample') return;
    near(sample.cop_x, 0.0925, 'cop_x');
    near(sample.cop_y, 0.0735, 'cop_y');
  });

  test('a force below 50 N gives no centre of pressure (NaN); 50 N exactly gives one', () => {
    const [low] = run(new SampleConverter(500), [frame(1, 100000, [100, 20, 49, 30, -40, 5])]);
    assert.ok(low?.kind === 'sample' && Number.isNaN(low.cop_x) && Number.isNaN(low.cop_y));
    // Wire signs: forceY 20 and momentX 8 give plate-frame fy -20 and mx -8, the Python inputs.
    const [edge] = run(new SampleConverter(500), [frame(1, 100000, [10, 20, 50, 8, 12, 0])]);
    assert.equal(edge?.kind, 'sample');
    if (edge?.kind !== 'sample') return;
    near(edge.cop_x, -0.246, 'cop_x at 50 N');
    near(edge.cop_y, 0.148, 'cop_y at 50 N');
  });

  test('plateCop matches Python at 400 N, is NaN at 49.9 N, and the threshold is inclusive', () => {
    const [x, y] = plateCop(10, -20, 400, -8, 12);
    near(x, -0.03075, 'x');
    near(y, 0.0185, 'y');
    const [lowX, lowY] = plateCop(10, -20, 49.9, -8, 12);
    assert.ok(Number.isNaN(lowX) && Number.isNaN(lowY));
  });

  test('a hole of 41 periods (step 41 x 20 ticks at 500 Hz) is one gap with 40 missing', () => {
    const converter = new SampleConverter(500);
    const out = run(converter, [frame(1, 100020), frame(1, 100020 + 41 * 20)]);
    const gap = out.find((item): item is Gap => item.kind === 'gap');
    assert.deepEqual(gap, { kind: 'gap', plate: 1, start_t: 10.002, end_t: 10.084, missing: 40 });
    assert.deepEqual(converter.gaps, [gap]);
  });

  test('a hole of 41 missing periods (step 42 periods) gives missing 41, reported before the Sample after it', () => {
    const converter = new SampleConverter(500);
    const out = run(converter, [frame(1, 100020), frame(1, 100020 + 42 * 20)]);
    assert.deepEqual(
      out.map((item) => item.kind),
      ['sample', 'gap', 'sample'],
    );
    assert.deepEqual(out[1], { kind: 'gap', plate: 1, start_t: 10.002, end_t: 10.086, missing: 41 });
  });

  test('a step of exactly 1.5 periods is not a gap, a longer one is', () => {
    const converter = new SampleConverter(500);
    const out = run(converter, [frame(1, 100020), frame(1, 100050)]);
    assert.deepEqual(
      out.map((item) => item.kind),
      ['sample', 'sample'],
    );
  });

  test('a step of 2.5 periods rounds half to even, as Python round() does: missing 1, not 2', () => {
    const converter = new SampleConverter(500);
    const out = run(converter, [frame(1, 20), frame(1, 70)]);
    assert.deepEqual(out[1], { kind: 'gap', plate: 1, start_t: 0.002, end_t: 0.007, missing: 1 });
  });

  test('without a rate the period is learnt from the smallest step, and the hole is found (Python: missing 4)', () => {
    const converter = new SampleConverter(null);
    const out = run(converter, [10, 20, 30, 40, 90, 100].map((ts) => frame(1, ts)));
    assert.deepEqual(out.find((item) => item.kind === 'gap'), {
      kind: 'gap',
      plate: 1,
      start_t: 0.004,
      end_t: 0.009,
      missing: 4,
    });
  });

  test('the uint32 stamp is unwrapped past 2^32, and a wrap is not a jump back (Python stamp 4294967300)', () => {
    const converter = new SampleConverter(null);
    const out = run(converter, [frame(1, 0xfffffff0), frame(1, 4)]);
    const last = out[out.length - 1];
    assert.equal(last?.kind, 'sample');
    if (last?.kind !== 'sample') return;
    assert.equal(last.stamp, 4294967300);
    near(last.t, 429496.73, 't');
  });

  test('events are converted with t = stamp/10000 + offset_us/1e6, and the event type name', () => {
    const converter = new SampleConverter(500);
    const [event] = converter.push({
      kind: 'event',
      event: { timeStamp: 100900, eventType: 1, source: 1, count: 3, offsetUs: 250, detail: 0, mode: 0x18 },
    });
    assert.deepEqual(event, {
      kind: 'event',
      t: 10.09 + 0.00025,
      type: 1,
      name: 'sync_in_rise',
      source: 1,
      count: 3,
      detail: 0,
      stamp: 100900,
      offset_us: 250,
    });
  });
});

describe('combine', () => {
  test('two plates: forces add, moments move to the pair origin, CoP from the combined wrench (Python values)', () => {
    const samples = new Map<number, Sample>([
      [1, sampleOf(1, 10, -20, 400, -8, 12, 3)],
      [2, sampleOf(2, -5, 30, 120, 2, -6, 1.5)],
    ]);
    const wrench = combine(samples);
    assert.equal(wrench.fx, 5);
    assert.equal(wrench.fy, 10);
    assert.equal(wrench.fz, 520);
    assert.equal(wrench.mx, -6);
    assert.equal(wrench.my, 55);
    assert.equal(wrench.mz, 13.25);
    near(wrench.cop_x, -0.10605769230769231, 'comb cop_x');
    near(wrench.cop_y, 0.012115384615384615, 'comb cop_y');
  });

  test('a lightly loaded plate still counts in the combined CoP, because the total is what is tested', () => {
    const samples = new Map<number, Sample>([
      [1, sampleOf(1, 0, 0, 400, 0, 0, 0)],
      [2, sampleOf(2, 0, 0, 10, 0, 0, 0)],
    ]);
    const wrench = combine(samples);
    assert.equal(wrench.fz, 410);
    assert.ok(Number.isFinite(wrench.cop_x));
  });
});
