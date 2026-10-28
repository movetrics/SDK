% Host tests of the MATLAB toolbox. Run from sdk/matlab in MATLAB or GNU Octave:  run tests/run_tests.m
% They use the SDK's byte vectors (sdk/vectors, python/tests/fixtures/sync_events.json) and excerpts of a
% real Studio export (python/tests/fixtures). No FDT, no serial port and no network are needed: the live FDT
% parts use tests/MockSerialPort, and the Python reference .mot is written by tests/mot_reference.py (python3).
% Set MOVETRICS_TEST_BASE to a stand-in API (matlab/tests/mock_api.py) to also test movetrics.Cloud.
here = fileparts(mfilename('fullpath'));
addpath(fileparts(here));
addpath(here);
fixtures = fullfile(here, '..', '..', 'python', 'tests', 'fixtures');
hex = @(s) uint8(sscanf(s, '%2x')');
passed = 0;

% CRC-16/CCITT-FALSE: published check value and the identification probe (vectors/crc16.json).
assert(movetrics.crc16(uint8('123456789')) == hex2dec('29B1'));
assert(movetrics.crc16([]) == hex2dec('FFFF'));
passed = passed + 2;

% Host commands: the probe, START, STOP and the SET_FILTER frames the bench tools send.
assert(isequal(movetrics.hostCommand(35, 0, 0), hex('feed0000239dd80404')));
assert(isequal(movetrics.hostCommand(1, 255, 255), hex('feedffff0121100404')));
assert(isequal(movetrics.hostCommand(5, 255, 0), hex('feedff00055a530404')));
f = movetrics.hostCommand(28, 0, 0, [0, 208, 7]);                % 2,000 frames/s, raw
assert(isequal(f(1:8), hex('feed00001c00d007')) && movetrics.crc16(f(3:8)) == double(f(9)) + 256 * double(f(10)));
threw = false;
try, movetrics.hostCommand(28, 0, 0, [0, 4, 4]); catch, threw = true; end   % rate 1028 = 04 04
assert(threw);
passed = passed + 5;

% SET_SYNC_MODE 0x28 frames, checked against the Python SDK (encode_host_frame(0x28, 0, 0, payload)).
assert(isequal(movetrics.hostCommand(40, 0, 0, [8 0 0 0 0 0]), hex('feed0000280800000000006be80404')));
assert(isequal(movetrics.hostCommand(40, 0, 0, [9 250 0 5 5 30]), hex('feed00002809fa0005051ec9330404')));
passed = passed + 2;

% Stream frames (vectors/stream_frames.json): fields, a placeholder, garbage, an ACK in between, a split.
a = hex('beef010100000000f9ff06000700000000000000189e0404');           % plate 1, ticks 0 (placeholder)
b = hex('beef0101850d0300deff00000500ffff00000200b7d30404');           % plate 1, ticks 200069
c = hex('beef020143fa01000d00dfffffffffffffff0000c40b0404');           % plate 2
ack = uint8([190 239 0 28 6 0 0 4 4]);
k = movetrics.crc16(ack(3:5)); ack(6:7) = [bitand(k, 255), bitshift(k, -8)];
[fr, rest, replies] = movetrics.decodeStream([uint8([1 2 190]), a, ack, b, c(1:10)]);
assert(isequal(fr.plate', [1 1]) && isequal(fr.ticks', [0 200069]));
assert(isequal([fr.fx(2) fr.fy(2) fr.fz(2) fr.mx(2) fr.my(2) fr.mz(2)], [-34 0 5 -1 0 2]));
assert(isequal(replies, [0 28 6 0]));
assert(isequal(rest, c(1:10)));
[fr2, rest2] = movetrics.decodeStream([rest, c(11:end)]);
assert(isequal(fr2.plate, 2) && isempty(rest2));
bad = b; bad(9) = bitxor(bad(9), 1);
fr3 = movetrics.decodeStream(bad);
assert(isempty(fr3.plate));
passed = passed + 7;

% Stream frame helper against the Python frame of the same values (encode_stream_frame, SDK doc 05).
assert(isequal(MockSerialPort.streamFrame(1, 200069, [-34 0 5 -1 0 2]), b));
assert(isequal(MockSerialPort.streamFrame(1, 200069, [-48 -6 404 20 18 -2]), hex('beef0101850d0300d0fffaff940114001200feff49730404')));
passed = passed + 2;

% Event frames (sync layout, docs/05 section 13): every sync-event case of the golden vectors decodes to its fields.
vec = jsondecode(fileread(fullfile(fixtures, 'sync_events.json')));
nEvents = 0;
for k = 1:numel(vec.cases)
    if iscell(vec.cases), cs = vec.cases{k}; else, cs = vec.cases(k); end
    if ~strncmp(cs.id, 'sync-event', 10), continue; end
    [~, ~, ~, ev] = movetrics.decodeStream(hex(cs.frame_hex));
    fl = cs.fields;
    assert(numel(ev) == 1, ['one event frame expected in ' cs.id]);
    assert(ev.stamp == fl.stamp && ev.type == fl.type && ev.source == fl.source && ev.count == fl.counter, cs.id);
    assert(ev.offset_us == fl.offset_us && ev.detail == fl.detail && ev.mode == fl.mode, cs.id);
    assert(abs(ev.t - (fl.stamp / 1e4 + fl.offset_us / 1e6)) < 1e-12, cs.id);
    assert(~strncmp(ev.name, 'unknown', 7), cs.id);
    nEvents = nEvents + 1;
end
assert(nEvents == 11);   % sync-event-* cases of sync_events.json (13 cases in all, 2 are 0x29 replies)
passed = passed + 2;
badEv = hex('beeffd0e0000000006000100000025000000190037e10404'); badEv(9) = bitxor(badEv(9), 1);
[~, ~, ~, evBad] = movetrics.decodeStream(badEv);
assert(isempty(evBad));                                                     % a CRC error is not an event
[sf, ~, ~, es] = movetrics.decodeStream([a, hex('beeffd0e0000000006000100000025000000190037e10404'), b]);
assert(numel(sf.plate) == 2 && numel(es) == 1 && es(1).type == 6);          % frames and events kept apart
passed = passed + 3;

% Sync modes: the six bits of SET_SYNC_MODE (sdk/python client.SyncMode).
m = movetrics.syncModes();
assert(m.START_ON_RISE == 1 && m.STOP_ON_FALL == 2 && m.MASTER_OUT == 4 && m.EVENT_FRAMES == 8);
assert(m.PULSE_TRAIN == 16 && m.SATURATION_EVENTS == 32);
passed = passed + 2;

% Vocabulary (docs/19): wire values to the plate frame, CoP, placeholders dropped. The expected numbers are
% movetrics_fdt.vocabulary.SampleConverter on StreamFrame(1,1,200069,-48,-6,404,20,18,-2) and (2,1,200069,-40,5,20,-7,9,3).
hex1 = hex('beef0101850d0300d0fffaff940114001200feff49730404');
hex2 = hex('beef0201850d0300d8ff05001400f9ff090003004b2d0404');
[v, gaps] = movetrics.convertFrames(movetrics.decodeStream([a, hex1, hex2]), [], []);
assert(isequal(v.plate, [1; 2]) && isempty(gaps));
assert(isequal(v.fx, [-48; -40]) && isequal(v.fy, [6; -5]) && isequal(v.fz, [404; 20]));
assert(isequal(v.mx, [-20; 7]) && isequal(v.my, [18; 9]) && isequal(v.mz, [-2; 3]));
assert(isequal(v.raw(1, :), [-48 -6 404 20 18 -2]));
assert(abs(v.cop_x(1) - (-0.040990099009900985)) < 1e-12 && abs(v.cop_y(1) - 0.04995049504950495) < 1e-12);
assert(isnan(v.cop_x(2)) && isnan(v.cop_y(2)));           % plate 2 at 20 N: no CoP below 50 N
assert(abs(v.t(1) - 20.0069) < 1e-9 && abs(v.time_s(1) - v.t(1)) == 0);
passed = passed + 8;

% Gaps: a fixed rate, a learnt period, and a gap that straddles two calls (SampleConverter gives the same numbers).
mk = @(t) struct('plate', ones(numel(t), 1), 'ticks', t(:), 'fx', zeros(numel(t), 1), 'fy', zeros(numel(t), 1), ...
                 'fz', zeros(numel(t), 1), 'mx', zeros(numel(t), 1), 'my', zeros(numel(t), 1), 'mz', zeros(numel(t), 1));
[~, g] = movetrics.convertFrames(mk([10000; 10005; 10030]), [], 2000);
assert(numel(g) == 1 && g.plate == 1 && abs(g.start_t - 1.0005) < 1e-12 && abs(g.end_t - 1.003) < 1e-12 && g.missing == 4);
[~, g] = movetrics.convertFrames(mk([10000; 10005; 10010; 10040]), [], []);
assert(numel(g) == 1 && abs(g.start_t - 1.001) < 1e-12 && abs(g.end_t - 1.004) < 1e-12 && g.missing == 5);
[~, g1, st] = movetrics.convertFrames(mk([10000; 10005]), [], 2000);
[~, g2] = movetrics.convertFrames(mk([10030]), st, 2000);
assert(isempty(g1) && numel(g2) == 1 && g2.missing == 4 && abs(g2.start_t - 1.0005) < 1e-12);
passed = passed + 3;

% writeMot: the Python reference on the Studio start export (no gap). Rows must match within 1e-6.
studio = fullfile(fixtures, 'studio-2026-10-14-start-channels.csv');
s = movetrics.readStudioCsv(studio);
d = s.data;
plates = struct('plate', {1, 2}, 'fx', {d.p1_ForceX, d.p2_ForceX}, 'fy', {d.p1_ForceY, d.p2_ForceY}, ...
                'fz', {d.p1_ForceZ, d.p2_ForceZ}, 'mx', {d.p1_MomentX, d.p2_MomentX}, ...
                'my', {d.p1_MomentY, d.p2_MomentY}, 'mz', {d.p1_MomentZ, d.p2_MomentZ});
dirA = tempname(); mkdir(dirA);
dirB = tempname(); mkdir(dirB);
mine = fullfile(dirA, 'start.mot');
movetrics.writeMot(mine, s.time_s, plates);
ref = fullfile(dirB, 'start.mot');
[status, out] = system(sprintf('python3 "%s" "%s" "%s"', fullfile(here, 'mot_reference.py'), studio, ref));
if status ~= 0
    error('movetrics:test', 'the Python reference failed (python3 needed): %s', out);
end
[hMine, dMine] = readMot(mine);
[hRef, dRef] = readMot(ref);
assert(isequal(hMine, hRef) && isequal(size(dMine), size(dRef)) && size(dMine, 1) == 200);
assert(max(abs(dMine(:) - dRef(:))) < 1e-6);
assert(strcmp(hMine{2}, '1_ground_force_vx') && strcmp(hMine{end}, '2_ground_torque_z'));
passed = passed + 4;

% writeMot: a gap is refused; a plate below 20 N gets zero force and torque at its centre (plate 1: 0.175, 0.300 m).
threw = '';
try
    movetrics.writeMot(fullfile(dirA, 'gap.mot'), [0; 0.001; 0.002; 0.010], plates(1));
catch err
    threw = err.identifier;
end
assert(strcmp(threw, 'movetrics:writeMot:gap'));
low = struct('plate', 1, 'fx', [1; 10], 'fy', [2; 20], 'fz', [5; 500], 'mx', [0; 0], 'my', [0; 0], 'mz', [0; 0]);
movetrics.writeMot(fullfile(dirA, 'low.mot'), [0; 0.001], low);
[~, dl] = readMot(fullfile(dirA, 'low.mot'));
assert(max(abs(dl(1, :) - [0 0 0 0 0.175 0 -0.300 0 0 0])) < 1e-9);
assert(max(abs(dl(2, :) - [0.001 10 500 -20 0.1744 0 -0.3012 0 0.024 0])) < 1e-9);
passed = passed + 2;

% Fdt against the mock port: the commands it sends, the replies it must raise on, and read() of the vocabulary.
port = MockSerialPort();
fdt = movetrics.Fdt(port);
assert(strcmp(fdt.firmware, '1.2.8.24-SYNC'));
fdt.setRate(2000, 0);
assert(isequal(port.written{end}, movetrics.hostCommand(28, 0, 0, [0 208 7])));
fdt.setSyncMode(m.EVENT_FRAMES);
assert(isequal(port.written{end}, hex('feed0000280800000000006be80404')));
fdt.setSyncMode(bitor(m.START_ON_RISE, m.EVENT_FRAMES), 250, 5, 5, 30);
assert(isequal(port.written{end}, hex('feed00002809fa0005051ec9330404')));
passed = passed + 3;
errs = {};
port.syncSupported = false;
try, fdt.setSyncMode(8); catch err, errs{end + 1} = err; end
port.syncSupported = true;
port.syncNack = 3;
try, fdt.setSyncMode(8); catch err, errs{end + 1} = err; end
port.syncNack = 8;
try, fdt.setSyncMode(8); catch err, errs{end + 1} = err; end
port.syncNack = 0;
assert(numel(errs) == 3 && all(strcmp(cellfun(@(e) e.identifier, errs, 'UniformOutput', false), 'movetrics:Fdt')));
assert(~isempty(strfind(errs{1}.message, 'no sync modes')) && ~isempty(strfind(errs{2}.message, 'NACK 3')));  %#ok<STREMP>
assert(~isempty(strfind(errs{3}.message, 'NACK 8')));  %#ok<STREMP>
passed = passed + 3;

fdt.start();
port.queue([a, b, hex('beeffd0e0000000006000100000025000000190037e10404')]);
data = fdt.read(0.05);
fdt.stop();
assert(isequal(data.plate, 1) && isequal(data.ticks, 200069) && isequal(data.raw, [-34 0 5 -1 0 2]));
assert(data.fx == -34 && data.fy == 0 && data.mx == 1 && data.my == 0 && data.mz == 2 && data.fz == 5);
assert(isnan(data.cop_x) && abs(data.t - 20.0069) < 1e-9 && isempty(data.gaps));
assert(numel(data.events) == 1 && strcmp(data.events(1).name, 'stream_started_by_trigger'));
assert(abs(data.events(1).t - 37e-6) < 1e-12 && data.events(1).source == 0 && data.events(1).offset_us == 37);
passed = passed + 4;

% The gap test through read(): 2,000 frames/s, a 30-tick hole (missing 5 periods) inside one stream.
fdt.setRate(2000, 0);
fdt.start();
port.queue([MockSerialPort.streamFrame(1, 200069, zeros(1, 6)), ...
            MockSerialPort.streamFrame(1, 200074, zeros(1, 6)), ...
            MockSerialPort.streamFrame(1, 200104, zeros(1, 6))]);
data = fdt.read(0.05);
fdt.stop();
assert(numel(data.gaps) == 1 && data.gaps(1).missing == 5 && abs(data.gaps(1).start_t - 20.0074) < 1e-9);
assert(numel(data.plate) == 3);
passed = passed + 2;
clear fdt

% Cloud API against the stand-in server, when it runs.
base = getenv('MOVETRICS_TEST_BASE');
if ~isempty(base)
    cloud = movetrics.Cloud('mvt_test', base);
    recs = cloud.recordings();
    assert(numel(recs) == 2 && strcmp(recs(1).id, 'r2'));
    smp = cloud.samples('r1', {'c3d-analog-15-comb_ForceZ'});
    assert(numel(smp.time_s) == 250000 && smp.data.c3d_analog_15_comb_ForceZ(end) == 249999);
    assert(strcmp(smp.names{1}, 'c3d-analog-15-comb_ForceZ'));
    res = cloud.results();
    passed = passed + 3;
else
    disp('Cloud tests skipped (MOVETRICS_TEST_BASE not set)');
end
% Vocabulary vectors (vectors/vocabulary.json, contract K4): the same frames give the same samples, gaps and
% events as in every other client. Expected values come from the contract's formulas, not from Python.
voc = jsondecode(fileread(fullfile(fileparts(fileparts(mfilename('fullpath'))), '..', 'vectors', 'vocabulary.json')));
for k = 1:numel(voc.cases)
    vc = voc.cases(k);
    if iscell(voc.cases), vc = voc.cases{k}; end
    bytes = uint8([]);
    for f = 1:numel(vc.frames), bytes = [bytes, hex(vc.frames{f})]; end %#ok<AGROW>
    [fr, ~, ~, evs] = movetrics.decodeStream(bytes);
    if isempty(vc.rate_hz), rate = []; else, rate = vc.rate_hz; end
    [smp, gp] = movetrics.convertFrames(fr, [], rate);
    exp = vc.expected;
    if ~iscell(exp), exp = num2cell(exp); end
    kinds = cellfun(@(e) e.kind, exp, 'UniformOutput', false);
    es = exp(strcmp(kinds, 'sample')); eg = exp(strcmp(kinds, 'gap')); ee = exp(strcmp(kinds, 'event'));
    assert(numel(smp.t) == numel(es), [vc.id ': sample count']);
    for j = 1:numel(es)
        e = es{j};
        assert(smp.plate(j) == e.plate && smp.ticks(j) == e.stamp, [vc.id ': plate/stamp']);
        got = [smp.t(j) smp.fx(j) smp.fy(j) smp.fz(j) smp.mx(j) smp.my(j) smp.mz(j)];
        want = [e.t e.fx e.fy e.fz e.mx e.my e.mz];
        assert(all(abs(got - want) <= 1e-9), [vc.id ': values']);
        assert(isequal(double(smp.raw(j, :)), e.raw(:)'), [vc.id ': raw']);
        if isempty(e.cop_x)
            assert(isnan(smp.cop_x(j)) && isnan(smp.cop_y(j)), [vc.id ': CoP should be NaN']);
        else
            assert(abs(smp.cop_x(j) - e.cop_x) <= 1e-9 && abs(smp.cop_y(j) - e.cop_y) <= 1e-9, [vc.id ': CoP']);
        end
    end
    assert(numel(gp) == numel(eg), [vc.id ': gap count']);
    for j = 1:numel(eg)
        e = eg{j};
        assert(gp(j).plate == e.plate && gp(j).missing == e.missing, [vc.id ': gap']);
        assert(abs(gp(j).start_t - e.start_t) <= 1e-9 && abs(gp(j).end_t - e.end_t) <= 1e-9, [vc.id ': gap times']);
    end
    assert(numel(evs) == numel(ee), [vc.id ': event count']);
    for j = 1:numel(ee)
        e = ee{j};
        assert(abs(evs(j).t - e.t) <= 1e-9 && evs(j).type == e.type && strcmp(evs(j).name, e.name), [vc.id ': event']);
        assert(evs(j).source == e.source && evs(j).count == e.count && evs(j).detail == e.detail, [vc.id ': event fields']);
        assert(evs(j).offset_us == e.offset_us, [vc.id ': offset_us']);
    end
    passed = passed + 1;
end

fprintf('%d checks passed\n', passed);
