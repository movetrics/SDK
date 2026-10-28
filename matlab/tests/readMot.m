function [header, data] = readMot(path)
%READMOT Read an OpenSim .mot written by movetrics.writeMot or movetrics_fdt.writers.write_mot.
%   [HEADER, DATA] = readMot(PATH): HEADER is a cell row of column names, DATA the numeric rows.
lines = strsplit(fileread(path), char(10));
header = strsplit(lines{7}, char(9));
rows = lines(8:end);
rows = rows(~cellfun(@isempty, rows));
data = zeros(numel(rows), numel(header));
for k = 1:numel(rows)
    data(k, :) = sscanf(rows{k}, '%f')';
end
end
