"""Smoke and example tests for ``DataResolver.resolve_players``.

Covers the live, partial-live, cache, and fallback paths defined in
Requirement 2 (clauses 2.1–2.5) and the cache-driven repeat-call behaviour
in Requirement 6.5 / 7.4. Property-based coverage for the player schema
lives in task 6.9 (``test_live_data_properties.py``); this file focuses on
representative examples that pin the contract.
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

# Some downstream modules require MONGO_URL / DB_NAME at import time; the
# resolver itself does not, but be defensive in case the environment is
# sparse.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "ipl_test")

from cache_layer import CacheLayer  # noqa: E402
from data_resolver import (  # noqa: E402
    CATALOG_TTL_SECONDS,
    DataResolver,
    _players_cache_key,
    _squadid_cache_key,
)
from ipl_data import get_players  # noqa: E402

from fastapi import HTTPException  # noqa: E402


# ---------------------------------------------------------------------------
# Stub Cricbuzz service. Hand-coded duck type so the test suite does not have
# to set up the real ``CricbuzzService`` (which needs ``httpx.AsyncClient``).
# ---------------------------------------------------------------------------


class StubCricbuzzService:
    """Duck-typed stand-in covering the methods ``resolve_players`` uses."""

    def __init__(
        self,
        series_id: Optional[int] = 7607,
        squads: Optional[list[dict[str, Any]]] = None,
        players_by_squad_id: Optional[dict[int, Optional[list[dict]]]] = None,
    ) -> None:
        self._series_id = series_id
        self._squads = squads
        self._players_by_squad_id = players_by_squad_id or {}
        self.series_calls = 0
        self.squad_calls = 0
        self.player_calls: list[tuple[int, int]] = []

    async def get_ipl_series_id(self) -> Optional[int]:
        self.series_calls += 1
        return self._series_id

    async def get_squads(self, series_id: int) -> Optional[list[dict[str, Any]]]:
        self.squad_calls += 1
        return self._squads

    async def get_squad_players(
        self,
        series_id: int,
        squad_id: int,
    ) -> Optional[list[dict[str, Any]]]:
        self.player_calls.append((series_id, squad_id))
        return self._players_by_squad_id.get(squad_id)


def _full_squads_payload() -> list[dict[str, Any]]:
    """Cricbuzz-style squads payload covering all ten franchises."""
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
    """Realistic Mumbai Indians roster shape from Cricbuzz.

    Includes section header rows (``isHeader=True``) and a mix of explicit
    ``role`` strings, missing roles, varied keeper phrasing, and at least
    one all-rounder.
    """
    return [
        {"isHeader": True, "name": "batsman"},
        {"id": 7000, "name": "Rohit Sharma", "role": "Batsman", "faceImageId": 1001, "teamName": "IND"},
        {"id": 7001, "name": "Suryakumar Yadav", "role": "Batsman", "faceImageId": 1002, "teamName": "IND"},
        {"isHeader": True, "name": "bowler"},
        {"id": 7002, "name": "Jasprit Bumrah", "role": "Bowler", "faceImageId": 1003, "teamName": "IND"},
        # Role intentionally missing — the resolver should fall back to the
        # current section header.
        {"id": 7003, "name": "Trent Boult", "faceImageId": 1004, "teamName": "NZ"},
        {"isHeader": True, "name": "all rounder"},
        # Cricbuzz role strings vary in casing and dashing — make sure the
        # canonical labels are produced regardless.
        {"id": 7004, "name": "Hardik Pandya", "role": "All-Rounder", "faceImageId": 1005, "teamName": "IND"},
        {"isHeader": True, "name": "wicket keeper"},
        {"id": 7005, "name": "Ishan Kishan", "role": "WK-Batsman", "faceImageId": 1006, "teamName": "IND"},
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


class TestResolvePlayersValidation(unittest.TestCase):
    """Requirement 2.5: 404 fires on both live and fallback paths."""

    def test_unknown_team_id_raises_404_with_cricbuzz_available(self) -> None:
        # Even with Cricbuzz fully wired, an unrecognised id must 404.
        cache = CacheLayer()
        svc = StubCricbuzzService(squads=_full_squads_payload())
        resolver = DataResolver(svc, cache)

        with self.assertRaises(HTTPException) as ctx:
            _arun(resolver.resolve_players("not_a_team"))
        self.assertEqual(ctx.exception.status_code, 404)
        # The Cricbuzz service must not be touched on this path.
        self.assertEqual(svc.series_calls, 0)
        self.assertEqual(svc.player_calls, [])

    def test_unknown_team_id_raises_404_when_cricbuzz_unavailable(self) -> None:
        # The same 404 must fire on the fallback path, before consulting
        # the static module.
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=None, squads=None)
        resolver = DataResolver(svc, cache)

        with self.assertRaises(HTTPException) as ctx:
            _arun(resolver.resolve_players("zzz"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_empty_string_id_raises_404(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(squads=_full_squads_payload())
        resolver = DataResolver(svc, cache)

        with self.assertRaises(HTTPException) as ctx:
            _arun(resolver.resolve_players(""))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_id_is_normalised_before_lookup(self) -> None:
        # Whitespace and casing should not defeat the validation step.
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: _mi_player_payload()},
        )
        resolver = DataResolver(svc, cache)

        players, source = _arun(resolver.resolve_players("  MI  "))
        self.assertEqual(source, "live")
        self.assertGreater(len(players), 0)


class TestResolvePlayersLivePath(unittest.TestCase):
    """Requirement 2.1, 2.2, 2.3, 7.4: live Cricbuzz path produces shaped records."""

    def test_returns_live_players_with_player_stat_schema(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: _mi_player_payload()},
        )
        resolver = DataResolver(svc, cache)

        players, source = _arun(resolver.resolve_players("mi"))

        self.assertEqual(source, "live")
        # 6 actual players in the payload (header rows dropped).
        self.assertEqual(len(players), 6)

        for record in players:
            for key in (
                "name", "role", "batting_avg", "strike_rate",
                "wickets", "economy", "country",
                "image_id", "cricbuzz_player_id", "source",
            ):
                self.assertIn(key, record)
            # Numeric defaults per Requirement 2.3.
            self.assertEqual(record["batting_avg"], 0)
            self.assertEqual(record["strike_rate"], 0)
            self.assertEqual(record["wickets"], 0)
            self.assertEqual(record["economy"], 0)
            self.assertEqual(record["source"], "live")

    def test_role_normalisation_covers_canonical_labels(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: _mi_player_payload()},
        )
        resolver = DataResolver(svc, cache)

        players, _ = _arun(resolver.resolve_players("mi"))
        by_name = {p["name"]: p for p in players}

        self.assertEqual(by_name["Rohit Sharma"]["role"], "Batsman")
        self.assertEqual(by_name["Jasprit Bumrah"]["role"], "Bowler")
        # Role missing on Boult, falls back to the "bowler" section header.
        self.assertEqual(by_name["Trent Boult"]["role"], "Bowler")
        self.assertEqual(by_name["Hardik Pandya"]["role"], "All-rounder")
        self.assertEqual(by_name["Ishan Kishan"]["role"], "Wicket-keeper")

    def test_carries_image_id_and_cricbuzz_player_id(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: _mi_player_payload()},
        )
        resolver = DataResolver(svc, cache)

        players, _ = _arun(resolver.resolve_players("mi"))
        rohit = next(p for p in players if p["name"] == "Rohit Sharma")
        self.assertEqual(rohit["cricbuzz_player_id"], 7000)
        self.assertEqual(rohit["image_id"], "1001")

    def test_country_codes_preserved_from_cricbuzz(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: _mi_player_payload()},
        )
        resolver = DataResolver(svc, cache)

        players, _ = _arun(resolver.resolve_players("mi"))
        by_name = {p["name"]: p for p in players}
        self.assertEqual(by_name["Trent Boult"]["country"], "NZ")
        self.assertEqual(by_name["Rohit Sharma"]["country"], "IND")

    def test_uses_cached_squad_id_mapping_from_resolve_teams(self) -> None:
        """Requirement 7.4: the cached mapping is reused on subsequent calls."""
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: _mi_player_payload()},
        )
        resolver = DataResolver(svc, cache)

        # Pre-populate the cache by resolving teams.
        _arun(resolver.resolve_teams())
        self.assertEqual(svc.squad_calls, 1)
        self.assertEqual(svc.series_calls, 1)

        # Now resolve players; the squads call must NOT happen again.
        _arun(resolver.resolve_players("mi"))
        self.assertEqual(svc.squad_calls, 1, "resolve_players re-issued get_squads")
        self.assertEqual(svc.player_calls, [(7607, 100)])

    def test_triggers_resolve_teams_when_squad_id_missing(self) -> None:
        """The resolver populates the squad-id mapping on demand."""
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: _mi_player_payload()},
        )
        resolver = DataResolver(svc, cache)

        # Cache is empty; resolve_players must internally trigger
        # resolve_teams to fill in squadid:mi.
        _arun(resolver.resolve_players("mi"))

        info, hit = cache.get(_squadid_cache_key("mi"))
        self.assertTrue(hit)
        self.assertEqual(info["cricbuzz_squad_id"], 100)
        self.assertEqual(svc.player_calls, [(7607, 100)])


class TestResolvePlayersCachePath(unittest.TestCase):
    """Requirement 6.5: cache hit re-tags every element's source as 'cache'."""

    def test_second_call_returns_cache_source(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: _mi_player_payload()},
        )
        resolver = DataResolver(svc, cache)

        first, first_source = _arun(resolver.resolve_players("mi"))
        self.assertEqual(first_source, "live")

        second, second_source = _arun(resolver.resolve_players("mi"))
        self.assertEqual(second_source, "cache")
        self.assertEqual(len(second), len(first))
        for record in second:
            self.assertEqual(record["source"], "cache")
        # Cricbuzz was not consulted again for players.
        self.assertEqual(len(svc.player_calls), 1)

    def test_cache_key_matches_design(self) -> None:
        # The design requires the key ``players:{internal_team_id}``.
        self.assertEqual(_players_cache_key("mi"), "players:mi")
        self.assertEqual(_players_cache_key("rcb"), "players:rcb")

    def test_cache_ttl_matches_design(self) -> None:
        # Sanity: 21600 seconds (6 hours) per Requirement 6.2.
        self.assertEqual(CATALOG_TTL_SECONDS, 21600)

    def test_cached_payload_is_keyed_per_team(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={
                100: _mi_player_payload(),
                101: [
                    {"id": 8000, "name": "MS Dhoni", "role": "WK-Batsman",
                     "faceImageId": 5000, "teamName": "IND"},
                    {"id": 8001, "name": "Ravindra Jadeja", "role": "All-rounder",
                     "faceImageId": 5001, "teamName": "IND"},
                ],
            },
        )
        resolver = DataResolver(svc, cache)

        mi_players, _ = _arun(resolver.resolve_players("mi"))
        csk_players, _ = _arun(resolver.resolve_players("csk"))

        mi_cache, mi_hit = cache.get(_players_cache_key("mi"))
        csk_cache, csk_hit = cache.get(_players_cache_key("csk"))

        self.assertTrue(mi_hit)
        self.assertTrue(csk_hit)
        self.assertEqual(len(mi_cache), len(mi_players))
        self.assertEqual(len(csk_cache), len(csk_players))
        # Different rosters in each cache entry.
        self.assertNotEqual(
            {p["name"] for p in mi_cache},
            {p["name"] for p in csk_cache},
        )


