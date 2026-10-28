function details = readStudioDetails(path)
%READSTUDIODETAILS Read the Field,Value table of a Studio <stem>-details.csv into a struct.
%   Field names become valid MATLAB names ("Exam Type" -> Exam_Type); the original names are in .fields.
%   It holds personal data (subject name, date of birth, weight): keep it apart from anything you share.
text = fileread(path);
text = regexprep(text, ['^' char(239) char(187) char(191)], '');
lines = regexp(text, '\r?\n', 'split');
if isempty(lines) || ~strcmp(strtrim(lines{1}), 'Field,Value')
    error('movetrics:readStudioDetails', '%s is not a Studio details file (first row must be Field,Value).', path);
end
details = struct();
details.fields = {};
for k = 2:numel(lines)
    line = lines{k};
    if isempty(strtrim(line)), continue, end
    comma = find(line == ',', 1);
    if isempty(comma), key = line; value = ''; else, key = line(1:comma-1); value = line(comma+1:end); end
    value = regexprep(strtrim(value), '^"(.*)"$', '$1');
    name = regexprep(strtrim(key), '[^A-Za-z0-9]+', '_');
    name = regexprep(name, '^_+|_+$', '');
    if isempty(name) || ~isletter(name(1)), name = ['f_' name]; end
    details.(name) = value;
    details.fields{end + 1} = strtrim(key);
end
end
