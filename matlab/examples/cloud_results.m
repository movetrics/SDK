% Read results and raw samples from the Movetrics Cloud. Create a token in the Cloud (Account > Access tokens)
% and set it outside the script, for example setenv("MOVETRICS_TOKEN", "mvt_...") in your startup.m.
addpath(fullfile(fileparts(mfilename('fullpath')), '..'));
cloud = movetrics.Cloud(getenv("MOVETRICS_TOKEN"));
results = cloud.results("since", "2026-10-01");     % one row per result, with method and engine version
disp(results(1:min(10, height(results)), {'recorded_at', 'movement', 'label', 'value', 'unit', 'method_version'}));
recs = cloud.recordings("since", "2026-10-01");
s = cloud.samples(recs(1).id);                        % every stored channel, unfiltered
disp(s.names');
