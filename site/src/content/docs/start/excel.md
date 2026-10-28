---
title: Excel in 5 minutes
description: Movetrics Cloud recordings, results and raw samples in Excel with Power Query, refreshed with one click.
---

You need a Movetrics Cloud workspace and Excel for Windows or Mac (Microsoft 365 or 2021 and later). Excel on the web cannot send the sign-in that the API needs.

The ready-made workbook and the Power Query code are in the SDK: [excel on GitHub](https://github.com/movetrics/sdk/tree/main/excel). Download `Movetrics-Cloud.xlsx`, open the **Start here** sheet, and follow it. The steps below are the short version.

## 1. Make a token

In Movetrics Cloud: **Account → Access tokens → New token**. Copy it (it starts with `mvt_`). Athletes appear as codes unless you switch names on for that token.

## 2. Connect Excel

1. **Data → Get Data → Launch Power Query Editor**, then **New Source → Blank Query → Advanced Editor**.
2. Paste the code from `queries/BaseUrl.pq`, then add `Results.pq`, `Recordings.pq`, `Athletes.pq` and `Samples.pq` the same way. Name each query after its file.
3. Load **Results** to a sheet. When Excel asks how to sign in, choose **Basic**. User name: anything (for example `token`). Password: your token (`mvt_…`).

Each query reads every page of its table, so you get all of the workspace's results, not just the first 100 recordings.

For a quick look without Power Query, **Data → Get Data → From Web** can open `https://beta.movetrics.com/api/v1/results?format=csv`, with the same Basic sign-in. That gives one page only.

## 3. Refresh

**Data → Refresh All** fetches new results. Excel keeps the token in its own credential store (**Data → Get Data → Data Source Settings**), not in the workbook, so you can share the file without sharing access.

## Tables

Base: `https://beta.movetrics.com`. All paths are under `/api/v1`. The contract is the OpenAPI file `contracts/movetrics-public-api-v1.json`.

| Path | Formats | Paging | What |
|---|---|---|---|
| `/results` | JSON, CSV (`?format=csv`) | `limit` (recordings per page, max 100), `cursor` / `next_cursor` (JSON) | One row per result: recording, time, athlete code, movement, metric, value, unit, method and version |
| `/recordings` | JSON | `limit` (max 100), `cursor` / `next_cursor` | Recordings, newest first, each with its results |
| `/recordings/{recording_id}` | JSON | none | One recording, with its samples summary |
| `/recordings/{recording_id}/samples` | JSON, CSV (`?format=csv`) | `start` / `next_start` (JSON), at most 100,000 samples a page | The stored samples of one recording, unfiltered |
| `/recordings/{recording_id}/samples.parquet` | Parquet file | none | The stored signal file, byte for byte |
| `/athletes` | JSON | none; `include_archived` | Athletes in the workspace |
| `/me` | JSON | none | Who the token reads as and what it may see |

The CSV form returns one page, with no next cursor. For more than one page, use the JSON form and follow the cursor, as the Power Query files do.

Limits: 600 requests a minute. Above that the API answers 429 with `Retry-After`. Samples answer 409 until they are ready.

Full list: [export formats](../../reference/18-export-formats/#6-movetrics-cloud-read-api-v1).

**Tested on:** the Power Query code was checked by reading it only. It has not been run in Excel yet.
