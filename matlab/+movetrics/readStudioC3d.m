function rec = readStudioC3d(path)
%READSTUDIOC3D Read a Movetrics Studio .c3d export with ezc3d (https://github.com/pyomeca/ezc3d, MATLAB binding).
%   REC = movetrics.readStudioC3d(PATH): rateHz, time_s, data (fields p1_ForceX ... comb_MomentZ, N and N*m),
%   units, and forcePlatform (CORNERS and ORIGIN in mm: plate 1 from x 0 to 350, plate 2 from 350 to 700,
%   y 0 to 600, moment origin 30 mm below the top).
%   The C3D is written on a uniform grid (1,000 Hz in the 14 Oct 2026 export). A hole in the stream is not
%   visible here: after it, C3D time runs early by the hole's length (41 ms in that export). Use the CSV
%   (movetrics.readStudioCsv) when timing across a gap matters. The C3D has no CoP channels: use movetrics.plateCop.
if exist('ezc3dRead', 'file') ~= 2 && exist('ezc3dRead', 'file') ~= 3
    error('movetrics:readStudioC3d', 'Install ezc3d for MATLAB and add it to the path (ezc3dRead not found).');
end
c3d = ezc3dRead(path);
analog = c3d.parameters.ANALOG;
rec.rateHz = double(analog.RATE.DATA(1));
labels = strtrim(analog.LABELS.DATA);
units = strtrim(analog.UNITS.DATA);
values = c3d.data.analogs;                      % samples x channels
rec.time_s = (0:size(values, 1) - 1)' / rec.rateHz;
rec.data = struct();
rec.units = struct();
for k = 1:numel(labels)
    rec.data.(labels{k}) = double(values(:, k));
    rec.units.(labels{k}) = units{k};
end
rec.forcePlatform = struct();
if isfield(c3d.parameters, 'FORCE_PLATFORM')
    fp = c3d.parameters.FORCE_PLATFORM;
    rec.forcePlatform.CORNERS = double(fp.CORNERS.DATA);
    rec.forcePlatform.ORIGIN = double(fp.ORIGIN.DATA);
    rec.forcePlatform.CHANNEL = double(fp.CHANNEL.DATA);
end
end
