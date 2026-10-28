function [x, y] = plateCop(fx, fy, fz, mx, my, minFz)
%PLATECOP Centre of pressure of one F1-3D plate in m, from the plate centre, from its own forces and moments.
%   [X, Y] = movetrics.plateCop(FX, FY, FZ, MX, MY) with the Studio export columns of one plate (N, N*m).
%   x = (-My - d*Fx) / Fz and y = (-Mx + d*Fy) / Fz, with d = 0.030 m, the depth of the moment reference below
%   the top surface. This reproduces Studio's own CoP columns to 0.28 mm rms (their 1 mm rounding) on the
%   14 Oct 2026 export, and the C3D FORCE_PLATFORM ORIGIN states the same 30 mm. NaN where Fz < MINFZ
%   (default 50 N, Studio's CopForceThreshold). For the raw FDT stream, see docs/18-export-formats.md: the
%   stream's Fy and Mx have the opposite sign to the export.
if nargin < 6, minFz = 50; end
d = 0.030;
x = (-my - d .* fx) ./ fz;
y = (-mx + d .* fy) ./ fz;
low = fz < minFz;
x(low) = NaN;
y(low) = NaN;
end
