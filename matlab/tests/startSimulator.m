function [link, pid] = startSimulator(profile, extraArgs)
%STARTSIMULATOR Start the SDK's FDT simulator on a pseudo-terminal: python3 -m movetrics_fdt simulate --pty LINK.
%   [LINK, PID] = startSimulator(PROFILE, EXTRAARGS) runs from sdk/python and waits for the READY line.
%   Stop it with stopSimulator(PID, LINK). Needs python3 (3.10 or later) and POSIX ptys (Linux, macOS).
if nargin < 2, extraArgs = ''; end
here = fileparts(mfilename('fullpath'));
pythonDir = fullfile(here, '..', '..', 'python');
link = [tempname() '-fdt'];
log = [link '.log'];
command = sprintf('cd "%s" && exec python3 -m movetrics_fdt simulate --pty "%s" --profile %s %s > "%s" 2>&1 & echo $!', ...
                  pythonDir, link, profile, extraArgs, log);
[status, out] = system(command);
if status ~= 0
    error('movetrics:test', 'could not start the simulator: %s', out);
end
pid = str2double(strtrim(out));
t0 = tic;
while toc(t0) < 15
    if exist(log, 'file') && ~isempty(strfind(fileread(log), 'READY'))  %#ok<STREMP>
        return
    end
    pause(0.1);
end
error('movetrics:test', 'the simulator did not print READY: %s', fileread(log));
end
