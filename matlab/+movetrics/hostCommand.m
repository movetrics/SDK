function frame = hostCommand(code, address, destination, payload)
%HOSTCOMMAND Bytes of one host request: FE ED address destination code payload CRC(LE) 04 04.
%   FRAME = movetrics.hostCommand(CODE, ADDRESS, DESTINATION, PAYLOAD) returns a uint8 row. It refuses a frame
%   with 04 04 before its end, because the FDT closes a message at the first 04 04 (a rate of 1028 does that).
if nargin < 4, payload = []; end
inner = [address, destination, code, double(payload(:)')];
crc = movetrics.crc16(inner);
frame = uint8([254, 237, inner, bitand(crc, 255), bitshift(crc, -8), 4, 4]);
early = find(frame(1:end-2) == 4 & frame(2:end-1) == 4, 1);
if ~isempty(early)
    error('movetrics:hostCommand', 'The frame has 04 04 before its end, so the FDT would split it.');
end
end
