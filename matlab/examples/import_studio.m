% Import a Movetrics Studio export (CSV, with its -details.csv partner) and plot force and centre of pressure.
addpath(fullfile(fileparts(mfilename('fullpath')), '..'));
rec = movetrics.readStudioCsv('2026-10-14_09_10_50_000_-_Exam-channels.csv');   % your file
fprintf('%s, %.0f rows/s, %d gap(s)\n', rec.details.Exam_Type, rec.rateHz, size(rec.gaps, 1));
subplot(2, 1, 1);
plot(rec.time_s, [rec.data.p1_ForceZ, rec.data.p2_ForceZ, rec.data.comb_ForceZ]);
ylabel('Fz (N)'); legend('plate 1', 'plate 2', 'combined');
% CoP of plate 1 from its forces and moments (works on older exports without CoP columns too).
d = rec.data;
[x, y] = movetrics.plateCop(d.p1_ForceX, d.p1_ForceY, d.p1_ForceZ, d.p1_MomentX, d.p1_MomentY);
subplot(2, 1, 2);
plot(1000 * x, 1000 * y); axis equal; xlabel('CoP x (mm from plate centre)'); ylabel('CoP y (mm)');
% The same exam as C3D (needs ezc3d): c3d = movetrics.readStudioC3d('...-Exam.c3d');