class TestResolvePlayersFallbackPath(unittest.TestCase):
    """Requirement 2.4 / 9.5: any Cricbuzz failure → fallback, never 500."""

    def test_no_series_id_returns_static_fallback(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=None, squads=None)
        resolver = DataResolver(svc, cache)

        players, source = _arun(resolver.resolve_players("mi"))
        self.assertEqual(source, "fallback")
        # Static roster shape preserved with the additive fields.
        static_roster = get_players("mi")
        self.assertEqual(len(players), len(static_roster))
        for record in players:
            self.assertEqual(record["source"], "fallback")
            self.assertIsNone(record["cricbuzz_player_id"])
            self.assertIsNone(record["image_id"])
            # PlayerStat schema fields must still be present.
            for key in ("name", "role", "batting_avg",
                        "strike_rate", "wickets", "economy", "country"):
                self.assertIn(key, record)

    def test_get_squad_players_returns_none_falls_back(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: None},
        )
        resolver = DataResolver(svc, cache)

        players, source = _arun(resolver.resolve_players("mi"))
        self.assertEqual(source, "fallback")
        self.assertEqual(len(players), len(get_players("mi")))

    def test_empty_player_list_falls_back(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: []},
        )
        resolver = DataResolver(svc, cache)

        players, source = _arun(resolver.resolve_players("mi"))
        self.assertEqual(source, "fallback")
        self.assertEqual(len(players), len(get_players("mi")))

    def test_only_headers_in_payload_falls_back(self) -> None:
        # A payload with only header rows yields an empty mapped roster,
        # which must trigger the fallback path.
        cache = CacheLayer()
        svc = StubCricbuzzService(
            squads=_full_squads_payload(),
            players_by_squad_id={100: [{"isHeader": True, "name": "batsman"}]},
        )
        resolver = DataResolver(svc, cache)

        players, source = _arun(resolver.resolve_players("mi"))
        self.assertEqual(source, "fallback")

    def test_does_not_cache_fallback(self) -> None:
        # Requirement 6.6: fallback responses must not poison the cache.
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=None, squads=None)
        resolver = DataResolver(svc, cache)

        _arun(resolver.resolve_players("mi"))
        _, hit = cache.get(_players_cache_key("mi"))
        self.assertFalse(hit)

    def test_cricbuzz_unmappable_squad_falls_back(self) -> None:
        # Cricbuzz returns squads but none map to ``mi``; resolve_teams
        # leaves squadid:mi unset, so resolve_players takes the fallback.
        cache = CacheLayer()
        svc = StubCricbuzzService(
            series_id=7607,
            squads=[{"squadId": 999, "teamId": 999,
                     "squadType": "Atlanta Crickets", "imageId": 1}],
            players_by_squad_id={},
        )
        resolver = DataResolver(svc, cache)

        players, source = _arun(resolver.resolve_players("mi"))
        self.assertEqual(source, "fallback")
        self.assertEqual(len(players), len(get_players("mi")))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
