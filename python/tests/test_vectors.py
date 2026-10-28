"""Runs every case in sdk/vectors (schema movetrics-fdt-vectors/1) against this package.

One test method is generated per case. A case that this SDK covers must pass. A case whose expectation needs a
part of the protocol this SDK leaves out is skipped, with the reason from SKIP_BY_ID or from its file family.
Before skipping, the checker verifies the part that is in scope (for example the CRC of a pad frame or the
envelope of an OTA reply). Anchors are never skipped: test_anchors_are_never_skipped checks that.

Status records that the pinned FDT reference rejects but this client accepts are passed and listed in
DOCUMENTED_STATUS_DEVIATIONS, as vectors/README.md (pass rule) asks. The reason is conflict 1 there, and
python/README.md repeats it.
"""

from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import Any, Final

from movetrics_fdt.crc import crc16_ccitt_false
from movetrics_fdt.errors import FrameError, UnsupportedCommandError
from movetrics_fdt.frames import (
    HostRxSplitter,
    decode_firmware_version,
    encode_host_frame,
    envelope_is_valid,
    parse_host_message,
)
from movetrics_fdt.status import StatusRecord, decode_status_record, parse_status
from movetrics_fdt.stream import StreamFrame, decode_stream_frame, encode_stream_frame

from .support import FIRMWARE_UPDATE_CASES, PUBLIC_REPOSITORY, VECTOR_FILES, controller_response, load_vector_file

SCHEMA: Final = "movetrics-fdt-vectors/1"

# Totals per file: (cases, anchors, derived), from the table in vectors/README.md.
EXPECTED_COUNTS: dict[str, tuple[int, int, int]] = {
    "crc16.json": (6, 2, 4),
    "host_frames.json": (24, 9, 15),
    "stream_frames.json": (13, 6, 7),
    "status.json": (6, 1, 5),
    "pad_bus.json": (12, 0, 12),
    "boot_frames.json": (8, 0, 8),
    "ota_frames.json": (8, 2, 6),
}
if PUBLIC_REPOSITORY:
    EXPECTED_COUNTS = {"crc16.json": (6, 2, 4), "host_frames.json": (24, 9, 15), "stream_frames.json": (13, 6, 7),
                       "status.json": (6, 1, 5), "ota_frames.json": (4, 2, 2)}
EXPECTED_TOTALS: Final = [53, 20, 33] if PUBLIC_REPOSITORY else [77, 20, 57]

DOCUMENTED_STATUS_DEVIATIONS: Final = frozenset(
    {
        "status-derived-86-general-record",
        "status-derived-86-platform-1-record",
        "status-derived-86-platform-2-record",
        "status-derived-86x3-reply",
    }
)

SKIP_PAD_BUS: Final = (
    "RS-485 pad-bus frames are outside this SDK: the host talks to the controller only, never to a pad "
    "(docs/07-pad-bus.md). The CRC rule of the frame is checked first."
)
SKIP_BOOT: Final = (
    "Pad bootloader frames (07 b0 requests, 08 b0 replies) are outside this SDK, because the host never "
    "reaches a pad (docs/08-pad-firmware-and-bootloader.md). The CRC rule of the frame is checked first."
)
SKIP_GET_CURRENT_CONFIG_ENCODE: Final = (
    "GET_CURRENT_CONFIG (0x1A) is in NOT_IMPLEMENTED (outside the first SDK surface, docs/04-host-commands.md "
    "Table 3.2), so encode_host_frame refuses it. The refusal is checked; the frame bytes are not produced."
)
SKIP_OTA_REPLY_FIELDS: Final = (
    "The 18-byte OTA reply belongs to firmware update (0x40), which is outside this SDK "
    "(docs/00-overview.md section 0.5). The envelope is checked; subop, status and the values are not decoded."
)

SKIP_BY_ID: Final[dict[str, str]] = {
    "host-encode-get-current-config": SKIP_GET_CURRENT_CONFIG_ENCODE,
    "ota-derived-reply-ok": SKIP_OTA_REPLY_FIELDS,
    "ota-derived-reply-param-error": SKIP_OTA_REPLY_FIELDS,
}


def _skip_reason(file_name: str, case: dict[str, Any]) -> str | None:
    if file_name == "pad_bus.json":
        return SKIP_PAD_BUS
    if file_name == "boot_frames.json":
        return SKIP_BOOT
    return SKIP_BY_ID.get(case["id"])


def _finish(test: unittest.TestCase, skip: str | None) -> None:
    if skip is not None:
        test.skipTest(skip)


def _field(record: object, name: str) -> object:
    value = getattr(record, name)
    return list(value) if isinstance(value, tuple) else value


def _check_crc(test: unittest.TestCase, case: dict[str, Any], skip: str | None) -> None:
    data = bytes.fromhex(case["input_hex"])
    value = crc16_ccitt_false(data)
    test.assertEqual(f"{value:04x}", case["crc_hex"])
    if "stored_hex" in case:
        test.assertEqual(value.to_bytes(2, "little").hex(), case["stored_hex"])
    if "frame_hex" in case:
        frame = bytes.fromhex(case["frame_hex"])
        test.assertEqual(frame[2:-4], data, "the CRC covers bytes 2 to n-5")
        test.assertEqual(frame[-4:-2].hex(), case["stored_hex"], "the CRC is stored low byte first")
        test.assertEqual(frame[-2:].hex(), "0404")
    _finish(test, skip)


