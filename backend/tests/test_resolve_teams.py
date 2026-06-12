"""Smoke and example tests for ``DataResolver.resolve_teams``.

Covers the live, partial-live, cache, and fallback paths defined in
Requirement 1 (clauses 1.1–1.6) and the cache-driven repeat-call behaviour in
Requirement 6.5 / 7.4. Property-based coverage for the ten-id contract lives
in task 6.5 (``test_data_resolver_properties.py``); this file focuses on
representative examples.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from typing import Any, Optional

# Ensure ``backend`` modules are importable when running ``pytest`` from the
# repo root without an explicit ``conftest.py``.
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Some downstream modules (``server.py``) require MONGO_URL / DB_NAME at
# import time; the resolver itself does not, but be defensive in case the
# environment is sparse.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "ipl_test")

from cache_layer import CacheLayer  # noqa: E402
from data_resolver import (  # noqa: E402
    CATALOG_TTL_SECONDS,
    DataResolver,
    TEAMS_RESOLVED_KEY,
)
from ipl_data import TEAMS  # noqa: E402

from fastapi import HTTPException  # noqa: E402


class StubCricbuzzService:
    """Minimal duck-typed stand-in for ``CricbuzzService``.

    The resolver only calls ``get_ipl_series_id`` and ``get_squads`` on this
    object during ``resolve_teams``. Each test wires the desired return
    values through the constructor.
    """

    def __init__(
        self,
        series_id: Optional[int] = 7607,
        squads: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self._series_id = series_id
        self._squads = squads
        self.series_calls = 0
        self.squad_calls = 0

    async def get_ipl_series_id(self) -> Optional[int]:
        self.series_calls += 1
        return self._series_id

    async def get_squads(self, series_id: int) -> Optional[list[dict[str, Any]]]:
        self.squad_calls += 1
        assert series_id == self._series_id, (
            f"resolver passed an unexpected series id: {series_id!r}"
        )
        return self._squads


def _full_squads_payload() -> list[dict[str, Any]]:
    """Cricbuzz-style squads payload covering all ten franchises.

    The names mix current ("Royal Challengers Bengaluru") and historical
    ("Royal Challengers Bangalore") spellings so we exercise the alias-based
    ID_Mapper resolution.
    """
    return [
        {"squadId": 100, "teamId": 200, "squadType": "Mumbai Indians", "imageId": 9001},
        {"squadId": 101, "teamId": 201, "squadType": "Chennai Super Kings", "imageId": 9002},
        {"squadId": 102, "teamId": 202, "squadType": "Royal Challengers Bangalore", "imageId": 9003},
        {"squadId": 103, "teamId": 203, "squadType": "Kolkata Knight Riders", "imageId": 9004},
        {"squadId": 104, "teamId": 204, "squadType": "Delhi Capitals", "imageId": 9005},
        {"squadId": 105, "teamId": 205, "squadType": "Punjab Kings", "imageId": 9006},
        {"squadId": 106, "teamId": 206, "squadType": "Rajasthan Royals", "imageId": 9007},
        {"squadId": 107, "teamId": 207, "squadType": "Sunrisers Hyderabad", "imageId": 9008},
        {"squadId": 108, "teamId": 208, "squadType": "Gujarat Titans", "imageId": 9009},
        {"squadId": 109, "teamId": 209, "squadType": "Lucknow Super Giants", "imageId": 9010},
    ]


def _arun(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResolveTeamsLivePath(unittest.TestCase):
    """Happy path: full Cricbuzz coverage of all ten franchises."""

    def test_returns_ten_teams_with_live_source(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(squads=_full_squads_payload())
        resolver = DataResolver(svc, cache)

        teams, source = _arun(resolver.resolve_teams())

        self.assertEqual(source, "live")
        self.assertEqual(len(teams), 10)

        ids = [t["id"] for t in teams]
        self.assertEqual(set(ids), {t["id"] for t in TEAMS})
        # No duplicates (Property 3 / Requirement 12.3).
        self.assertEqual(len(ids), len(set(ids)))

        # Every record carries the additive Cricbuzz fields and source="live".
        for record in teams:
            self.assertIn("cricbuzz_team_id", record)
            self.assertIn("cricbuzz_squad_id", record)
            self.assertIn("image_id", record)
            self.assertEqual(record["source"], "live")

        # Static schema preserved.
        for record in teams:
            for key in (
                "id", "name", "short_name",
                "primary_color", "secondary_color",
                "home_venue_id", "captain", "titles", "rating",
            ):
                self.assertIn(key, record)

    def test_records_carry_cricbuzz_ids_and_image(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(squads=_full_squads_payload())
        resolver = DataResolver(svc, cache)

        teams, _ = _arun(resolver.resolve_teams())
        by_id = {t["id"]: t for t in teams}

        mi = by_id["mi"]
        self.assertEqual(mi["cricbuzz_team_id"], 200)
        self.assertEqual(mi["cricbuzz_squad_id"], 100)
        self.assertEqual(mi["image_id"], "9001")
        # name comes from Cricbuzz when the live path is taken
        self.assertEqual(mi["name"], "Mumbai Indians")

    def test_caches_squad_id_mapping_for_resolve_players(self) -> None:
        """Requirement 7.4: per-team Cricbuzz ids are cached for reuse."""
        cache = CacheLayer()
        svc = StubCricbuzzService(squads=_full_squads_payload())
        resolver = DataResolver(svc, cache)

        _arun(resolver.resolve_teams())

        for tid in ("mi", "csk", "rcb", "kkr", "dc",
                    "pbks", "rr", "srh", "gt", "lsg"):
            mapping, hit = cache.get(f"squadid:{tid}")
            self.assertTrue(hit, f"missing squadid mapping for {tid}")
            self.assertEqual(mapping["series_id"], 7607)
            self.assertIn("cricbuzz_team_id", mapping)
            self.assertIn("cricbuzz_squad_id", mapping)


class TestResolveTeamsPartialLiveMerge(unittest.TestCase):
    """Requirement 1.4: partial Cricbuzz coverage merges with static fallback."""

    def test_unmapped_squads_are_filled_from_static(self) -> None:
        cache = CacheLayer()
        # Only three teams come back live; the other seven must be filled in
        # from ``ipl_data.TEAMS`` so the ten-id contract is preserved.
        squads = [
            {"squadId": 100, "teamId": 200, "squadType": "Mumbai Indians", "imageId": 9001},
            {"squadId": 101, "teamId": 201, "squadType": "Chennai Super Kings", "imageId": 9002},
            {"squadId": 109, "teamId": 209, "squadType": "Lucknow Super Giants", "imageId": 9010},
            # An entirely unknown franchise that must NOT pollute the response.
            {"squadId": 999, "teamId": 999, "squadType": "Some Other XI", "imageId": 9999},
        ]
        svc = StubCricbuzzService(squads=squads)
        resolver = DataResolver(svc, cache)

        teams, source = _arun(resolver.resolve_teams())
        self.assertEqual(source, "live")

        ids = [t["id"] for t in teams]
        # Ten-id contract preserved (Requirement 1.4 / Property 3).
        self.assertEqual(set(ids), {t["id"] for t in TEAMS})
        self.assertEqual(len(ids), 10)

        by_id = {t["id"]: t for t in teams}
        # Live-mapped record carries the Cricbuzz fields.
        self.assertEqual(by_id["mi"]["cricbuzz_squad_id"], 100)
        self.assertEqual(by_id["mi"]["image_id"], "9001")
        # Filled-from-static record is tagged "live" (uniform per the design)
        # but Cricbuzz fields are None.
        self.assertEqual(by_id["rcb"]["source"], "live")
        self.assertIsNone(by_id["rcb"]["cricbuzz_squad_id"])
        self.assertIsNone(by_id["rcb"]["image_id"])

    def test_only_one_team_live_still_yields_ten(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(squads=[
            {"squadId": 100, "teamId": 200, "squadType": "Mumbai Indians", "imageId": 9001},
        ])
        resolver = DataResolver(svc, cache)

        teams, source = _arun(resolver.resolve_teams())
        self.assertEqual(source, "live")
        self.assertEqual(len(teams), 10)


class TestResolveTeamsFallbackPath(unittest.TestCase):
    """Requirement 1.3 / 9.5: any Cricbuzz failure path → fallback, never 500."""

    def test_no_series_id_returns_static_fallback(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=None, squads=None)
        resolver = DataResolver(svc, cache)

        teams, source = _arun(resolver.resolve_teams())
        self.assertEqual(source, "fallback")
        self.assertEqual(len(teams), 10)
        for record in teams:
            self.assertEqual(record["source"], "fallback")
            self.assertIsNone(record["cricbuzz_team_id"])
            self.assertIsNone(record["image_id"])

    def test_empty_squads_returns_static_fallback(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=7607, squads=[])
        resolver = DataResolver(svc, cache)

        teams, source = _arun(resolver.resolve_teams())
        self.assertEqual(source, "fallback")
        self.assertEqual(len(teams), 10)

    def test_all_squads_unmappable_returns_static_fallback(self) -> None:
        # Every Cricbuzz squad name is unknown to ID_Mapper; the resolver must
        # not return an empty live list — it falls through to the static
        # fallback so the ten-team contract is preserved.
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=7607, squads=[
            {"squadId": 1, "teamId": 1, "squadType": "Atlanta Crickets", "imageId": 1},
            {"squadId": 2, "teamId": 2, "squadType": "Munich United XI", "imageId": 2},
        ])
        resolver = DataResolver(svc, cache)

        teams, source = _arun(resolver.resolve_teams())
        self.assertEqual(source, "fallback")
        self.assertEqual(len(teams), 10)

    def test_none_squads_returns_static_fallback(self) -> None:
        # ``CricbuzzService.get_squads`` returns ``None`` for any error.
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=7607, squads=None)
        resolver = DataResolver(svc, cache)

        teams, source = _arun(resolver.resolve_teams())
        self.assertEqual(source, "fallback")
        self.assertEqual(len(teams), 10)

    def test_does_not_cache_fallback(self) -> None:
        # Requirement 6.6: a fallback response must not poison the cache; the
        # next call should retry Cricbuzz.
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=None, squads=None)
        resolver = DataResolver(svc, cache)

        _arun(resolver.resolve_teams())
        _, hit = cache.get(TEAMS_RESOLVED_KEY)
        self.assertFalse(hit)


class TestResolveTeamsCachePath(unittest.TestCase):
    """Requirement 6.5: cache hit re-tags every element's source as 'cache'."""

    def test_second_call_returns_cache_source(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(squads=_full_squads_payload())
        resolver = DataResolver(svc, cache)

        # First call populates the cache via the live path.
        first, first_source = _arun(resolver.resolve_teams())
        self.assertEqual(first_source, "live")

        # Second call must hit the cache: no further outbound calls.
        second, second_source = _arun(resolver.resolve_teams())
        self.assertEqual(second_source, "cache")
        self.assertEqual(len(second), 10)
        for record in second:
            self.assertEqual(record["source"], "cache")
        # The series/squads endpoints were each called exactly once.
        self.assertEqual(svc.series_calls, 1)
        self.assertEqual(svc.squad_calls, 1)

    def test_cache_ttl_matches_design(self) -> None:
        # Sanity: the cached payload should expire after CATALOG_TTL_SECONDS,
        # which equals the 21600 seconds (6 hours) called out in Requirement
        # 6.2.
        self.assertEqual(CATALOG_TTL_SECONDS, 21600)


class TestResolveTeamsBothEmpty(unittest.TestCase):
    """Requirement 1.5: both Cricbuzz and static empty → HTTP 503."""

    def test_raises_503_when_static_is_empty(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=None, squads=None)
        resolver = DataResolver(svc, cache)

        # Temporarily empty the static fallback to simulate the deployment
        # misconfiguration. Restored in ``tearDown`` below.
        from ipl_data import TEAMS as STATIC_TEAMS  # noqa: WPS433

        original = list(STATIC_TEAMS)
        STATIC_TEAMS.clear()
        try:
            with self.assertRaises(HTTPException) as ctx:
                _arun(resolver.resolve_teams())
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertEqual(ctx.exception.detail, "No team data available")
        finally:
            STATIC_TEAMS.extend(original)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
