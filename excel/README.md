# Movetrics Cloud in Excel

Get your Movetrics Cloud results and raw samples into Excel with Power Query. Refresh with one click. The token is never stored in the workbook.

## What is here

- `Movetrics-Cloud.xlsx`: a workbook with three sheets. **Start here** has the steps. **Queries** holds the text of each query. **Results** is an empty table with the expected column headers.
- `queries/*.pq`: the Power Query (M) code, one file per query:
  - `BaseUrl.pq`: the server address (default `https://beta.movetrics.com`).
  - `Results.pq`: one row per result (`/api/v1/results`).
  - `Recordings.pq`: one row per recording (`/api/v1/recordings`).
  - `Athletes.pq`: the athletes (`/api/v1/athletes`).
  - `Samples.pq`: a function, `Samples("recording-id")`, that reads all stored samples of one recording (`/api/v1/recordings/{id}/samples`, following `next_start`).
- `build_workbook.py`: rebuilds `Movetrics-Cloud.xlsx` from the `.pq` files. Run it with `python3 sdk/excel/build_workbook.py` (needs `openpyxl`).

## Steps

1. In Movetrics Cloud, make a token under Account > Access tokens > New token. It starts with `mvt_`.
2. In Excel, go to Data > Get Data > Launch Power Query Editor. Then New Source > Blank Query > Advanced Editor.
3. Paste the text of `queries/BaseUrl.pq`. Click Done. Name the query `BaseUrl`.
4. Repeat for `Results.pq`, `Recordings.pq`, `Athletes.pq` and `Samples.pq`. Name each query after its file.
5. Load Results to a sheet (Close & Load To). When Excel asks, choose **Basic**. User name: anything. Password: the `mvt_` token.
6. Data > Refresh All fetches new data. Excel keeps the token in its own credential store (Data > Get Data > Data Source Settings), not in the file.

The workbook cannot hold the queries itself. The script puts the code in the **Queries** sheet so you can paste it. This takes about two minutes, once.

## Excel versions

- Microsoft 365 or Excel 2021 and later, on Windows or Mac.
- Not Excel on the web. It cannot send the Basic sign-in that the API needs.

## API notes

These follow `contracts/movetrics-public-api-v1.json`.

- Paged tables (`results`, `recordings`) use `limit` (max 100) and `next_cursor`. The queries read JSON, because `next_cursor` is only in JSON. A CSV would give one page only.
- `recordings` and `athletes` have no CSV option in the contract. `results` and a recording's `samples` do.
- Samples are paged by `start` and `next_start`, at most 100,000 samples a page.
- The API allows 600 requests a minute. Above that it returns 429 with `Retry-After`.
- A recording's samples return 409 until they are ready.

## Tested

M code checked for syntax by reading only. Not run in Excel: there is no Excel in this environment. The sign-in prompt, Refresh All, and refresh from the cloud (for example a scheduled refresh) have not been tried.
