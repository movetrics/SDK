"""CloudClient against a local stand-in for /api/v1 that pages the way api_v1.py does (no network, no token)."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from movetrics_fdt.cloud import CloudClient, CloudError

TOKEN = "mvt_test"
N = 250_000  # three sample pages of at most 100,000


class _Api(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def _send(self, status: int, body: Any, kind: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"detail": {"code": "UNAUTHORIZED", "message": "Send an access token"}})
        if url.path == "/api/v1/recordings":
            if "cursor" not in query:
                return self._send(200, {"data": [{"id": "r2"}], "next_cursor": "c1"})
            return self._send(200, {"data": [{"id": "r1"}], "next_cursor": None})
        if url.path == "/api/v1/recordings/r1/samples":
            start, stop = int(query["start"][0]), min(N, int(query["stop"][0]))
            names = query.get("channel", ["fz"])
            return self._send(200, {"canonical_digest": "d", "sample_count": N, "start": start, "stop": stop,
                                    "next_start": stop if stop < N else None, "time_s": [i / 1000 for i in range(start, stop)],
                                    "channels": {name: list(range(start, stop)) for name in names}})
        if url.path == "/api/v1/results" and query.get("format") == ["csv"]:
            return self._send(200, b"recording_id,metric_id,value\nr1,jump.height.flight_time,0.31\n", "text/csv")
        return self._send(404, {"detail": {"code": "NOT_FOUND", "message": "Recording not found."}})


def _redirecting_handler(target: str) -> type[BaseHTTPRequestHandler]:
    class _Redirect(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()

    return _Redirect


class CloudClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), _Api)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}/api/v1"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def test_recordings_follow_the_cursor(self) -> None:
        self.assertEqual([r["id"] for r in CloudClient(TOKEN, self.base).recordings()], ["r2", "r1"])

    def test_samples_join_every_page_in_order(self) -> None:
        samples = CloudClient(TOKEN, self.base).samples("r1", channels=["fz", "fx"])
        self.assertEqual(len(samples["time_s"]), N)
        self.assertEqual(samples["channels"]["fz"][:2] + samples["channels"]["fz"][-1:], [0, 1, N - 1])
        self.assertEqual(sorted(samples["channels"]), ["fx", "fz"])

    def test_a_window_stops_where_asked(self) -> None:
        samples = CloudClient(TOKEN, self.base).samples("r1", start=10, stop=20)
        self.assertEqual(samples["channels"]["fz"], list(range(10, 20)))

    def test_results_csv(self) -> None:
        rows = CloudClient(TOKEN, self.base).results_csv()
        self.assertEqual(rows[0]["metric_id"], "jump.height.flight_time")

    def test_errors_carry_the_server_code(self) -> None:
        with self.assertRaises(CloudError) as raised:
            CloudClient(TOKEN, self.base).recording("nope")
        self.assertEqual((raised.exception.status, raised.exception.code), (404, "NOT_FOUND"))
        with self.assertRaises(CloudError) as raised:
            CloudClient("mvt_wrong", self.base).me()
        self.assertEqual(raised.exception.code, "UNAUTHORIZED")

    def test_a_token_must_look_like_one(self) -> None:
        with self.assertRaises(ValueError):
            CloudClient("secret")

    def test_a_non_local_http_base_is_refused(self) -> None:
        for base in ("http://example.com/api/v1", "http://localhost.example.com/api/v1", "ftp://example.com/api/v1"):
            with self.subTest(base=base), self.assertRaises(ValueError):
                CloudClient(TOKEN, base)

    def test_local_http_bases_are_allowed(self) -> None:
        port = self.server.server_port
        for host in ("localhost", "127.0.0.1", "[::1]"):
            with self.subTest(host=host):
                CloudClient(TOKEN, f"http://{host}:{port}/api/v1")

    def test_a_cross_origin_redirect_is_refused_and_gets_no_token(self) -> None:
        seen: list[dict[str, str]] = []

        class _Collector(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                seen.append(dict(self.headers))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

        elsewhere = HTTPServer(("127.0.0.1", 0), _Collector)
        threading.Thread(target=elsewhere.serve_forever, daemon=True).start()
        redirector = HTTPServer(("127.0.0.1", 0),
                                _redirecting_handler(f"http://127.0.0.1:{elsewhere.server_port}/steal"))
        threading.Thread(target=redirector.serve_forever, daemon=True).start()
        try:
            cloud = CloudClient(TOKEN, f"http://127.0.0.1:{redirector.server_port}/api/v1")
            with self.assertRaises(CloudError) as raised:
                cloud.get("/me")
            self.assertEqual(raised.exception.code, "REDIRECT_REFUSED")
            self.assertEqual(seen, [])
        finally:
            redirector.shutdown()
            elsewhere.shutdown()
            redirector.server_close()
            elsewhere.server_close()


if __name__ == "__main__":
    unittest.main()
