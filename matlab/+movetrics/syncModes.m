function modes = syncModes()
%SYNCMODES The bits of SET_SYNC_MODE (DRAFT; sdk/python movetrics_fdt.client.SyncMode). 0 = no sync modes.
%   m = movetrics.syncModes();
%   mode = bitor(m.START_ON_RISE, m.EVENT_FRAMES);      % then fdt.setSyncMode(mode)
%   START_ON_RISE 1: arm, START waits for a rising edge on SYNC IN
%   STOP_ON_FALL 2: stop the stream on a falling edge on SYNC IN
%   MASTER_OUT 4: SYNC OUT high while streaming
%   EVENT_FRAMES 8: send an event frame (address 0xFD, code 0x0E) for every edge; read() returns them as events
%   PULSE_TRAIN 16: SYNC OUT pulses every pulse period while streaming
%   SATURATION_EVENTS 32: event type 7 when a plate value leaves the int16 range
modes = struct('START_ON_RISE', 1, 'STOP_ON_FALL', 2, 'MASTER_OUT', 4, 'EVENT_FRAMES', 8, ...
               'PULSE_TRAIN', 16, 'SATURATION_EVENTS', 32);
end
