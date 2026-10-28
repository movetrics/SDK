% Record 10 s from the FDT at 2,000 frames/s per plate, no low-pass, and plot vertical force per plate.
% Close Movetrics Studio first (one app on the port at a time). Needs Movetrics firmware 1.2.8.0 or later.
addpath(fullfile(fileparts(mfilename('fullpath')), '..'));
port = "COM5";                       % Windows; on a Mac: "/dev/tty.usbserial-XXXX" (see serialportlist)
fdt = movetrics.Fdt(port);
fprintf('FDT firmware %s\n', fdt.firmware);
fdt.setRate(2000, 0);
fdt.start();
data = fdt.read(10);
fdt.stop();
clear fdt
for plate = 1:2
    on = data.plate == plate;
    plot(data.time_s(on), data.fz(on)); hold on
end
xlabel('time (s, FDT clock)'); ylabel('Fz (N)'); legend('plate 1', 'plate 2'); hold off
% The stream's Fy and Mx have the opposite sign to Studio exports (docs/18-export-formats.md).
