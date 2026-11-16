classdef ClockMap < handle
    %CLOCKMAP FDT seconds to host seconds from (FDT time, arrival time) pairs: the clock mapping of docs/22.
    %   map = movetrics.ClockMap();                                % 1 s blocks, the last 300 of them, no latency
    %   map = movetrics.ClockMap('BlockSeconds', 0.5, 'WindowBlocks', 4, 'LatencySeconds', 0.004);
    %   host = map.observe(deviceS, arrivalS);                     % take the pairs in order: host time of each
    %   host = map.toHost(deviceS);                                % map without taking pairs
    %
    %   In each block of BlockSeconds the pair that waited least (smallest arrival - device, the first one on a tie)
    %   gives one point; a least-squares line through the last WindowBlocks points gives offset and drift. Until
    %   three blocks have closed, the smallest difference seen so far is the offset, so treat the first three
    %   blocks as warm-up. observe returns each pair's host time as mapped right after that pair was taken: the
    %   numbers of Python's ClockMap.observe followed by to_host, pair by pair (vectors/clock_map.json). arrivalS
    %   may be one value for the whole batch, for example the time a read returned.

    properties (SetAccess = private)
        BlockSeconds = 1
        WindowBlocks = 300
        LatencySeconds = 0
        ResidualSeconds = []     % rms of the points around the line; [] before the first line
    end

    properties (Access = private)
        points = zeros(0, 2)     % closed blocks: [device, arrival - device] of the least-delayed pair
        block = []               % index of the open block
        blockPoint = []          % its least-delayed pair so far
        floorDiff = Inf          % smallest arrival - device seen
        fit = []                 % [mean device, mean difference, slope]
    end

    methods
        function obj = ClockMap(varargin)
            for k = 1:2:numel(varargin)
                name = char(varargin{k});
                if ~any(strcmp(name, {'BlockSeconds', 'WindowBlocks', 'LatencySeconds'}))
                    error('movetrics:ClockMap', 'Unknown option %s.', name);
                end
                obj.(name) = double(varargin{k + 1});
            end
            if ~(obj.BlockSeconds > 0) || ~(obj.WindowBlocks >= 3)
                error('movetrics:ClockMap', 'BlockSeconds must be positive and WindowBlocks at least 3.');
            end
        end

        function d = driftPpm(obj)
            % Drift of the FDT clock against the host clock, in ppm; [] before the first line.
            if isempty(obj.fit), d = []; else, d = obj.fit(3) * 1e6; end
        end

        function host = observe(obj, deviceS, arrivalS)
            deviceS = double(deviceS(:));
            arrivalS = double(arrivalS(:));
            if isscalar(arrivalS), arrivalS = repmat(arrivalS, size(deviceS)); end
            if numel(arrivalS) ~= numel(deviceS)
                error('movetrics:ClockMap', 'arrivalS needs one value per pair, or one for all of them.');
            end
            host = zeros(size(deviceS));
            if isempty(deviceS), return; end
            diffs = arrivalS - deviceS;
            blocks = floor(deviceS / obj.BlockSeconds);
            starts = [1; find(diff(blocks) ~= 0) + 1];
            ends = [starts(2:end) - 1; numel(blocks)];
            for r = 1:numel(starts)
                s = starts(r);
                e = ends(r);
                if isempty(obj.block) || blocks(s) ~= obj.block
                    if ~isempty(obj.blockPoint)
                        obj.closeBlock();      % the first pair of a later block closes the open one
                    end
                    obj.block = blocks(s);
                    obj.blockPoint = [deviceS(s), diffs(s)];
                end
                [least, at] = min(diffs(s:e));  % min returns the first of equal values: the first pair wins a tie
                if least < obj.blockPoint(2)
                    obj.blockPoint = [deviceS(s + at - 1), least];
                end
                floors = min(obj.floorDiff, cummin(diffs(s:e)));
                obj.floorDiff = floors(end);
                if isempty(obj.fit)
                    offsets = floors;
                else
                    offsets = obj.fit(2) + obj.fit(3) * (deviceS(s:e) - obj.fit(1));
                end
                host(s:e) = deviceS(s:e) + offsets - obj.LatencySeconds;
            end
        end

        function host = toHost(obj, deviceS)
            deviceS = double(deviceS);
            if isempty(obj.fit)
                host = deviceS + obj.floorDiff - obj.LatencySeconds;
            else
                host = deviceS + obj.fit(2) + obj.fit(3) * (deviceS - obj.fit(1)) - obj.LatencySeconds;
            end
        end

        function reset(obj)
            obj.points = zeros(0, 2);
            obj.block = [];
            obj.blockPoint = [];
            obj.floorDiff = Inf;
            obj.fit = [];
            obj.ResidualSeconds = [];
        end
    end

    methods (Access = private)
        function closeBlock(obj)
            obj.points(end + 1, :) = obj.blockPoint;
            if size(obj.points, 1) > obj.WindowBlocks
                obj.points = obj.points(end - obj.WindowBlocks + 1:end, :);
            end
            if size(obj.points, 1) >= 3
                x = obj.points(:, 1);
                y = obj.points(:, 2);
                meanX = sum(x) / numel(x);
                meanY = sum(y) / numel(y);
                sxx = sum((x - meanX) .^ 2);
                slope = 0;
                if sxx > 0
                    slope = sum((x - meanX) .* (y - meanY)) / sxx;
                end
                obj.fit = [meanX, meanY, slope];
                obj.ResidualSeconds = sqrt(sum((y - (meanY + slope * (x - meanX))) .^ 2) / numel(x));
            end
        end
    end
end
