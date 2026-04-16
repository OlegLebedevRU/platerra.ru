import sys
import unittest
from pathlib import Path

import requests

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = WORKSPACE_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import extract_wayback_content as extractor


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else []
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, handlers):
        self.handlers = handlers
        self.calls = []

    @staticmethod
    def _normalize_params(params):
        normalized = []
        for key, value in (params or {}).items():
            if isinstance(value, list):
                value = tuple(value)
            normalized.append((key, value))
        return tuple(sorted(normalized))

    def get(self, url, params=None, timeout=None):
        normalized_params = self._normalize_params(params)
        self.calls.append((url, normalized_params, timeout))
        key = (url, normalized_params)
        handler = self.handlers[key]
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            result = handler()
            if isinstance(result, Exception):
                raise result
            return result
        return handler


def norm_params(params):
    return FakeSession._normalize_params(params)


class ListSnapshotsTests(unittest.TestCase):
    def make_config(self, **wayback_overrides):
        config = {
            "domain": "platerra.ru",
            "request_timeout_seconds": 5,
            "wayback": {
                "cdx_endpoint": "https://web.archive.org/cdx/search/cdx",
                "collapse": "digest",
                "retries": 1,
                "retry_backoff_seconds": 0,
                "segment_by_year_on_error": True,
                "year_start": 2000,
                "year_end": 2002,
                "request_timeout_seconds": 7,
            },
        }
        config["wayback"].update(wayback_overrides)
        return config

    def test_list_snapshots_uses_bulk_result_when_available(self):
        config = self.make_config()
        params = norm_params(
            {
                "url": "*.platerra.ru/*",
                "output": "json",
                "fl": "timestamp,original,mimetype,statuscode",
                "filter": ["statuscode:200", "mimetype:text/html"],
                "collapse": "digest",
            }
        )
        session = FakeSession(
            {
                (
                    "https://web.archive.org/cdx/search/cdx",
                    params,
                ): FakeResponse(
                    [
                        ["timestamp", "original", "mimetype", "statuscode"],
                        ["20010101000000", "http://platerra.ru/", "text/html", "200"],
                    ]
                )
            }
        )

        snapshots = extractor.list_snapshots(session, config)

        self.assertEqual([(s.timestamp, s.original_url) for s in snapshots], [("20010101000000", "http://platerra.ru/")])
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][2], (5, 7))

    def test_list_snapshots_falls_back_to_yearly_requests(self):
        config = self.make_config(year_start=2001, year_end=2002)
        bulk_params = norm_params(
            {
                "url": "*.platerra.ru/*",
                "output": "json",
                "fl": "timestamp,original,mimetype,statuscode",
                "filter": ["statuscode:200", "mimetype:text/html"],
                "collapse": "digest",
            }
        )
        year_2001_params = norm_params(
            {
                "url": "*.platerra.ru/*",
                "output": "json",
                "fl": "timestamp,original,mimetype,statuscode",
                "filter": ["statuscode:200", "mimetype:text/html"],
                "collapse": "digest",
                "from": "2001",
                "to": "2001",
            }
        )
        year_2002_params = norm_params(
            {
                "url": "*.platerra.ru/*",
                "output": "json",
                "fl": "timestamp,original,mimetype,statuscode",
                "filter": ["statuscode:200", "mimetype:text/html"],
                "collapse": "digest",
                "from": "2002",
                "to": "2002",
            }
        )
        endpoint = "https://web.archive.org/cdx/search/cdx"
        session = FakeSession(
            {
                (endpoint, bulk_params): requests.exceptions.SSLError("EOF during handshake"),
                (endpoint, year_2001_params): FakeResponse(
                    [
                        ["timestamp", "original", "mimetype", "statuscode"],
                        ["20010101000000", "http://platerra.ru/", "text/html", "200"],
                    ]
                ),
                (endpoint, year_2002_params): FakeResponse(
                    [
                        ["timestamp", "original", "mimetype", "statuscode"],
                        ["20010101000000", "http://platerra.ru/", "text/html", "200"],
                        ["20020202000000", "http://platerra.ru/about", "text/html", "200"],
                    ]
                ),
            }
        )

        snapshots = extractor.list_snapshots(session, config)

        self.assertEqual(
            [(s.timestamp, s.original_url) for s in snapshots],
            [
                ("20010101000000", "http://platerra.ru/"),
                ("20020202000000", "http://platerra.ru/about"),
            ],
        )
        self.assertEqual(len(session.calls), 3)

    def test_list_snapshots_raises_detailed_error_when_all_attempts_fail(self):
        config = self.make_config(year_start=2001, year_end=2001)
        endpoint = "https://web.archive.org/cdx/search/cdx"
        bulk_params = norm_params(
            {
                "url": "*.platerra.ru/*",
                "output": "json",
                "fl": "timestamp,original,mimetype,statuscode",
                "filter": ["statuscode:200", "mimetype:text/html"],
                "collapse": "digest",
            }
        )
        year_params = norm_params(
            {
                "url": "*.platerra.ru/*",
                "output": "json",
                "fl": "timestamp,original,mimetype,statuscode",
                "filter": ["statuscode:200", "mimetype:text/html"],
                "collapse": "digest",
                "from": "2001",
                "to": "2001",
            }
        )
        session = FakeSession(
            {
                (endpoint, bulk_params): requests.exceptions.ReadTimeout("bulk timeout"),
                (endpoint, year_params): requests.exceptions.SSLError("handshake failed"),
            }
        )

        with self.assertRaises(extractor.WaybackEnumerationError) as ctx:
            extractor.list_snapshots(session, config)

        message = str(ctx.exception)
        self.assertIn("Wayback CDX enumeration failed.", message)
        self.assertIn("bulk timeout", message)
        self.assertIn("handshake failed", message)


if __name__ == "__main__":
    unittest.main()



