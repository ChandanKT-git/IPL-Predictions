"""Tests for the new endpoints introduced in this milestone:

* ``GET  /api/upcoming-matches``
* ``POST /api/predictions/{id}/reconcile``
* ``GET  /api/calibration``
* ``GET  /api/live-match-score/{id}/stream`` (SSE — header / opening frame only)

All Cricbuzz-touching tests use a duck-typed stub to avoid hitting RapidAPI.
The reconcile and calibration tests use an in-memory pseudo Mongo so no
real MongoDB is required.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from typing import Any, Optional
from unittest import mock

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "ipl_test")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


class StubCricbuzzService:
    def __init__(self, upcoming: Optional[dict] = None, has_api_key: bool = True) -> None:
        self._upcoming = upcoming
        self.has_api_key = has_api_key

    async def get_upcoming_matches(self) -> Optional[dict]:
        return self._upcoming

    async def get_match_info(self, match_id: int) -> Optional[dict]:
        return {"miniscore": {"batTeamScore": "120/3 (15.0)", "status": "MI 120/3"}}

    async def fetch_image(self, *args, **kwargs):
        return None


class FakeCollection:
    """Minimal in-memory async collection mirroring the calls server.py uses."""

    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def create_index(self, *args, **kwargs):
        return None

    async def insert_one(self, doc: dict):
        self.docs.append(doc)

        class _Result:
            inserted_id = "x"

        return _Result()

    async def find_one(self, q: dict, projection: Optional[dict] = None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items() if not k.startswith("output.")):
                return _strip(d, projection)
        return None

    async def update_one(self, q: dict, update: dict):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                self._apply_update(d, update)

                class _Result:
                    modified_count = 1

                return _Result()

        class _Result:
            modified_count = 0

        return _Result()

    @staticmethod
    def _apply_update(doc: dict, update: dict) -> None:
        for op, payload in update.items():
            if op == "$set":
                for path, value in payload.items():
                    parts = path.split(".")
                    node = doc
                    for part in parts[:-1]:
                        node = node.setdefault(part, {})
                    node[parts[-1]] = value

    def find(self, q: dict, projection: Optional[dict] = None):
        matches: list[dict] = []
        for d in self.docs:
            ok = True
            for key, expected in q.items():
                if isinstance(expected, dict) and "$ne" in expected:
                    actual = _resolve(d, key)
                    if actual is None or actual == expected["$ne"]:
                        ok = False
                        break
                else:
                    if d.get(key) != expected:
                        ok = False
                        break
            if ok:
                matches.append(_strip(d, projection))
        return _Cursor(matches)


def _resolve(doc: dict, dotted: str):
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _strip(doc: dict, projection: Optional[dict]):
    if not projection:
        return doc
    if all(v == 1 for v in projection.values()):
        return {k: doc.get(k) for k in projection}
    return {k: v for k, v in doc.items() if projection.get(k) != 0}


class _Cursor:
    def __init__(self, items: list[dict]) -> None:
        self._items = items

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, n: int):
        self._items = self._items[:n]
        return self

    async def to_list(self, length: int):
        return self._items[:length]


class _RouteTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (server.cricbuzz, server.db)
        server.cricbuzz = StubCricbuzzService()
        # Patch only the predictions collection so we don't break startup.
        self._fake = FakeCollection()
        server.db = mock.MagicMock()
        server.db.predictions = self._fake
        server.db.admin = mock.MagicMock(command=mock.AsyncMock(return_value={}))
        self.client = TestClient(server.app)

    def tearDown(self) -> None:
        server.cricbuzz, server.db = self._saved


class TestUpcomingMatches(_RouteTestBase):
    def test_returns_payload_when_cricbuzz_replies(self) -> None:
        server.cricbuzz = StubCricbuzzService(
            upcoming={
                "typeMatches": [
                    {
                        "seriesMatches": [
                            {
                                "seriesAdWrapper": {
                                    "matches": [
                                        {
                                            "matchInfo": {
                                                "matchId": 99,
                                                "seriesName": "Indian Premier League 2026",
                                                "team1": {"teamName": "MI"},
                                                "team2": {"teamName": "CSK"},
                                                "venueInfo": {
                                                    "ground": "Wankhede",
                                                    "city": "Mumbai",
                                                },
                                                "startDate": "1748462400000",
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        )
        r = self.client.get("/api/upcoming-matches")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(
            body["typeMatches"][0]["seriesMatches"][0]["seriesAdWrapper"]
                ["matches"][0]["matchInfo"]["matchId"],
            99,
        )

    def test_returns_empty_payload_when_cricbuzz_unavailable(self) -> None:
        server.cricbuzz = StubCricbuzzService(upcoming=None, has_api_key=False)
        r = self.client.get("/api/upcoming-matches")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"typeMatches": []})


class TestReconcileAndCalibration(_RouteTestBase):
    def _seed(self, *, predicted_score=170, low=150, high=190, prob=60,
              actual_score=178, winner="csk", batting_team_id="csk",
              bowling_team_id="mi"):
        doc = {
            "id": "abc",
            "input": {"team_a": batting_team_id, "team_b": bowling_team_id},
            "output": {
                "predicted_score": predicted_score,
                "score_range_low": low,
                "score_range_high": high,
                "win_probability_batting": prob,
                "batting_team_id": batting_team_id,
                "bowling_team_id": bowling_team_id,
            },
        }
        self._fake.docs.append(doc)
        return doc

    def test_reconcile_records_actual(self) -> None:
        self._seed()
        r = self.client.post(
            "/api/predictions/abc/reconcile",
            json={"actual_score": 178, "actual_winner": "csk"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["score_error"], 8)  # 178 - 170
        self.assertTrue(body["inside_interval"])
        self.assertTrue(body["correct_winner"])
        # Persisted under output.actual.
        doc = self._fake.docs[0]
        self.assertIn("actual", doc["output"])
        self.assertEqual(doc["output"]["actual"]["score_error"], 8)

    def test_reconcile_marks_outside_interval(self) -> None:
        self._seed(low=160, high=180, predicted_score=170)
        r = self.client.post(
            "/api/predictions/abc/reconcile",
            json={"actual_score": 220, "actual_winner": "mi"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["score_error"], 50)
        self.assertFalse(body["inside_interval"])
        # The favourite was the batting team (prob 60); actual_winner is MI → wrong.
        self.assertFalse(body["correct_winner"])

    def test_reconcile_404_for_unknown_id(self) -> None:
        r = self.client.post(
            "/api/predictions/missing/reconcile",
            json={"actual_score": 100},
        )
        self.assertEqual(r.status_code, 404)

    def test_calibration_aggregates_reconciled_rows(self) -> None:
        self._seed()
        # Reconcile two predictions to populate calibration.
        self.client.post(
            "/api/predictions/abc/reconcile",
            json={"actual_score": 178, "actual_winner": "csk"},
        )
        self._fake.docs.append({
            "id": "def",
            "input": {"team_a": "csk", "team_b": "mi"},
            "output": {
                "predicted_score": 170, "score_range_low": 150, "score_range_high": 190,
                "win_probability_batting": 30,
                "batting_team_id": "csk", "bowling_team_id": "mi",
            },
        })
        self.client.post(
            "/api/predictions/def/reconcile",
            json={"actual_score": 200, "actual_winner": "mi"},
        )
        r = self.client.get("/api/calibration")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["count"], 2)
        self.assertGreater(body["mae"], 0)
        # Both correctly classified — abc's favourite was CSK (won),
        # def's favourite was MI (won). 100% win accuracy.
        self.assertEqual(body["win_accuracy"], 1.0)
        self.assertGreaterEqual(len(body["win_calibration"]), 1)


class TestSseStream(_RouteTestBase):
    """Test the SSE generator directly to avoid TestClient hanging on reads."""

    def _consume_first_frame(self, route_response) -> bytes:
        """Pull frames from a StreamingResponse body until we have one."""
        async def _drain() -> bytes:
            buf = b""
            try:
                async for chunk in route_response.body_iterator:
                    buf += chunk
                    if b"\n\n" in buf:
                        break
            finally:
                # Drain and close the underlying generator so pytest doesn't
                # raise a "coroutine was never awaited" warning.
                close = getattr(route_response.body_iterator, "aclose", None)
                if callable(close):
                    await close()
            return buf

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_drain())
        finally:
            loop.close()

    def test_stream_emits_score_event_when_cricbuzz_responds(self) -> None:
        with mock.patch.object(server, "SSE_INTERVAL_SECONDS", 0.05):
            request = mock.MagicMock()
            request.is_disconnected = mock.AsyncMock(return_value=False)
            response = asyncio.new_event_loop().run_until_complete(
                server.live_match_score_stream(123, request)
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            buf = self._consume_first_frame(response)
            self.assertIn(b"event: score", buf)
            line = buf.split(b"data: ", 1)[1].split(b"\n", 1)[0]
            payload = json.loads(line)
            self.assertEqual(payload["miniscore"]["batTeamScore"], "120/3 (15.0)")

    def test_stream_returns_error_frame_when_key_missing(self) -> None:
        server.cricbuzz = StubCricbuzzService(has_api_key=False)
        request = mock.MagicMock()
        request.is_disconnected = mock.AsyncMock(return_value=False)
        response = asyncio.new_event_loop().run_until_complete(
            server.live_match_score_stream(123, request)
        )
        self.assertEqual(response.status_code, 200)
        buf = self._consume_first_frame(response)
        self.assertIn(b"event: error", buf)
        self.assertIn(b"Cricbuzz API key not configured", buf)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
