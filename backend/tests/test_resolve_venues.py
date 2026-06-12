"""Smoke and example tests for ``DataResolver.resolve_venues``.

Covers the live, cache, and fallback paths defined in Requirement 4
(clauses 4.1–4.5), the empty-live edge case (4.3), the cache-driven
repeat-call behaviour in Requirement 6.5, and the no-duplicate-id
invariant in Requirement 12.4. Property-based coverage for the venue
shape lives in task 6.6 (``test_data_resolver_properties.py``); this
file pins the contract with representative examples.
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
    DEFAULT_AVG_FIRST_INNINGS,
    DEFAULT_PITCH,
    DataResolver,
    VENUES_RESOLVED_KEY,
)
from ipl_data import VENUES, get_venue  # noqa: E402


# ---------------------------------------------------------------------------
# Stub Cricbuzz service. Hand-coded duck type so the test suite does not have
# to set up the real ``CricbuzzService`` (which needs ``httpx.AsyncClient``).
# ---------------------------------------------------------------------------


class StubCricbuzzService:
    """Duck-typed stand-in covering the methods ``resolve_venues`` uses."""

    def __init__(
        self,
        series_id: Optional[int] = 7607,
        venues: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self._series_id = series_id
        self._venues = venues
        self.series_calls = 0
        self.venue_calls = 0

    async def get_ipl_series_id(self) -> Optional[int]:
        self.series_calls += 1
        return self._series_id

    async def get_series_venues(
        self,
        series_id: int,
    ) -> Optional[list[dict[str, Any]]]:
        self.venue_calls += 1
        assert series_id == self._series_id, (
            f"resolver passed an unexpected series id: {series_id!r}"
        )
        return self._venues


def _full_venues_payload() -> list[dict[str, Any]]:
    """Cricbuzz-style venue payload covering all ten static venues.

    Mixes current and historical city spellings (``Bengaluru`` vs.
    ``Bangalore``) and stadium phrasings (``M Chinnaswamy`` vs.
    ``M. Chinnaswamy``) so we exercise the alias-based ID_Mapper
    resolution. The ``id`` field is the Cricbuzz numeric venue id.
    """
    return [
        {"id": 27, "ground": "Wankhede Stadium", "city": "Mumbai"},
        {"id": 31, "ground": "M Chinnaswamy Stadium", "city": "Bengaluru"},
        {"id": 36, "ground": "Eden Gardens", "city": "Kolkata"},
        {"id": 11, "ground": "MA Chidambaram Stadium", "city": "Chennai"},
        {"id": 81, "ground": "Narendra Modi Stadium", "city": "Ahmedabad"},
        {"id": 46, "ground": "Arun Jaitley Stadium", "city": "Delhi"},
        {"id": 41, "ground": "Punjab Cricket Association IS Bindra Stadium",
         "city": "Mohali"},
        {"id": 13, "ground": "Sawai Mansingh Stadium", "city": "Jaipur"},
        {"id": 50, "ground": "Rajiv Gandhi International Stadium",
         "city": "Hyderabad"},
        {"id": 95, "ground": "Bharat Ratna Shri Atal Bihari Vajpayee Ekana "
                              "Cricket Stadium", "city": "Lucknow"},
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


class TestResolveVenuesLivePath(unittest.TestCase):
    """Requirement 4.1, 4.2, 4.5: live Cricbuzz path produces shaped records."""

    def test_returns_live_venues_with_source_live(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=_full_venues_payload())
        resolver = DataResolver(svc, cache)

        venues, source = _arun(resolver.resolve_venues())

        self.assertEqual(source, "live")
        self.assertEqual(len(venues), 10)
        for record in venues:
            self.assertEqual(record["source"], "live")
            for key in ("id", "name", "city", "default_pitch",
                        "avg_first_innings", "cricbuzz_venue_id"):
                self.assertIn(key, record)

    def test_static_id_overlay_preserves_static_metadata(self) -> None:
        """Requirement 4.5: known venues keep their static id/pitch/avg."""
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=_full_venues_payload())
        resolver = DataResolver(svc, cache)

        venues, _ = _arun(resolver.resolve_venues())
        by_id = {v["id"]: v for v in venues}

        # Every static id present.
        self.assertEqual(set(by_id.keys()), {v["id"] for v in VENUES})

        # Static metadata carried over.
        for static in VENUES:
            live = by_id[static["id"]]
            self.assertEqual(live["default_pitch"], static["default_pitch"])
            self.assertEqual(live["avg_first_innings"],
                             static["avg_first_innings"])

    def test_carries_cricbuzz_venue_id_and_live_name(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=_full_venues_payload())
        resolver = DataResolver(svc, cache)

        venues, _ = _arun(resolver.resolve_venues())
        by_id = {v["id"]: v for v in venues}

        wankhede = by_id["wankhede"]
        self.assertEqual(wankhede["cricbuzz_venue_id"], 27)
        # Live ``name`` comes from the Cricbuzz ``ground`` field.
        self.assertEqual(wankhede["name"], "Wankhede Stadium")
        self.assertEqual(wankhede["city"], "Mumbai")

    def test_historical_city_spelling_resolves_to_static_id(self) -> None:
        # ``Bangalore`` is the historical city spelling for Chinnaswamy; the
        # ID_Mapper alias table accepts both.
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=[
            {"id": 31, "ground": "M Chinnaswamy Stadium", "city": "Bangalore"},
        ])
        resolver = DataResolver(svc, cache)

        venues, source = _arun(resolver.resolve_venues())
        self.assertEqual(source, "live")
        self.assertEqual(len(venues), 1)
        self.assertEqual(venues[0]["id"], "chinnaswamy")
        # Static metadata still wins over the defaults.
        self.assertEqual(
            venues[0]["default_pitch"], get_venue("chinnaswamy")["default_pitch"]
        )

    def test_unknown_venue_uses_slug_id_and_defaults(self) -> None:
        """Requirement 4.2: unknown venue → slug id + balanced/170 defaults."""
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=[
            {"id": 999, "ground": "Greenfield International Stadium",
             "city": "Thiruvananthapuram"},
        ])
        resolver = DataResolver(svc, cache)

        venues, source = _arun(resolver.resolve_venues())
        self.assertEqual(source, "live")
        self.assertEqual(len(venues), 1)
        record = venues[0]
        self.assertEqual(record["id"], "greenfield-international-stadium")
        self.assertEqual(record["default_pitch"], DEFAULT_PITCH)
        self.assertEqual(record["avg_first_innings"], DEFAULT_AVG_FIRST_INNINGS)
        self.assertEqual(DEFAULT_PITCH, "balanced")
        self.assertEqual(DEFAULT_AVG_FIRST_INNINGS, 170)
        self.assertEqual(record["cricbuzz_venue_id"], 999)
        self.assertEqual(record["source"], "live")

    def test_mixed_known_and_unknown_venues(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=[
            {"id": 27, "ground": "Wankhede Stadium", "city": "Mumbai"},
            {"id": 999, "ground": "Holkar Cricket Stadium", "city": "Indore"},
        ])
        resolver = DataResolver(svc, cache)

        venues, source = _arun(resolver.resolve_venues())
        self.assertEqual(source, "live")
        self.assertEqual(len(venues), 2)

        wank = next(v for v in venues if v["city"] == "Mumbai")
        holkar = next(v for v in venues if v["city"] == "Indore")

        # Known venue: static id + static metadata.
        self.assertEqual(wank["id"], "wankhede")
        self.assertEqual(wank["default_pitch"],
                         get_venue("wankhede")["default_pitch"])
        # Unknown venue: slug id + defaults.
        self.assertEqual(holkar["id"], "holkar-cricket-stadium")
        self.assertEqual(holkar["default_pitch"], DEFAULT_PITCH)
        self.assertEqual(holkar["avg_first_innings"], DEFAULT_AVG_FIRST_INNINGS)


class TestResolveVenuesUniqueIds(unittest.TestCase):
    """Requirement 12.4: live venues have unique non-empty ids."""

    def test_slug_collision_is_disambiguated_with_suffix(self) -> None:
        # Two distinct grounds whose slug collides; the second must get a
        # deterministic ``-2`` suffix so neither id is overwritten.
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=[
            {"id": 1, "ground": "Test Ground", "city": "Cityville"},
            {"id": 2, "ground": "test ground", "city": "Othertown"},
            {"id": 3, "ground": "TEST GROUND", "city": "Threeburg"},
        ])
        resolver = DataResolver(svc, cache)

        venues, source = _arun(resolver.resolve_venues())
        self.assertEqual(source, "live")
        ids = [v["id"] for v in venues]
        self.assertEqual(ids, ["test-ground", "test-ground-2", "test-ground-3"])
        # All ids must be unique and non-empty (Requirement 12.4).
        self.assertEqual(len(ids), len(set(ids)))
        for vid in ids:
            self.assertTrue(vid)

    def test_two_cricbuzz_entries_resolving_to_same_static_id_collapse(self) -> None:
        # If two Cricbuzz rows both resolve to the same static id (e.g. an
        # accidental duplicate listing), the second is dropped so the
        # uniqueness invariant holds.
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=[
            {"id": 27, "ground": "Wankhede Stadium", "city": "Mumbai"},
            {"id": 28, "ground": "Wankhede Stadium", "city": "Mumbai"},
        ])
        resolver = DataResolver(svc, cache)

        venues, source = _arun(resolver.resolve_venues())
        self.assertEqual(source, "live")
        self.assertEqual(len(venues), 1)
        self.assertEqual(venues[0]["id"], "wankhede")

    def test_skips_malformed_entries_without_ground(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=[
            {"id": 1, "ground": "", "city": "Nowhere"},
            {"id": 2, "city": "Empty"},
            {"id": 3, "ground": "Wankhede Stadium", "city": "Mumbai"},
            "not-a-dict",
        ])
        resolver = DataResolver(svc, cache)

        venues, source = _arun(resolver.resolve_venues())
        self.assertEqual(source, "live")
        # Only the valid Wankhede entry survives.
        self.assertEqual(len(venues), 1)
        self.assertEqual(venues[0]["id"], "wankhede")


class TestResolveVenuesEmptyLive(unittest.TestCase):
    """Requirement 4.3: HTTP 200 with empty list yields ``([], 'live')``."""

    def test_empty_cricbuzz_list_returns_empty_live(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=[])
        resolver = DataResolver(svc, cache)

        venues, source = _arun(resolver.resolve_venues())
        self.assertEqual(venues, [])
        self.assertEqual(source, "live")

    def test_empty_live_payload_is_cached_for_subsequent_hits(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=[])
        resolver = DataResolver(svc, cache)

        # First call populates the empty payload.
        first, first_source = _arun(resolver.resolve_venues())
        self.assertEqual(first, [])
        self.assertEqual(first_source, "live")

        # Second call must hit the cache; Cricbuzz is not consulted again.
        second, second_source = _arun(resolver.resolve_venues())
        self.assertEqual(second, [])
        self.assertEqual(second_source, "cache")
        self.assertEqual(svc.series_calls, 1)
        self.assertEqual(svc.venue_calls, 1)


class TestResolveVenuesCachePath(unittest.TestCase):
    """Requirement 6.5: cache hit re-tags every element's source as 'cache'."""

    def test_second_call_returns_cache_source(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=_full_venues_payload())
        resolver = DataResolver(svc, cache)

        first, first_source = _arun(resolver.resolve_venues())
        self.assertEqual(first_source, "live")

        second, second_source = _arun(resolver.resolve_venues())
        self.assertEqual(second_source, "cache")
        self.assertEqual(len(second), len(first))
        for record in second:
            self.assertEqual(record["source"], "cache")
        # Cricbuzz was not consulted again.
        self.assertEqual(svc.series_calls, 1)
        self.assertEqual(svc.venue_calls, 1)

    def test_cache_key_matches_design(self) -> None:
        # The design requires the key ``venues:resolved``.
        self.assertEqual(VENUES_RESOLVED_KEY, "venues:resolved")

    def test_cached_payload_uses_catalog_ttl(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(venues=_full_venues_payload())
        resolver = DataResolver(svc, cache)

        _arun(resolver.resolve_venues())
        cached, hit = cache.get(VENUES_RESOLVED_KEY)
        self.assertTrue(hit)
        self.assertEqual(len(cached), 10)
        # Sanity: 21600 seconds (6 hours) per Requirement 6.2.
        self.assertEqual(CATALOG_TTL_SECONDS, 21600)


class TestResolveVenuesFallbackPath(unittest.TestCase):
    """Requirement 4.4 / 9.5: any Cricbuzz failure path → fallback, never 500."""

    def test_no_series_id_returns_static_fallback(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=None, venues=None)
        resolver = DataResolver(svc, cache)

        venues, source = _arun(resolver.resolve_venues())
        self.assertEqual(source, "fallback")
        self.assertEqual(len(venues), len(VENUES))
        for record in venues:
            self.assertEqual(record["source"], "fallback")
            self.assertIsNone(record["cricbuzz_venue_id"])
            for key in ("id", "name", "city", "default_pitch",
                        "avg_first_innings"):
                self.assertIn(key, record)

    def test_get_series_venues_returns_none_falls_back(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=7607, venues=None)
        resolver = DataResolver(svc, cache)

        venues, source = _arun(resolver.resolve_venues())
        self.assertEqual(source, "fallback")
        self.assertEqual(len(venues), len(VENUES))

    def test_does_not_cache_fallback(self) -> None:
        # Requirement 6.6: fallback responses must not poison the cache.
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=None, venues=None)
        resolver = DataResolver(svc, cache)

        _arun(resolver.resolve_venues())
        _, hit = cache.get(VENUES_RESOLVED_KEY)
        self.assertFalse(hit)

    def test_fallback_preserves_static_metadata(self) -> None:
        cache = CacheLayer()
        svc = StubCricbuzzService(series_id=None, venues=None)
        resolver = DataResolver(svc, cache)

        venues, _ = _arun(resolver.resolve_venues())
        by_id = {v["id"]: v for v in venues}
        for static in VENUES:
            record = by_id[static["id"]]
            self.assertEqual(record["name"], static["name"])
            self.assertEqual(record["city"], static["city"])
            self.assertEqual(record["default_pitch"], static["default_pitch"])
            self.assertEqual(record["avg_first_innings"],
                             static["avg_first_innings"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
