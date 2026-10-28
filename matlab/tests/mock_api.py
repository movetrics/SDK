"""Stand-in for the Cloud read API v1, for the MATLAB tests: python3 tests/mock_api.py 8765, then
MOVETRICS_TEST_BASE=http://127.0.0.1:8765/api/v1. Pages like services/api/app/api_v1.py; token mvt_test."""

import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

N = 250_000


class Api(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if self.headers.get("Authorization") != "Bearer mvt_test":
            return self.send(401, {"detail": {"code": "UNAUTHORIZED", "message": "token"}})
        if url.path == "/api/v1/recordings":
            more = "cursor" not in q
            return self.send(200, {"data": [{"id": "r2" if more else "r1", "movement": "Countermovement jump"}],
                                   "next_cursor": "c1" if more else None})
        if url.path == "/api/v1/recordings/r1":
            return self.send(200, {"id": "r1", "samples": {"count": N, "channels": []}})
        if url.path == "/api/v1/recordings/r1/samples" and q.get("format") == ["csv"]:
            start, stop = int(q["start"][0]), min(N, int(q["stop"][0]))
            names = q.get("channel", ["fz"])
            lines = ["sample,time_s," + ",".join(names)]
            lines += [f"{i},{i / 1000},{','.join(str(i) for _ in names)}" for i in range(start, stop)]
            return self.send(200, ("\n".join(lines) + "\n").encode(), "text/csv")
        if url.path == "/api/v1/results":
            return self.send(200, {"data": [{"recording_id": "r1", "metric_id": "jump.height.flight_time", "value": 0.31,
                                             "unit": "m", "method": "jump.height.flight_time", "method_version": "2.0.0"}],
                                   "next_cursor": None})
        return self.send(404, {"detail": {"code": "NOT_FOUND", "message": "Recording not found."}})


HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), Api).serve_forever()
