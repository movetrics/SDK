function name = eventName(type)
%EVENTNAME Name of an event type (contracts/vocabulary.v1.json "events"). Event frame layout and names: firmware thread, final (types 1-10).
names = {'sync_in_rise', 'sync_in_fall', 'sync_out_rise', 'sync_out_fall', 'stream_armed', ...
         'stream_started_by_trigger', 'saturation', 'frames_dropped', 'saturation_end', 'arm_expired'};
if type >= 1 && type <= numel(names)
    name = names{type};
else
    name = sprintf('unknown_%d', type);
end
end
