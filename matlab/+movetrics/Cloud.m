classdef Cloud
    %CLOUD Read your Movetrics Cloud data from MATLAB (read API v1, read only).
    %   Create an access token in the Cloud: Account > Access tokens. It starts with mvt_ and reads one
    %   workspace. Keep it out of scripts you share: put it in an environment variable.
    %
    %   cloud = movetrics.Cloud(getenv("MOVETRICS_TOKEN"));
    %   recs = cloud.recordings("since", "2026-10-01");    % struct array, newest first, with engine results
    %   s = cloud.samples(recs(1).id);                      % s.time_s, s.data.<column>, s.names (original ids)
    %   r = cloud.results();                                % table: one row per result, with method + version
    %
    %   Samples come out exactly as stored, unfiltered. Every result names its metric, method, method version
    %   and engine version. Reference: docs/18-export-formats.md (Cloud section).

    properties (SetAccess = private)
        baseUrl = 'https://beta.movetrics.com/api/v1'
    end
    properties (Access = private)
        options
    end
    properties (Constant)
        PAGE = 100000   % the server's largest sample page
    end

    methods
        function obj = Cloud(token, baseUrl)
            token = char(token);
            if ~strncmp(token, 'mvt_', 4)
                error('movetrics:Cloud', 'A Movetrics access token starts with mvt_ (Account > Access tokens).');
            end
            if nargin > 1, obj.baseUrl = char(baseUrl); end
            obj.options = weboptions('HeaderFields', {'Authorization', ['Bearer ' token]}, 'Timeout', 60, ...
                                     'ContentType', 'text');
        end

        function info = me(obj)
            info = jsondecode(obj.get('/me'));
        end

        function list = recordings(obj, varargin)
            % recordings("athlete_id", id, "since", "2026-10-01", "until", ...): every recording, newest first.
            list = [];
            cursor = '';
            while true
                query = [varargin, {'limit', '50'}];
                if ~isempty(cursor), query = [query, {'cursor', cursor}]; end %#ok<AGROW>
                page = jsondecode(obj.get('/recordings', query{:}));
                list = [list; movetrics.Cloud.asColumn(page.data)]; %#ok<AGROW>
                if isempty(page.next_cursor), break, end
                cursor = page.next_cursor;
            end
        end

        function rec = recording(obj, id)
            rec = jsondecode(obj.get(['/recordings/' char(id)]));
        end

        function s = samples(obj, id, channels)
            % samples(id) or samples(id, {"channel-id", ...}): every stored sample, pages joined. s.names holds
            % the channel ids as the API names them; s.data uses valid MATLAB names in the same order.
            info = obj.recording(id);
            total = info.samples.count;
            query = {};
            if nargin > 2
                channels = cellstr(channels);
                for k = 1:numel(channels), query = [query, {'channel', channels{k}}]; end %#ok<AGROW>
            end
            columns = [];
            for first = 0:movetrics.Cloud.PAGE:max(total - 1, 0)
                last = min(total, first + movetrics.Cloud.PAGE);
                text = obj.get(['/recordings/' char(id) '/samples'], query{:}, 'format', 'csv', ...
                               'start', sprintf('%d', first), 'stop', sprintf('%d', last));
                [names, block] = movetrics.Cloud.parseCsv(text);
                columns = [columns; block]; %#ok<AGROW>
            end
            s.names = names(3:end);
            s.sample = columns(:, 1);
            s.time_s = columns(:, 2);
            s.data = struct();
            for k = 3:numel(names)
                s.data.(movetrics.Cloud.validName(names{k})) = columns(:, k);
            end
        end

        function t = results(obj, varargin)
            % results("athlete_id", id, "metric_id", "jump.height.flight_time", "since", ...): a table, one row
            % per result: recording_id, recorded_at, athlete_code, movement, metric_id, label, value, unit,
            % method, method_version, engine_version, origin.
            rows = [];
            cursor = '';
            while true
                query = [varargin, {'limit', '100'}];
                if ~isempty(cursor), query = [query, {'cursor', cursor}]; end %#ok<AGROW>
                page = jsondecode(obj.get('/results', query{:}));
                rows = [rows; movetrics.Cloud.asColumn(page.data)]; %#ok<AGROW>
                if isempty(page.next_cursor), break, end
                cursor = page.next_cursor;
            end
            if exist('struct2table', 'file') && ~isempty(rows)
                t = struct2table(rows, 'AsArray', true);
            else
                t = rows;
            end
        end

        function text = get(obj, path, varargin)
            % Raw GET of baseUrl + path with name/value query pairs; returns the body as text.
            url = [obj.baseUrl path];
            if ~isempty(varargin)
                parts = cell(1, numel(varargin) / 2);
                for k = 1:2:numel(varargin)
                    parts{(k + 1) / 2} = [movetrics.Cloud.encode(varargin{k}) '=' movetrics.Cloud.encode(varargin{k + 1})];
                end
                url = [url '?' strjoin(parts, '&')];
            end
            text = webread(url, obj.options);
            if ~ischar(text), text = char(text); end
        end
    end

    methods (Static, Access = private)
        function v = asColumn(v)
            % jsondecode gives a struct array, or a cell when the items have different fields.
            if isempty(v), v = []; else, v = v(:); end
        end

        function s = encode(value)
            value = char(value);
            keep = isletter(value) | (value >= '0' & value <= '9') | ismember(value, '-_.~');
            s = '';
            for k = 1:numel(value)
                if keep(k), s = [s value(k)]; else, s = [s sprintf('%%%02X', double(value(k)))]; end %#ok<AGROW>
            end
        end

        function name = validName(id)
            name = regexprep(id, '[^A-Za-z0-9_]', '_');
            if isempty(name) || ~isletter(name(1)), name = ['x' name]; end
            name = name(1:min(end, 63));
        end

        function [names, values] = parseCsv(text)
            lines = regexp(text, '\r?\n', 'split');
            lines = lines(~cellfun(@isempty, strtrim(lines)));
            names = strtrim(strsplit(lines{1}, ','));
            body = strjoin(lines(2:end), sprintf('\n'));
            cols = textscan(body, repmat('%f', 1, numel(names)), 'Delimiter', ',', 'EmptyValue', NaN);
            values = cell2mat(cols);
        end
    end
end
