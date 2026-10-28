function [out, gaps, state] = convertFrames(frames, state, rateHz)
%CONVERTFRAMES Wire frames to the shared vocabulary (docs/19-vocabulary-and-units.md): plate frame, SI units, CoP.
%   [OUT, GAPS, STATE] = movetrics.convertFrames(FRAMES, STATE, RATEHZ)
%   FRAMES is the struct from movetrics.decodeStream (wire int16 values, ticks as uint32). Placeholders with
%   ticks == 0 are dropped. OUT has one row per sample, in arrival order, with the columns:
%     plate            1 or 2
%     ticks, time_s   FDT stamp in 0.1 ms ticks (unwrapped past 2^32, as double) and t = ticks / 10,000 s
%     t               vocabulary name of time_s
%     fx fy fz        N, plate frame: fx = +forceX, fy = -forceY, fz = +forceZ (Studio's QuadrantTransform 4,3,2,1)
%     mx my mz        N*m, plate frame: mx = -momentX, my = +momentY, mz = +momentZ
%     cop_x cop_y     m from the plate centre, NaN below 50 N (movetrics.plateCop)
%     raw             N x 6 wire values in wire order: forceX forceY forceZ momentX momentY momentZ
%   GAPS is a struct array (sorted by end_t): plate, start_t, end_t, missing. A gap is a step longer than 1.5
%   nominal periods between consecutive samples of one plate. Gaps are reported, never filled.
%   RATEHZ is the nominal frames/s per plate; [] learns the period as the smallest step seen per plate.
%   STATE carries the last tick per plate and the learnt period between calls on one stream: pass [] at the start
%   of each stream (after each START) and the STATE returned by the previous call after that.
if nargin < 2 || isempty(state)
    state = struct('last', [NaN NaN], 'learnt', [NaN NaN], 'high', 0, 'prevWire', 0);
end
if ~isfield(state, 'high'), state.high = 0; state.prevWire = 0; end
if nargin < 3, rateHz = []; end
keep = frames.ticks ~= 0;
out.plate = frames.plate(keep);
% The wire stamp is uint32 (wraps after 4.97 days); a jump back by more than half the range is a wrap, not disorder.
wire = double(frames.ticks(keep));
ticks = zeros(size(wire));
for j = 1:numel(wire)
    if wire(j) < state.prevWire && state.prevWire - wire(j) > 2^31
        state.high = state.high + 2^32;
    end
    state.prevWire = wire(j);
    ticks(j) = state.high + wire(j);
end
out.ticks = ticks;
out.time_s = out.ticks / 10000;
out.t = out.time_s;
raw = [frames.fx(keep), frames.fy(keep), frames.fz(keep), frames.mx(keep), frames.my(keep), frames.mz(keep)];
out.raw = raw;
plateValues = raw .* [1 -1 1 -1 1 1];            % STREAM_SIGN: Studio's plate frame
out.fx = plateValues(:, 1); out.fy = plateValues(:, 2); out.fz = plateValues(:, 3);
out.mx = plateValues(:, 4); out.my = plateValues(:, 5); out.mz = plateValues(:, 6);
[out.cop_x, out.cop_y] = movetrics.plateCop(out.fx, out.fy, out.fz, out.mx, out.my, 50);

plate = []; startT = []; endT = []; missing = [];
for p = [1 2]
    idx = find(out.plate == p);
    if isempty(idx), continue; end
    tk = out.ticks(idx);
    if isnan(state.last(p))
        seq = tk;
    else
        seq = [state.last(p); tk];
    end
    if numel(seq) > 1
        step = diff(seq);
        positive = step(step > 0);
        if ~isempty(positive)
            state.learnt(p) = min([state.learnt(p), min(positive)]);
        end
        if isempty(rateHz)
            period = state.learnt(p);
        else
            period = 10000 / rateHz;
        end
        for j = find(step > 1.5 * period)'
            plate(end + 1, 1) = p; %#ok<AGROW>
            startT(end + 1, 1) = seq(j) / 10000; %#ok<AGROW>
            endT(end + 1, 1) = seq(j + 1) / 10000; %#ok<AGROW>
            missing(end + 1, 1) = round(step(j) / period) - 1; %#ok<AGROW>
        end
    end
    state.last(p) = tk(end);
end
[~, order] = sort(endT);
gaps = struct('plate', num2cell(plate(order)), 'start_t', num2cell(startT(order)), ...
              'end_t', num2cell(endT(order)), 'missing', num2cell(missing(order)));
gaps = gaps(:);
if isempty(gaps)
    gaps = struct('plate', cell(0, 1), 'start_t', cell(0, 1), 'end_t', cell(0, 1), 'missing', cell(0, 1));
end
end
