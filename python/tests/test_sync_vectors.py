"""Event frames and GET_SYNC_MODE replies against the firmware's own vectors (sync_events.json, written by the
FDT 1.2.8.24 encoder, commit c71cb2f; copied here until that PR's sdk/vectors lands)."""

import json
import unittest
from pathlib import Path

from movetrics_fdt.stream import (
    EventFrame,
    StreamDecoder,
    SyncModeReply,
    decode_event_frame,
    decode_sync_mode_reply,
    encode_event_frame,
    encode_sync_mode_reply,
)
from movetrics_fdt.vocabulary import SampleConverter

CASES = json.loads((Path(__file__).parent / "fixtures" / "sync_events.json").read_text())["cases"]


class SyncVectorTests(unittest.TestCase):
    def test_every_event_case_decodes_and_encodes_byte_for_byte(self):
        events = [c for c in CASES if c["id"].startswith("sync-event")]
        self.assertEqual(len(events), 11)
        for case in events:
            with self.subTest(case=case["id"]):
                raw = bytes.fromhex(case["frame_hex"])
                frame = decode_event_frame(raw)
                f = case["fields"]
                self.assertEqual((frame.timeStamp, frame.event_type, frame.source, frame.count, frame.offset_us,
                                  frame.detail, frame.mode),
                                 (f["stamp"], f["type"], f["source"], f["counter"], f["offset_us"], f["detail"], f["mode"]))
                self.assertEqual(encode_event_frame(frame), raw)
                self.assertFalse(frame.name.startswith("unknown"))

    def test_get_sync_mode_replies(self):
        for case in (c for c in CASES if c["id"].startswith("sync-get")):
            with self.subTest(case=case["id"]):
                raw = bytes.fromhex(case["frame_hex"])
                reply = decode_sync_mode_reply(raw)
                self.assertEqual(reply, SyncModeReply(**case["fields"]))
                self.assertEqual(encode_sync_mode_reply(reply), raw)

    def test_decoder_routes_them_between_stream_frames(self):
        got = []
        decoder = StreamDecoder(on_reply=got.append)
        blob = b"".join(bytes.fromhex(c["frame_hex"]) for c in CASES)
        self.assertEqual(decoder.push(blob), [])
        self.assertEqual(len(got), 13)
        self.assertEqual(decoder.discarded_bytes, 0)

    def test_event_time_includes_the_offset(self):
        raw = bytes.fromhex(next(c for c in CASES if c["id"] == "sync-event-in-fall")["frame_hex"])
        [event] = SampleConverter().push(decode_event_frame(raw))
        self.assertAlmostEqual(event.t, 12.3456 - 41e-6)
        self.assertEqual(event.name, "sync_in_fall")


if __name__ == "__main__":
    unittest.main()
