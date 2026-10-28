"""A small client for the Movetrics Cloud read API, version 1 (https://beta.movetrics.com/api/v1).

Standard library only. Create an access token in the Cloud under Account > Access tokens (it starts with mvt_ and
reads one workspace, read only). Keep it out of code and out of version control: pass it from an environment
variable, as the examples do with MOVETRICS_TOKEN.

    cloud = CloudClient(os.environ["MOVETRICS_TOKEN"])
    for recording in cloud.recordings(since="2026-10-01"):
        print(recording["id"], recording["movement"])
    samples = cloud.samples(recording_id)          # every stored channel, all pages joined

Endpoints and their shapes: services/api/app/api_v1.py in the Movetrics firmware repository (private), and docs/18-export-formats.md.
Samples come out exactly as stored, unfiltered; results name their metric, method, method version and engine
version.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any, Final

DEFAULT_BASE_URL: Final = "https://beta.movetrics.com/api/v1"
SAMPLE_PAGE: Final = 100_000  # the server's largest page (SAMPLE_PAGE_LIMIT)


class CloudError(Exception):
    """An HTTP error from the API, with the server's code (NOT_FOUND, SAMPLES_NOT_READY, ...) when it sent one."""

    def __init__(self, status: int, code: str | None, message: str) -> None:
        super().__init__(f"{status} {code or ''} {message}".strip())
        self.status = status
        self.code = code


class CloudClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL, timeout_s: float = 60.0) -> None:
        if not token.startswith("mvt_"):
            raise ValueError("a Movetrics access token starts with mvt_ (Account > Access tokens)")
        self._token = token
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    def get(self, path: str, **query: Any) -> bytes:
        """GET base_url + path with the token; list values repeat the parameter (channel=a&channel=b)."""
        pairs = [(key, item) for key, value in query.items() if value is not None
                 for item in (value if isinstance(value, (list, tuple)) else [value])]
        url = self._base + path + ("?" + urllib.parse.urlencode(pairs) if pairs else "")
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._token}", "Accept": "*/*"})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body: bytes = response.read()
                return body
        except urllib.error.HTTPError as error:
            raw = error.read()
            code, message = None, raw.decode("utf-8", "replace")[:300]
            try:
                detail = json.loads(raw).get("detail")
                if isinstance(detail, dict):
                    code, message = detail.get("code"), detail.get("message", message)
                elif isinstance(detail, str):
                    message = detail
            except (ValueError, AttributeError):
                pass
            raise CloudError(error.code, code, message) from None

    def _json(self, path: str, **query: Any) -> Any:
        return json.loads(self.get(path, **query))

    def me(self) -> dict[str, Any]:
        """Which workspace and role this token reads as, and whether names are shown."""
        result: dict[str, Any] = self._json("/me")
        return result

    def athletes(self, include_archived: bool = False) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = self._json("/athletes", include_archived=str(include_archived).lower())["data"]
        return data

    def recordings(self, *, athlete_id: str | None = None, since: str | None = None, until: str | None = None,
                   page_size: int = 50) -> Iterator[dict[str, Any]]:
        """Every recording, newest first, with the engine's results; follows next_cursor."""
        cursor = None
        while True:
            page = self._json("/recordings", athlete_id=athlete_id, since=since, until=until, cursor=cursor, limit=page_size)
            yield from page["data"]
            cursor = page.get("next_cursor")
            if not cursor:
                return

    def recording(self, recording_id: str) -> dict[str, Any]:
        """One recording: results, methods, engine version, channel list and sample count."""
        result: dict[str, Any] = self._json(f"/recordings/{urllib.parse.quote(recording_id)}")
        return result

    def samples(self, recording_id: str, channels: list[str] | None = None, start: int = 0,
                stop: int | None = None) -> dict[str, Any]:
        """Stored samples from start to stop (all of them by default), pages joined:
        {"time_s": [...], "channels": {id: [...]}, "canonical_digest": ...}."""
        joined: dict[str, Any] = {"time_s": [], "channels": {}}
        position = start
        while True:
            page_stop = position + SAMPLE_PAGE if stop is None else min(stop, position + SAMPLE_PAGE)
            page = self._json(f"/recordings/{urllib.parse.quote(recording_id)}/samples", start=position, stop=page_stop, channel=channels)
            joined["canonical_digest"] = page["canonical_digest"]
            joined["sample_count"] = page["sample_count"]
            joined["time_s"].extend(page.get("time_s") or [])
            for name, values in page["channels"].items():
                joined["channels"].setdefault(name, []).extend(values)
            following = page.get("next_start")
            if following is None or (stop is not None and following >= stop):
                return joined
            position = following

    def results(self, *, athlete_id: str | None = None, metric_id: str | None = None, since: str | None = None,
                until: str | None = None) -> list[dict[str, Any]]:
        """One row per result over every recording (the table Excel reads): recording_id, recorded_at,
        athlete_code, movement, metric_id, label, value, unit, method, method_version, engine_version."""
        rows: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = self._json("/results", athlete_id=athlete_id, metric_id=metric_id, since=since, until=until,
                              cursor=cursor, limit=100)
            rows.extend(page["data"])
            cursor = page.get("next_cursor")
            if not cursor:
                return rows

    def results_csv(self, **query: Any) -> list[dict[str, str]]:
        """The first page of /results?format=csv as rows, the same table Excel's From Web import shows."""
        text = self.get("/results", format="csv", **query).decode("utf-8")
        return list(csv.DictReader(io.StringIO(text)))
