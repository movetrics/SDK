// Byte helpers for the framing code. Only ECMAScript built-ins are used, so the
// same code runs in browsers and in Node.

// Reads one byte. Throws instead of returning undefined, so a short buffer is a
// bug in the caller and not a silent zero.
export function at(bytes: Uint8Array, index: number): number {
  const value = bytes[index];
  if (value === undefined) {
    throw new RangeError(`byte index ${index} is outside a ${bytes.length}-byte buffer`);
  }
  return value;
}

export function concatBytes(parts: readonly Uint8Array[]): Uint8Array {
  let total = 0;
  for (const part of parts) total += part.length;
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

export function toHex(bytes: Uint8Array): string {
  let out = '';
  for (const byte of bytes) out += byte.toString(16).padStart(2, '0');
  return out;
}

export function fromHex(hex: string): Uint8Array {
  if (hex.length % 2 !== 0 || !/^[0-9a-fA-F]*$/.test(hex)) {
    throw new RangeError(`not an even-length hex string: ${hex}`);
  }
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = Number.parseInt(hex.slice(2 * i, 2 * i + 2), 16);
  }
  return out;
}

export function dataView(bytes: Uint8Array): DataView {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}

// Reads a fixed-width text field that ends at the first NUL byte (or at its width).
// Bytes are read as Latin-1, one character per byte.
export function asciiField(bytes: Uint8Array, start: number, width: number): string {
  let out = '';
  for (let i = start; i < start + width; i++) {
    const byte = at(bytes, i);
    if (byte === 0) break;
    out += String.fromCharCode(byte);
  }
  return out;
}
