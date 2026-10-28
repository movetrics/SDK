// vectors/vocabulary.json: the same frames give the same samples, events and gaps in every client (contract
// K4). Expected values come from the contract's formulas (tools/gen_vocabulary_vectors.py), not from Python.

import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { fromHex } from './support.ts';
import { StreamDecoder, type StreamItem } from '../src/stream.ts';
import { SampleConverter } from '../src/vocabulary.ts';

interface VocabularyCase {
  readonly id: string;
  readonly rate_hz: number | null;
  readonly frames: readonly string[];
  readonly expected: readonly Record<string, unknown>[];
}

const VECTORS = fileURLToPath(new URL('../../vectors/vocabulary.json', import.meta.url));
const cases = (JSON.parse(readFileSync(VECTORS, 'utf8')) as { cases: VocabularyCase[] }).cases;

describe('vocabulary vectors (vocabulary.json)', () => {
  test('the file has its seven cases', () => assert.equal(cases.length, 7));
  for (const vector of cases) {
    test(vector.id, () => {
      const decoder = new StreamDecoder();
      const items: StreamItem[] = [];
      for (const frame of vector.frames) items.push(...decoder.pushItems(fromHex(frame)));
      const got = [...new SampleConverter(vector.rate_hz).convert(items)] as unknown as Record<string, unknown>[];
      assert.equal(got.length, vector.expected.length);
      got.forEach((actual, index) => {
        const expected = vector.expected[index]!;
        assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort(), `item ${index} fields`);
        for (const [key, want] of Object.entries(expected)) {
          const have = actual[key];
          if (want === null) assert.ok(Number.isNaN(have), `${index}.${key} should be NaN`);
          else if (typeof want === 'number' && !Number.isInteger(want)) {
            assert.ok(Math.abs((have as number) - want) <= 1e-9, `${index}.${key}: ${String(have)} vs ${want}`);
          } else assert.deepEqual(have, want, `${index}.${key}`);
        }
      });
    });
  }
});
