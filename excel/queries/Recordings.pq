// Recordings: newest first, one row per recording, with the key result as JSON text.
// The API has no CSV for this table, so the query reads JSON and follows next_cursor.
// Sign-in: Basic, any user name, the token as the password. No token in this file.
let
    PageSize = "100",

    GetPage = (cursor as nullable text) as record =>
        Json.Document(
            Web.Contents(
                BaseUrl,
                [
                    RelativePath = "api/v1/recordings",
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

    Recordings = List.Combine(Pages),

    Flat = List.Transform(
        Recordings,
        (r as record) as record =>
            let
                athlete = Record.FieldOrDefault(r, "athlete"),
                analysis = Record.FieldOrDefault(r, "analysis"),
                keyResult = Record.FieldOrDefault(r, "key_result"),
                results = Record.FieldOrDefault(r, "results", {})
            in
                [
                    id = Record.FieldOrDefault(r, "id"),
                    recorded_at = Record.FieldOrDefault(r, "recorded_at"),
                    athlete_code = if athlete = null then null else Record.FieldOrDefault(athlete, "code"),
                    athlete_name = if athlete = null then null else Record.FieldOrDefault(athlete, "name"),
                    movement = Record.FieldOrDefault(r, "movement"),
                    protocol = Record.FieldOrDefault(r, "protocol"),
                    status = Record.FieldOrDefault(r, "status"),
                    origin = Record.FieldOrDefault(r, "origin"),
                    engine_version = if analysis = null then null else Record.FieldOrDefault(analysis, "engine_version"),
                    result_count = List.Count(results),
                    key_result = if keyResult = null then null else Text.FromBinary(Json.FromValue(keyResult)),
                    title = Record.FieldOrDefault(r, "title"),
                    filename = Record.FieldOrDefault(r, "filename")
                ]
    ),

    Columns = {
        "id", "recorded_at", "athlete_code", "athlete_name", "movement", "protocol",
        "status", "origin", "engine_version", "result_count", "key_result", "title", "filename"
    },

    Source = Table.FromRecords(Flat, Columns, MissingField.UseNull),

    Typed = Table.TransformColumnTypes(Source, {
        {"id", type text},
        {"recorded_at", type datetimezone},
        {"athlete_code", type text},
        {"athlete_name", type text},
        {"movement", type text},
        {"protocol", type text},
        {"status", type text},
        {"origin", type text},
        {"engine_version", type text},
        {"result_count", Int64.Type},
        {"key_result", type text},
        {"title", type text},
        {"filename", type text}
    })
in
    Typed
