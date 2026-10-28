// Athletes: the athletes in the workspace. Names appear only when the token was made with names on.
// Set IncludeArchived to "true" to list archived athletes too.
// Sign-in: Basic, any user name, the token as the password. No token in this file.
let
    IncludeArchived = "false",

    Response = Json.Document(
        Web.Contents(
            BaseUrl,
            [
                RelativePath = "api/v1/athletes",
                Query = [include_archived = IncludeArchived]
            ]
        )
    ),

    Source = Table.FromRecords(
        Response[data],
        {"id", "code", "name", "archived"},
        MissingField.UseNull
    ),

    Typed = Table.TransformColumnTypes(Source, {
        {"id", type text},
        {"code", type text},
        {"name", type text},
        {"archived", type logical}
    })
in
    Typed