def _check_host_encode(test: unittest.TestCase, case: dict[str, Any], skip: str | None) -> None:
    command = int(case["command"], 16)
    address = int(case["address_hex"], 16)
    destination = int(case["destination_hex"], 16)
    payload = bytes.fromhex(case["payload_hex"])
    if case["expect_frame_hex"] is None:
        with test.assertRaises(FrameError) as raised:
            encode_host_frame(command, address, destination, payload)
        test.assertEqual(raised.exception.reason, case["expect_error"])
        test.assertEqual(raised.exception.would_be, bytes.fromhex(case["would_be_frame_hex"]))
        return
    if skip is not None:
        with test.assertRaises(UnsupportedCommandError):
            encode_host_frame(command, address, destination, payload)
        return
    test.assertEqual(encode_host_frame(command, address, destination, payload).hex(), case["expect_frame_hex"])


def _check_host_decode(test: unittest.TestCase, case: dict[str, Any]) -> None:
    frame = bytes.fromhex(case["frame_hex"])
    expected_messages = case.get("rx_messages_hex", [case["frame_hex"]])
    messages = HostRxSplitter().feed(frame)
    test.assertEqual([message.hex() for message in messages], expected_messages)
    test.assertEqual(len(messages), 1, "each host decode case delivers exactly one message")
    message = messages[0]
    expect = case["expect"]
    try:
        host = parse_host_message(message)
    except FrameError as error:
        test.assertFalse(expect["valid"], f"the parser rejected a frame the vector calls valid ({error.reason})")
        reason: str | None = error.reason
    else:
        test.assertTrue(expect["valid"], "the parser accepted a frame the vector calls invalid")
        test.assertEqual(f"{host.command:02x}", expect["command"])
        test.assertEqual(host.payload.hex(), expect["payload_hex"])
        reason = None
    if "device_reply" in expect:
        reply, dispatched = controller_response(message)
        test.assertEqual(reply, expect["device_reply"])
        test.assertEqual(dispatched, expect["dispatched"])
        if reason is not None and "reason" in expect["device_reply"]:
            test.assertEqual(reason, expect["device_reply"]["reason"])


def _check_host(test: unittest.TestCase, case: dict[str, Any], skip: str | None) -> None:
    if "command" in case:
        _check_host_encode(test, case, skip)
    else:
        _check_host_decode(test, case)
    _finish(test, skip)


def _check_stream(test: unittest.TestCase, case: dict[str, Any], skip: str | None) -> None:
    expect = case["expect"]
    if "expect_frame_hex" in case:
        built = encode_stream_frame(StreamFrame(**expect["fields"]))
        test.assertEqual(built.hex(), case["expect_frame_hex"])
        decoded = decode_stream_frame(built)
    else:
        raw = bytes.fromhex(case["frame_hex"])
        if not expect["valid"]:
            with test.assertRaises(FrameError) as raised:
                decode_stream_frame(raw)
            test.assertEqual(raised.exception.reason, expect["reason"])
            _finish(test, skip)
            return
        decoded = decode_stream_frame(raw)
    if "command" in expect:
        test.assertEqual(f"{decoded.commandCode:02x}", expect["command"])
    for name, value in expect.get("fields", {}).items():
        test.assertEqual(getattr(decoded, name), value, name)
    _finish(test, skip)


def _check_record_fields(test: unittest.TestCase, record: StatusRecord, expected: dict[str, Any]) -> None:
    for name, value in expected.items():
        test.assertEqual(_field(record, name), value, f"{name} of platform {record.platform_address}")


def _check_status(test: unittest.TestCase, case: dict[str, Any], skip: str | None) -> None:
    frame = bytes.fromhex(case["frame_hex"])
    if "records" in case:
        status = parse_status(frame)
        test.assertEqual(status.length_class, case["expect_length_class"])
        test.assertEqual(len(status.records), len(case["records"]))
        for record, expected in zip(status.records, case["records"]):
            _check_record_fields(test, record, expected)
    else:
        # One record is checked as a record, with the length class taken from its byte count, as
        # ts/test/vectors.test.ts does. parse_status is not called: a reply starts with the general record.
        record = decode_status_record(frame)
        test.assertEqual("85" if len(frame) == 85 else "86", case["expect_length_class"])
        _check_record_fields(test, record, case["fields"])
    reference = case["expect"]["reference_parser"]
    if reference == "reject":
        test.assertIn(
            case["id"],
            DOCUMENTED_STATUS_DEVIATIONS,
            "the pinned reference rejects this frame; the deviation must be documented",
        )
    else:
        test.assertEqual(reference, "accept")
    _finish(test, skip)


