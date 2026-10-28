function stopSimulator(pid, link)
%STOPSIMULATOR Stop a simulator started with startSimulator and remove its pseudo-terminal link.
if ~isnan(pid)
    system(sprintf('kill %d 2>/dev/null', pid));
end
if exist(link, 'file') || exist(link, 'dir')
    delete(link);
end
if exist([link '.log'], 'file')
    delete([link '.log']);
end
end
