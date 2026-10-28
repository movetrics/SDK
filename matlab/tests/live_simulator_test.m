% movetrics.Fdt against the SDK simulator (python3 -m movetrics_fdt simulate --pty LINK --profile sync). No hardware.
% Needs a serial port class: MATLAB R2019b+, or GNU Octave with the instrument-control package (pkg load
% instrument-control). Run from sdk/matlab:  octave --eval "run tests/live_simulator_test.m"
here = fileparts(mfilename('fullpath'));
addpath(fileparts(here));
if exist('OCTAVE_VERSION', 'builtin'), pkg load instrument-control, end
m = movetrics.syncModes();
passed = 0;

% 1. Sync firmware: setRate, setSyncMode (ACK), a stream with no events and no gaps.
[link, pid] = startSimulator('sync');
cleanup = onCleanup(@() stopSimulator(pid, link));
fdt = movetrics.Fdt(link, 115200);
assert(strcmp(fdt.firmware, '1.2.8.24-SYNC'));
fdt.setRate(2000, 0);
fdt.setSyncMode(m.EVENT_FRAMES);
fdt.start();
data = fdt.read(1.0);
fdt.stop();
clear fdt
n1 = sum(data.plate == 1);
assert(n1 > 1500 && all(diff(data.ticks(data.plate == 1)) == 5));   % 2,000 frames/s = 5 ticks of 0.1 ms
assert(isempty(data.gaps) && isempty(data.events));
passed = passed + 3;
clear cleanup

% 2. Events: armed by SYNC IN (START_ON_RISE), the simulator's SYNC IN pulses every 0.4 s.
[link, pid] = startSimulator('sync', '--sync-pulse-s 0.4');
cleanup = onCleanup(@() stopSimulator(pid, link));
fdt = movetrics.Fdt(link, 115200);
fdt.setRate(2000, 0);
fdt.setSyncMode(bitor(m.START_ON_RISE, m.EVENT_FRAMES));
fdt.start();
data = fdt.read(2.0);
fdt.stop();
clear fdt
names = {data.events.name};
assert(any(strcmp(names, 'stream_armed')) && any(strcmp(names, 'stream_started_by_trigger')));
assert(any(strcmp(names, 'sync_in_rise')) && any(strcmp(names, 'sync_in_fall')));
assert(all(diff([data.events.t]) >= 0));
passed = passed + 4;
clear cleanup

% 3. Firmware without sync modes: NACK 7 raises an error that says so.
[link, pid] = startSimulator('1.2.8.20');
cleanup = onCleanup(@() stopSimulator(pid, link));
fdt = movetrics.Fdt(link, 115200);
threw = false;
try
    fdt.setSyncMode(m.EVENT_FRAMES);
catch err
    threw = ~isempty(strfind(err.message, 'no sync modes'));  %#ok<STREMP>
end
assert(threw);
passed = passed + 1;
clear fdt cleanup

fprintf('%d live simulator checks passed\n', passed);
