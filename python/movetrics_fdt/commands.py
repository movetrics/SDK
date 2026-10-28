"""Host command codes: the commands this client sends, and every other one with the reason it is left out.

Codes and names: the firmware. Safety classes: docs/04-host-commands.md section 1.
Coverage rule: a command is implemented only when its request bytes are a case in sdk/vectors and its
reply is confirmed by a vector or by the cited code. Frames are never built for a command in
NOT_IMPLEMENTED (see frames.encode_host_frame).
"""

from __future__ import annotations

from dataclasses import dataclass

READ_ONLY = "Read-only"
CONFIGURATION = "Configuration"
PERSISTENT_WRITE = "Persistent write"
DESTRUCTIVE = "Destructive"
FIRMWARE_UPDATE = "Firmware update"
NOT_DISPATCHED = "Not dispatched"


@dataclass(frozen=True)
class Command:
    """A host command this client implements."""

    code: int
    name: str
    safety_class: str


@dataclass(frozen=True)
class OmittedCommand:
    """A host command this client does not implement, with the reason."""

    code: int
    name: str
    safety_class: str
    reason: str


START_STREAM = Command(0x01, "START_STREAM", CONFIGURATION)
STOP_STREAM = Command(0x05, "STOP_STREAM", CONFIGURATION)
GET_STATUS = Command(0x22, "GET_STATUS", READ_ONLY)
GET_FW_VERSION = Command(0x23, "GET_FW_VERSION", READ_ONLY)
KEEP_ALIVE = Command(0x26, "KEEP_ALIVE", CONFIGURATION)
# Movetrics firmware 1.2.8.0 and later only: cutoff in Hz at byte 5, frames per second as uint16 LE at bytes 6-7
# (the firmware, case CMD_SET_FILTER). Other firmware lines read 0x1C differently (doc 17), so the client
# sends it only after GET_FW_VERSION names a Movetrics 1.2.8+ build (FdtClient.set_rate).
SET_FILTER = Command(0x1C, "SET_FILTER", CONFIGURATION)

# Sync modes, FDT 1.2.8.24 (docs/04 section 3.9, draft until that firmware is released).
# SET_SYNC_MODE payload: mode bits, pulse period ms (u16 LE), pulse width ms, debounce 0.1 ms, arm timeout min; 0 in
# any byte after the mode takes the default. GET_SYNC_MODE is also the capability probe: NACK 7 on firmware before
# 1.2.8.24 and on the digital variant.
SET_SYNC_MODE = Command(0x28, "SET_SYNC_MODE", CONFIGURATION)
GET_SYNC_MODE = Command(0x29, "GET_SYNC_MODE", READ_ONLY)

IMPLEMENTED: tuple[Command, ...] = (
    START_STREAM, STOP_STREAM, SET_FILTER, GET_STATUS, GET_FW_VERSION, KEEP_ALIVE, SET_SYNC_MODE, GET_SYNC_MODE,
)
IMPLEMENTED_CODES: frozenset[int] = frozenset(command.code for command in IMPLEMENTED)

_NOT_DISPATCHED_NOTE = "the firmware has no case for it and answers NACK 7 (doc 04 section 3.7)"

