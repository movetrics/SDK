// CRC-16/CCITT-FALSE: polynomial 0x1021, initial value 0xFFFF by default, no
// reflection, no final XOR. Same routine as the firmware. The check
// value of the ASCII string "123456789" is 0x29B1. The CRC is stored low byte first.

export function crc16CcittFalse(data: Uint8Array, init = 0xffff): number {
  let crc = init & 0xffff;
  for (const byte of data) {
    crc ^= byte << 8;
    for (let bit = 0; bit < 8; bit++) {
      crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
    }
  }
  return crc;
}
