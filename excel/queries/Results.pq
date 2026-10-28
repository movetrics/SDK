// Results: one row per result, for every recording the token can read.
// The API pages by recordings (limit 100) and returns next_cursor in JSON,
// so this query reads JSON and follows the cursor until it is null.
// Sign-in: Basic, any user name, the token as the password. No token in this file.
let
    PageSize = "100",

    GetPage = (cursor as nullable text) as record =>
        Json.Document(
            Web.Contents(
                BaseUrl,
                [
                    RelativePath = "api/v1/results",
                    Query = if cursor = null
                        then [limit = PageSize]
                        else [limit = PageSize, cursor = cursor]
                ]
            )
        ),

    Pages = List.Generate(
        () => GetPage(null),
        each _ <> null,
        each if _[next_cursor] = null then null else GetPage(_[next_cursor]),
        each _[data]
    ),

    Rows = List.Combine(Pages),

    Columns = {
        "recording_id", "recorded_at", "athlete_code", "athlete_name", "movement",
        "metric_id", "label", "value", "unit", "method", "method_version",
        "engine_version", "origin"
    },

    Source = Table.FromRecords(Rows, Columns, MissingField.UseNull),

    // value is left untyped: the API sends numbers, integers and text for it.
    Typed = Table.TransformColumnTypes(Source, {
        {"recording_id", type text},
        {"recorded_at", type datetimezone},
        {"athlete_code", type text},
        {"athlete_name", type text},
        {"movement", type text},
        {"metric_id", type text},
        {"label", type text},
        {"unit", type text},
        {"method", type text},
        {"method_version", type text},
        {"engine_version", type text},
        {"origin", type text}
    })
in
    Typed