def _check_ota(test: unittest.TestCase, case: dict[str, Any], skip: str | None) -> None:
    frame = bytes.fromhex(case["frame_hex"])
    expect = case["expect"]
    if frame[:2] == b"\xfe\xed":
        host = parse_host_message(frame)
        test.assertTrue(expect["valid"])
        if "command" in expect:
            test.assertEqual(f"{host.command:02x}", expect["command"])
        if "salt_count" in case:
            test.assertEqual(host.payload.count(b"."), case["salt_count"], "salt bytes are the trailing dots")
    else:
        test.assertTrue(envelope_is_valid(frame), "device reply envelope: BE EF header, CRC, 04 04")
        if "fields" in case and "stm32FW" in case["fields"]:
            reply = decode_firmware_version(frame)
            test.assertEqual(reply.platform_address, case["fields"]["platform_address"])
            test.assertEqual(reply.command, case["fields"]["commandCode"])
            test.assertEqual(reply.stm32FW, case["fields"]["stm32FW"])
            test.assertEqual(reply.esp32FW, case["fields"]["esp32FW"])
            test.assertEqual(f"{reply.command:02x}", expect.get("command", f"{reply.command:02x}"))
    _finish(test, skip)


def _check_frame_family(test: unittest.TestCase, case: dict[str, Any], skip: str | None) -> None:
    """Pad-bus and bootloader frames: check the CRC rule they share with the host frames, then skip."""
    if "crc_covers" in case:
        frame = bytes.fromhex(case["frame_hex"])
        stored = bytes.fromhex(case["crc_stored_hex"])
        test.assertEqual(frame[-2:], stored, "the CRC is the last two bytes, low byte first")
        covers = case["crc_covers"]
        value = crc16_ccitt_false(frame[covers["first"] : covers["last"] + 1])
        test.assertEqual(value.to_bytes(2, "little"), stored)
    _finish(test, skip)


CHECKERS: Final[dict[str, Callable[[unittest.TestCase, dict[str, Any], str | None], None]]] = {
    "crc16.json": _check_crc,
    "host_frames.json": _check_host,
    "stream_frames.json": _check_stream,
    "status.json": _check_status,
    "ota_frames.json": _check_ota,
    "pad_bus.json": _check_frame_family,
    "boot_frames.json": _check_frame_family,
}


class VectorSetTests(unittest.TestCase):
    """Checks on the vector set itself, before any case runs."""

    def test_every_file_has_the_schema_keys_in_order(self) -> None:
        for file_name in VECTOR_FILES:
            with self.subTest(file=file_name):
                document = load_vector_file(file_name)
                self.assertEqual(list(document), ["schema", "file", "description", "cases"])
                self.assertEqual(document["schema"], SCHEMA)
                self.assertEqual(document["file"], file_name)

    def test_counts_match_the_readme_table(self) -> None:
        self.assertEqual(sorted(EXPECTED_COUNTS), sorted(VECTOR_FILES))
        for file_name in VECTOR_FILES:
            with self.subTest(file=file_name):
                cases = load_vector_file(file_name)["cases"]
                anchors = sum(1 for case in cases if case["kind"] == "anchor")
                derived = sum(1 for case in cases if case["kind"] == "derived")
                self.assertEqual((len(cases), anchors, derived), EXPECTED_COUNTS[file_name])
        totals = [sum(counts[index] for counts in EXPECTED_COUNTS.values()) for index in range(3)]
        self.assertEqual(totals, EXPECTED_TOTALS)

    def test_case_ids_are_unique_across_files(self) -> None:
        ids = [case["id"] for file_name in VECTOR_FILES for case in load_vector_file(file_name)["cases"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_anchors_are_never_skipped(self) -> None:
        for file_name in VECTOR_FILES:
            for case in load_vector_file(file_name)["cases"]:
                if case["kind"] == "anchor":
                    with self.subTest(case=case["id"]):
                        self.assertIsNone(_skip_reason(file_name, case))

    def test_every_skip_names_a_case_that_exists(self) -> None:
        ids = {case["id"] for file_name in VECTOR_FILES for case in load_vector_file(file_name)["cases"]}
        expected = set(SKIP_BY_ID) - (FIRMWARE_UPDATE_CASES if PUBLIC_REPOSITORY else set())
        self.assertTrue(expected <= ids)
        self.assertTrue(DOCUMENTED_STATUS_DEVIATIONS <= ids)


class VectorCaseTests(unittest.TestCase):
    """Replaced below by one generated test method per vector case."""


def _make_case_test(file_name: str, case: dict[str, Any]) -> Callable[[unittest.TestCase], None]:
    checker = CHECKERS[file_name]
    skip = _skip_reason(file_name, case)

    def run_case(self: unittest.TestCase) -> None:
        checker(self, case, skip)

    run_case.__doc__ = f"{file_name}: {case['id']}"
    return run_case


for _file_name in VECTOR_FILES:
    for _case in load_vector_file(_file_name)["cases"]:
        _method = "test_" + _file_name.removesuffix(".json") + "__" + _case["id"].replace("-", "_")
        setattr(VectorCaseTests, _method, _make_case_test(_file_name, _case))