NOT_IMPLEMENTED: tuple[OmittedCommand, ...] = (
    OmittedCommand(0x02, "START_ACQ", NOT_DISPATCHED, _NOT_DISPATCHED_NOTE),
    OmittedCommand(0x03, "STOP_ACQ", NOT_DISPATCHED, _NOT_DISPATCHED_NOTE),
    OmittedCommand(0x04, "CLEAR_CACHE", NOT_DISPATCHED, _NOT_DISPATCHED_NOTE),
    OmittedCommand(
        0x06, "GET_FRAME", READ_ONLY,
        "no reply; it polls the pads, which the stream already does (doc 04 Table 3.1)",
    ),
    OmittedCommand(
        0x07, "SET_SAMPLING_RATE", CONFIGURATION,
        "stores a value with no effect on the stream; no vector (vectors README, item 5)",
    ),
    OmittedCommand(
        0x08, "GET_SAMPLING_RATE", READ_ONLY,
        "reports a stored value that is not the stream rate (doc 04 M5); no reply vector",
    ),
    OmittedCommand(
        0x11, "SET_CALIBRATION", CONFIGURATION,
        "alias of START_STREAM in the firmware (doc 04 Table 3.1, F2)",
    ),
    OmittedCommand(
        0x12, "SET_CHANNEL_MASK", CONFIGURATION,
        "stores a mask with no effect on acquisition; no vector (vectors README, item 5)",
    ),
    OmittedCommand(
        0x13, "GET_CHANNEL_MASK", READ_ONLY,
        "outside the first SDK surface (doc 04 Table 3.2); no reply vector",
    ),
    OmittedCommand(
        0x14, "INCREASE_VALUE", CONFIGURATION,
        "silent RAM step with no reply; no vector (vectors README, item 5)",
    ),
    OmittedCommand(
        0x15, "DECREASE_VALUE", CONFIGURATION,
        "silent RAM step with no reply; no vector (vectors README, item 5)",
    ),
    OmittedCommand(
        0x16, "END_CALIBRATION", CONFIGURATION,
        "alias of STOP_STREAM in the firmware (doc 04 Table 3.1)",
    ),
    OmittedCommand(0x17, "GET_CALIBRATION", NOT_DISPATCHED, _NOT_DISPATCHED_NOTE),
    OmittedCommand(
        0x18, "SET_LAYOUT", READ_ONLY,
        "outside the first SDK surface (doc 04 Table 3.2); no reply vector",
    ),
    OmittedCommand(
        0x19, "SAVE_CALIBRATION", PERSISTENT_WRITE,
        "writes controller flash; out of scope for version 0.1 (doc 00 section 0.5)",
    ),
    OmittedCommand(
        0x1A, "GET_CURRENT_CONFIG", READ_ONLY,
        "runs pad transactions first; outside the first SDK surface; no reply vector",
    ),
    OmittedCommand(
        0x1B, "SET_TARE", CONFIGURATION,
        "no vector covers 0x1B; a tare re-zeroes the plates, so Movetrics decides (doc 04 M4)",
    ),
    OmittedCommand(
        0x21, "RUN_SELF_TEST", READ_ONLY,
        "sends an ACK and runs no test (doc 04 Table 3.2)",
    ),
    OmittedCommand(
        0x24, "GET_SERIAL_NUMBER", READ_ONLY,
        "outside the first SDK surface; the identification reply has no case (vectors README, item 6)",
    ),
    OmittedCommand(
        0x25, "CONTROLLER_RESET", DESTRUCTIVE,
        "destructive: resets the controller and ends the stream (doc 04 3.4); with destination 0 "
        "it writes flash first; doc 17: never send 0x25 as tare",
    ),
    OmittedCommand(
        0x27, "GET_PAD_HEALTH", READ_ONLY,
        "reply T_PadHealthResponse has no vector (vectors README, item 4)",
    ),
    OmittedCommand(
        0x31, "SET_SERIAL_PARAM", CONFIGURATION,
        "setter outside the reviewed set (vectors README, item 5); the new rate reaches the port "
        "only after a boot, and only if a flash write stored it (doc 04 3.3)",
    ),
    OmittedCommand(0x32, "SET_WIFI_SSID", NOT_DISPATCHED, _NOT_DISPATCHED_NOTE),
    OmittedCommand(
        0x33, "SERVER_AP_ENABLE", CONFIGURATION,
        "ACK only, no effect (doc 04 Table 3.3)",
    ),
    OmittedCommand(
        0x34, "ANALOG_ENABLE", CONFIGURATION,
        "analogue output switch; no vector (vectors README, item 5)",
    ),
    OmittedCommand(
        0x35, "SERVER_BT_ENABLE", CONFIGURATION,
        "ACK only, no effect (doc 04 Table 3.3)",
    ),
    OmittedCommand(
        0x36, "SERVER_USB_ENABLE", CONFIGURATION,
        "ACK only, no effect (doc 04 Table 3.3)",
    ),
    OmittedCommand(
        0x37, "PRINTOUT_ENABLE", CONFIGURATION,
        "debug output on USART2, no host reply (doc 04 Table 3.3)",
    ),
    OmittedCommand(
        0x38, "PRINTOUT_DISABLE", CONFIGURATION,
        "debug output on USART2, no host reply (doc 04 Table 3.3)",
    ),
    OmittedCommand(
        0x39, "ANALOG_TEST", DESTRUCTIVE,
        "sends an ACK and then never returns (doc 04 F1)",
    ),
    OmittedCommand(
        0x40, "FIRMWARE_UPDATE", FIRMWARE_UPDATE,
        "firmware update is out of scope for version 0.1 (doc 00 section 0.5)",
    ),
    OmittedCommand(0x50, "PADS_CALIBRATION_START", NOT_DISPATCHED, _NOT_DISPATCHED_NOTE),
    OmittedCommand(0x51, "PADS_CALIBRATION_STOP", NOT_DISPATCHED, _NOT_DISPATCHED_NOTE),
    OmittedCommand(
        0x52, "PADS_GET_FACTORY_GF", READ_ONLY,
        "calibration data; no vector (doc 04 Table 3.4)",
    ),
    OmittedCommand(
        0x53, "PADS_SAVE_FACTORY_GF", PERSISTENT_WRITE,
        "pad flash write with no backup (doc 04 F5; vectors README, item 5)",
    ),
    OmittedCommand(
        0x54, "PADS_GET_CF", NOT_DISPATCHED,
        "not dispatched on the host side (doc 04 section 3.7)",
    ),
    OmittedCommand(
        0x55, "PADS_SAVE_CF", NOT_DISPATCHED,
        "not dispatched on the host side; pad flash save (vectors README, item 5)",
    ),
    OmittedCommand(
        0x60, "DEBUG_ADC_CLOCK_DRIVE", CONFIGURATION,
        "bench experiment that changes the pads' ADC clock (doc 04 Table 3.5)",
    ),
    OmittedCommand(
        0x61, "DEBUG_POLL_TIMING", CONFIGURATION,
        "bench experiment on the pad poll timing (doc 04 Table 3.5)",
    ),
    OmittedCommand(
        0x62, "DEBUG_PADS_RESTART", DESTRUCTIVE,
        "bench experiment that power-cycles the pads (doc 04 Table 3.5)",
    ),
    OmittedCommand(
        0x63, "DEBUG_PAD_SAMPLES", CONFIGURATION,
        "bench experiment that switches the pad polling between GET_FRAME and queued samples, RAM only (doc 04 Table 3.5)",
    ),
)

NOT_IMPLEMENTED_CODES: frozenset[int] = frozenset(command.code for command in NOT_IMPLEMENTED)

if IMPLEMENTED_CODES & NOT_IMPLEMENTED_CODES:  # pragma: no cover - guards the list itself
    raise RuntimeError("a command is listed as both implemented and not implemented")


def not_implemented_reason(code: int) -> str | None:
    """Return the reason a command code is left out, or None when it is implemented or unknown."""
    for command in NOT_IMPLEMENTED:
        if command.code == code:
            return command.reason
    return None
