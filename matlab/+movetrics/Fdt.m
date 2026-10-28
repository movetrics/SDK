classdef Fdt < handle
    %FDT Live link to a Movetrics FDT over USB (serial, 1,500,000 baud). Needs MATLAB R2019b+ (serialport).
    %   fdt = movetrics.Fdt("COM5");               % Windows; "/dev/tty.usbserial-..." on macOS
    %   fdt.setRate(2000, 0);                       % 2,000 frames/s per plate, no low-pass (1.2.8.0+ only)
    %   fdt.setSyncMode(bitor(movetrics.syncModes().START_ON_RISE, movetrics.syncModes().EVENT_FRAMES));
    %   fdt.start();
    %   data = fdt.read(5);                         % about 5 s: struct of columns in the shared vocabulary
    %   fdt.stop(); clear fdt
    %
    %   One commanding host at a time: close Movetrics Studio (or any other app on the port) first.
    %   The FDT keeps the rate in RAM; after a reset or power cycle it streams 500 frames/s with a 50 Hz low-pass.
    %   read() returns the vocabulary of docs/19-vocabulary-and-units.md: t (s from START), plate, fx fy fz
    %   (N), mx my mz (N*m) in the plate frame (fy and mx are the wire values with the sign changed, as Studio
    %   writes them), cop_x cop_y (m, NaN below 50 N), raw (the six wire integers), events and gaps.
    %   The frame layout and the commands are docs/04-host-commands.md and 05-measurement-stream.md.

    properties (SetAccess = private)
        port            % the serialport object
        firmware = ''   % STM32 firmware version string from GET_FW_VERSION
        streaming = false
        rateHz = []     % frames/s per plate set by setRate (empty: unknown, the gap test learns it)
        rest = uint8([])
        replies = zeros(0, 4)
        conv = []       % converter state of the current stream (movetrics.convertFrames); reset by start()
    end

    properties (Constant)
        BAUD = 1500000
        TICKS_PER_SECOND = 10000
    end

    methods
        function obj = Fdt(portName, baud)
            % baud: leave it out (1,500,000, the FDT's USB rate). The tests pass 115200 to a pseudo-terminal.
            if nargin < 2, baud = movetrics.Fdt.BAUD; end
            if isobject(portName)
                obj.port = portName;  % an open port object (the tests pass tests/MockSerialPort)
            elseif exist('OCTAVE_VERSION', 'builtin')  % GNU Octave: pkg load instrument-control
                obj.port = serialport(portName, 'BaudRate', baud, 'Timeout', 2);
            else
                obj.port = serialport(portName, baud, 'Timeout', 2);
            end
            flush(obj.port);
            obj.firmware = obj.firmwareVersion();
        end

        function delete(obj)
            if obj.streaming
                try, obj.stop(); catch, end %#ok<CTCH>
            end
            obj.port = [];
        end

        function version = firmwareVersion(obj)
            % GET_FW_VERSION 0x23 to 00/00. The reply is 38 bytes: BE EF 00 23, 15 bytes STM32, 15 bytes ESP32.
            flush(obj.port);
            write(obj.port, movetrics.hostCommand(35, 0, 0), 'uint8');
            reply = obj.waitFor(@(b) numel(b) >= 38 && ~isempty(strfind(char(b), char([190 239 0 35]))), 2); %#ok<STREMP>
            i = strfind(char(reply), char([190 239 0 35]));
            if isempty(i) || numel(reply) < i(1) + 37
                error('movetrics:Fdt', 'No GET_FW_VERSION reply. Is the FDT connected, and is no other app using the port?');
            end
            field = reply(i(1) + 4:i(1) + 18);
            version = char(field(1:find([field 0] == 0, 1) - 1));
        end

        function setRate(obj, framesPerSecond, cutoffHz)
            % SET_FILTER 0x1C: frames per second per plate (50..2000) and low-pass cutoff in Hz (0 = off,
            % otherwise below half the rate). Movetrics firmware 1.2.8.0 or later only; other firmware reads
            % 0x1C differently, so this refuses. Leaves 100 ms before the next START, as the bench tools do.
            if nargin < 3, cutoffHz = 50; end
            if ~obj.atLeast([1 2 8 0])
                error('movetrics:Fdt', 'setRate needs Movetrics firmware 1.2.8.0 or later; this FDT reports "%s".', obj.firmware);
            end
            if obj.streaming, error('movetrics:Fdt', 'Stop the stream before setRate.'); end
            if ~(framesPerSecond >= 50 && framesPerSecond <= 2000 && framesPerSecond == round(framesPerSecond))
                error('movetrics:Fdt', 'framesPerSecond must be a whole number from 50 to 2000.');
            end
            if ~(cutoffHz == 0 || (cutoffHz >= 1 && cutoffHz <= 255 && 2 * cutoffHz < framesPerSecond))
                error('movetrics:Fdt', 'cutoffHz must be 0 (off) or 1..255 and below half the rate.');
            end
            frame = movetrics.hostCommand(28, 0, 0, [cutoffHz, bitand(framesPerSecond, 255), bitshift(framesPerSecond, -8)]);
            flush(obj.port);
            write(obj.port, frame, 'uint8');
            ack = obj.waitFor(@(b) obj.hasReply(b, 28), 2);
            [~, ~, replies] = movetrics.decodeStream(ack);
            r = replies(replies(:, 2) == 28, :);
            if isempty(r)
                error('movetrics:Fdt', 'No ACK for SET_FILTER.');
            elseif r(1, 3) == 21
                error('movetrics:Fdt', 'The FDT refused SET_FILTER (NACK %d).', r(1, 4));
            end
            obj.rateHz = framesPerSecond;
            pause(0.1);
        end

        function setSyncMode(obj, mode, pulsePeriodMs, pulseWidthMs, debounceTicks, armTimeoutMin)
            % SET_SYNC_MODE 0x28 to 00/00, payload of six bytes: mode (u8), pulse period ms (u16 LE), pulse width ms
            % (u8), debounce in 0.1 ms units (u8), arm timeout in minutes (u8). A 0 in any field means the firmware
            % default, so the optional fields default to 0. mode is the sum of bits: see movetrics.syncModes.
            % DRAFT: needs firmware with sync modes (1.2.8.24 and later). Errors: NACK 7 (no sync modes on this
            % firmware), NACK 3 (bad parameters, for example MASTER_OUT with PULSE_TRAIN), NACK 8 (stream running or
            % armed). Stop the stream first.
            if nargin < 3, pulsePeriodMs = 0; end
            if nargin < 4, pulseWidthMs = 0; end
            if nargin < 5, debounceTicks = 0; end
            if nargin < 6, armTimeoutMin = 0; end
            movetrics.Fdt.checkByte(mode, 'mode');
            movetrics.Fdt.checkByte(pulseWidthMs, 'pulseWidthMs');
            movetrics.Fdt.checkByte(debounceTicks, 'debounceTicks');
            movetrics.Fdt.checkByte(armTimeoutMin, 'armTimeoutMin');
            if ~(isnumeric(pulsePeriodMs) && isscalar(pulsePeriodMs) && pulsePeriodMs == round(pulsePeriodMs) ...
                    && pulsePeriodMs >= 0 && pulsePeriodMs <= 65535)
                error('movetrics:Fdt', 'pulsePeriodMs must be a whole number from 0 (default) to 65535.');
            end
            if obj.streaming, error('movetrics:Fdt', 'Stop the stream before setSyncMode.'); end
            payload = [mode, bitand(pulsePeriodMs, 255), bitshift(pulsePeriodMs, -8), pulseWidthMs, debounceTicks, armTimeoutMin];
            flush(obj.port);
            write(obj.port, movetrics.hostCommand(40, 0, 0, payload), 'uint8');
            ack = obj.waitFor(@(b) obj.hasReply(b, 40), 2);
            [~, ~, replies] = movetrics.decodeStream(ack);
            r = replies(replies(:, 2) == 40, :);
            if isempty(r)
                error('movetrics:Fdt', 'No ACK for SET_SYNC_MODE within 2 s.');
            elseif r(1, 3) == 21
                switch r(1, 4)
                    case 7
                        error('movetrics:Fdt', ['this FDT firmware has no sync modes (SET_SYNC_MODE answered NACK 7, ' ...
                              'unknown command). Update to firmware with sync modes (docs/04).']);
                    case 3
                        error('movetrics:Fdt', ['The FDT refused SET_SYNC_MODE: bad parameters (NACK 3). Check the mode ' ...
                              '(MASTER_OUT and PULSE_TRAIN together are refused) and the field ranges.']);
                    case 8
                        error('movetrics:Fdt', 'The FDT refused SET_SYNC_MODE: the stream is running or armed (NACK 8). Stop it first.');
                    otherwise
                        error('movetrics:Fdt', 'The FDT refused SET_SYNC_MODE (NACK %d).', r(1, 4));
                end
            end
        end

        function start(obj)
            % START_STREAM 0x01 to FF/FF. No ACK; frames follow. The FDT's clock restarts at 0 here, so the converter
            % state is new for every stream.
            flush(obj.port);
            obj.rest = uint8([]);
            obj.conv = [];
            write(obj.port, movetrics.hostCommand(1, 255, 255), 'uint8');
            obj.streaming = true;
        end

        function data = read(obj, seconds)
            % Read for SECONDS and return the samples in the shared vocabulary (see the class help). Placeholders with
            % ticks 0 are dropped. data.events: struct array of the FDT's event frames (only when sync EVENT_FRAMES is
            % set). data.gaps: struct array of holes in a plate's stream (plate, start_t, end_t, missing). Call
            % repeatedly to keep reading; the gap test continues across calls.
            wire = obj.emptyFrames();
            events = [];
            t0 = tic;
            while toc(t0) < seconds
                count = obj.port.NumBytesAvailable;
                if count == 0
                    pause(0.005);
                    continue
                end
                [frames, obj.rest, replies, ev] = movetrics.decodeStream([obj.rest, read(obj.port, count, 'uint8')]);
                obj.replies = [obj.replies; replies];
                names = fieldnames(frames);
                for k = 1:numel(names)
                    wire.(names{k}) = [wire.(names{k}); frames.(names{k})];
                end
                if isempty(events)
                    events = ev;
                elseif ~isempty(ev)
                    events = [events; ev];
                end
            end
            [data, gaps, obj.conv] = movetrics.convertFrames(wire, obj.conv, obj.rateHz);
            data.events = events;
            if isempty(data.events)
                data.events = struct('t', cell(0, 1), 'stamp', cell(0, 1), 'type', cell(0, 1), 'name', cell(0, 1), ...
                                     'source', cell(0, 1), 'count', cell(0, 1), 'offset_us', cell(0, 1), ...
                                     'detail', cell(0, 1), 'mode', cell(0, 1));
            end
            data.gaps = gaps;
        end

        function stop(obj)
            % STOP_STREAM 0x05 to FF/00, then wait for its ACK.
            write(obj.port, movetrics.hostCommand(5, 255, 0), 'uint8');
            obj.waitFor(@(b) obj.hasReply(b, 5), 2);
            obj.streaming = false;
        end
    end

    methods (Access = private)
        function ok = atLeast(obj, minimum)
            parts = sscanf(obj.firmware, '%d.%d.%d.%d')';
            ok = numel(parts) == 4;
            if ok
                d = find(parts ~= minimum, 1);
                ok = isempty(d) || parts(d) > minimum(d);
            end
        end

        function bytes = waitFor(obj, done, timeout)
            bytes = uint8([]);
            t0 = tic;
            while toc(t0) < timeout
                if obj.port.NumBytesAvailable > 0
                    bytes = [bytes, read(obj.port, obj.port.NumBytesAvailable, 'uint8')]; %#ok<AGROW>
                    if done(bytes), return, end
                else
                    pause(0.005);
                end
            end
        end
    end

    methods (Static, Access = private)
        function checkByte(value, name)
            if ~(isnumeric(value) && isscalar(value) && value == round(value) && value >= 0 && value <= 255)
                error('movetrics:Fdt', '%s must be a whole number from 0 to 255.', name);
            end
        end

        function ok = hasReply(bytes, command)
            [~, ~, replies] = movetrics.decodeStream(bytes);
            ok = any(replies(:, 2) == command);
        end

        function s = emptyFrames()
            z = zeros(0, 1);
            s = struct('plate', z, 'ticks', z, 'fx', z, 'fy', z, 'fz', z, 'mx', z, 'my', z, 'mz', z);
        end
    end
end
