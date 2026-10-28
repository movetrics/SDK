function rec = readStudioCsv(path)
%READSTUDIOCSV Read a Movetrics Studio <stem>-channels.csv export.
%   REC = movetrics.readStudioCsv(PATH) returns a struct:
%     time_s     seconds from the first row, from the FDT clock (Timestamp / 10,000)
%     ticks      the Timestamp column: FDT ticks of 100 us since the stream started
%     data       struct with one field per Studio column (p1_ForceZ, comb_COPx, ...); empty cells are NaN
%     names      the column names in file order
%     rateHz     rows per second from the median step (500 or 1,000 in the exports seen so far)
%     gaps       [row, start_s, length_s] for every step longer than 1.5 times the usual one. The 14 Oct 2026
%                export has one 41 ms hole; the C3D of the same exam does not show it.
%     details    the partner <stem>-details.csv as a struct (movetrics.readStudioDetails), or [] when absent
%   Units: forces N, moments N*m, CoP m (per plate from the plate centre, comb from the middle between the
%   plates). Fz is vertical and positive under load. See docs/18-export-formats.md.
fid = fopen(path, 'r');
if fid < 0, error('movetrics:readStudioCsv', 'Cannot open %s', path); end
cleaner = onCleanup(@() fclose(fid));
header = strtrim(fgetl(fid));
header = regexprep(header, ['^' char(239) char(187) char(191)], '');  % UTF-8 byte order mark
names = strtrim(strsplit(header, ','));
if isempty(names) || ~strcmp(names{1}, 'Timestamp')
    error('movetrics:readStudioCsv', '%s is not a Studio channels file (first column must be Timestamp).', path);
end
pattern = '^(p1|p2|comb)_(ForceX|ForceY|ForceZ|MomentX|MomentY|MomentZ|COPx|COPy)$';
bad = names(2:end);
bad = bad(cellfun(@isempty, regexp(bad, pattern, 'once')));
if ~isempty(bad)
    error('movetrics:readStudioCsv', 'Unexpected Studio columns: %s', strjoin(bad, ', '));
end
columns = textscan(fid, repmat('%f', 1, numel(names)), 'Delimiter', ',', 'EmptyValue', NaN, 'ReturnOnError', false);
clear cleaner
rec.ticks = columns{1};
rec.time_s = (rec.ticks - rec.ticks(1)) / 10000;
rec.names = names;
rec.data = struct();
for k = 2:numel(names)
    rec.data.(names{k}) = columns{k};
end
steps = diff(rec.ticks);
usual = median(steps);
rec.rateHz = 10000 / usual;
long = find(steps > 1.5 * usual);
rec.gaps = [long + 1, rec.time_s(long), steps(long) / 10000];
partner = regexprep(path, '-channels\.csv$', '-details.csv');
if ~strcmp(partner, path) && exist(partner, 'file') == 2
    rec.details = movetrics.readStudioDetails(partner);
else
    rec.details = [];
end
end
