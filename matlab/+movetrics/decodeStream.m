function [frames, rest, replies, events] = decodeStream(bytes)
%DECODESTREAM Split FDT output bytes into 24-byte measurement frames, event frames and other replies.
%   [FRAMES, REST, REPLIES, EVENTS] = movetrics.decodeStream(BYTES)
%   FRAMES is a struct with one entry per field, each a column: plate (address 1 or 2), ticks (uint32 stamp,
%   0.1 ms ticks of the FDT clock, restarting at 0 on every START), fx, fy, fz, mx, my, mz (int16 counts as the
%   FDT sends them: the wire values, not yet the plate frame; see movetrics.convertFrames and
%   docs/19-vocabulary-and-units.md). Frames with ticks == 0 are start-up placeholders (docs/05 section
%   6): movetrics.Fdt drops them.
%   REST holds trailing bytes of an incomplete frame: prepend them to the next read.
%   REPLIES lists ACK (9 bytes) and NACK (11 bytes) replies as rows [address, command, ackOrNack, errorCode],
%   ackOrNack 6 for ACK and 21 for NACK.
%   EVENTS is a column struct array, one element per event frame (address 0xFD, code 0x0E; sent only when the
%   EVENT_FRAMES bit of SET_SYNC_MODE is set): t (s = stamp / 10,000 + offset_us / 1e6), stamp (ticks), type, name
%   (from contracts/vocabulary.v1.json), source (sync input index, or plate for saturation), count (counter since
%   START), offset_us (int16), detail (uint16), mode (the SYNC mode byte in the frame).
%   The frame layout is docs/05-measurement-stream.md section 2: BE EF address 01 stamp(u32 LE)
%   Fx Fy Fz Mx My Mz (i16 LE) CRC(LE over bytes 2..19) 04 04. An event frame has the same envelope: address FD,
%   code 0E, stamp(u32 LE), type(u8), source(u8), count(u32 LE), offset_us(i16 LE), detail(u16 LE), mode(u8), 0, CRC.
b = double(bytes(:)');
n = numel(b);
frames = emptyFrames();
events = emptyEvents();
replies = zeros(0, 4);
if n < 9
    rest = uint8(b);
    return
end
% Candidate frame starts: header and end marker in place, then the command (stream 0x01 at byte 3, or event
% frame address 0xFD and code 0x0E); the CRC decides. Kind 0 = stream frame, 1 = event frame.
s = zeros(1, 0);
kind = zeros(1, 0);
if n >= 24
    m = n - 23;
    header = b(1:m) == 190 & b(2:m+1) == 239;
    ends = b(23:n-1) == 4 & b(24:n) == 4;
    stream = header & ends & b(4:m+3) == 1;
    event = header & ends & b(3:m+2) == 253 & b(4:m+3) == 14;
    s = [find(stream), find(event)];
    kind = [zeros(1, nnz(stream)), ones(1, nnz(event))];
    [s, order] = sort(s);
    kind = kind(order);
end
if ~isempty(s)
    body = b(s(:) + (2:19));                     % bytes 2..19 of each candidate, one row each
    crc = reshape(b(s(:) + 20) + 256 * b(s(:) + 21), [], 1);
    ok = movetrics.crc16(body) == crc;
    s = s(ok);
    kind = kind(ok);
end
% Drop candidates that overlap a frame already taken (a header pattern inside a frame's data).
keep = true(size(s));
last = -Inf;
for k = 1:numel(s)
    if s(k) < last + 24
        keep(k) = false;
    else
        last = s(k);
    end
end
s = s(keep);
kind = kind(keep);
covered = false(1, n);
for k = 1:numel(s)
    covered(s(k):s(k) + 23) = true;
end
% ACK BE EF a c 06 crc crc 04 04 and NACK BE EF a c 15 e 00 crc crc 04 04 between frames.
h = find(b(1:n-8) == 190 & b(2:n-7) == 239 & ~covered(1:n-8));
for k = 1:numel(h)
    i = h(k);
    if b(i + 4) == 6 && b(i + 7) == 4 && b(i + 8) == 4 && movetrics.crc16(b(i+2:i+4)) == b(i+5) + 256 * b(i+6)
        replies(end + 1, :) = [b(i + 2), b(i + 3), 6, 0]; %#ok<AGROW>
        covered(i:i + 8) = true;
    elseif i + 10 <= n && b(i + 4) == 21 && b(i + 9) == 4 && b(i + 10) == 4 && ...
            movetrics.crc16(b(i+2:i+6)) == b(i+7) + 256 * b(i+8)
        replies(end + 1, :) = [b(i + 2), b(i + 3), 21, b(i + 5)]; %#ok<AGROW>
        covered(i:i + 10) = true;
    end
end
s = s(:);  % indexing a row vector gives a row, so make every field a column explicitly
u32 = @(o, t) b(t + o) + 256 * b(t + o + 1) + 65536 * b(t + o + 2) + 16777216 * b(t + o + 3);
u16 = @(o, t) b(t + o) + 256 * b(t + o + 1);
i16 = @(o, t) u16(o, t) - 65536 * (u16(o, t) >= 32768);
sf = s(kind == 0);
if ~isempty(sf)
    sf = sf(:);
    frames.plate = reshape(b(sf + 2), [], 1);
    frames.ticks = reshape(u32(4, sf), [], 1);
    frames.fx = reshape(i16(8, sf), [], 1);  frames.fy = reshape(i16(10, sf), [], 1);
    frames.fz = reshape(i16(12, sf), [], 1); frames.mx = reshape(i16(14, sf), [], 1);
    frames.my = reshape(i16(16, sf), [], 1); frames.mz = reshape(i16(18, sf), [], 1);
end
se = s(kind == 1);
if ~isempty(se)
    se = se(:);
    typ = reshape(b(se + 8), [], 1);
    stamp = reshape(u32(4, se), [], 1);
    offset = reshape(i16(14, se), [], 1);
    names = cell(numel(typ), 1);
    for k = 1:numel(typ)
        names{k} = movetrics.eventName(typ(k));
    end
    events = struct('t', num2cell(stamp / 10000 + offset / 1e6), 'stamp', num2cell(stamp), 'type', num2cell(typ), ...
                    'name', names, 'source', num2cell(reshape(b(se + 9), [], 1)), ...
                    'count', num2cell(reshape(u32(10, se), [], 1)), 'offset_us', num2cell(offset), ...
                    'detail', num2cell(reshape(u16(16, se), [], 1)), 'mode', num2cell(reshape(b(se + 18), [], 1)));
    events = events(:);
end
% Keep the tail after the last decoded item when it may still become a frame.
done = find(covered, 1, 'last');
if isempty(done), done = 0; end
tail = b(max(done + 1, n - 22):n);
start = find(tail == 190, 1);
if isempty(start)
    rest = uint8([]);
else
    rest = uint8(tail(start:end));
end
end

function s = emptyFrames()
z = zeros(0, 1);
s = struct('plate', z, 'ticks', z, 'fx', z, 'fy', z, 'fz', z, 'mx', z, 'my', z, 'mz', z);
end

function e = emptyEvents()
e = struct('t', cell(0, 1), 'stamp', cell(0, 1), 'type', cell(0, 1), 'name', cell(0, 1), 'source', cell(0, 1), ...
           'count', cell(0, 1), 'offset_us', cell(0, 1), 'detail', cell(0, 1), 'mode', cell(0, 1));
end
