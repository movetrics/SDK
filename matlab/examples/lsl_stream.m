% Stream an FDT to Lab Streaming Layer from MATLAB: one stream per plate plus markers. Record them with LabRecorder.
% Needs liblsl-Matlab on the path (https://github.com/labstreaminglayer/liblsl-Matlab) and Movetrics firmware
% 1.2.8.0 or later. Close Movetrics Studio first (one app on the port at a time). Names, units and signs:
% docs/19-vocabulary-and-units.md; streams and timing: docs/22-lsl-and-sync.md.
addpath(fullfile(fileparts(mfilename('fullpath')), '..'));
port = "COM5";                       % Windows; on a Mac: "/dev/tty.usbserial-XXXX" (see serialportlist)
fdt = movetrics.Fdt(port);
fdt.setRate(2000, 0);
bridge = movetrics.LslBridge(2000, [1 2], 'Firmware', fdt.firmware);   % add 'Device', 'B' for a second FDT
fprintf('Streaming FDT %s to LSL as: %s. Ctrl-C stops.\n', fdt.firmware, strjoin(bridge.StreamNames, ', '));
fdt.start();
stopper = onCleanup(@() fdt.stop());
while true
    bridge.push(fdt.read(0.05));     % short reads keep each sample's arrival time close to its frame
end
