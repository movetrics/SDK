// The shared vocabulary: one set of names, units and frames for every Movetrics client, file and API.
// Contract: contracts/vocabulary.v1.json and docs/19-vocabulary-and-units.md. Port of
// python/movetrics_fdt/vocabulary.py, which it must match number for number.
//
// Field names are the contract's names (cop_x, start_t, end_t), not camelCase, so a record reads the
// same in every client. Each record has a kind field so that the union can be told apart.
//
// SampleConverter turns stream items into Samples, Events and Gaps. It drops the stamp-0 placeholders
// after START, unwraps the uint32 stamp, applies Studio's sign map (so a live sample carries the same
// numbers as the same sample in a Studio export) and reports every hole in the stream instead of hiding it.
import { eventName } from "./stream.js";
export const TICKS_PER_SECOND = 10_000;
export const STAMP_MODULUS = 2 ** 32;
// Moment reference, 30 mm below the centre of the top surface (measured, docs/19 section 3).
export const MOMENT_REFERENCE_DEPTH_M = 0.03;
// Below this vertical force no centre of pressure is reported (Studio's CopForceThreshold).
export const COP_MIN_FZ_N = 50;
// Plate-frame value = sign * wire value: Studio's QuadrantTransform 4,3,2,1 negates Fy and Mx. From
// configuration; the bench check with one known off-centre load is still open (docs/19 section 2).
export const STREAM_SIGN = [1, -1, 1, -1, 1, 1];
// Plate centres in the pair frame (Studio's comb_ frame), fitted on the 14 Oct 2026 export (residual 0.37 mm).
const PAIR_CENTRE_X_M = { 1: -0.175, 2: 0.175 };
// A step longer than this many nominal periods is a gap.
const GAP_FACTOR = 1.5;
// Centre of pressure (x, y) in m from the plate centre, plate frame. NaN below minFzN.
// x = (-my - d*fx) / fz, y = (-mx + d*fy) / fz with d = 0.030 m reproduces Studio's CoP columns to
// 0.28 mm rms on the 14 Oct 2026 export (measured, docs/19 section 3).
export function plateCop(fx, fy, fz, mx, my, minFzN = COP_MIN_FZ_N, depthM = MOMENT_REFERENCE_DEPTH_M) {
    // Written as "not >=" so that a NaN force gives NaN too.
    if (!(fz >= minFzN))
        return [Number.NaN, Number.NaN];
    return [(-my - depthM * fx) / fz, (-mx + depthM * fy) / fz];
}
// Python's round() on a float: halves go to the even neighbour (round(2.5) = 2). Math.round would give 3.
// The gap count depends on it at exact halves, such as a step of 2.5 periods.
function roundHalfEven(value) {
    const floor = Math.floor(value);
    const fraction = value - floor;
    if (fraction < 0.5)
        return floor;
    if (fraction > 0.5)
        return floor + 1;
    return floor % 2 === 0 ? floor : floor + 1;
}
// Converts stream items. One converter per stream: create a new one after each START, because the stamp
// restarts at 0. rateHz is the nominal frames per second per plate (setRate). When it is null the period is
// learnt as the smallest step seen per plate, which is right once two consecutive frames arrived without a hole.
export class SampleConverter {
    #period;
    #copMinFzN;
    #last = new Map();
    #learnt = new Map();
    #high = 0;
    #previousWire = 0;
    #placeholders = 0;
    // Every gap found so far, in order.
    gaps = [];
    constructor(rateHz = null, options = {}) {
        this.#period = rateHz ? TICKS_PER_SECOND / rateHz : null;
        this.#copMinFzN = options.copMinFzN ?? COP_MIN_FZ_N;
    }
    // Stamp-0 frames counted and dropped (START sends two).
    get placeholders() {
        return this.#placeholders;
    }
    // Unwraps the uint32 stamp. A jump back by more than half the range is a wrap, not disorder.
    #unwrap(stamp) {
        if (stamp < this.#previousWire && this.#previousWire - stamp > STAMP_MODULUS / 2) {
            this.#high += STAMP_MODULUS;
        }
        this.#previousWire = stamp;
        return this.#high + stamp;
    }
    // Converts one item. Returns nothing for a placeholder, and a Gap before the Sample after a hole.
    push(item) {
        if (item.kind === 'event') {
            const stamp = this.#unwrap(item.event.timeStamp);
            return [
                {
                    kind: 'event',
                    t: stamp / TICKS_PER_SECOND + item.event.offsetUs / 1_000_000,
                    type: item.event.eventType,
                    name: eventName(item.event.eventType),
                    source: item.event.source,
                    count: item.event.count,
                    detail: item.event.detail,
                    stamp,
                    offset_us: item.event.offsetUs,
                },
            ];
        }
        const frame = item.frame;
        if (frame.timeStamp === 0) {
            this.#placeholders++;
            return [];
        }
        const stamp = this.#unwrap(frame.timeStamp);
        const plate = frame.platformAddress;
        const out = [];
        const last = this.#last.get(plate);
        if (last !== undefined) {
            const step = stamp - last;
            if (step > 0 && this.#period === null) {
                this.#learnt.set(plate, Math.min(step, this.#learnt.get(plate) ?? step));
            }
            const period = this.#period ?? this.#learnt.get(plate) ?? null;
            if (period !== null && period > 0 && step > GAP_FACTOR * period) {
                const gap = {
                    kind: 'gap',
                    plate,
                    start_t: last / TICKS_PER_SECOND,
                    end_t: stamp / TICKS_PER_SECOND,
                    missing: roundHalfEven(step / period) - 1,
                };
                this.gaps.push(gap);
                out.push(gap);
            }
        }
        this.#last.set(plate, stamp);
        // "+ 0" turns a signed zero into +0, as Python's float(0) does.
        const signed = (index, value) => (STREAM_SIGN[index] ?? 1) * value + 0;
        const fx = signed(0, frame.forceX);
        const fy = signed(1, frame.forceY);
        const fz = signed(2, frame.forceZ);
        const mx = signed(3, frame.momentX);
        const my = signed(4, frame.momentY);
        const mz = signed(5, frame.momentZ);
        const [copX, copY] = plateCop(fx, fy, fz, mx, my, this.#copMinFzN);
        out.push({
            kind: 'sample',
            t: stamp / TICKS_PER_SECOND,
            plate,
            fx,
            fy,
            fz,
            mx,
            my,
            mz,
            cop_x: copX,
            cop_y: copY,
            stamp,
            raw: [frame.forceX, frame.forceY, frame.forceZ, frame.momentX, frame.momentY, frame.momentZ],
        });
        return out;
    }
    // Converts a sequence of items, in order.
    *convert(items) {
        for (const item of items)
            yield* this.push(item);
    }
}
// Sum of the plates of one instant in the pair frame: forces add, moments move to the pair origin
// (M + r x F with r = (cx, 0, 0), cx = -0.175 m for plate 1 and +0.175 m for plate 2). The combined CoP
// follows from the combined wrench like a plate's, so a lightly loaded plate still counts.
// Measured against the 14 Oct 2026 export: comb_ moments within 0.004 N*m rms (docs/19 section 3).
export function combine(samples, copMinFzN = COP_MIN_FZ_N) {
    let fx = 0;
    let fy = 0;
    let fz = 0;
    let mx = 0;
    let my = 0;
    let mz = 0;
    for (const [plate, sample] of samples) {
        const cx = PAIR_CENTRE_X_M[plate] ?? 0;
        fx += sample.fx;
        fy += sample.fy;
        fz += sample.fz;
        mx += sample.mx;
        my += sample.my - cx * sample.fz;
        mz += sample.mz + cx * sample.fy;
    }
    const [copX, copY] = plateCop(fx, fy, fz, mx, my, copMinFzN);
    return { fx, fy, fz, mx, my, mz, cop_x: copX, cop_y: copY };
}
