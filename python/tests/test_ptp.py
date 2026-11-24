"""PTP time base (docs/25): the pulse map on synthetic clocks, the host map, pmc parsing, and end to end on the
simulator with a pulse per second on SYNC IN. Synthetic and simulated only; nothing here touches a network."""

import random
import unittest

from movetrics_fdt import SyncMode
from movetrics_fdt.frames import encode_host_frame
from movetrics_fdt.ptp import (NS, HostMap, PtpRecorder, make_host_clock, parse_pmc_time_status, pulse_map)
from movetrics_fdt.simulator import Faults, Synthetic, VirtualFdt
from movetrics_fdt.stream import EventFrame, StreamDecoder
from movetrics_fdt.vocabulary import Event, Sample, SampleConverter

T0 = 1_795_000_000 * NS  # a PTP time in November 2026 (TAI ns)


def _truth(ppm: float, start_ns: int):
    """FDT seconds -> true PTP ns for an FDT clock ppm fast that started at start_ns."""
    return lambda t: start_ns + round(t / (1 + ppm * 1e-6) * NS)


def _edges(ppm: float, start_ns: int, seconds: int, jitter_s: float, rng: random.Random):
    """FDT times of the rising edges of a pulse per second (PTP whole seconds) as an FDT ppm fast sees them."""
    first = -(-start_ns // NS)  # the first whole second after the start
    out = []
    for k in range(first, first + seconds):
        true_fdt = (k * NS - start_ns) / NS * (1 + ppm * 1e-6)
        out.append(true_fdt + rng.gauss(0, jitter_s))
    return out


class PulseMapTests(unittest.TestCase):
    def test_drift_jitter_noise_and_missed_pulses(self):
        rng = random.Random(3)
        start = T0 + 123_456_789
        truth = _truth(40, start)
        edges = _edges(40, start, 600, 5e-6, rng)
        del edges[100], edges[300]  # two pulses lost
        edges += [17.25, 222.9]  # static on the jack: edges at no whole second
        edges.append(edges[50] + 0.002)  # a bounce 2 ms after a real edge
        coarse = lambda t: truth(t) + 20_000_000  # the host clock 20 ms off PTP: only picks the second
        m = pulse_map(edges, coarse)
        self.assertEqual(len(m.anchors), 598)
        self.assertEqual(m.missing, 2)
        self.assertEqual(len(m.rejected), 3)
        self.assertAlmostEqual(m.drift_ppm, -40, delta=0.05)
        self.assertAlmostEqual(m.host_offset_s, 0.020, delta=0.001)
        self.assertLess(m.jitter_rms_s, 8e-6)
        self.assertEqual(m.warnings, ())
        to_ptp = m.mapper()
        errors = [abs(to_ptp(t) - truth(t)) / NS for t in (k * 0.0005 + 1.0 for k in range(0, 1_100_000, 997))]
        # 5 us edge jitter averaged over 11 pulses: well under the jitter itself.
        self.assertLess(max(errors), 5e-6)

    def test_four_hours_at_50_ppm_with_static(self):
        # The FDT drifts 0.72 s from PTP over four hours; the host clock follows it, so no pulse gets the wrong second.
        rng = random.Random(1)
        truth = _truth(50, T0)
        edges = [k * (1 + 50e-6) + rng.gauss(0, 4e-6) for k in range(1, 4 * 3600)]
        edges += [rng.uniform(0, 14400) for _ in range(200)]
        m = pulse_map(edges, lambda t: truth(t) + 12_000_000)
        self.assertEqual((len(m.anchors), m.missing, len(m.rejected)), (4 * 3600 - 1, 0, 200))
        to_ptp = m.mapper()
        self.assertLess(max(abs(to_ptp(t) - truth(t)) for t in (x * 3.7 for x in range(3800))) / NS, 10e-6)

    def test_wrong_host_second_is_flagged(self):
        rng = random.Random(5)
        start = T0
        truth = _truth(0, start)
        edges = _edges(0, start, 30, 2e-6, rng)
        m = pulse_map(edges, lambda t: truth(t) + 400_000_000)  # 0.4 s off: every pulse lands on the wrong second
        self.assertTrue(m.warnings)
        self.assertIn("wrong second", m.warnings[0])

    def test_needs_two_edges(self):
        with self.assertRaises(ValueError):
            pulse_map([1.0], lambda t: T0)

    def test_pulses_at_a_phase_and_period(self):
        rng = random.Random(9)
        start = T0 + 0.37e9
        truth = _truth(-25, int(start))
        # Pulses every 0.5 s at 0.1 s past: PTP times k*0.5 s + 0.1 s.
        edges = []
        k = int((start - 0.1e9) // 0.5e9) + 1
        for _ in range(200):
            ptp = k * 500_000_000 + 100_000_000
            edges.append((ptp - start) / NS * (1 - 25e-6) + rng.gauss(0, 3e-6))
            k += 1
        m = pulse_map(edges, truth, period_s=0.5, phase_ns=100_000_000)
        self.assertEqual(len(m.anchors), 200)
        self.assertAlmostEqual(m.drift_ppm, 25, delta=0.1)
        self.assertLess(abs(m.to_ptp_ns(50.0) - truth(50.0)) / NS, 5e-6)


class HostMapTests(unittest.TestCase):
    def test_usb_jitter_out_latency_constant_in(self):
        rng = random.Random(11)
        host = HostMap()
        truth = _truth(30, T0 + 5_000_000)
        for k in range(60 * 1000):
            t = k / 1000
            delay = 0.012 + rng.uniform(0, 0.016)  # 12 ms frame latency plus USB bursts
            host.observe(t, truth(t) + round(delay * NS))
        host.finish()
        errors = [(host.to_ptp_ns(t) - truth(t)) / NS for t in (5.0, 30.0, 55.0)]
        # The jitter is gone; the constant 12 ms is not: that is what latency_s is for.
        for e in errors:
            self.assertAlmostEqual(e, 0.012, delta=0.0005)


class PmcTests(unittest.TestCase):
    TEXT = """sending: GET TIME_STATUS_NP
\t001b21.fffe.6f2a10-1 seq 0 RESPONSE MANAGEMENT TIME_STATUS_NP
\t\tmaster_offset              -38
\t\tingress_time               1795000123456789012
\t\tcumulativeScaledRateOffset +0.000000000
\t\tscaledLastGmPhaseChange    0
\t\tgmTimeBaseIndicator        0
\t\tlastGmPhaseChange          0x0000'0000000000000000.0000
\t\tgmPresent                  true
\t\tgmIdentity                 ec4670.fffe.0a1b2c
"""

    def test_parse(self):
        status = parse_pmc_time_status(self.TEXT)
        self.assertIsNotNone(status)
        self.assertTrue(status.gm_present)
        self.assertEqual(status.gm_identity, "ec4670.fffe.0a1b2c")
        self.assertEqual(status.master_offset_ns, -38)
        self.assertEqual(status.port_identity, "001b21.fffe.6f2a10-1")

    def test_no_response(self):
        self.assertIsNone(parse_pmc_time_status("sending: GET TIME_STATUS_NP\n"))

    def test_host_clock_kinds(self):
        clock = make_host_clock("utc", 37)
        self.assertGreater(clock(), 1_700_000_000 * NS)
        with self.assertRaises(ValueError):
            make_host_clock("gps")


def _command(fdt, code, payload, now):
    fdt.feed(encode_host_frame(code, 0xFF if code == 0x01 else 0, 0xFF if code == 0x01 else 0, payload), now)


class SimulatedPpsTests(unittest.TestCase):
    """A simulated FDT 35 ppm fast, a PPS on SYNC IN at every whole PTP second, USB delivery 12 to 28 ms late."""

    def _run(self, seconds: float, *, pps: bool, latency_s: float = 0.0):
        rng = random.Random(21)
        ptp_at_host_zero = T0 + 431_000_000  # PTP time when the simulation's clock reads 0
        fdt = VirtualFdt("sync", Synthetic("cmj", seed=4), Faults(clock_ppm=35))
        _command(fdt, 0x28, bytes((int(SyncMode.EVENT_FRAMES), 0, 0, 0, 1)), 0.0)  # debounce 0.1 ms
        _command(fdt, 0x01, b"", 0.0)
        recorder = PtpRecorder(latency_s=latency_s)
        converter = SampleConverter(1000)
        samples: list[Sample] = []
        events: list[Event] = []
        now = 0.0
        step = 0.001
        next_pps = (-(-ptp_at_host_zero // NS) * NS - ptp_at_host_zero) / NS  # host time of the next whole second

        def drain(at: float) -> None:
            arrival = ptp_at_host_zero + round((at + 0.012 + rng.uniform(0, 0.016)) * NS)
            for frame in decoder.push(fdt.advance(at)):
                for item in converter.push(frame):
                    recorder.push(item, arrival)
                    (samples if isinstance(item, Sample) else events).append(item)

        def on_reply(reply) -> None:  # event frames come out of the decoder as replies
            if isinstance(reply, EventFrame):
                for item in converter.push(reply):
                    recorder.push(item, ptp_at_host_zero)
                    events.append(item)

        decoder = StreamDecoder(on_reply=on_reply)
        fall_at = None
        while now < seconds:
            if pps and next_pps <= now + step:
                drain(next_pps)
                fdt.sync_in(1, next_pps)  # the edge exactly at the whole PTP second
                fall_at = next_pps + 0.1  # 100 ms wide, as many pulse-per-second outputs
                next_pps += 1.0
            if fall_at is not None and fall_at <= now + step:
                drain(fall_at)
                fdt.sync_in(0, fall_at)
                fall_at = None
            now += step
            drain(now)
        truth = lambda s: ptp_at_host_zero + round(s.t / (1 + 35e-6) * NS)
        return recorder.finish(), samples, truth

    def test_pulse_route_puts_samples_on_ptp_time(self):
        ptp_map, samples, truth = self._run(40.0, pps=True)
        self.assertEqual(ptp_map.method, "pulse")
        self.assertGreaterEqual(len(ptp_map.pulse.anchors), 38)
        to_ptp = ptp_map.mapper()
        inside = [s for s in samples if ptp_map.pulse.covers(s.t)]
        worst = max(abs(to_ptp(s.t) - truth(s)) for s in inside) / NS
        # The simulator stamps an edge to 1 us (its offset field) and its tick is 0.1 ms: the map is exact to a few us.
        self.assertLess(worst, 20e-6)
        mean, _ = ptp_map.host_minus_pulse_s
        self.assertAlmostEqual(mean, 0.012, delta=0.003)  # the host route's constant, measured by the pulses

    def test_host_route_without_pulses(self):
        ptp_map, samples, truth = self._run(20.0, pps=False, latency_s=0.012)
        self.assertEqual(ptp_map.method, "host")
        self.assertIn("no pulse", ptp_map.warnings[0])
        to_ptp = ptp_map.mapper()
        late = [s for s in samples if s.t > 5]
        worst = max(abs(to_ptp(s.t) - truth(s)) for s in late) / NS
        self.assertLess(worst, 0.002)


if __name__ == "__main__":
    unittest.main()
