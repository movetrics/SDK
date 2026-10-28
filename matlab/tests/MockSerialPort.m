classdef MockSerialPort < handle
    %MOCKSERIALPORT A stand-in for the serialport object, for movetrics.Fdt tests without hardware or Octave's
    %   instrument-control package. It answers the host commands the way the FDT does (GET_FW_VERSION, SET_FILTER,
    %   SET_SYNC_MODE, STOP_STREAM) and gives back whatever bytes the test queued with queue().
    %   port = MockSerialPort(); port.syncSupported = false;   % firmware without sync modes: NACK 7 to 0x28
    %   port.syncNack = 8;                                     % or any NACK code to SET_SYNC_MODE
    %   port.written: the host frames sent, one cell per write.
    properties
        NumBytesAvailable = 0
        syncSupported = true   % false: firmware without sync modes, NACK 7 to 0x28
        syncNack = 0           % non-zero: NACK with this error to 0x28 (3 bad parameters, 8 stream running or armed)
        written = {}
    end

    properties (Access = private)
        buffer = uint8([])
    end

    methods
        function queue(obj, bytes)
            obj.buffer = [obj.buffer, uint8(bytes(:)')];
            obj.NumBytesAvailable = numel(obj.buffer);
        end

        function flush(obj)
            obj.buffer = uint8([]);
            obj.NumBytesAvailable = 0;
        end

        function write(obj, data, precision) %#ok<INUSD>
            data = uint8(data(:)');
            obj.written{end + 1} = data;
            if numel(data) < 5, return, end
            switch double(data(5))
                case 35   % GET_FW_VERSION: 15 bytes STM32, 15 bytes ESP32
                    body = [0 35, uint8('1.2.8.24-SYNC'), zeros(1, 2), uint8('000.000.000'), zeros(1, 4)];
                    obj.reply(body);
                case {28, 1}  % SET_FILTER: ACK. START (0x01) has no reply.
                    if data(5) == 28, obj.reply([0 28 6]); end
                case 40   % SET_SYNC_MODE: ACK, or NACK 7 (unknown command) on firmware without sync modes
                    if obj.syncNack ~= 0
                        obj.reply([0 40 21 obj.syncNack 0]);
                    elseif obj.syncSupported
                        obj.reply([0 40 6]);
                    else
                        obj.reply([0 40 21 7 0]);
                    end
                case 5    % STOP_STREAM
                    obj.reply([255 5 6]);
                otherwise
                    obj.reply([0 double(data(5)) 21 7 0]);
            end
        end

        function bytes = read(obj, count, precision) %#ok<INUSD>
            count = min(count, numel(obj.buffer));
            bytes = obj.buffer(1:count);
            obj.buffer(1:count) = [];
            obj.NumBytesAvailable = numel(obj.buffer);
        end
    end

    methods (Static)
        function frame = streamFrame(plate, ticks, wire)
            % One 24-byte stream frame: plate address, command 01, stamp (u32 LE), six int16 LE wire values.
            wire = mod(wire(:)', 65536);
            body = [plate, 1, mod(ticks, 256), mod(floor(ticks / 256), 256), mod(floor(ticks / 65536), 256), ...
                    floor(ticks / 16777216), reshape([mod(wire, 256); floor(wire / 256)], 1, [])];
            crc = movetrics.crc16(uint8(body));
            frame = [190 239 body bitand(crc, 255) bitshift(crc, -8) 4 4];
        end
    end

    methods (Access = private)
        function reply(obj, body)
            % A device frame: BE EF, the body (address, code, data), CRC-16 over the body (low byte first), 04 04.
            crc = movetrics.crc16(uint8(body));
            obj.queue([190 239 uint8(body) bitand(crc, 255) bitshift(crc, -8) 4 4]);
        end
    end
end
