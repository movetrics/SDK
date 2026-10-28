import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { crc16CcittFalse } from '../src/crc.ts';

function ascii(text: string): Uint8Array {
  return Uint8Array.from(text, (character) => character.charCodeAt(0));
}

describe('crc16CcittFalse', () => {
  test('the published check value of 123456789 is 0x29B1', () => {
    assert.equal(crc16CcittFalse(ascii('123456789')), 0x29b1);
  });

  test('the empty input returns the initial value 0xFFFF', () => {
    assert.equal(crc16CcittFalse(new Uint8Array(0)), 0xffff);
  });

  test('single bytes 00 and FF', () => {
    assert.equal(crc16CcittFalse(Uint8Array.of(0x00)), 0xe1f0);
    assert.equal(crc16CcittFalse(Uint8Array.of(0xff)), 0xff00);
  });

  test('the initial value can be passed in', () => {
    assert.equal(crc16CcittFalse(new Uint8Array(0), 0x1234), 0x1234);
    assert.equal(crc16CcittFalse(ascii('123456789'), 0xffff), crc16CcittFalse(ascii('123456789')));
  });

  test('the GET_STATUS body 00 00 22 has CRC 0xC8BC', () => {
    assert.equal(crc16CcittFalse(Uint8Array.of(0x00, 0x00, 0x22)), 0xc8bc);
  });
});
