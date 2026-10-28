// Samples: the stored samples of one recording, one row per sample.
// Use it from a blank query:  Samples("recording-id-here")
// The JSON page has next_start; this function follows it until it is null, so long recordings load in full.
// Each channel becomes a column, named by its channel id (see the API's channel list in the recording detail).
// Sign-in: Basic, any user name, the token as the password. No token in this file.
(recordingId as text) as table =>
let
    RecordingPath = "api/v1/recordings/" & Uri.EscapeDataString(recordingId) & "/samples",

    GetPage = (start as number) as record =>
        Json.Document(
            Web.Contents(
                BaseUrl,
                [
                    RelativePath = RecordingPath,
                    Query = [format = "json", start = Text.From(start)]
                ]
            )
        ),

    FirstPage = GetPage(0),

    Pages = List.Generate(
        () => FirstPage,
        each _ <> null,
        each if _[next_start] = null then null else GetPage(_[next_start]),
        each _
    ),

    ChannelNames = Record.FieldNames(FirstPage[channels]),

    // Number of samples in one page, taken from the first channel (every channel has one value per sample).
    PageLength = (page as record) as number =>
        List.Count(Record.Field(page[channels], List.First(ChannelNames))),

    TimeS = List.Combine(
        List.Transform(
            Pages,
            each if _[time_s] = null then List.Repeat({null}, PageLength(_)) else _[time_s]
        )
    ),

    SampleNo = List.Numbers(0, List.Count(TimeS)),

    ChannelColumns = List.Transform(
        ChannelNames,
        (name as text) as list =>
            List.Combine(List.Transform(Pages, each Record.Field(_[channels], name)))
    ),

    Source = Table.FromColumns(
        {SampleNo, TimeS} & ChannelColumns,
        {"sample", "time_s"} & ChannelNames
    ),

    Typed = Table.TransformColumnTypes(
        Source,
        {{"sample", Int64.Type}, {"time_s", type number}}
            & List.Transform(ChannelNames, (name as text) => {name, type number})
    )
in
    Typed
