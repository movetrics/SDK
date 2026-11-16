"""NOKOV XINGYING support: Remote Trigger / Remote Control messages, take cutting, UDP, the analog worksheet."""

import asyncio
import json
import math
import os
import tempfile
import time
import unittest
from pathlib import Path

from movetrics_fdt import nokov
from movetrics_fdt.nokov import (CaptureMessage, NokovMessageError, TakeCutter, TriggerListener, analog_worksheet,
                                 capture_start_message, capture_stop_message, parse_capture_message,
                                 send_capture_message, take_file_stem, write_take)
from movetrics_fdt.sync import ClockMap
from movetrics_fdt.vocabulary import STREAM_SIGN, Event, Gap, Sample, plate_cop

try:
    import ezc3d
except ImportError:  # pragma: no cover
    ezc3d = None

# The manual's examples (XingYing 4.7, Plugins & SDKs), one line each as the page says the packets are sent. The
# trigger examples carry a bare '&'; the stop example names another take than the start example.
TRIGGER_START = (b'<?xml version="1.0" encoding="UTF-8" standalone="no" ?><CaptureStart>'
                 b'<Name VALUE="RemoteTriggerTest_take0116" /><DatabasePath VALUE="F:\\20230712\\test1" />'
                 b'<Notes VALUE="This is Beijing NOKOV Science & Technology Co., Ltd Motion Capture Start Msg" />'
                 b'<Description VALUE="NULL" /><Delay VALUE="33" /><PacketID VALUE="10028" /></CaptureStart>')
TRIGGER_STOP = (b'<?xml version="1.0" encoding="UTF-8" standalone="no" ?><CaptureStop RESULT="SUCCESS">'
                b'<Name VALUE="RemoteTriggerTest_take0114" /><DatabasePath VALUE="F:\\20230712\\test1" />'
                b'<Notes VALUE="This is Beijing NOKOV Science & Technology Co., Ltd Motion Capture Stop Msg" />'
                b'<Description VALUE="NULL" /><Delay VALUE="33" /><PacketID VALUE="10025" /></CaptureStop>')
CONTROL_START = (b'<?xml version="1.0" encoding="UTF-8" standalone="no" ?><CaptureStart><Name VALUE="Remotetake01"/>'
                 b'<SessionName VALUE="SessionName" /><Notes VALUE="Take notes if any"/><Delay VALUE="Reserved" />'
                 b'<Description VALUE="" /><DatabasePath VALUE="F:/shared/"/><TimeCode VALUE="00:00:00:00"/>'
                 b'<PacketID VALUE="0"/></CaptureStart>')
CONTROL_STOP = (b'<?xml version="1.0" encoding="utf-8"?><CaptureStop><Name VALUE="Remotetake01" />'
                b'<Notes VALUE="Take notes go here if any." /><Assets VALUE="skel1, skel2, sword" />'
                b'<TimeCode VALUE="00:00:00:00" /><HostName VALUE="optional host name" />'
                b'<ProcessID VALUE="optional process id" /></CaptureStop>')


def start(name="take01", packet="1"):
    return parse_capture_message(f'<CaptureStart><Name VALUE="{name}"/><PacketID VALUE="{packet}"/></CaptureStart>'.encode())


def stop(name="take01", packet="2", result="SUCCESS"):
    return parse_capture_message(f'<CaptureStop RESULT="{result}"><Name VALUE="{name}"/><PacketID VALUE="{packet}"/>'
                                 f'</CaptureStop>'.encode())


def sample(t, plate=1, fz=700.0):
    return Sample(t, plate, 1.0, 2.0, fz, 3.0, -4.0, 0.5, 0.01, -0.02, round(t * 10000), (1, -2, int(fz), -3, -4, 0))


def stream(cutter, t_from, t_to, rate=1000, delay=0.002, plates=(1, 2)):
    """Samples from t_from to t_to (FDT s), each arriving delay plus a little jitter later on the host clock."""
    done = []
    k = round(t_from * rate)
    while k < round(t_to * rate):
        t = k / rate
        for plate in plates:
            done += cutter.add(sample(t, plate), t + delay + (k % 7) * 0.0003)
        k += 1
    return done


