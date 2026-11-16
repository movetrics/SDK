classdef LslBridge < handle
    %LSLBRIDGE Lab Streaming Layer outlets for an FDT: one per plate plus a marker stream, on the LSL clock.
    %   Needs liblsl-Matlab (https://github.com/labstreaminglayer/liblsl-Matlab) on the path. Then:
    %     fdt = movetrics.Fdt("COM3"); fdt.setRate(2000, 0);
    %     bridge = movetrics.LslBridge(2000, [1 2], 'Firmware', fdt.firmware);   % 'Device', 'B' for a second FDT
    %     fdt.start();
    %     while true, bridge.push(fdt.read(0.05)); end      % Ctrl-C stops; LabRecorder records the streams
    %
    %   The streams are the Python SDK's (docs/22-lsl-and-sync.md): "Movetrics FDT plate N" (type Force, float32,
    %   fx fy fz N, mx my mz N*m, cop_x cop_y m from the plate centre, NaN below 50 N; source id
    %   movetrics-fdt-plateN) and "Movetrics FDT markers" (event names, "gap plate=P missing=N", notes from mark).
    %   push takes the struct movetrics.Fdt.read returns. Each sample's stamp is its FDT time mapped onto the LSL
    %   clock by movetrics.ClockMap from the times the reads returned, never the arrival time itself; short reads
    %   (50 ms or less) keep those times close to the frames. LSL needs rising stamps per stream: a repeated FDT
    %   stamp is dropped (counted in stats), and a stamp that would not rise is held 1 microsecond above the last.
    %
    %   Options: 'Device' (a label: "Movetrics FDT B plate 1", source id movetrics-fdt-B-plate1), 'Firmware',
    %   'Name', 'SourceId', 'LatencySeconds' (a measured constant delay to subtract), 'Lib' (from lsl_loadlib).

    properties (SetAccess = private)
        Plates                 % plate numbers, in the order of Outlets
        StreamNames = {}       % what to tick in LabRecorder: the plate streams, then the marker stream
        Clock                  % the movetrics.ClockMap
        Outlets = {}           % one lsl_outlet per plate
        Markers = []           % the marker lsl_outlet
        Repeated = 0           % samples dropped because their FDT stamp did not rise
    end

    properties (Access = private)
        lib
        lastTicks
        lastStamp
        closed = false
    end

    methods
        function obj = LslBridge(rateHz, plates, varargin)
            if nargin < 2 || isempty(plates), plates = [1 2]; end
            opts = struct('Name', 'Movetrics FDT', 'SourceId', 'movetrics-fdt', 'Device', '', 'Firmware', 'unknown', ...
                          'LatencySeconds', 0, 'Lib', []);
            for k = 1:2:numel(varargin)
                key = char(varargin{k});
                if ~isfield(opts, key), error('movetrics:LslBridge', 'Unknown option %s.', key); end
                opts.(key) = varargin{k + 1};
            end
            name = char(opts.Name);
            sourceId = char(opts.SourceId);
            device = char(opts.Device);
            if ~isempty(device)
                if isempty(regexp(device, '^[A-Za-z0-9_-]+$', 'once'))
                    error('movetrics:LslBridge', ['Device labels one FDT in the LSL names and source ids: use ' ...
                          'letters, digits, ''-'' or ''_'', not "%s".'], device);
                end
                name = [name ' ' device];
                sourceId = [sourceId '-' device];
            end
            if ~(isnumeric(rateHz) && isscalar(rateHz) && rateHz > 0)
                error('movetrics:LslBridge', 'rateHz must be a positive number.');
            end
            lib = opts.Lib;
            if isempty(lib)
                if exist('lsl_loadlib', 'file') ~= 2
                    error('movetrics:LslBridge', ['LSL needs liblsl-Matlab on the path: ' ...
                          'https://github.com/labstreaminglayer/liblsl-Matlab (docs/22-lsl-and-sync.md).']);
                end
                lib = lsl_loadlib();
            end
            obj.lib = lib;
            obj.Plates = double(plates(:)');
            obj.Clock = movetrics.ClockMap('LatencySeconds', opts.LatencySeconds);
            obj.lastTicks = -ones(1, numel(obj.Plates));
            obj.lastStamp = -Inf(1, numel(obj.Plates));
            labels = {'fx', 'fy', 'fz', 'mx', 'my', 'mz', 'cop_x', 'cop_y'};
            units = {'N', 'N', 'N', 'N*m', 'N*m', 'N*m', 'm', 'm'};
            kinds = {'Force', 'Force', 'Force', 'Moment', 'Moment', 'Moment', 'CoP', 'CoP'};
            for k = 1:numel(obj.Plates)
                plateName = sprintf('%s plate %d', name, obj.Plates(k));
                info = lsl_streaminfo(lib, plateName, 'Force', 8, rateHz, 'cf_float32', sprintf('%s-plate%d', sourceId, obj.Plates(k)));
                desc = info.desc();
                channels = desc.append_child('channels');
                for c = 1:8
                    channel = channels.append_child('channel');
                    channel.append_child_value('label', labels{c});
                    channel.append_child_value('unit', units{c});
                    channel.append_child_value('type', kinds{c});
                end
                acquisition = desc.append_child('acquisition');
                acquisition.append_child_value('manufacturer', 'Movetrics');
                acquisition.append_child_value('firmware', char(opts.Firmware));
                if ~isempty(device), acquisition.append_child_value('device', device); end
                acquisition.append_child_value('vocabulary', 'movetrics.vocabulary/1 (docs/19)');
                acquisition.append_child_value('frame', 'plate: Studio file signs; CoP from the plate centre');
                clock = desc.append_child('clock');
                clock.append_child_value('source', 'FDT stamp, 0.1 ms ticks, one clock for all plates');
                clock.append_child_value('mapping', 'least-squares line through the least-delayed frame of each second');
                obj.Outlets{k} = lsl_outlet(info);
                obj.StreamNames{end + 1} = plateName;
            end
            markers = lsl_streaminfo(lib, [name ' markers'], 'Markers', 1, 0, 'cf_string', [sourceId '-markers']);
            obj.Markers = lsl_outlet(markers);
            obj.StreamNames{end + 1} = [name ' markers'];
        end

        function push(obj, data, arrival)
            % Push what movetrics.Fdt.read returned. arrival: lsl_local_clock when the read returned (default: now).
            obj.checkOpen();
            if nargin < 3 || isempty(arrival), arrival = lsl_local_clock(obj.lib); end
            if isfield(data, 't') && ~isempty(data.t)
                host = obj.Clock.observe(data.t, arrival);
                values = [data.fx(:), data.fy(:), data.fz(:), data.mx(:), data.my(:), data.mz(:), data.cop_x(:), data.cop_y(:)];
                for k = 1:numel(obj.Plates)
                    rows = find(data.plate(:) == obj.Plates(k));
                    if isempty(rows), continue; end
                    ticks = double(data.ticks(rows));
                    keep = ticks > cummax([obj.lastTicks(k); ticks(1:end - 1)]);
                    obj.Repeated = obj.Repeated + sum(~keep);
                    rows = rows(keep);
                    if isempty(rows), continue; end
                    obj.lastTicks(k) = max([obj.lastTicks(k); ticks(keep)]);
                    stamps = host(rows);
                    last = obj.lastStamp(k);
                    for j = 1:numel(stamps)
                        if stamps(j) <= last, stamps(j) = last + 1e-6; end
                        last = stamps(j);
                    end
                    obj.lastStamp(k) = last;
                    obj.Outlets{k}.push_chunk(values(rows, :)', stamps');
                end
            end
            if isfield(data, 'events')
                for j = 1:numel(data.events)
                    obj.Markers.push_sample({char(data.events(j).name)}, obj.Clock.toHost(data.events(j).t));
                end
            end
            if isfield(data, 'gaps')
                for j = 1:numel(data.gaps)
                    gap = data.gaps(j);
                    obj.Markers.push_sample({sprintf('gap plate=%d missing=%d', gap.plate, gap.missing)}, obj.Clock.toHost(gap.start_t));
                end
            end
        end

        function mark(obj, text)
            % A free-text marker at the current time (trial names, 'jump 3').
            obj.checkOpen();
            obj.Markers.push_sample({char(text)}, lsl_local_clock(obj.lib));
        end

        function s = stats(obj)
            residual = obj.Clock.ResidualSeconds;
            if ~isempty(residual), residual = residual * 1000; end
            s = struct('drift_ppm', obj.Clock.driftPpm(), 'residual_ms', residual, 'repeated_dropped', obj.Repeated);
        end

        function close(obj)
            % Take the streams off the network. Pushing after this is an error.
            % The outlets are released, not deleted: an lsl_outlet destroys its stream once, when its last reference
            % goes, while an explicit delete would destroy it twice in GNU Octave and crash.
            if obj.closed, return; end
            obj.Outlets = {};
            obj.Markers = [];
            obj.closed = true;
        end

        function delete(obj)
            obj.close();
        end
    end

    methods (Access = private)
        function checkOpen(obj)
            if obj.closed, error('movetrics:LslBridge', 'This LslBridge is closed.'); end
        end
    end
end
