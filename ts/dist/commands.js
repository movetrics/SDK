// Command codes of the Discovery central board (firmware 1.2.8.0).
// Names and values: the firmware. Safety classes follow
// docs/04-host-commands.md section 1.
// Commands the client sends. Nothing else is ever written by FdtClient.
export const COMMANDS = {
    START_STREAM: { code: 0x01, name: 'START_STREAM', safety: 'configuration' },
    STOP_STREAM: { code: 0x05, name: 'STOP_STREAM', safety: 'configuration' },
    GET_STATUS: { code: 0x22, name: 'GET_STATUS', safety: 'read-only' },
    GET_FW_VERSION: { code: 0x23, name: 'GET_FW_VERSION', safety: 'read-only' },
    KEEP_ALIVE: { code: 0x26, name: 'KEEP_ALIVE', safety: 'configuration' },
    // Movetrics firmware 1.2.8.0 and later only: cutoff in Hz at payload byte 0, frames per second as
    // uint16 LE at bytes 1-2 (the firmware, case CMD_SET_FILTER). Other firmware lines read 0x1C
    // differently, so FdtClient.setRate sends it only after GET_FW_VERSION names a Movetrics 1.2.8+ build.
    SET_FILTER: { code: 0x1c, name: 'SET_FILTER', safety: 'configuration' },
    // DRAFT (28 Oct 2026): six payload bytes, mode (uint8), pulse period ms (uint16 LE), pulse width ms
    // (uint8), debounce in 0.1 ms (uint8), arm timeout in minutes (uint8). A 0 in any byte means the firmware
    // default. NACK 3: bad parameters (MASTER_OUT with PULSE_TRAIN); NACK 7: no sync modes; NACK 8: stream
    // running or armed. The code is a proposal until the firmware release publishes it in docs/04 and vectors.
    SET_SYNC_MODE: { code: 0x28, name: 'SET_SYNC_MODE', safety: 'configuration' },
    // DRAFT: reads the sync mode state back. 26-byte reply; NACK 7 means no sync modes.
    GET_SYNC_MODE: { code: 0x29, name: 'GET_SYNC_MODE', safety: 'read-only' },
};
export const IMPLEMENTED_CODES = new Set(Object.values(COMMANDS).map((command) => command.code));
// Every code in the firmware enum (46 entries, the firmware).
export const FIRMWARE_COMMAND_NAMES = {
    0x01: 'START_STREAM',
    0x02: 'START_ACQ',
    0x03: 'STOP_ACQ',
    0x04: 'CLEAR_CACHE',
    0x05: 'STOP_STREAM',
    0x06: 'GET_FRAME',
    0x07: 'SET_SAMPLING_RATE',
    0x08: 'GET_SAMPLING_RATE',
    0x11: 'SET_CALIBRATION',
    0x12: 'SET_CHANNEL_MASK',
    0x13: 'GET_CHANNEL_MASK',
    0x14: 'INCREASE_VALUE',
    0x15: 'DECREASE_VALUE',
    0x16: 'END_CALIBRATION',
    0x17: 'GET_CALIBRATION',
    0x18: 'SET_LAYOUT',
    0x19: 'SAVE_CALIBRATION',
    0x1a: 'GET_CURRENT_CONFIG',
    0x1b: 'SET_TARE',
    0x1c: 'SET_FILTER',
    0x21: 'RUN_SELF_TEST',
    0x22: 'GET_STATUS',
    0x23: 'GET_FW_VERSION',
    0x24: 'GET_SERIAL_NUMBER',
    0x25: 'CONTROLLER_RESET',
    0x26: 'KEEP_ALIVE',
    0x27: 'GET_PAD_HEALTH',
    0x31: 'SET_SERIAL_PARAM',
    0x32: 'SET_WIFI_SSID',
    0x33: 'SERVER_AP_ENABLE',
    0x34: 'ANALOG_ENABLE',
    0x35: 'SERVER_BT_ENABLE',
    0x36: 'SERVER_USB_ENABLE',
    0x37: 'PRINTOUT_ENABLE',
    0x38: 'PRINTOUT_DISABLE',
    0x39: 'ANALOG_TEST',
    0x40: 'FIRMWARE_UPDATE',
    0x50: 'PADS_CALIBRATION_START',
    0x51: 'PADS_CALIBRATION_STOP',
    0x52: 'PADS_GET_FACTORY_GF',
    0x53: 'PADS_SAVE_FACTORY_GF',
    0x54: 'PADS_GET_CF',
    0x55: 'PADS_SAVE_CF',
    0x60: 'DEBUG_ADC_CLOCK_DRIVE',
    0x61: 'DEBUG_POLL_TIMING',
    0x62: 'DEBUG_PADS_RESTART',
    0x63: 'DEBUG_PAD_SAMPLES',
};
// Every firmware command the client does not send, with the reason. Sources are in
// docs/04-host-commands.md, docs/17-prior-art-and-compatibility.md and the vector
// README "Not covered" list (vectors/README.md).
export const NOT_IMPLEMENTED = [
    { code: 0x02, name: 'START_ACQ', reason: 'not dispatched by the firmware (NACK 7), doc 04 3.7' },
    { code: 0x03, name: 'STOP_ACQ', reason: 'not dispatched by the firmware (NACK 7), doc 04 3.7' },
    { code: 0x04, name: 'CLEAR_CACHE', reason: 'not dispatched by the firmware (NACK 7), doc 04 3.7' },
    { code: 0x06, name: 'GET_FRAME', reason: 'no reply; polls the pads and changes their link counters, doc 04 3.1' },
    { code: 0x07, name: 'SET_SAMPLING_RATE', reason: 'setter outside the reviewed set (vectors README, not covered 5); stored value has no effect on the stream, doc 04 3.3' },
    { code: 0x08, name: 'GET_SAMPLING_RATE', reason: 'query outside the first SDK surface (doc 04 3.2); reports a stored value, not the stream rate (doc 04 M5)' },
    { code: 0x11, name: 'SET_CALIBRATION', reason: 'alias of START_STREAM (doc 04 3.1); sending it starts the stream' },
    { code: 0x12, name: 'SET_CHANNEL_MASK', reason: 'setter outside the reviewed set (vectors README, not covered 5); no effect on acquisition, doc 04 3.3' },
    { code: 0x13, name: 'GET_CHANNEL_MASK', reason: 'query outside the first SDK surface, doc 04 3.2' },
    { code: 0x14, name: 'INCREASE_VALUE', reason: 'calibration factor step outside the reviewed set (vectors README, not covered 5); no reply, doc 04 3.3' },
    { code: 0x15, name: 'DECREASE_VALUE', reason: 'calibration factor step outside the reviewed set (vectors README, not covered 5); no reply, doc 04 3.3' },
    { code: 0x16, name: 'END_CALIBRATION', reason: 'alias of STOP_STREAM (doc 04 3.1)' },
    { code: 0x17, name: 'GET_CALIBRATION', reason: 'not dispatched by the firmware (NACK 7), doc 04 3.7' },
    { code: 0x18, name: 'SET_LAYOUT', reason: 'layout query outside the first SDK surface; the name does not match the behaviour, doc 04 3.2' },
    { code: 0x19, name: 'SAVE_CALIBRATION', reason: 'persistent flash write (doc 04 3.4); outside version 0.1 (doc 00 0.5)' },
    { code: 0x1a, name: 'GET_CURRENT_CONFIG', reason: 'identification query outside the first SDK surface; runs pad transactions first, doc 04 3.2' },
    { code: 0x1b, name: 'SET_TARE', reason: 'no vector covers 0x1B; a tare re-zeroes the plates, so Movetrics decides (doc 04 M4)' },
    { code: 0x21, name: 'RUN_SELF_TEST', reason: 'ACK only; runs no test, doc 04 3.2' },
    { code: 0x24, name: 'GET_SERIAL_NUMBER', reason: 'identification query outside the first SDK surface, doc 04 3.2' },
    { code: 0x25, name: 'CONTROLLER_RESET', reason: 'destructive: resets the controller and ends the stream (doc 04 3.4); with destination 0 it writes flash first; doc 17: never send 0x25 as tare' },
    { code: 0x27, name: 'GET_PAD_HEALTH', reason: 'excluded: no vector covers its 120-byte reply (vectors README, not covered 4); its layout is in doc 06' },
    { code: 0x31, name: 'SET_SERIAL_PARAM', reason: 'setter outside the reviewed set (vectors README, not covered 5); the new rate reaches the port only after a boot, and only if a flash write stored it, doc 04 3.3' },
    { code: 0x32, name: 'SET_WIFI_SSID', reason: 'not dispatched by the firmware (NACK 7); the firmware has no Wi-Fi, doc 04 3.7' },
    { code: 0x33, name: 'SERVER_AP_ENABLE', reason: 'acknowledged and ignored by the firmware, doc 04 3.3' },
    { code: 0x34, name: 'ANALOG_ENABLE', reason: 'analogue output switch outside the reviewed set (vectors README, not covered 5), doc 04 3.3' },
    { code: 0x35, name: 'SERVER_BT_ENABLE', reason: 'acknowledged and ignored by the firmware, doc 04 3.3' },
    { code: 0x36, name: 'SERVER_USB_ENABLE', reason: 'acknowledged and ignored by the firmware, doc 04 3.3' },
    { code: 0x37, name: 'PRINTOUT_ENABLE', reason: 'debug output with no host reply, doc 04 3.3' },
    { code: 0x38, name: 'PRINTOUT_DISABLE', reason: 'debug output with no host reply, doc 04 3.3' },
    { code: 0x39, name: 'ANALOG_TEST', reason: 'destructive: never returns (doc 04 6.1)' },
    { code: 0x40, name: 'FIRMWARE_UPDATE', reason: 'firmware update over the host link, outside version 0.1 (doc 00 0.5); described in doc 09, not sent by this client' },
    { code: 0x50, name: 'PADS_CALIBRATION_START', reason: 'not dispatched by the firmware (NACK 7), doc 04 3.7' },
    { code: 0x51, name: 'PADS_CALIBRATION_STOP', reason: 'not dispatched by the firmware (NACK 7), doc 04 3.7' },
    { code: 0x52, name: 'PADS_GET_FACTORY_GF', reason: 'calibration data; the 100 ms wait is unmeasured (doc 04 3.4, U4)' },
    { code: 0x53, name: 'PADS_SAVE_FACTORY_GF', reason: 'pad flash write without backup (doc 04 6.4); outside the reviewed set (vectors README, not covered 5)' },
    { code: 0x54, name: 'PADS_GET_CF', reason: 'not dispatched on the host side (NACK 7), doc 04 3.7' },
    { code: 0x55, name: 'PADS_SAVE_CF', reason: 'pad flash save; not dispatched on the host side (NACK 7), doc 04 3.7' },
    { code: 0x60, name: 'DEBUG_ADC_CLOCK_DRIVE', reason: 'bench experiment that changes the pads ADC clock, doc 04 3.5' },
    { code: 0x61, name: 'DEBUG_POLL_TIMING', reason: 'bench experiment, doc 04 3.5' },
    { code: 0x62, name: 'DEBUG_PADS_RESTART', reason: 'destructive: switches pad power off or resets the pads, doc 04 3.5' },
    { code: 0x63, name: 'DEBUG_PAD_SAMPLES', reason: 'bench experiment that switches the pad polling between GET_FRAME and queued samples, RAM only, doc 04 3.5' },
];
// The codes in NOT_IMPLEMENTED. encodeHostFrame refuses every one of them.
export const NOT_IMPLEMENTED_CODES = new Set(NOT_IMPLEMENTED.map((command) => command.code));
// Firmware dispatch switch labels (the firmware): 38 codes. Any other
// code in the enum gets NACK 7 (doc 04 3.7).
export const FIRMWARE_DISPATCH = new Set([
    0x01, 0x05, 0x06, 0x07, 0x08, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x18, 0x19, 0x1a, 0x1b, 0x1c,
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x31, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x40,
    0x52, 0x53, 0x60, 0x61, 0x62, 0x63,
]);
// Commands that send no reply when they succeed (doc 04 section 2), and command 0x00.
export const NO_REPLY_ON_SUCCESS = new Set([0x00, 0x01, 0x06, 0x11, 0x14, 0x15, 0x26, 0x37, 0x38]);
// NACK error names (the firmware).
export const NACK_ERROR_NAMES = {
    1: 'ERR_PLATFORM_NOT_EXIST',
    2: 'ERR_PLATFORM_NO_RESPONSE',
    3: 'ERR_INVALID_PARAMETER',
    4: 'ERR_SELF_TEST_FAILED',
    5: 'ERR_WIFI_CONNECTION_FAILED',
    6: 'ERR_WIFI_AP_START_FAILED',
    7: 'ERR_UNKNOWN_COMMAND',
    8: 'ERR_UNEFFECTIVE_COMMAND',
    9: 'ERR_CRC',
};
