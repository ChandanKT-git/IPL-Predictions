"""Per-endpoint orchestration of live, cached, and fallback catalog data.

Implements the ``Data_Resolver`` component described in the
``real-data-cricbuzz-integration`` design document. ``resolve_teams`` (task
6.1), ``resolve_players`` (task 6.2), ``resolve_venues`` (task 6.3), and
``resolve_live_xi`` (task 6.4) all live here.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from fastapi import HTTPException

import id_mapper
from cache_layer import CacheLayer
from ipl_data import TEAMS, VENUES, get_players, get_team, get_venue

if TYPE_CHECKING:  # pragma: no cover - type-only import
    # CricbuzzService is implemented in task 4.1; we depend on its interface
    # (``get_ipl_series_id``, ``get_squads``) but avoid a runtime import so
    # this module can be exercised before the service module lands.
    from cricbuzz_service import CricbuzzService

logger = logging.getLogger("ipl.data_resolver")

# TTL for catalog-level resolved payloads (teams, players, venues). Matches the
# upstream catalog TTL from the design (Requirement 6.2).
CATALOG_TTL_SECONDS = 21600

# Cache keys.
TEAMS_RESOLVED_KEY = "teams:resolved"
VENUES_RESOLVED_KEY = "venues:resolved"

# Defaults applied to live Cricbuzz venue records that do not match any entry
# in the static ``VENUES`` table (Requirement 4.2).
DEFAULT_PITCH = "balanced"
DEFAULT_AVG_FIRST_INNINGS = 170


def _players_cache_key(internal_team_id: str) -> str:
    """Cache key for the resolved player roster of one ``Internal_Team_Id``."""
    return f"players:{internal_team_id}"


def _squadid_cache_key(internal_team_id: str) -> str:
    """Cache key for the per-team Cricbuzz squad/team id mapping."""
    return f"squadid:{internal_team_id}"


def _build_fallback_team_record(static_team: dict, source: str) -> dict:
    """Return a copy of ``static_team`` augmented with the new fields.

    The static record carries every key from the existing ``TEAMS`` schema
    (``id``, ``name``, ``short_name``, ``primary_color``, ``secondary_color``,
    ``home_venue_id``, ``captain``, ``titles``, ``rating``); we add the three
    Cricbuzz-derived fields with ``None`` defaults plus the ``source`` tag so
    that the response shape is identical regardless of the path that produced
    it (Requirement 1.6, 12.3).
    """
    return {
        **static_team,
        "cricbuzz_team_id": None,
        "cricbuzz_squad_id": None,
        "image_id": None,
        "source": source,
    }


def _build_live_team_record(
    internal_id: str,
    static_team: dict,
    cricbuzz_team_id: Optional[int],
    cricbuzz_squad_id: Optional[int],
    cricbuzz_name: Optional[str],
    image_id: Optional[Any],
) -> dict:
    """Merge live Cricbuzz fields onto the static ``TEAMS`` schema.

    ``primary_color``, ``secondary_color``, ``home_venue_id``, ``captain``,
    ``titles``, ``rating``, and ``short_name`` are carried verbatim from the
    static record. ``name`` prefers the live Cricbuzz string when present so
    the user sees the current franchise display name (e.g. ``Royal Challengers
    Bengaluru`` vs. the historical ``Bangalore``) — Requirement 1.2.
    """
    return {
        "id": internal_id,
        "name": cricbuzz_name or static_team["name"],
        "short_name": static_team["short_name"],
        "primary_color": static_team["primary_color"],
        "secondary_color": static_team["secondary_color"],
        "home_venue_id": static_team["home_venue_id"],
        "captain": static_team["captain"],
        "titles": static_team["titles"],
        "rating": static_team["rating"],
        "cricbuzz_team_id": cricbuzz_team_id,
        "cricbuzz_squad_id": cricbuzz_squad_id,
        "image_id": str(image_id) if image_id else None,
        "source": "live",
    }


class DataResolver:
    """Decides per catalog endpoint whether to serve live, cached, or fallback data."""

    def __init__(self, svc: "CricbuzzService", cache: CacheLayer) -> None:
        self._svc = svc
        self._cache = cache

    async def resolve_teams(self) -> Tuple[List[dict], str]:
        """Resolve the ten-team IPL catalog with the live/cache/fallback policy.

        Returns
        -------
        ``(teams, source)`` where ``teams`` is a list of dicts shaped like the
        static ``TEAMS`` records plus the additive Cricbuzz fields, and
        ``source`` is one of ``"live"``, ``"cache"``, or ``"fallback"``.

        Raises
        ------
        HTTPException
            With status ``503`` when both Cricbuzz and the static fallback
            yield zero teams (Requirement 1.5). This is a deployment-level
            misconfiguration, not a runtime condition.
        """
        # 1. Cache hit short-circuit. The stored payload was built by a prior
        #    successful live path; on hit we re-tag every element's source so
        #    the badge in the frontend renders "CACHED" (Requirement 6.5).
        cached, hit = self._cache.get(TEAMS_RESOLVED_KEY)
        if hit and cached:
            cached_with_cache_source = [
                {**team, "source": "cache"} for team in cached
            ]
            return cached_with_cache_source, "cache"

        # 2. Cricbuzz live path: discover the IPL series id, then list its
        #    squads. Either step returning ``None`` is treated as "Cricbuzz
        #    unavailable" and falls through to the static fallback.
        live_by_internal_id: dict[str, dict] = {}
        series_id = await self._svc.get_ipl_series_id()
        if series_id is not None:
            squads = await self._svc.get_squads(series_id)
            if squads:
                live_by_internal_id = self._build_live_index(series_id, squads)

        # 3. Partial-live merge (Requirement 1.4). When at least one Cricbuzz
        #    squad mapped successfully, return the union of those live records
        #    and static-fallback records for any Internal_Team_Id that did not
        #    resolve, so the ten-team contract is preserved. The overall
        #    response carries source="live"; each element's source field
        #    matches (live records keep "live", filled-in static records also
        #    report "live" per Requirement 1.4 — the badge reflects the
        #    overall response, not individual rows).
        if live_by_internal_id:
            merged: List[dict] = []
            for static_team in TEAMS:
                tid = static_team["id"]
                if tid in live_by_internal_id:
                    merged.append(live_by_internal_id[tid])
                else:
                    # Static-fallback fill, tagged "live" so the merged response
                    # is uniformly tagged. Cricbuzz fields stay None.
                    filled = {**static_team,
                              "cricbuzz_team_id": None,
                              "cricbuzz_squad_id": None,
                              "image_id": None,
                              "source": "live"}
                    merged.append(filled)
            # Cache the merged payload for subsequent requests within the TTL.
            self._cache.set(TEAMS_RESOLVED_KEY, merged, ttl=CATALOG_TTL_SECONDS)
            return merged, "live"

        # 4. Cricbuzz unavailable: serve the static fallback verbatim, tagged
        #    "fallback". Do not cache the fallback payload — the next request
        #    should retry Cricbuzz so the app recovers automatically once the
        #    upstream issue clears (Requirement 6.6 forbids caching failures).
        if TEAMS:
            fallback = [_build_fallback_team_record(t, "fallback") for t in TEAMS]
            return fallback, "fallback"

        # 5. Both empty — deployment misconfiguration. Surface as HTTP 503 so
        #    the frontend can render an explicit error rather than an empty
        #    selector (Requirement 1.5).
        raise HTTPException(status_code=503, detail="No team data available")

    async def resolve_players(
        self,
        internal_team_id: str,
    ) -> Tuple[List[dict], str]:
        """Resolve a single team's player roster with the live/cache/fallback policy.

        Parameters
        ----------
        internal_team_id:
            One of the ten ``Internal_Team_Id`` codes (``mi``, ``csk``, ...).

        Returns
        -------
        ``(players, source)`` where ``players`` is a list of dicts shaped to
        match the existing ``PlayerStat`` Pydantic schema (``name``, ``role``,
        ``batting_avg``, ``strike_rate``, ``wickets``, ``economy``,
        ``country``) plus the additive Cricbuzz fields ``image_id``,
        ``cricbuzz_player_id``, and ``source``. ``source`` is one of
        ``"live"``, ``"cache"``, or ``"fallback"``.

        Raises
        ------
        HTTPException
            With status ``404`` when ``internal_team_id`` is not one of the
            ten recognised codes. The check runs before any Cricbuzz call
            and applies on the fallback path as well, so the existing 404
            contract is preserved regardless of which path would otherwise
            serve the response (Requirement 2.5).
        """
        # 0. Validate the team id up front. The 404 must fire on both the
        #    live and the fallback path (Requirement 2.5), so we do this
        #    check before consulting Cricbuzz or the static module.
        normalized_id = internal_team_id.strip().lower() if isinstance(internal_team_id, str) else ""
        if not normalized_id or get_team(normalized_id) is None:
            raise HTTPException(status_code=404, detail="Team not found")

        # 1. Cache hit short-circuit. The stored payload was built by a
        #    prior successful live path; on hit we re-tag every element's
        #    ``source`` so the badge in the frontend renders "CACHED"
        #    (Requirement 6.5).
        cache_key = _players_cache_key(normalized_id)
        cached, hit = self._cache.get(cache_key)
        if hit and cached:
            return [{**player, "source": "cache"} for player in cached], "cache"

        # 2. Resolve the Cricbuzz ``(series_id, squad_id)`` pair for this
        #    team. ``resolve_teams`` populates the ``squadid:{tid}`` mapping
        #    on its live path; if it is absent (e.g. the player endpoint is
        #    hit before any teams call) we trigger ``resolve_teams`` once
        #    so the mapping is filled.
        squad_info = await self._get_squad_info(normalized_id)

        # 3. Cricbuzz live path. Either step returning ``None`` (or any
        #    exception, defensively) routes through to the static fallback
        #    so catalog endpoints never fail with HTTP 500 due to a
        #    Cricbuzz problem (Requirement 9.5).
        live_players: Optional[List[dict]] = None
        if squad_info is not None:
            try:
                live_players = await self._svc.get_squad_players(
                    squad_info["series_id"],
                    squad_info["cricbuzz_squad_id"],
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Cricbuzz get_squad_players raised %s for %s; "
                    "falling back to static roster",
                    type(exc).__name__,
                    normalized_id,
                )
                live_players = None

        if live_players:
            mapped = self._map_live_players(live_players)
            if mapped:
                # Cache the resolved payload so subsequent requests within
                # the TTL skip the upstream call (Requirement 2.2 / 6.2).
                self._cache.set(cache_key, mapped, ttl=CATALOG_TTL_SECONDS)
                return mapped, "live"

        # 4. Cricbuzz unavailable or returned an unusable payload: serve
        #    the static fallback roster verbatim, tagged ``fallback``. The
        #    fallback payload is intentionally not cached so the next
        #    request retries Cricbuzz (Requirement 6.6).
        return self._build_fallback_players(normalized_id), "fallback"

    async def resolve_venues(self) -> Tuple[List[dict], str]:
        """Resolve the IPL venue catalog with the live/cache/fallback policy.

        Returns
        -------
        ``(venues, source)`` where ``venues`` is a list of dicts shaped like
        the static ``VENUES`` records (``id``, ``name``, ``city``,
        ``default_pitch``, ``avg_first_innings``) plus the additive
        ``cricbuzz_venue_id`` and ``source`` fields, and ``source`` is one of
        ``"live"``, ``"cache"``, or ``"fallback"``.

        Resolution rules:

        * Cache hit short-circuits to ``source="cache"`` with every record's
          ``source`` re-tagged accordingly (Requirement 6.5).
        * On the live path, each Cricbuzz entry is mapped via
          ``ID_Mapper.to_internal_venue_id``; on a miss, the ground name is
          slugged to produce a fallback id. Records whose internal id matches
          a static ``VENUES`` entry inherit the static
          ``id``/``default_pitch``/``avg_first_innings`` so previously stored
          predictions still resolve (Requirement 4.5); other live records use
          ``default_pitch="balanced"`` and ``avg_first_innings=170``
          (Requirement 4.2).
        * A successful Cricbuzz call returning an empty list yields
          ``([], "live")`` per Requirement 4.3 (the empty payload is also
          cached so a subsequent request reports ``source="cache"`` while the
          TTL is alive).
        * Slug collisions between two distinct live entries are broken with a
          deterministic ``-2``, ``-3``, … suffix so no two live records share
          the same ``id`` (Requirement 12.4).
        * Any Cricbuzz failure (``None`` from ``get_ipl_series_id`` or
          ``get_series_venues``) routes through to the static ``VENUES``
          table tagged ``"fallback"`` (Requirement 4.4 / 9.5). The fallback
          payload is intentionally not cached so the next request retries
          Cricbuzz (Requirement 6.6).
        """
        # 1. Cache hit short-circuit. The stored payload was built by a prior
        #    successful live path; on hit we re-tag every element's source so
        #    the badge in the frontend renders "CACHED" (Requirement 6.5).
        cached, hit = self._cache.get(VENUES_RESOLVED_KEY)
        if hit and cached is not None:
            cached_with_cache_source = [
                {**venue, "source": "cache"} for venue in cached
            ]
            return cached_with_cache_source, "cache"

        # 2. Cricbuzz live path: discover the IPL series id, then list its
        #    venues. ``CricbuzzService.get_series_venues`` returns:
        #      * a non-empty list on cricbuzz_success → live path
        #      * an empty list on HTTP 200 with an empty array → empty live
        #        path (Requirement 4.3)
        #      * ``None`` on every failure mode → fallback
        series_id = await self._svc.get_ipl_series_id()
        if series_id is None:
            return self._build_fallback_venues(), "fallback"

        try:
            cb_venues = await self._svc.get_series_venues(series_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Cricbuzz get_series_venues raised %s; "
                "falling back to static venues",
                type(exc).__name__,
            )
            cb_venues = None

        if cb_venues is None:
            # Failure / malformed payload: serve static fallback (Req 4.4).
            return self._build_fallback_venues(), "fallback"

        # 3. Cricbuzz returned 200 with an empty list (Requirement 4.3).
        #    Cache the empty payload so subsequent requests within the TTL
        #    can short-circuit and return ``source="cache"``.
        if not cb_venues:
            self._cache.set(VENUES_RESOLVED_KEY, [], ttl=CATALOG_TTL_SECONDS)
            return [], "live"

        # 4. Cricbuzz returned a non-empty list: map each entry through
        #    ID_Mapper, overlay static metadata when the resolved id is
        #    recognised, and break slug collisions deterministically.
        mapped = self._build_live_venues(cb_venues)
        self._cache.set(VENUES_RESOLVED_KEY, mapped, ttl=CATALOG_TTL_SECONDS)
        return mapped, "live"

    async def resolve_live_xi(self, match_id: int) -> dict:
        """Augment a Cricbuzz scorecard with a top-level ``xi`` dict.

        Calls :meth:`CricbuzzService.fetch_match_scorecard_detail` and,
        on success, returns the raw scorecard payload extended with two
        extra top-level keys:

        * ``xi`` — a dict keyed by ``Internal_Team_Id`` whose values are
          arrays of ``{name, image_id, cricbuzz_player_id, role}``
          records derived from each ``batTeamDetails.playersData`` entry,
          ordered by Cricbuzz batting position. Players whose name does
          not match the static fallback roster for the same internal id
          are still included verbatim (Requirement 3.3).
        * ``source`` — ``"live"`` whenever the payload originated from
          Cricbuzz_Service, ``"cache"`` whenever it was served from the
          ``Cache_Layer`` (Requirement 6.5). The route handler does not
          inspect ``source`` for the live-XI flow, but emitting it keeps
          the response shape uniform with the catalog endpoints.

        On every failure path the method returns a small dict whose
        ``ok`` field is ``False`` so the route handler in
        ``backend/server.py`` can map the failure category to the
        live-only error matrix from Requirements 3.4–3.6 without
        catching exceptions:

        * ``{"ok": False, "error": "missing_key"}``
            → HTTP 503 with body
            ``{"detail": "Cricbuzz API key not configured", "source": "fallback"}``
            (Requirement 3.4).
        * ``{"ok": False, "error": "auth_failed", "status": 401|403}``
            → HTTP 503 with body
            ``{"detail": "Cricbuzz authentication failed", "source": "fallback"}``
            (Requirement 3.6).
        * ``{"ok": False, "error": "upstream", "status": <int>}``
            → HTTP 502 with body
            ``{"detail": "Cricbuzz upstream error", "status": <int>}``
            (Requirement 3.5).
        * ``{"ok": False, "error": "unparseable"}``
            → HTTP 502 with body
            ``{"detail": "Cricbuzz returned an unparseable scorecard"}``
            (Requirement 3.5).

        Network errors (transport-level failures, timeouts) and the
        active 429 cooldown collapse to the same ``upstream`` outcome
        with ``status=503`` so the route handler treats them as a
        Cricbuzz outage (Requirement 9.2 / 9.3) — a richer mapping was
        considered but is not required by Requirement 3.

        Parameters
        ----------
        match_id:
            Cricbuzz numeric match id (the same value returned in
            ``matches/v1/live`` payloads).

        Returns
        -------
        dict
            On success, the raw scorecard dict augmented with ``xi`` and
            ``source``. On failure, a small ``{"ok": False, "error":
            ...}`` envelope as described above.
        """
        # 0. Missing-key short-circuit. We surface this before any I/O so
        #    Requirement 3.4 holds on a misconfigured deployment without
        #    relying on the upstream returning anything specific.
        if not getattr(self._svc, "has_api_key", True):
            return {"ok": False, "error": "missing_key"}

        # 1. Fetch the scorecard with explicit error detail so we can
        #    discriminate auth-failures from other upstream errors. This
        #    method honours the same cache key as ``get_match_scorecard``
        #    so the live-XI path benefits from any cached scorecard.
        try:
            outcome = await self._svc.fetch_match_scorecard_detail(match_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Cricbuzz fetch_match_scorecard_detail raised %s for match %s",
                type(exc).__name__,
                match_id,
            )
            return {"ok": False, "error": "upstream", "status": 503}

        if not isinstance(outcome, dict):
            # Defensive: a stub or future change returning something other
            # than the documented tagged dict is treated as upstream
            # failure rather than crashing the route handler.
            return {"ok": False, "error": "unparseable"}

        kind = outcome.get("kind")
        if kind == "missing_key":
            return {"ok": False, "error": "missing_key"}
        if kind == "auth_failed":
            return {
                "ok": False,
                "error": "auth_failed",
                "status": _coerce_status(outcome.get("status"), default=401),
            }
        if kind == "upstream":
            return {
                "ok": False,
                "error": "upstream",
                "status": _coerce_status(outcome.get("status"), default=502),
            }
        if kind in ("network", "cooldown"):
            # Transport-level / cooldown errors map to the same
            # "upstream unavailable" outcome the route handler will
            # report as HTTP 502 (Requirement 3.5 / 9.2 / 9.3).
            return {"ok": False, "error": "upstream", "status": 503}
        if kind != "ok":
            return {"ok": False, "error": "unparseable"}

        payload = outcome.get("payload")
        if not isinstance(payload, dict) or not payload:
            return {"ok": False, "error": "unparseable"}

        # 2. Build the ``xi`` map. The augmentation is total — even when
        #    the scorecard is missing ``scoreCard``/``batTeamDetails``,
        #    we still attach an empty ``xi`` dict so the response shape
        #    stays uniform.
        xi = self._build_live_xi(payload)

        # ``source`` is reported alongside ``xi`` so the response shape
        # matches the catalog endpoints. Cache-vs-live is inferred from
        # whether the cached entry was already populated — this is a
        # best-effort signal because the underlying fetch helper does
        # not currently surface that distinction.
        cached, was_cache_hit = self._cache.get(f"scard:{match_id}")
        source = "cache" if was_cache_hit and cached is payload else "live"

        # Avoid mutating the cached payload in-place: shallow-copy the
        # outer dict so the augmentation does not leak back into the
        # cache (the cached entry must keep matching upstream shape).
        augmented = dict(payload)
        augmented["xi"] = xi
        augmented["source"] = source
        return augmented

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_live_index(
        self,
        series_id: int,
        squads: List[dict],
    ) -> dict[str, dict]:
        """Walk a Cricbuzz squads payload and build the Internal_Team_Id index.

        Side effects:
        * Logs a WARNING for every Cricbuzz squad that ``ID_Mapper`` cannot
          resolve to one of the ten Internal_Team_Ids (Requirement 1.4).
        * Stores ``squadid:{internal_id}`` in the cache so ``resolve_players``
          can look up the Cricbuzz ``squadId`` and ``teamId`` without
          re-issuing the squads call (Requirement 7.4).
        """
        live_by_internal_id: dict[str, dict] = {}
        for squad in squads:
            if not isinstance(squad, dict):
                continue

            # Cricbuzz's squads endpoint identifies each team-in-series by
            # ``squadId``. Some payload variants also expose ``teamId``; treat
            # ``teamId`` as the franchise-level id when present and
            # ``squadId`` as the per-series squad id.
            cb_squad_id = _coerce_int(squad.get("squadId"))
            cb_team_id = _coerce_int(squad.get("teamId")) or cb_squad_id
            squad_name = (
                squad.get("squadType")
                or squad.get("squadName")
                or squad.get("teamName")
                or ""
            )
            image_id = squad.get("imageId")

            internal_id = id_mapper.to_internal_team_id(cb_team_id, squad_name)
            if internal_id is None:
                logger.warning(
                    "Cricbuzz squad %r (teamId=%s, squadId=%s) did not map to "
                    "an Internal_Team_Id; excluding from live response",
                    squad_name,
                    cb_team_id,
                    cb_squad_id,
                )
                continue

            # First match wins; subsequent duplicate mappings are ignored so
            # the response never contains duplicate ids (Property 3).
            if internal_id in live_by_internal_id:
                continue

            static_team = get_team(internal_id)
            if static_team is None:
                # Defensive: id_mapper only emits ids known to ipl_data.TEAMS,
                # but if that ever drifts we skip the entry rather than crash.
                continue

            live_by_internal_id[internal_id] = _build_live_team_record(
                internal_id=internal_id,
                static_team=static_team,
                cricbuzz_team_id=cb_team_id,
                cricbuzz_squad_id=cb_squad_id,
                cricbuzz_name=squad_name or None,
                image_id=image_id,
            )

            # Persist the per-team Cricbuzz id mapping for resolve_players.
            if cb_squad_id is not None:
                self._cache.set(
                    _squadid_cache_key(internal_id),
                    {
                        "series_id": series_id,
                        "cricbuzz_team_id": cb_team_id,
                        "cricbuzz_squad_id": cb_squad_id,
                    },
                    ttl=CATALOG_TTL_SECONDS,
                )

        return live_by_internal_id

    async def _get_squad_info(
        self,
        internal_team_id: str,
    ) -> Optional[dict]:
        """Return the cached ``(series_id, cricbuzz_team_id, cricbuzz_squad_id)``.

        ``resolve_teams`` populates ``squadid:{tid}`` whenever its live path
        maps a squad. If the entry is missing — typically because the
        players endpoint was hit before any teams call — we trigger
        ``resolve_teams`` once to populate it. Returns ``None`` if the
        mapping is still absent (i.e. Cricbuzz is unavailable or the team
        has no resolved Cricbuzz squad), which routes ``resolve_players``
        to the static fallback (Requirement 2.4).
        """
        info, hit = self._cache.get(_squadid_cache_key(internal_team_id))
        if hit and isinstance(info, dict) and info.get("cricbuzz_squad_id") is not None:
            return info

        # Trigger a one-shot teams resolution so the squad-id mapping gets
        # populated. ``resolve_teams`` swallows Cricbuzz failures, so we
        # only need to guard against it raising HTTP 503 (the both-empty
        # case from Requirement 1.5) — that's a deployment-level error
        # which we re-surface to the players path as a fallback (the
        # static module is guaranteed to have rosters in this build).
        try:
            await self.resolve_teams()
        except HTTPException:
            return None
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "resolve_teams raised %s while resolving players for %s",
                type(exc).__name__,
                internal_team_id,
            )
            return None

        info, hit = self._cache.get(_squadid_cache_key(internal_team_id))
        if hit and isinstance(info, dict) and info.get("cricbuzz_squad_id") is not None:
            return info
        return None

    def _map_live_players(self, players: List[Any]) -> List[dict]:
        """Convert a Cricbuzz ``player`` array into the resolver's player schema.

        The Cricbuzz squads endpoint groups players under header rows
        (``"isHeader": true`` entries like ``"batsmen"``, ``"bowlers"``,
        ``"all rounder"``, ``"wicket keeper"``). Header rows are dropped;
        every actual player row is mapped into a ``PlayerStat``-compatible
        dict with the four numeric fields defaulted to ``0`` per
        Requirement 2.3, the ``role`` normalised via :func:`_normalize_role`,
        and the additive ``image_id`` / ``cricbuzz_player_id`` /
        ``source="live"`` fields attached.
        """
        # Track the most recent header so we can use it as a role hint
        # when an individual player record omits the ``role`` field.
        current_section: Optional[str] = None
        mapped: List[dict] = []
        seen_keys: set[tuple[Optional[int], str]] = set()

        for entry in players:
            if not isinstance(entry, dict):
                continue

            if entry.get("isHeader"):
                # Header rows look like {"isHeader": true, "name": "batsmen"}.
                header_name = entry.get("name") or entry.get("title") or ""
                current_section = header_name if isinstance(header_name, str) else None
                continue

            name = entry.get("name") or entry.get("fullName") or entry.get("nickName")
            if not isinstance(name, str) or not name.strip():
                # Skip malformed records rather than crash the whole roster.
                continue
            name = name.strip()

            cricbuzz_player_id = _coerce_int(entry.get("id") or entry.get("playerId"))

            # De-duplicate when Cricbuzz repeats a player across sections
            # (rare but observed for all-rounders in some payload variants).
            dedupe_key = (cricbuzz_player_id, name.lower())
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            raw_role = entry.get("role") or current_section or ""
            role = _normalize_role(raw_role)

            country = _country_code(
                entry.get("teamName")
                or entry.get("countryName")
                or entry.get("country")
            )

            image_id = entry.get("faceImageId") or entry.get("imageId")
            mapped.append(
                {
                    "name": name,
                    "role": role,
                    # Cricbuzz does not surface these aggregates, so they
                    # default to 0 to preserve the ``PlayerStat`` schema
                    # (Requirement 2.3).
                    "batting_avg": 0,
                    "strike_rate": 0,
                    "wickets": 0,
                    "economy": 0,
                    "country": country,
                    "image_id": str(image_id) if image_id else None,
                    "cricbuzz_player_id": cricbuzz_player_id,
                    "source": "live",
                }
            )

        return mapped

    def _build_fallback_players(self, internal_team_id: str) -> List[dict]:
        """Return the static roster augmented with the additive resolver fields.

        Static records carry every key already used by ``PlayerStat`` so we
        only need to extend each one with ``image_id``, ``cricbuzz_player_id``
        (both ``None`` on the fallback path), and ``source="fallback"``.
        """
        static_roster = get_players(internal_team_id) or []
        return [
            {
                **player,
                "image_id": None,
                "cricbuzz_player_id": None,
                "source": "fallback",
            }
            for player in static_roster
        ]

    # ------------------------------------------------------------------
    # Venue helpers
    # ------------------------------------------------------------------

    def _build_live_venues(self, cb_venues: List[Any]) -> List[dict]:
        """Map a Cricbuzz venues array into the resolver's venue schema.

        Each entry is resolved via ``ID_Mapper.to_internal_venue_id``; on a
        miss the ``ground`` name is slugged to produce a fallback id. When
        the resolved id is in ``ipl_data.VENUES`` we overlay
        ``id``/``default_pitch``/``avg_first_innings`` from the static
        record so previously stored predictions keep resolving
        (Requirement 4.5). Otherwise the live record uses
        ``default_pitch="balanced"`` and ``avg_first_innings=170``
        (Requirement 4.2).

        Slug collisions between two distinct live entries are broken with
        a deterministic ``-2``, ``-3``, … suffix so no two live records
        share the same ``id`` (Requirement 12.4). Static-id matches are
        not subject to suffixing because each static id can only be
        produced once (the first Cricbuzz entry that resolves to it
        wins; subsequent entries that would also resolve to the same
        static id are deduplicated like any other slug collision).
        """
        # ``id``s already used in this response, in the order they were
        # claimed. Used both to detect collisions and to short-circuit
        # duplicate Cricbuzz entries that map to the same internal venue.
        used_ids: set[str] = set()
        mapped: List[dict] = []

        for entry in cb_venues:
            if not isinstance(entry, dict):
                continue
            ground = entry.get("ground") or entry.get("groundName") or ""
            city = entry.get("city") or entry.get("cityName") or ""
            if not isinstance(ground, str) or not ground.strip():
                # Skip malformed records (no ground name) rather than crash
                # the whole catalog.
                continue
            ground = ground.strip()
            city = city.strip() if isinstance(city, str) else ""

            cb_venue_id = _coerce_int(entry.get("id") or entry.get("venueId"))

            internal_id = id_mapper.to_internal_venue_id(ground, city)
            static_venue = get_venue(internal_id) if internal_id else None

            if static_venue is not None:
                # Static-id overlay path (Requirement 4.5).
                resolved_id = static_venue["id"]
                if resolved_id in used_ids:
                    # Two live entries resolved to the same static id —
                    # collapse to the first one. This protects the
                    # uniqueness invariant (Requirement 12.4).
                    continue
                default_pitch = static_venue["default_pitch"]
                avg_first_innings = static_venue["avg_first_innings"]
            else:
                # Slug fallback path. Build a unique id by appending a
                # deterministic ``-2``, ``-3``, … suffix on collision.
                base_slug = _slug_ground(ground) or "venue"
                resolved_id = _disambiguate_id(base_slug, used_ids)
                default_pitch = DEFAULT_PITCH
                avg_first_innings = DEFAULT_AVG_FIRST_INNINGS

            used_ids.add(resolved_id)
            mapped.append(
                {
                    "id": resolved_id,
                    "name": ground,
                    "city": city,
                    "cricbuzz_venue_id": cb_venue_id,
                    "default_pitch": default_pitch,
                    "avg_first_innings": avg_first_innings,
                    "source": "live",
                }
            )

        return mapped

    def _build_fallback_venues(self) -> List[dict]:
        """Return the static ``VENUES`` augmented with the additive resolver fields.

        The static records already carry the schema the frontend expects
        (``id``, ``name``, ``city``, ``default_pitch``, ``avg_first_innings``);
        we only extend each one with ``cricbuzz_venue_id=None`` and
        ``source="fallback"``.
        """
        return [
            {
                **venue,
                "cricbuzz_venue_id": None,
                "source": "fallback",
            }
            for venue in VENUES
        ]

    # ------------------------------------------------------------------
    # Live XI helpers
    # ------------------------------------------------------------------

    def _build_live_xi(self, scorecard: dict) -> dict:
        """Build the ``xi`` map from a Cricbuzz scorecard payload.

        Walks every ``batTeamDetails`` block under either ``scoreCard``
        (the historical-style key used by ``/mcenter/v1/{id}/hscard``)
        or the legacy ``scorecard`` field. For each block we resolve
        the team via ``ID_Mapper.to_internal_team_id`` from the
        Cricbuzz ``batTeamId``/``batTeamName``/``batTeamShortName``
        fields, then expand ``playersData`` into an ordered list of
        ``{name, image_id, cricbuzz_player_id, role}`` records.

        Ordering rule (Requirement 3.2): players are sorted by Cricbuzz
        ``batOrder`` ascending where present, falling back to the
        original ``playersData`` insertion order for entries without a
        batting position. ``playersData`` keys are typically the
        Cricbuzz player id; the records themselves carry ``id`` /
        ``playerId`` / ``batOrder`` / ``role`` / ``name`` / ``shortName``
        / ``faceImageId``.

        Unmatched team ids (Requirement 3.3 / 1.4): when ID_Mapper does
        not recognise the team — e.g. an exhibition fixture — the block
        is skipped silently. When ID_Mapper resolves the team but a
        player's ``name`` does not match anything in the static fallback
        roster, the player is still included in the array using the
        Cricbuzz name verbatim (this is enforced implicitly because the
        live-XI build path never consults the static roster).

        Returns
        -------
        dict
            ``{<internal_team_id>: [{name, image_id, cricbuzz_player_id,
            role}, ...]}``. Empty when the scorecard carries no
            recognisable ``batTeamDetails`` blocks.
        """
        xi: dict[str, list[dict]] = {}

        # Locate the array of ``{batTeamDetails, ...}`` blocks. The
        # ``hscard`` endpoint nests them under ``scoreCard``; older
        # variants used the lower-cased ``scorecard`` key.
        innings_list = scorecard.get("scoreCard")
        if not isinstance(innings_list, list):
            innings_list = scorecard.get("scorecard")
        if not isinstance(innings_list, list):
            return xi

        for innings in innings_list:
            if not isinstance(innings, dict):
                continue
            details = innings.get("batTeamDetails") or innings.get("battingTeamDetails")
            if not isinstance(details, dict):
                continue

            cb_team_id = _coerce_int(
                details.get("batTeamId")
                or details.get("teamId")
            )
            team_name = (
                details.get("batTeamName")
                or details.get("batTeamShortName")
                or details.get("teamName")
                or ""
            )

            internal_id = id_mapper.to_internal_team_id(cb_team_id, team_name)
            if internal_id is None:
                # Unrecognised team — skip this block but keep walking
                # the rest of the scorecard so the other side still
                # appears in ``xi``.
                continue

            players_data = details.get("playersData")
            if not isinstance(players_data, dict):
                # Some payload variants embed the players under an
                # ``order`` field; we accept both.
                fallback_order = details.get("order")
                if isinstance(fallback_order, list):
                    players_iter = list(enumerate(fallback_order))
                else:
                    players_iter = []
            else:
                players_iter = list(enumerate(players_data.values()))

            xi[internal_id] = self._players_data_to_xi_array(players_iter)

        return xi

    @staticmethod
    def _players_data_to_xi_array(
        players_iter: list[tuple[int, Any]],
    ) -> list[dict]:
        """Transform a Cricbuzz ``playersData`` iterable into ordered XI records.

        ``players_iter`` is a list of ``(insertion_index, player_dict)``
        tuples so we can sort by ``batOrder`` while keeping the
        ``playersData`` insertion order as a stable tiebreak when the
        payload omits ``batOrder`` for some entries (Requirement 3.2).
        Each output record carries exactly the four fields documented
        in the task: ``name``, ``image_id``, ``cricbuzz_player_id``,
        ``role``. Names are preserved verbatim — including unicode and
        non-ASCII characters — so the frontend can render them as-is
        even when ID_Mapper cannot match them to a static roster
        (Requirement 3.3).
        """
        prepared: list[tuple[float, int, dict]] = []
        for insertion_index, raw in players_iter:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name") or raw.get("fullName") or raw.get("shortName")
            if not isinstance(name, str) or not name.strip():
                continue
            name = name.strip()

            cricbuzz_player_id = _coerce_int(raw.get("id") or raw.get("playerId"))

            face_image = raw.get("faceImageId") or raw.get("imageId")
            image_id = str(face_image) if face_image else None

            raw_role = raw.get("role") or raw.get("playingRole") or ""
            role = _normalize_role(raw_role)

            order_raw = raw.get("batOrder")
            order_value = _coerce_int(order_raw)
            sort_key = (
                float(order_value)
                if order_value is not None
                else float("inf")
            )

            prepared.append((
                sort_key,
                insertion_index,
                {
                    "name": name,
                    "image_id": image_id,
                    "cricbuzz_player_id": cricbuzz_player_id,
                    "role": role,
                },
            ))

        # Sort by (batOrder ascending, insertion order) so entries without
        # a batting position trail in their original order — Requirement
        # 3.2 (ordered by Cricbuzz batting position).
        prepared.sort(key=lambda item: (item[0], item[1]))
        return [record for _sort, _idx, record in prepared]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


# Cricbuzz role strings vary in case and phrasing across payload variants;
# we normalise them into the four canonical labels expected by the
# ``PlayerStat`` schema (Requirement 2.2).
_ROLE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    # Order matters: keep "wk-batsman" / "wicket keeper" before plain
    # "batsman" so a wicket-keeper-batsman is classified as a keeper, not
    # a batsman. Likewise "all rounder" before its constituents.
    (("wicketkeeper", "wicket-keeper", "wicket keeper", "wk-bat", "wk batsman", "keeper"), "Wicket-keeper"),
    (("allrounder", "all-rounder", "all rounder", "all_rounder"), "All-rounder"),
    (("bowler", "bowling"), "Bowler"),
    (("batsman", "batter", "batting", "batsmen"), "Batsman"),
]


def _normalize_role(raw: Any) -> str:
    """Map a Cricbuzz ``role``/section string to a canonical role label.

    Returns one of ``"Batsman"``, ``"Bowler"``, ``"All-rounder"``, or
    ``"Wicket-keeper"``. Falls back to ``"Batsman"`` for empty or
    unrecognised inputs so the resulting record always conforms to the
    ``PlayerStat`` schema (Requirement 2.2).
    """
    if not isinstance(raw, str):
        return "Batsman"
    needle = raw.strip().lower()
    if not needle:
        return "Batsman"
    for keywords, canonical in _ROLE_KEYWORDS:
        for kw in keywords:
            if kw in needle:
                return canonical
    return "Batsman"


def _country_code(value: Any) -> str:
    """Return a 2- or 3-letter country code, defaulting to ``"IND"``.

    Cricbuzz uses short country codes for the ``teamName``/``countryName``
    field — typically 3 letters (``"IND"``, ``"AUS"``, ``"ENG"``, ``"AFG"``)
    but sometimes 2 letters (``"WI"``, ``"NZ"``, ``"SA"``, ``"SL"``). The
    static module uses the same codes, so we pass them through verbatim.
    Anything longer or non-alphabetic falls back to ``"IND"`` to keep the
    response shape aligned with the existing ``PlayerStat`` contract.
    """
    if not isinstance(value, str):
        return "IND"
    cleaned = value.strip()
    if not cleaned:
        return "IND"
    if 2 <= len(cleaned) <= 3 and cleaned.isalpha():
        return cleaned.upper()
    return "IND"


def _coerce_int(value: Any) -> Optional[int]:
    """Best-effort conversion of Cricbuzz numeric ids to ``int``.

    Cricbuzz occasionally returns string-encoded ids; we accept both and
    silently drop anything else (returning ``None`` so ID_Mapper falls back
    to name-based resolution).
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Pattern matching any run of non-alphanumeric characters; used by
# ``_slug_ground`` to collapse punctuation and whitespace into single hyphens.
_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _slug_ground(ground: str) -> str:
    """Return a URL-safe slug derived from a Cricbuzz ``ground`` name.

    The slug is lower-cased, whitespace and punctuation are collapsed into
    single ``-`` characters, and leading/trailing hyphens are stripped.
    Returns an empty string when no alphanumeric characters survive (the
    caller substitutes a generic fallback in that case so the response
    record always carries a non-empty ``id`` per Requirement 12.4).
    """
    if not isinstance(ground, str):
        return ""
    return _SLUG_NON_ALNUM.sub("-", ground.lower()).strip("-")


def _disambiguate_id(base: str, used: set[str]) -> str:
    """Return ``base`` or ``base-2``, ``base-3``, … not in ``used``.

    Pure helper used by ``_build_live_venues`` to enforce the no-duplicate-id
    invariant on slug-fallback records (Requirement 12.4). The first
    available ``base-N`` integer is returned (``N >= 2``) so the suffix is
    deterministic given a fixed input order.
    """
    if base not in used:
        return base
    counter = 2
    while True:
        candidate = f"{base}-{counter}"
        if candidate not in used:
            return candidate
        counter += 1


def _coerce_status(value: Any, default: int) -> int:
    """Coerce a status field from a tagged-union outcome into an ``int``.

    Used by ``resolve_live_xi`` to defensively normalise the ``status``
    field returned by ``CricbuzzService.fetch_match_scorecard_detail``
    (which already emits ``int``) so that future stub implementations or
    payload drift cannot leak a non-integer status into the route
    handler. Returns ``default`` for ``None``, non-coercible values, or
    statuses outside the legal HTTP range.
    """
    coerced = _coerce_int(value)
    if coerced is None or not (100 <= coerced <= 599):
        return default
    return coerced
