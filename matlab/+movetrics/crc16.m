function crc = crc16(bytes)
%CRC16 CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) of each row of BYTES.
%   CRC = movetrics.crc16(BYTES) takes a uint8/double row vector, or a matrix with one message per row, and
%   returns the CRC of each row as double. The FDT stores it low byte first (docs/03-host-link-framing.md).
%   Check value: movetrics.crc16(uint8('123456789')) == hex2dec('29B1').
persistent table
if isempty(table)
    table = zeros(256, 1);
    for n = 0:255
        c = bitshift(n, 8);
        for k = 1:8
            if bitand(c, 32768)
                c = bitxor(bitand(bitshift(c, 1), 65535), 4129);
            else
                c = bitand(bitshift(c, 1), 65535);
            end
        end
        table(n + 1) = c;
    end
end
bytes = double(bytes);
if isempty(bytes), bytes = zeros(1, 0); end  % one empty message, CRC = init
crc = repmat(65535, size(bytes, 1), 1);
for k = 1:size(bytes, 2)
    index = bitxor(bitshift(crc, -8), bytes(:, k));
    crc = bitxor(bitand(bitshift(crc, 8), 65535), table(index + 1));
end
end