class MessageTests(unittest.TestCase):
    def test_the_manuals_trigger_examples_parse_leniently(self):
        message = parse_capture_message(TRIGGER_START)
        self.assertEqual((message.kind, message.name, message.packet_id), ("start", "RemoteTriggerTest_take0116", "10028"))
        self.assertEqual(message.fields["DatabasePath"], "F:\\20230712\\test1")
        self.assertIn("Science & Technology", message.fields["Notes"])
        self.assertTrue(message.lenient)
        self.assertEqual(message.raw, TRIGGER_START)
        stopped = parse_capture_message(TRIGGER_STOP)
        self.assertEqual((stopped.kind, stopped.name, stopped.result), ("stop", "RemoteTriggerTest_take0114", "SUCCESS"))

    def test_the_manuals_control_examples_parse_strictly(self):
        message = parse_capture_message(CONTROL_START)
        self.assertFalse(message.lenient)
        self.assertEqual(list(message.fields), ["Name", "SessionName", "Notes", "Delay", "Description", "DatabasePath",
                                                "TimeCode", "PacketID"])
        stopped = parse_capture_message(CONTROL_STOP)
        self.assertEqual((stopped.kind, stopped.fields["Assets"], stopped.result), ("stop", "skel1, skel2, sword", None))

    def test_what_a_network_adds_is_tolerated(self):
        escaped = TRIGGER_START.replace(b"Science & Technology", b"Science &amp; Technology")
        self.assertFalse(parse_capture_message(escaped).lenient)
        self.assertEqual(parse_capture_message(escaped).fields["Notes"], parse_capture_message(TRIGGER_START).fields["Notes"])
        for variant in (CONTROL_START + b"\x00\x00", b"\xef\xbb\xbf" + CONTROL_START, b"\n " + CONTROL_START + b"\r\n",
                        CONTROL_START.replace(b"><", b">\n  <")):
            with self.subTest(variant=variant[:12]):
                self.assertEqual(parse_capture_message(variant).name, "Remotetake01")

    def test_chinese_take_names_in_utf8_and_gbk(self):
        name = "跳跃测试01"
        body = f'<CaptureStart><Name VALUE="{name}"/></CaptureStart>'
        utf8 = parse_capture_message(body.encode("utf-8"))
        self.assertEqual((utf8.name, utf8.encoding, utf8.warnings), (name, "utf-8", ()))
        gbk = parse_capture_message(body.encode("gbk"))
        self.assertEqual((gbk.name, gbk.encoding), (name, "gbk"))
        self.assertIn("decoded as GBK, not UTF-8", gbk.warnings)

    def test_hostile_or_foreign_datagrams_are_refused(self):
        bomb = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
                b'<CaptureStart><Name VALUE="&lol2;"/></CaptureStart>')
        external = b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><CaptureStart><Name VALUE="&e;"/></CaptureStart>'
        for data in (bomb, external, b"<CaptureStart><Name VALUE='x'/>" + b" " * nokov.MAX_MESSAGE_BYTES + b"</CaptureStart>",
                     b"<Foo><Name VALUE='x'/></Foo>", b"<CaptureStart/>", b'<CaptureStart><Name VALUE="  "/></CaptureStart>',
                     b"hello", b"\xff\xfe\xfd\x80", b"<CaptureStart><Name VALUE='x'></CaptureStart>", b""):
            with self.subTest(data=data[:30]), self.assertRaises(NokovMessageError):
                parse_capture_message(data)

    def test_unusual_but_valid_messages_say_why(self):
        failed = stop(result="FAILED")
        self.assertIn("RESULT is 'FAILED', not SUCCESS", failed.warnings)
        repeated = parse_capture_message(b'<CaptureStart><Name VALUE="a"/><Name VALUE="b"/></CaptureStart>')
        self.assertEqual(repeated.name, "a")
        self.assertIn("field Name repeated; the first is kept", repeated.warnings)

    def test_outgoing_messages_follow_the_manual_and_round_trip(self):
        data = capture_start_message("jump <3> & \"go\"", "D:/data", notes="a & b", packet_id=7)
        self.assertTrue(data.startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="no" ?><CaptureStart><Name '))
        message = parse_capture_message(data)
        self.assertFalse(message.lenient)
        self.assertEqual(list(message.fields), ["Name", "SessionName", "Notes", "Delay", "Description", "DatabasePath",
                                                "TimeCode", "PacketID"])
        self.assertEqual((message.name, message.fields["Notes"], message.packet_id), ('jump <3> & "go"', "a & b", "7"))
        stopped = parse_capture_message(capture_stop_message("跳跃01", packet_id=8))
        self.assertEqual((stopped.kind, stopped.name, list(stopped.fields)[:6]),
                         ("stop", "跳跃01", ["Name", "Notes", "Assets", "TimeCode", "HostName", "ProcessID"]))
        self.assertNotIn(b"&", capture_stop_message("x"))  # defaults carry no '&' (XINGYING's handling of &amp; is unknown)
        for call in (lambda: capture_start_message("", "D:/"), lambda: capture_start_message("x", " "),
                     lambda: capture_stop_message("bad\nname"), lambda: capture_start_message("x", "D:/", notes="\x07")):
            with self.assertRaises(ValueError):
                call()

    def test_take_names_become_safe_file_names(self):
        cases = {"take01": "take01", "跳跃 测试 01": "跳跃 测试 01", "a:b*c?d": "a_b_c_d", "": "take", "....": "take",
                 "CON": "_CON", "con.txt": "_con.txt", "LPT9": "_LPT9", "name. ": "name", "x\x00y": "x_y"}
        for name, stem in cases.items():
            with self.subTest(name=name):
                self.assertEqual(take_file_stem(name), stem)
        for name in ("../../etc/passwd", "..\\..\\Windows\\win.ini", "/abs/path", "C:\\x"):
            with self.subTest(name=name):
                stem = take_file_stem(name)
                self.assertFalse(any(part in stem for part in ("/", "\\", ":")) or stem.startswith("."), stem)
        self.assertEqual(len(take_file_stem("a" * 300)), 100)


class ClockInverseTests(unittest.TestCase):
    def test_to_device_inverts_to_host(self):
        clock = ClockMap(latency_seconds=0.004)
        with self.assertRaises(ValueError):
            clock.to_device(1.0)
        clock.observe(0.5, 100.502)
        self.assertAlmostEqual(clock.to_device(clock.to_host(0.7)), 0.7, delta=1e-12)  # warm-up: floor only
        for k in range(1, 6000):
            t = k / 1000
            clock.observe(t, 100 + t * (1 + 50e-6) + 0.002 + (k % 5) * 0.001)
        self.assertIsNotNone(clock.drift_ppm)
        for t in (0.0, 3.3, 5.999, 40.0):
            self.assertAlmostEqual(clock.to_device(clock.to_host(t)), t, delta=1e-9)


class TakeCutterTests(unittest.TestCase):
    def test_a_take_is_cut_in_fdt_time_with_the_preroll(self):
        cutter = TakeCutter()
        self.assertEqual(stream(cutter, 0.001, 5.0), [])
        self.assertEqual(cutter.trigger(start("jump 1"), 5.002 + 0.0006), [])  # arrives just after FDT 5.000
        self.assertEqual(stream(cutter, 5.0, 7.0), [])
        self.assertEqual(cutter.trigger(stop("jump 1"), 7.002 + 0.0006), [])
        takes = stream(cutter, 7.0, 7.1)
        self.assertEqual(len(takes), 1)
        take = takes[0]
        samples = take.samples()
        per_plate = take.summary()["samples_per_plate"]
        self.assertEqual(set(per_plate), {"1", "2"})
        for count in per_plate.values():
            self.assertLessEqual(abs(count - 2000), 2)
        self.assertLess(abs(samples[0].t - 5.0), 0.002)
        self.assertLess(abs(samples[-1].t - 7.0), 0.002)
        self.assertEqual(take.notes, [])
        self.assertEqual(take.summary()["alignment"], nokov.ALIGNMENT)

    def test_repeats_strays_and_supersession(self):
        cutter = TakeCutter()
        stream(cutter, 0.001, 4.0)
        self.assertEqual(cutter.trigger(stop("ghost"), 4.0), [])  # no open take
        cutter.trigger(start("a"), 4.002)
        self.assertEqual(cutter.trigger(start("a"), 4.003), [])  # the same broadcast again: ignored
        reasons = [reason for _, reason in cutter.ignored]
        self.assertTrue(any("without an open take" in r for r in reasons) and any("repeat" in r for r in reasons))
        stream(cutter, 4.0, 5.0)
        closed = cutter.trigger(start("b", packet="9"), 5.002)
        self.assertEqual([t.name for t in closed], ["a"])
        self.assertIn("arrived before a CaptureStop", closed[0].notes[0])
        stream(cutter, 5.0, 6.0)
        cutter.trigger(stop("other name"), 6.002)
        done = stream(cutter, 6.0, 6.1)
        self.assertEqual([t.name for t in done], ["b"])
        self.assertIn("CaptureStop names 'other name'", done[0].notes[0])

    def test_guards_warmup_and_close(self):
        cutter = TakeCutter(max_take_s=1.0)
        cutter.trigger(start("early"), 0.0)  # before any sample
        done = stream(cutter, 0.001, 1.5)
        self.assertEqual(len(done), 1)
        self.assertTrue(any("before any FDT sample" in n for n in done[0].notes))
        self.assertTrue(any("no CaptureStop within 1 s" in n for n in done[0].notes))
        # The take starts with the first sample and the guard closes it 1 s later.
        self.assertEqual(done[0].start_t, 0.001)
        self.assertEqual(done[0].summary()["samples_per_plate"], {"1": 1000, "2": 1000})
        warm = TakeCutter()
        stream(warm, 0.001, 1.0)
        warm.trigger(start("warm"), 1.002)
        stream(warm, 1.0, 1.5)
        closed = warm.close()
        self.assertTrue(any("warm-up" in n for n in closed[0].notes))
        self.assertTrue(any("stopped before a CaptureStop" in n for n in closed[0].notes))
        self.assertEqual(warm.close(), [])

    def test_events_gaps_and_repaired_messages_travel_with_the_take(self):
        cutter = TakeCutter()
        stream(cutter, 0.001, 4.0)
        cutter.trigger(parse_capture_message(TRIGGER_START), 4.002)
        cutter.add(Event(4.5, 1, "sync_in_rise"), 4.502)
        cutter.add(Gap(1, 4.6, 4.61, 9), 4.612)
        stream(cutter, 4.0, 5.0)
        cutter.trigger(parse_capture_message(TRIGGER_STOP), 5.002)
        take = stream(cutter, 5.0, 5.1)[0]
        kinds = {type(item).__name__ for item in take.items}
        self.assertEqual(kinds, {"Sample", "Event", "Gap"})
        self.assertTrue(any("needed repair" in n for n in take.notes))
        self.assertTrue(any("CaptureStop names" in n for n in take.notes))  # the manual's own example pair


class WriteTakeTests(unittest.TestCase):
    def take(self, name="jump 1"):
        cutter = TakeCutter()
        stream(cutter, 0.001, 4.0)
        cutter.trigger(start(name), 4.002)
        stream(cutter, 4.0, 4.5)
        cutter.trigger(stop(name), 4.502)
        return stream(cutter, 4.5, 4.6)[0]

    def test_csv_and_sidecar_without_overwriting(self):
        with tempfile.TemporaryDirectory() as out:
            first = write_take(self.take("../jump 1"), out, 1000)
            second = write_take(self.take("../jump 1"), out, 1000)
            self.assertEqual([p.name for p in first], ["_jump 1.csv", "_jump 1.nokov.json"])
            self.assertEqual([p.name for p in second], ["_jump 1-2.csv", "_jump 1-2.nokov.json"])
            companion = json.loads(Path(str(first[0]) + ".json").read_text(encoding="utf-8"))
            self.assertEqual(companion["metadata"]["nokov"]["name"], "../jump 1")
            sidecar = json.loads(first[1].read_text(encoding="utf-8"))
            self.assertEqual(sidecar["start"]["kind"], "start")
            self.assertTrue(all(p.parent == Path(out) for p in first + second))

    def test_a_take_without_samples_keeps_its_triggers(self):
        cutter = TakeCutter()
        cutter.trigger(start("empty"), 1.0)
        take = cutter.close()[0]
        with tempfile.TemporaryDirectory() as out:
            paths = write_take(take, out, 1000)
            self.assertEqual([p.name for p in paths], ["empty.nokov.json"])
            self.assertIn("no FDT samples in the take", json.loads(paths[0].read_text(encoding="utf-8"))["notes"])

    @unittest.skipIf(ezc3d is None, "ezc3d not installed (pip install ezc3d)")
    def test_c3d(self):
        with tempfile.TemporaryDirectory() as out:
            paths = write_take(self.take(), out, 1000, fmt="c3d")
            self.assertEqual([p.suffix for p in paths], [".c3d", ".json"])


class UdpTests(unittest.TestCase):
    def test_listener_receives_what_the_sender_sends(self):
        async def run():
            async with TriggerListener("127.0.0.1", 0) as listener:
                port = listener.port
                send_capture_message(b"not xml at all", "127.0.0.1", port)
                send_capture_message(capture_start_message("take 7", "D:/x", packet_id=1), "127.0.0.1", port)
                send_capture_message(TRIGGER_STOP, "127.0.0.1", port)
                first = await asyncio.wait_for(listener.__anext__(), 5)
                second = await asyncio.wait_for(listener.__anext__(), 5)
                return first, second, list(listener.rejected)

        (first, arrival, address), (second, _, _), rejected = asyncio.run(run())
        self.assertEqual((first.kind, first.name, second.kind), ("start", "take 7", "stop"))
        self.assertEqual(address[0], "127.0.0.1")
        self.assertLessEqual(abs(arrival - time.monotonic()), 10)
        self.assertEqual(len(rejected), 1)

    def test_record_takes_end_to_end_in_real_time(self):
        async def items():
            k = 0
            begin = time.monotonic()
            while time.monotonic() - begin < 2.6:
                k += 1
                for plate in (1, 2):
                    yield sample(k / 200, plate)
                await asyncio.sleep(max(0.0, begin + k / 200 - time.monotonic()))

        async def run(out):
            async with TriggerListener("127.0.0.1", 0) as listener:
                async def triggers():
                    await asyncio.sleep(0.9)
                    for _ in range(2):  # one broadcast arrives once per network card
                        send_capture_message(capture_start_message("live", "D:/x"), "127.0.0.1", listener.port)
                    await asyncio.sleep(1.0)
                    send_capture_message(capture_stop_message("live"), "127.0.0.1", listener.port)

                sender = asyncio.create_task(triggers())
                lines, marks = [], []
                written = await nokov.record_takes(items(), 200, out, listener, log=lines.append, on_trigger=marks.append)
                await sender
                return written, lines, marks

        with tempfile.TemporaryDirectory() as out:
            written, lines, marks = asyncio.run(run(out))
            self.assertEqual(len(written), 1, lines)
            self.assertEqual([mark.kind for mark in marks], ["start", "stop"])  # the repeat makes no second marker
            self.assertTrue(any(line.startswith("ignored CaptureStart 'live': repeat") for line in lines), lines)
            summary = json.loads(written[0][-1].read_text(encoding="utf-8"))
            for count in summary["samples_per_plate"].values():
                self.assertLess(abs(count - 200), 30)  # 1 s at 200/s; the scheduler's jitter is in the cut


class AnalogWorksheetTests(unittest.TestCase):
    def test_wiring_and_matrix(self):
        sheet = analog_worksheet("1.2.8.24")
        plate1, plate2 = sheet["derived"]["plates"]
        self.assertEqual([w["fdt_output"] for w in plate1["wiring"]], ["A2", "A3", "A1", "A5", "A6", "A4"])
        self.assertEqual([w["fdt_output"] for w in plate2["wiring"]], ["A10", "A11", "A9", "A13", "A14", "A12"])
        self.assertEqual(plate1["unused_outputs"], ["A7", "A8"])
        m = plate1["matrix_surface_moments"]
        self.assertEqual([m[k][k] for k in range(6)], [200, 200, 800, 72, 72, 72])
        self.assertAlmostEqual(m[3][1], -6.0)
        self.assertAlmostEqual(m[4][0], 6.0)
        off_diagonal = [m[r][c] for r in range(6) for c in range(6) if r != c and (r, c) not in ((3, 1), (4, 0))]
        self.assertEqual(set(off_diagonal), {0.0})
        self.assertTrue(sheet["unknown"] and sheet["check"] and sheet["limits"])
        self.assertIn("Set Force Units to Newtons", sheet["check"][0])

    def test_firmware_and_plates_are_checked(self):
        with self.assertRaises(ValueError):
            analog_worksheet("1.2.8.20")
        with self.assertRaises(ValueError):
            analog_worksheet(plates=(3,))
        self.assertEqual(len(analog_worksheet("1.2.8.21", plates=(2,))["derived"]["plates"]), 1)

    def voltages(self, fx, fy, fz, mx, my, mz):
        """Plate-frame values (Studio's signs) to the voltages on XINGYING channels 1-6 (wired as the worksheet says)."""
        wire = [s * v for s, v in zip(STREAM_SIGN, (fx, fy, fz, mx, my, mz))]
        gains = {"fx": 200, "fy": 200, "fz": 800, "mx": 72, "my": 72, "mz": 72}
        names = ("fx", "fy", "fz", "mx", "my", "mz")
        return [wire[names.index(name)] / gains[name] for name in ("fx", "fy", "fz", "mx", "my", "mz")]

    def test_computed_consistency_with_the_vocabulary_cop(self):
        """Not a validation in XINGYING: the matrix and our CoP formula come from one contract. With origin 0, a C3D
        type-2 reader puts the CoP at (-My/Fz, Mx/Fz); that must equal the vocabulary's plate CoP."""
        m = analog_worksheet()["derived"]["plates"][0]["matrix_surface_moments"]
        for values in ((10.0, -20.0, 750.0, 15.0, -30.0, 2.0), (-80.0, 45.0, 1200.0, -60.0, 40.0, -5.0)):
            volts = self.voltages(*values)
            fx, fy, fz, mx_s, my_s, mz = (sum(m[r][c] * volts[c] for c in range(6)) for r in range(6))
            cop = plate_cop(*values[:5])
            self.assertAlmostEqual(-my_s / fz, cop[0], delta=1e-9)
            self.assertAlmostEqual(mx_s / fz, cop[1], delta=1e-9)

    @unittest.skipIf(ezc3d is None, "ezc3d not installed (pip install ezc3d)")
    def test_computed_consistency_with_our_c3d_writer(self):
        """The matrix gives the channel values our C3D writer writes for the same sample (moments in N*mm there)."""
        from movetrics_fdt.writers import Recording, write_c3d

        values = (10.0, -20.0, 750.0, 15.0, -30.0, 2.0)
        m = analog_worksheet()["derived"]["plates"][0]["matrix_surface_moments"]
        volts = self.voltages(*values)
        expected = [sum(m[r][c] * volts[c] for c in range(6)) for r in range(6)]
        rows = [Sample(k / 1000, 1, *values, *plate_cop(*values[:5]), k * 10, (0,) * 6) for k in range(1, 6)]
        with tempfile.TemporaryDirectory() as out:
            path = write_c3d(Recording.from_samples(rows, 1000), os.path.join(out, "one.c3d"))[0]
            data = ezc3d.c3d(str(path))
        labels = data["parameters"]["ANALOG"]["LABELS"]["value"]
        analogs = data["data"]["analogs"][0]
        for k, name in enumerate(("Fx1", "Fy1", "Fz1", "Mx1", "My1", "Mz1")):
            written = float(analogs[labels.index(name)][0])
            want = expected[k] * (1000 if k >= 3 else 1)
            self.assertAlmostEqual(written, want, delta=1e-3 * max(1.0, abs(want)), msg=name)

    def test_cli_prints_the_worksheet(self):
        text = nokov.format_worksheet(analog_worksheet())
        for phrase in ("channel 1 (fx): A2", "channel 3 (fz): A1", "leave unconnected: A7, A8", "Check on site",
                       "on an F1-3D S plate Mz is derived (0.02 m x Fx)"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
