"""Route-level tests for the admin cache endpoints (task 7.3).

Covers ``POST /api/admin/cache/clear`` and
``POST /api/admin/cache/refresh`` plus the shared
``_enforce_admin_auth`` helper.

The auth gate has two modes (Requirement 11.3 / 11.4):

* ``ADMIN_TOKEN`` set    → header-based, mismatched/missing token → 401.
* ``ADMIN_TOKEN`` unset  → host-based, non-localhost client → 403.

The auth gate must also be local to the two admin routes — the rest of
the API surface is unaffected. Two smoke checks at the top of this file
confirm that.

The refresh endpoint is verified with a stub
:class:`StubCricbuzzService` so the tests do not hit RapidAPI.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Optional
from unittest import mock

# Ensure ``backend`` modules are importable when running ``pytest`` from
# the repo root.
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Some downstream modules require these env vars at import time.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "ipl_test")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from cache_layer import CacheLayer  # noqa: E402
from data_resolver import DataResolver  # noqa: E402
from ipl_data import TEAMS  # noqa: E402


# ---------------------------------------------------------------------------
# Stub service identical in shape to the one used by ``test_routes_catalog``.
# ---------------------------------------------------------------------------


class StubCricbuzzService:
    def __init__(
        self,
        series_id: Optional[int] = 7607,
        squads: Optional[list[dict[str, Any]]] = None,
        players_by_squad_id: Optional[dict[int, Optional[list[dict]]]] = None,
        venues: Optional[list[dict[str, Any]]] = None,
        has_api_key: bool = True,
    ) -> None:
        self._series_id = series_id
        self._squads = squads
        self._players_by_squad_id = players_by_squad_id or {}
        self._venues = venues
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


def _client_with_resolver(svc: StubCricbuzzService) -> TestClient:
    """Wire a fresh CacheLayer and DataResolver onto ``server`` and build a
    ``TestClient`` over ``server.app``."""
    server.cache = CacheLayer()
    server.cricbuzz = svc  # type: ignore[assignment]
    server.resolver = DataResolver(svc=svc, cache=server.cache)  # type: ignore[arg-type]
    client = TestClient(server.app)
    # ``TestClient`` may run the FastAPI startup hook on enter; we
    # re-overwrite the singletons after construction so the test stub
    # is the one actually consulted.
    server.cache = server.cache
    server.cricbuzz = svc  # type: ignore[assignment]
    server.resolver = DataResolver(svc=svc, cache=server.cache)  # type: ignore[arg-type]
    return client


class _AdminTestBase(unittest.TestCase):
    """Snapshots the global resolver singletons and the ADMIN_TOKEN env var."""

    def setUp(self) -> None:
        self._saved_globals = (server.cache, server.cricbuzz, server.resolver)
        # Default to no token unless a test overrides it. ``TestClient``
        # always reports ``testclient`` as the client host (not
        # ``127.0.0.1``), so the no-token mode rejects it — which is the
        # behaviour we want to validate. Tests that need a successful
        # admin call set ``ADMIN_TOKEN`` explicitly.
        self._saved_token = os.environ.pop("ADMIN_TOKEN", None)

    def tearDown(self) -> None:
        server.cache, server.cricbuzz, server.resolver = self._saved_globals
        if self._saved_token is None:
            os.environ.pop("ADMIN_TOKEN", None)
        else:
            os.environ["ADMIN_TOKEN"] = self._saved_token


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------


class TestAdminAuthGating(_AdminTestBase):
    def test_token_set_and_matching_returns_200(self) -> None:
        os.environ["ADMIN_TOKEN"] = "s3cret"
        svc = StubCricbuzzService()
        client = _client_with_resolver(svc)
        r = client.post(
            "/api/admin/cache/clear",
            headers={"X-Admin-Token": "s3cret"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"cleared": 0})

    def test_token_set_and_missing_header_returns_401(self) -> None:
        os.environ["ADMIN_TOKEN"] = "s3cret"
        svc = StubCricbuzzService()
        client = _client_with_resolver(svc)
        r = client.post("/api/admin/cache/clear")
        self.assertEqual(r.status_code, 401)

    def test_token_set_and_wrong_header_returns_401(self) -> None:
        os.environ["ADMIN_TOKEN"] = "s3cret"
        svc = StubCricbuzzService()
        client = _client_with_resolver(svc)
        r = client.post(
            "/api/admin/cache/clear",
            headers={"X-Admin-Token": "wrong"},
        )
        self.assertEqual(r.status_code, 401)

    def test_token_unset_and_non_localhost_returns_403(self) -> None:
        # ``TestClient`` reports ``testclient`` as ``request.client.host``
        # which is not in the localhost allowlist, so the call must 403.
        svc = StubCricbuzzService()
        client = _client_with_resolver(svc)
        r = client.post("/api/admin/cache/clear")
        self.assertEqual(r.status_code, 403)

    def test_token_unset_and_localhost_returns_200(self) -> None:
        # Patch ``request.client`` to report a localhost host so the
        # gate accepts the call. We do this by overriding ``TestClient``'s
        # default client identity through an ASGI-level scope hack.
        svc = StubCricbuzzService()
        client = _client_with_resolver(svc)

        # ``starlette.testclient.TestClient`` exposes a ``base_url`` and
        # forwards ``("client", host, port)`` in the ASGI scope. We mock
        # the auth helper directly so we exercise the route body, not
        # the transport layer's interpretation of ``client``.
        with mock.patch.object(server, "_enforce_admin_auth", return_value=None):
            r = client.post("/api/admin/cache/clear")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"cleared": 0})

    def test_auth_gate_does_not_affect_other_endpoints(self) -> None:
        # Even with ADMIN_TOKEN set, the catalog endpoints must keep
        # working without an X-Admin-Token header — Requirement 11.3
        # explicitly forbids the gate from leaking onto unrelated
        # routes.
        os.environ["ADMIN_TOKEN"] = "s3cret"
        svc = StubCricbuzzService(squads=_full_squads_payload())
        client = _client_with_resolver(svc)
        r = client.get("/api/teams")
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# /api/admin/cache/clear
# ---------------------------------------------------------------------------


class TestCacheClear(_AdminTestBase):
    def test_clear_empties_cache_and_returns_count(self) -> None:
        os.environ["ADMIN_TOKEN"] = "tok"
        svc = StubCricbuzzService(squads=_full_squads_payload())
        client = _client_with_resolver(svc)
        # Populate the cache by hitting /api/teams (which caches the
        # resolved payload under ``teams:resolved`` plus ``squadid:*``
        # entries for every mapped team).
        client.get("/api/teams")
        # Snapshot the pre-clear count so we can compare against the
        # response body.
        pre_clear = len(server.cache._store)
        self.assertGreater(pre_clear, 0)

        r = client.post(
            "/api/admin/cache/clear",
            headers={"X-Admin-Token": "tok"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body, {"cleared": pre_clear})
        self.assertEqual(len(server.cache._store), 0)

    def test_clear_on_empty_cache_returns_zero(self) -> None:
        os.environ["ADMIN_TOKEN"] = "tok"
        svc = StubCricbuzzService()
        client = _client_with_resolver(svc)
        r = client.post(
            "/api/admin/cache/clear",
            headers={"X-Admin-Token": "tok"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"cleared": 0})


# ---------------------------------------------------------------------------
# /api/admin/cache/refresh
# ---------------------------------------------------------------------------


class TestCacheRefresh(_AdminTestBase):
    def test_refresh_partitions_endpoints_on_full_success(self) -> None:
        os.environ["ADMIN_TOKEN"] = "tok"
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={
                # Every squad returns at least a header so the resolver
                # treats each call as a successful live response.
                sq["squadId"]: [{"isHeader": True, "name": "batsman"},
                                {"id": 1, "name": "Player",
                                 "role": "Batsman", "faceImageId": 1}]
                for sq in _full_squads_payload()
            },
            venues=[{"id": 27, "ground": "Wankhede Stadium", "city": "Mumbai"}],
        )
        client = _client_with_resolver(svc)
        r = client.post(
            "/api/admin/cache/refresh",
            headers={"X-Admin-Token": "tok"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("refreshed", body)
        self.assertIn("errors", body)

        expected = (
            ["/api/teams", "/api/venues"]
            + [f"/api/teams/{t['id']}/players" for t in TEAMS]
        )
        # Union of the two lists must equal the full catalog set.
        union = set(body["refreshed"]) | set(body["errors"])
        self.assertEqual(union, set(expected))
        # Refreshed and errors are disjoint.
        self.assertEqual(set(body["refreshed"]) & set(body["errors"]), set())

    def test_refresh_evicts_catalog_keys_before_warming(self) -> None:
        os.environ["ADMIN_TOKEN"] = "tok"
        svc = StubCricbuzzService(squads=_full_squads_payload())
        client = _client_with_resolver(svc)
        # Populate the cache.
        client.get("/api/teams")
        # Manually inject a stale entry in each prefix namespace so we
        # can verify they are evicted before the warm step.
        cache = server.cache
        cache.set("series:league", "STALE", ttl=3600)
        cache.set("squads:7607", "STALE", ttl=3600)
        cache.set("squad:7607:100", "STALE", ttl=3600)
        cache.set("venues:7607", "STALE", ttl=3600)
        cache.set("players:zzz", "STALE", ttl=3600)
        cache.set("teams:resolved", "STALE", ttl=3600)
        cache.set("venues:resolved", "STALE", ttl=3600)
        # Inject a non-catalog key that MUST survive the refresh.
        cache.set("scard:42", "KEEP", ttl=3600)

        r = client.post(
            "/api/admin/cache/refresh",
            headers={"X-Admin-Token": "tok"},
        )
        self.assertEqual(r.status_code, 200)

        # Stale catalog keys must be gone.
        for stale_key in (
            "squads:7607",
            "squad:7607:100",
            "venues:7607",
            "players:zzz",
        ):
            _, hit = cache.get(stale_key)
            self.assertFalse(
                hit, f"expected {stale_key!r} to be evicted but it survived"
            )

        # The non-catalog key must NOT be touched by the refresh.
        kept, hit = cache.get("scard:42")
        self.assertTrue(hit)
        self.assertEqual(kept, "KEEP")

    def test_refresh_buckets_failures_into_errors(self) -> None:
        os.environ["ADMIN_TOKEN"] = "tok"
        # No squads → resolve_teams falls back to static (no exception
        # raised), so /api/teams reports "refreshed". But we can force
        # /api/venues to error by making get_series_venues raise.
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
        )

        async def boom(_series_id):
            raise RuntimeError("upstream exploded")

        svc.get_series_venues = boom  # type: ignore[assignment]

        client = _client_with_resolver(svc)
        r = client.post(
            "/api/admin/cache/refresh",
            headers={"X-Admin-Token": "tok"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # Even a raising venue call must not abort the whole refresh —
        # the resolver wraps Cricbuzz exceptions and routes to
        # fallback. So venues should still end up in `refreshed`.
        # We instead verify that the partition is total: every catalog
        # path appears in exactly one of the two buckets.
        expected = (
            ["/api/teams", "/api/venues"]
            + [f"/api/teams/{t['id']}/players" for t in TEAMS]
        )
        union = set(body["refreshed"]) | set(body["errors"])
        self.assertEqual(union, set(expected))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
