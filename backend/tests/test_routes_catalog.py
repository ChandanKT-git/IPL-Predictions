"""Route-level tests for the catalog and live-XI endpoints (task 7.1).

Verifies the wiring in ``backend/server.py`` after the Cricbuzz refactor:

* ``GET /api/teams``                          → live/cache/fallback + ``X-Data-Source``
* ``GET /api/teams/{id}/players``             → live/cache/fallback + ``X-Data-Source`` + 404 for unknown ids
* ``GET /api/venues``                         → live/cache/fallback + ``X-Data-Source``
* ``GET /api/live-match-xi/{match_id}``       → maps the resolver's tagged-union outcomes to the
                                                live-only error matrix (Requirements 3.4, 3.5, 3.6)

The Cricbuzz integration is exercised through a ``StubCricbuzzService``
duck type so the tests do not hit the real RapidAPI host. We monkeypatch
``server.resolver`` after FastAPI's startup hook runs so the global
singletons stay intact for the rest of the suite.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Optional

# Ensure ``backend`` modules are importable when running ``pytest`` from
# the repo root.
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Some downstream modules require MONGO_URL / DB_NAME at import time.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "ipl_test")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from cache_layer import CacheLayer  # noqa: E402
from data_resolver import DataResolver  # noqa: E402
from ipl_data import TEAMS, VENUES, get_players  # noqa: E402


# ---------------------------------------------------------------------------
# Stub Cricbuzz service. Hand-coded duck type covering the methods the
# resolver consumes — no real httpx/RapidAPI traffic.
# ---------------------------------------------------------------------------


class StubCricbuzzService:
    """Duck-typed stand-in for ``CricbuzzService``."""

    def __init__(
        self,
        series_id: Optional[int] = 7607,
        squads: Optional[list[dict[str, Any]]] = None,
        players_by_squad_id: Optional[dict[int, Optional[list[dict]]]] = None,
        venues: Optional[list[dict[str, Any]]] = None,
        scorecard_outcome: Optional[dict] = None,
        has_api_key: bool = True,
    ) -> None:
        self._series_id = series_id
        self._squads = squads
        self._players_by_squad_id = players_by_squad_id or {}
        self._venues = venues
        self._scorecard_outcome = scorecard_outcome
        self.has_api_key = has_api_key

    async def get_ipl_series_id(self) -> Optional[int]:
        return self._series_id

    async def get_squads(self, series_id: int) -> Optional[list[dict[str, Any]]]:
        return self._squads

    async def get_squad_players(
        self, series_id: int, squad_id: int
    ) -> Optional[list[dict[str, Any]]]:
        return self._players_by_squad_id.get(squad_id)

    async def get_series_venues(
        self, series_id: int
    ) -> Optional[list[dict[str, Any]]]:
        return self._venues

    async def fetch_match_scorecard_detail(self, match_id: int) -> dict:
        return self._scorecard_outcome or {"kind": "ok", "payload": {}}


def _full_squads_payload() -> list[dict[str, Any]]:
    return [
        {"squadId": 100, "teamId": 200, "squadType": "Mumbai Indians", "imageId": 9001},
        {"squadId": 101, "teamId": 201, "squadType": "Chennai Super Kings", "imageId": 9002},
        {"squadId": 102, "teamId": 202, "squadType": "Royal Challengers Bengaluru", "imageId": 9003},
        {"squadId": 103, "teamId": 203, "squadType": "Kolkata Knight Riders", "imageId": 9004},
        {"squadId": 104, "teamId": 204, "squadType": "Delhi Capitals", "imageId": 9005},
        {"squadId": 105, "teamId": 205, "squadType": "Punjab Kings", "imageId": 9006},
        {"squadId": 106, "teamId": 206, "squadType": "Rajasthan Royals", "imageId": 9007},
        {"squadId": 107, "teamId": 207, "squadType": "Sunrisers Hyderabad", "imageId": 9008},
        {"squadId": 108, "teamId": 208, "squadType": "Gujarat Titans", "imageId": 9009},
        {"squadId": 109, "teamId": 209, "squadType": "Lucknow Super Giants", "imageId": 9010},
    ]


def _mi_player_payload() -> list[dict]:
    return [
        {"isHeader": True, "name": "batsman"},
        {"id": 7000, "name": "Rohit Sharma", "role": "Batsman", "faceImageId": 1001, "teamName": "IND"},
        {"id": 7001, "name": "Suryakumar Yadav", "role": "Batsman", "faceImageId": 1002, "teamName": "IND"},
        {"isHeader": True, "name": "bowler"},
        {"id": 7002, "name": "Jasprit Bumrah", "role": "Bowler", "faceImageId": 1003, "teamName": "IND"},
    ]


def _mock_scorecard_payload() -> dict:
    return {
        "scoreCard": [
            {
                "batTeamDetails": {
                    "batTeamId": 200,
                    "batTeamName": "Mumbai Indians",
                    "playersData": {
                        "7000": {
                            "id": 7000,
                            "name": "Rohit Sharma",
                            "batOrder": 1,
                            "role": "Batsman",
                            "faceImageId": 1001,
                        },
                        "7001": {
                            "id": 7001,
                            "name": "Suryakumar Yadav",
                            "batOrder": 2,
                            "role": "Batsman",
                            "faceImageId": 1002,
                        },
                    },
                },
            },
            {
                "batTeamDetails": {
                    "batTeamId": 201,
                    "batTeamName": "Chennai Super Kings",
                    "playersData": {
                        "8000": {
                            "id": 8000,
                            "name": "MS Dhoni",
                            "batOrder": 4,
                            "role": "WK-Batsman",
                            "faceImageId": 5000,
                        },
                    },
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# Fixture: build a TestClient with a clean cache and stub-driven resolver.
# ---------------------------------------------------------------------------


def _client_with_resolver(svc: StubCricbuzzService) -> TestClient:
    """Return a ``TestClient`` whose ``server.resolver`` uses ``svc``.

    The fixture wires a fresh ``CacheLayer`` and ``DataResolver`` per
    invocation so individual tests cannot leak cached state into one
    another. The original module-level singletons in ``server`` are saved
    and restored by the test class's ``setUp``/``tearDown`` hooks.
    """
    server.cache = CacheLayer()
    server.cricbuzz = svc  # type: ignore[assignment]
    server.resolver = DataResolver(svc=svc, cache=server.cache)  # type: ignore[arg-type]
    # ``TestClient`` runs the FastAPI startup hook which would otherwise
    # overwrite our injected resolver; we sidestep that by NOT entering
    # the context manager (the lifespan is only triggered on ``__enter__``
    # since starlette ≥ 0.31). For older starlette we re-overwrite after
    # construction — safe either way.
    client = TestClient(server.app)
    server.cache = server.cache
    server.cricbuzz = svc  # type: ignore[assignment]
    server.resolver = DataResolver(svc=svc, cache=server.cache)  # type: ignore[arg-type]
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class _RouteTestBase(unittest.TestCase):
    """Base class that snapshots the global resolver singletons."""

    def setUp(self) -> None:
        self._saved = (server.cache, server.cricbuzz, server.resolver)

    def tearDown(self) -> None:
        server.cache, server.cricbuzz, server.resolver = self._saved


class TestTeamsRoute(_RouteTestBase):
    def test_live_path_sets_x_data_source_header(self) -> None:
        svc = StubCricbuzzService(squads=_full_squads_payload())
        client = _client_with_resolver(svc)
        r = client.get("/api/teams")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("X-Data-Source"), "live")
        body = r.json()
        self.assertEqual(len(body), 10)
        for record in body:
            self.assertEqual(record["source"], "live")

    def test_cache_path_sets_x_data_source_header(self) -> None:
        svc = StubCricbuzzService(squads=_full_squads_payload())
        client = _client_with_resolver(svc)
        # Warm the cache.
        first = client.get("/api/teams")
        self.assertEqual(first.headers.get("X-Data-Source"), "live")
        # Second call must hit the cache.
        second = client.get("/api/teams")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers.get("X-Data-Source"), "cache")
        for record in second.json():
            self.assertEqual(record["source"], "cache")

    def test_fallback_path_sets_x_data_source_header(self) -> None:
        svc = StubCricbuzzService(series_id=None, squads=None)
        client = _client_with_resolver(svc)
        r = client.get("/api/teams")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("X-Data-Source"), "fallback")
        body = r.json()
        self.assertEqual(len(body), 10)
        for record in body:
            self.assertEqual(record["source"], "fallback")

    def test_response_shape_preserves_static_keys(self) -> None:
        svc = StubCricbuzzService(squads=_full_squads_payload())
        client = _client_with_resolver(svc)
        r = client.get("/api/teams")
        body = r.json()
        ids = [t["id"] for t in body]
        self.assertEqual(set(ids), {t["id"] for t in TEAMS})
        for record in body:
            for key in ("id", "name", "short_name", "primary_color",
                        "secondary_color", "rating",
                        "cricbuzz_team_id", "image_id", "source"):
                self.assertIn(key, record)


class TestPlayersRoute(_RouteTestBase):
    def test_live_path_returns_players_with_source(self) -> None:
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: _mi_player_payload()},
        )
        client = _client_with_resolver(svc)
        r = client.get("/api/teams/mi/players")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("X-Data-Source"), "live")
        body = r.json()
        self.assertGreater(len(body), 0)
        for record in body:
            self.assertEqual(record["source"], "live")
            for key in ("name", "role", "batting_avg",
                        "strike_rate", "wickets", "economy", "country",
                        "image_id", "cricbuzz_player_id"):
                self.assertIn(key, record)

    def test_unknown_team_id_returns_404(self) -> None:
        svc = StubCricbuzzService(squads=_full_squads_payload())
        client = _client_with_resolver(svc)
        r = client.get("/api/teams/not_a_team/players")
        self.assertEqual(r.status_code, 404)

    def test_unknown_team_id_404_on_fallback_path_too(self) -> None:
        svc = StubCricbuzzService(series_id=None, squads=None)
        client = _client_with_resolver(svc)
        r = client.get("/api/teams/zzz/players")
        self.assertEqual(r.status_code, 404)

    def test_fallback_path_returns_static_roster(self) -> None:
        svc = StubCricbuzzService(series_id=None, squads=None)
        client = _client_with_resolver(svc)
        r = client.get("/api/teams/mi/players")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("X-Data-Source"), "fallback")
        body = r.json()
        self.assertEqual(len(body), len(get_players("mi")))
        for record in body:
            self.assertEqual(record["source"], "fallback")
            self.assertIsNone(record["cricbuzz_player_id"])


class TestVenuesRoute(_RouteTestBase):
    def test_live_path(self) -> None:
        svc = StubCricbuzzService(
            venues=[
                {"id": 27, "ground": "Wankhede Stadium", "city": "Mumbai"},
            ],
        )
        client = _client_with_resolver(svc)
        r = client.get("/api/venues")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("X-Data-Source"), "live")
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["id"], "wankhede")
        self.assertEqual(body[0]["source"], "live")

    def test_fallback_path(self) -> None:
        svc = StubCricbuzzService(series_id=None, venues=None)
        client = _client_with_resolver(svc)
        r = client.get("/api/venues")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("X-Data-Source"), "fallback")
        body = r.json()
        self.assertEqual(len(body), len(VENUES))
        for record in body:
            self.assertEqual(record["source"], "fallback")
            self.assertIsNone(record["cricbuzz_venue_id"])

    def test_empty_live_returns_empty_array_with_live_header(self) -> None:
        svc = StubCricbuzzService(venues=[])
        client = _client_with_resolver(svc)
        r = client.get("/api/venues")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("X-Data-Source"), "live")
        self.assertEqual(r.json(), [])


class TestLiveMatchXiRoute(_RouteTestBase):
    def test_missing_key_returns_503(self) -> None:
        svc = StubCricbuzzService(has_api_key=False)
        client = _client_with_resolver(svc)
        r = client.get("/api/live-match-xi/12345")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(
            r.json(),
            {"detail": "Cricbuzz API key not configured", "source": "fallback"},
        )

    def test_auth_failed_returns_503(self) -> None:
        svc = StubCricbuzzService(
            has_api_key=True,
            scorecard_outcome={"kind": "auth_failed", "status": 401},
        )
        client = _client_with_resolver(svc)
        r = client.get("/api/live-match-xi/12345")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(
            r.json(),
            {"detail": "Cricbuzz authentication failed", "source": "fallback"},
        )

    def test_upstream_non_2xx_returns_502(self) -> None:
        svc = StubCricbuzzService(
            has_api_key=True,
            scorecard_outcome={"kind": "upstream", "status": 500},
        )
        client = _client_with_resolver(svc)
        r = client.get("/api/live-match-xi/12345")
        self.assertEqual(r.status_code, 502)
        body = r.json()
        self.assertEqual(body["detail"], "Cricbuzz upstream error")
        self.assertEqual(body["status"], 500)

    def test_unparseable_returns_502(self) -> None:
        svc = StubCricbuzzService(
            has_api_key=True,
            scorecard_outcome={"kind": "unparseable"},
        )
        client = _client_with_resolver(svc)
        r = client.get("/api/live-match-xi/12345")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(
            r.json(),
            {"detail": "Cricbuzz returned an unparseable scorecard"},
        )

    def test_network_error_returns_502(self) -> None:
        # Network failures from the service collapse to upstream/503 in
        # the resolver outcome, which the route maps to HTTP 502.
        svc = StubCricbuzzService(
            has_api_key=True,
            scorecard_outcome={"kind": "network"},
        )
        client = _client_with_resolver(svc)
        r = client.get("/api/live-match-xi/12345")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["detail"], "Cricbuzz upstream error")

    def test_ok_returns_augmented_scorecard_with_xi(self) -> None:
        svc = StubCricbuzzService(
            has_api_key=True,
            scorecard_outcome={
                "kind": "ok",
                "payload": _mock_scorecard_payload(),
            },
        )
        client = _client_with_resolver(svc)
        r = client.get("/api/live-match-xi/12345")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("xi", body)
        self.assertIn("mi", body["xi"])
        self.assertIn("csk", body["xi"])
        self.assertEqual(
            [p["name"] for p in body["xi"]["mi"]],
            ["Rohit Sharma", "Suryakumar Yadav"],
        )
        self.assertEqual(body["source"], "live")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
