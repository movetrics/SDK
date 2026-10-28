function writeMot(path, t, plates, minFz)
%WRITEMOT Write an OpenSim external-loads file (.mot) from per-plate samples, in the shared vocabulary.
%   movetrics.writeMot(PATH, T, PLATES)            % minFz defaults to 20 N
%   movetrics.writeMot(PATH, T, PLATES, MINFZ)
%   T is the time column in s (the FDT clock). PLATES is a struct array, one element per plate (1 or 2), with fields
%   plate, fx, fy, fz (N), mx, my, mz (N*m), each a column the length of T, in the plate frame (the values
%   movetrics.readStudioCsv returns as data.p1_ForceX etc., or movetrics.convertFrames returns). NaN is allowed.
%   Columns: time, then per plate n: n_ground_force_vx/vy/vz, n_ground_force_px/py/pz, n_ground_torque_x/y/z.
%   OpenSim's ground frame (Y up): X = lab x, Y = lab z, Z = -lab y; metres and newtons. The point is the CoP in
%   the lab, the torque the free moment about the vertical through the CoP: Tz = Mz - (x*Fy - y*Fx).
%   Plate centres in the lab (Studio's layout, docs/18): plate 1 (0.175, 0.300) m, plate 2 (0.525, 0.300) m.
%   Below MINFZ a plate's force and torque are 0 and its point is the plate centre.
%   A recording with a gap is refused (error movetrics:writeMot:gap): OpenSim needs a uniform clock, and this writer
%   does not resample or split. Matches movetrics_fdt.writers.write_mot on the same input (tests/run_tests.m).
if nargin < 4, minFz = 20; end
t = t(:);
n = numel(t);
if n == 0
    error('movetrics:writeMot', 'There are no samples to write.');
end
if n > 1
    dt = diff(t);
    period = median(dt);
    if any(dt > 1.5 * period)
        error('movetrics:writeMot:gap', ['The recording has a gap (%d step(s) longer than 1.5 periods). OpenSim needs ' ...
              'a uniform clock: split the recording at the gap first.'], nnz(dt > 1.5 * period));
    end
end
centres = struct('plate', {1, 2}, 'xy', {[0.175 0.300], [0.525 0.300]});
[~, order] = sort([plates.plate]);
plates = plates(order);
header = {'time'};
block = zeros(n, 1 + 9 * numel(plates));
block(:, 1) = t - t(1);
for k = 1:numel(plates)
    p = plates(k);
    if ~any([centres.plate] == p.plate)
        error('movetrics:writeMot', 'No layout for plate %d (the Studio layout has plates 1 and 2).', p.plate);
    end
    c = centres([centres.plate] == p.plate).xy;
    for name = {'fx', 'fy', 'fz', 'mx', 'my', 'mz'}
        if numel(p.(name{1})) ~= n
            error('movetrics:writeMot', 'plate %d %s has %d values, the time column has %d.', p.plate, name{1}, numel(p.(name{1})), n);
        end
    end
    fx = p.fx(:); fy = p.fy(:); fz = p.fz(:); mx = p.mx(:); my = p.my(:); mz = p.mz(:);
    [x, y] = movetrics.plateCop(fx, fy, fz, mx, my, minFz);
    tz = mz - (x .* fy - y .* fx);
    low = isnan(fz) | isnan(x) | fz < minFz;
    % Columns: force v (lab x, lab z, -lab y), point (centre + CoP, 0, -(centre + CoP)), torque (0, Tz, 0).
    cols = [fx, fz, -fy, c(1) + x, zeros(n, 1), -(c(2) + y), zeros(n, 1), tz, zeros(n, 1)];
    cols(low, :) = repmat([0 0 0 c(1) 0 -c(2) 0 0 0], nnz(low), 1);
    block(:, 2 + 9 * (k - 1):1 + 9 * k) = cols;
    header = [header, {sprintf('%d_ground_force_vx', p.plate), sprintf('%d_ground_force_vy', p.plate), ...
                       sprintf('%d_ground_force_vz', p.plate), sprintf('%d_ground_force_px', p.plate), ...
                       sprintf('%d_ground_force_py', p.plate), sprintf('%d_ground_force_pz', p.plate), ...
                       sprintf('%d_ground_torque_x', p.plate), sprintf('%d_ground_torque_y', p.plate), ...
                       sprintf('%d_ground_torque_z', p.plate)}]; %#ok<AGROW>
end
[~, stem] = fileparts(path);
fid = fopen(path, 'w');
if fid < 0, error('movetrics:writeMot', 'Cannot write %s', path); end
cleaner = onCleanup(@() fclose(fid));
fprintf(fid, '%s\nversion=1\nnRows=%d\nnColumns=%d\ninDegrees=yes\nendheader\n', stem, n, numel(header));
fprintf(fid, '%s\n', strjoin(header, sprintf('\t')));
fmt = [repmat('%.6f\t', 1, size(block, 2) - 1), '%.6f\n'];
fprintf(fid, fmt, block');
end
