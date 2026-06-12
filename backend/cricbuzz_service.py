"""Async client for the RapidAPI Cricbuzz endpoints used by the backend.

Implements the ``Cricbuzz_Service`` component described in the
``real-data-cricbuzz-integration`` design document (task 4.1).

Responsibilities
----------------
* Owns a single shared :class:`httpx.AsyncClient` (injected) so connection
  pooling is reused across requests.
* Reads the RapidAPI key once at construction and never echoes it into log
  output (Requirements 3.6, 9.4).
* Applies a 10-second connect+read timeout to every outbound call
  (Requirement 9.1).
* Tracks an internal ``_cooldown_until`` timestamp; while ``now() <
  _cooldown_until`` every public method short-circuits to ``None`` without
  any I/O (Requirement 9.3).
* Implements the failure-handling matrix from the design verbatim: missing
  key, network error/timeout, 401/403, 429, 5xx, and 200-with-empty-body
  all return ``None`` so the ``Data_Resolver`` can apply its fallback path
  (Requirements 9.2, 9.4, 9.5; design's failure-handling matrix).
* Caches only ``cricbuzz_success`` (200 + non-empty) payloads with the
  TTLs specified in the design's cache key catalog (Requirements 6.1–6.4,
  6.6).

The class never raises for upstream failures: every public method either
returns the decoded JSON / extracted array / image bytes on success, or
``None`` on any failure path.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, List, Optional

import httpx

from cache_layer import CacheLayer

logger = logging.getLogger("ipl.cricbuzz_service")


# ---------------------------------------------------------------------------
# Constants — match the design's cache key catalog and TTL table verbatim.
# ---------------------------------------------------------------------------

# RapidAPI host configuration. The base URL never carries the API key.
CRICBUZZ_BASE_URL = "https://cricbuzz-cricket.p.rapidapi.com"
CRICBUZZ_HOST = "cricbuzz-cricket.p.rapidapi.com"

# Connect+read timeout applied to every outbound call (Requirement 9.1).
REQUEST_TIMEOUT_SECONDS = 10.0

# 429 cooldown duration (Requirement 9.3).
COOLDOWN_SECONDS = 60.0

# TTLs from Requirement 6.2 / 6.3 / 6.4 and the design's cache-key table.
CATALOG_TTL_SECONDS = 21600  # 6 hours: series listing, squads, players, venues
LIVE_MATCHES_TTL_SECONDS = 60  # /matches/v1/live
UPCOMING_MATCHES_TTL_SECONDS = 300  # /matches/v1/upcoming
SCORECARD_TTL_SECONDS = 30  # /mcenter/v1/{matchId}/hscard and /mcenter/v1/{matchId}

# Cache keys (kept module-level so tests and the admin refresh handler can
# reference them without hard-coding strings).
SERIES_LIST_KEY = "series:league"
LIVE_MATCHES_KEY = "matches:live"
UPCOMING_MATCHES_KEY = "matches:upcoming"


def _squads_cache_key(series_id: int) -> str:
    return f"squads:{series_id}"


def _squad_players_cache_key(series_id: int, squad_id: int) -> str:
    return f"squad:{series_id}:{squad_id}"


def _series_venues_cache_key(series_id: int) -> str:
    return f"venues:{series_id}"


def _scorecard_cache_key(match_id: int) -> str:
    return f"scard:{match_id}"


def _match_info_cache_key(match_id: int) -> str:
    return f"minfo:{match_id}"


# ---------------------------------------------------------------------------
# CricbuzzService
# ---------------------------------------------------------------------------


class CricbuzzService:
    """Thin async client for the RapidAPI Cricbuzz endpoints.

    Parameters
    ----------
    api_key:
        Value of the ``CRICBUZZ_API_KEY`` environment variable. ``None`` or
        an empty string disables every outbound call (Requirement 9.4).
    cache:
        Shared :class:`CacheLayer` instance. Populated only on
        ``cricbuzz_success`` (Requirement 6.1, 6.6).
    http:
        Shared :class:`httpx.AsyncClient`. Reused for connection pooling.
    clock:
        Callable returning a monotonic float timestamp in seconds. Injected
        so tests can drive a virtual clock against the 60-second 429
        cooldown. Defaults to :func:`time.monotonic`.
    """

    def __init__(
        self,
        api_key: Optional[str],
        cache: CacheLayer,
        http: httpx.AsyncClient,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._api_key: str = (api_key or "").strip()
        self._cache = cache
        self._http = http
        self._clock: Callable[[], float] = clock or time.monotonic
        # ``None`` means "no cooldown active". When set, holds the monotonic
        # timestamp at which outbound calls may resume.
        self._cooldown_until: Optional[float] = None

        if not self._api_key:
            # Single startup WARNING — every subsequent call short-circuits
            # without further logging (Requirement 9.4).
            logger.warning(
                "CRICBUZZ_API_KEY is not configured; "
                "Cricbuzz calls will be skipped and catalog endpoints "
                "will serve static fallback data"
            )

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def has_api_key(self) -> bool:
        """Whether a non-empty Cricbuzz API key is configured.

        Used by the live-XI resolver to distinguish "missing key" (which
        Requirement 3.4 maps to HTTP 503 with detail
        ``"Cricbuzz API key not configured"``) from every other failure
        mode without issuing any I/O. Pure read of ``_api_key``.
        """
        return bool(self._api_key)

    # ------------------------------------------------------------------
    # Public methods (one per Cricbuzz endpoint we consume)
    # ------------------------------------------------------------------

    async def get_series_list(self) -> Optional[dict]:
        """``GET /series/v1/league`` — list of all series across formats.

        Cache key ``series:league``, TTL 21600s. Returns the raw decoded
        JSON or ``None`` on any failure / empty body.
        """
        cached, hit = self._cache.get(SERIES_LIST_KEY)
        if hit:
            return cached
        payload = await self._http_get_json("/series/v1/league")
        if not payload:
            return None
        self._cache.set(SERIES_LIST_KEY, payload, ttl=CATALOG_TTL_SECONDS)
        return payload

    async def get_ipl_series_id(self) -> Optional[int]:
        """Locate the current IPL series id within the series listing.

        Walks ``payload["seriesMapProto"][*]["seriesAdWrapper"]["series"][*]``
        in document order and returns the integer ``id`` of the first
        entry whose ``seriesName`` contains ``"Indian Premier League"``.
        Returns ``None`` if the series listing is unavailable or no entry
        matches (Property 19).
        """
        payload = await self.get_series_list()
        if not isinstance(payload, dict):
            return None
        groups = payload.get("seriesMapProto")
        if not isinstance(groups, list):
            return None
        for group in groups:
            if not isinstance(group, dict):
                continue
            wrapper = group.get("seriesAdWrapper")
            if not isinstance(wrapper, dict):
                continue
            series_list = wrapper.get("series")
            if not isinstance(series_list, list):
                continue
            for series in series_list:
                if not isinstance(series, dict):
                    continue
                name = series.get("seriesName")
                if not isinstance(name, str):
                    continue
                if "Indian Premier League" not in name:
                    continue
                series_id = series.get("id")
                coerced = _coerce_int(series_id)
                if coerced is not None:
                    return coerced
        return None

    async def get_squads(self, series_id: int) -> Optional[List[dict]]:
        """``GET /series/v1/{series_id}/squads`` — IPL squads index.

        Cache key ``squads:{series_id}``, TTL 21600s. Returns the
        ``squads`` array of dicts (one per franchise) or ``None`` on any
        failure / empty body / missing array.
        """
        key = _squads_cache_key(series_id)
        cached, hit = self._cache.get(key)
        if hit:
            return cached
        payload = await self._http_get_json(f"/series/v1/{series_id}/squads")
        if not isinstance(payload, dict) or not payload:
            return None
        squads = _extract_first_list(payload, "squads")
        # An empty squads list is treated as a Cricbuzz failure for the
        # purposes of the resolver (Requirement 1.3) — return ``None`` so
        # the fallback path engages and do not cache.
        if not squads:
            return None
        self._cache.set(key, squads, ttl=CATALOG_TTL_SECONDS)
        return squads

    async def get_squad_players(
        self,
        series_id: int,
        squad_id: int,
    ) -> Optional[List[dict]]:
        """``GET /series/v1/{series_id}/squads/{squad_id}`` — one squad's roster.

        Cache key ``squad:{series_id}:{squad_id}``, TTL 21600s. Returns
        the ``player`` array (one record per squad member) or ``None`` on
        any failure / empty body / missing array.
        """
        key = _squad_players_cache_key(series_id, squad_id)
        cached, hit = self._cache.get(key)
        if hit:
            return cached
        payload = await self._http_get_json(
            f"/series/v1/{series_id}/squads/{squad_id}"
        )
        if not isinstance(payload, dict) or not payload:
            return None
        # Cricbuzz uses the singular key ``player``; some payload variants
        # also expose ``players``. We accept both.
        players = _extract_first_list(payload, "player", "players")
        if not players:
            return None
        self._cache.set(key, players, ttl=CATALOG_TTL_SECONDS)
        return players

    async def get_series_venues(
        self,
        series_id: int,
    ) -> Optional[List[dict]]:
        """``GET /series/v1/{series_id}/venues`` — venues hosting a series.

        Cache key ``venues:{series_id}``, TTL 21600s. Returns the venue
        list, possibly empty, or ``None`` on any failure / empty body /
        missing array. The empty-but-successful path is preserved so the
        resolver can return ``([], "live")`` per Requirement 4.3 — that
        empty list is **not** cached (cricbuzz_success requires a non-empty
        result).
        """
        key = _series_venues_cache_key(series_id)
        cached, hit = self._cache.get(key)
        if hit:
            return cached
        payload = await self._http_get_json(f"/series/v1/{series_id}/venues")
        if not isinstance(payload, dict) or not payload:
            return None
        venues = _extract_first_list(
            payload, "seriesVenue", "venues", "venue"
        )
        if venues is None:
            # Malformed payload — no recognisable venue array.
            return None
        if not venues:
            # Status 200, empty list. Surface it to the resolver but do
            # not cache (Requirement 6.1, Requirement 4.3).
            return []
        self._cache.set(key, venues, ttl=CATALOG_TTL_SECONDS)
        return venues

    async def get_live_matches(self) -> Optional[dict]:
        """``GET /matches/v1/live`` — currently live matches across all formats.

        Cache key ``matches:live``, TTL 60s. Returns the raw payload
        (typically ``{"typeMatches": [...]}``) or ``None`` on any failure
        / empty body.
        """
        cached, hit = self._cache.get(LIVE_MATCHES_KEY)
        if hit:
            return cached
        payload = await self._http_get_json("/matches/v1/live")
        if not payload:
            return None
        self._cache.set(LIVE_MATCHES_KEY, payload, ttl=LIVE_MATCHES_TTL_SECONDS)
        return payload

    async def get_upcoming_matches(self) -> Optional[dict]:
        """``GET /matches/v1/upcoming`` — scheduled fixtures across all formats.

        Cache key ``matches:upcoming``, TTL 300s (5 minutes — schedules
        change less often than live state). Returns ``None`` on any
        failure path so the route can serve an empty payload.
        """
        cached, hit = self._cache.get(UPCOMING_MATCHES_KEY)
        if hit:
            return cached
        payload = await self._http_get_json("/matches/v1/upcoming")
        if not payload:
            return None
        self._cache.set(UPCOMING_MATCHES_KEY, payload, ttl=UPCOMING_MATCHES_TTL_SECONDS)
        return payload

    async def get_match_scorecard(self, match_id: int) -> Optional[dict]:
        """``GET /mcenter/v1/{match_id}/hscard`` — full historical-style scorecard.

        Cache key ``scard:{match_id}``, TTL 30s. Returns the raw
        scorecard JSON or ``None`` on any failure / empty body.
        """
        key = _scorecard_cache_key(match_id)
        cached, hit = self._cache.get(key)
        if hit:
            return cached
        payload = await self._http_get_json(f"/mcenter/v1/{match_id}/hscard")
        if not payload:
            return None
        self._cache.set(key, payload, ttl=SCORECARD_TTL_SECONDS)
        return payload

    async def fetch_match_scorecard_detail(
        self,
        match_id: int,
    ) -> dict:
        """``GET /mcenter/v1/{match_id}/hscard`` with explicit error detail.

        Sister method to :meth:`get_match_scorecard` for callers (notably
        the live-XI resolver) that need to distinguish failure modes —
        missing key vs. auth failure vs. upstream non-2xx vs. network /
        unparseable — so that the route handler can map them to the
        live-only error matrix described in Requirements 3.4, 3.5, 3.6.

        The cache lifecycle matches :meth:`get_match_scorecard`: a cached
        payload is reused, and a fresh ``cricbuzz_success`` response is
        cached with TTL 30s.

        Returns a tagged-union dict, never ``None``:

        * ``{"kind": "ok",         "payload": <dict>}``
          — 2xx with a non-empty JSON body (cache hit or live).
        * ``{"kind": "missing_key"}``
          — ``CRICBUZZ_API_KEY`` empty/unset (Requirement 3.4).
        * ``{"kind": "auth_failed",  "status": 401|403}``
          — Cricbuzz returned 401/403 (Requirement 3.6).
        * ``{"kind": "upstream",     "status": int}``
          — Cricbuzz returned any other non-2xx (Requirement 3.5).
        * ``{"kind": "network"}``
          — transport-level failure or request timeout (Requirement 9.2).
        * ``{"kind": "unparseable"}``
          — 2xx but the body did not decode as a non-empty JSON dict
          (Requirement 3.5 — the resolver maps this to HTTP 502).
        * ``{"kind": "cooldown"}``
          — the 429 cooldown is active (Requirement 9.3); the resolver
          treats this as an upstream failure for the live-XI path.

        The 401/403 logging side effect, the 429 cooldown arming side
        effect, and the empty-body handling all match
        :meth:`_http_get_json` so behaviour is identical except that the
        outcome is exposed through the return value rather than collapsed
        to ``None``.
        """
        key = _scorecard_cache_key(match_id)
        cached, hit = self._cache.get(key)
        if hit and isinstance(cached, dict) and cached:
            return {"kind": "ok", "payload": cached}

        if not self._api_key:
            return {"kind": "missing_key"}
        if self._is_in_cooldown():
            return {"kind": "cooldown"}

        path = f"/mcenter/v1/{match_id}/hscard"
        try:
            response = await self._http.get(
                f"{CRICBUZZ_BASE_URL}{path}",
                headers=self._auth_headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning(
                "Cricbuzz request to %s failed with %s",
                path,
                type(exc).__name__,
            )
            return {"kind": "network"}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Cricbuzz request to %s raised %s", path, type(exc).__name__
            )
            return {"kind": "network"}

        status = response.status_code
        if 200 <= status < 300:
            try:
                payload = response.json()
            except ValueError:
                logger.warning(
                    "Cricbuzz request to %s returned %d with invalid JSON",
                    path,
                    status,
                )
                return {"kind": "unparseable"}
            if not isinstance(payload, dict) or not payload:
                # 200 with empty / non-dict body — treat as unparseable so
                # the route handler returns HTTP 502 rather than silently
                # serving an empty xi map (Requirement 3.5).
                return {"kind": "unparseable"}
            self._cache.set(key, payload, ttl=SCORECARD_TTL_SECONDS)
            return {"kind": "ok", "payload": payload}

        # Apply the standard failure-handling matrix side effects
        # (logging + 429 cooldown) before returning the tagged outcome.
        self._handle_failure_status(status, path)
        if status in (401, 403):
            return {"kind": "auth_failed", "status": status}
        return {"kind": "upstream", "status": status}

    async def get_match_info(self, match_id: int) -> Optional[dict]:
        """``GET /mcenter/v1/{match_id}`` — match centre summary.

        Cache key ``minfo:{match_id}``, TTL 30s. Returns the raw
        payload or ``None`` on any failure / empty body.
        """
        key = _match_info_cache_key(match_id)
        cached, hit = self._cache.get(key)
        if hit:
            return cached
        payload = await self._http_get_json(f"/mcenter/v1/{match_id}")
        if not payload:
            return None
        self._cache.set(key, payload, ttl=SCORECARD_TTL_SECONDS)
        return payload

    async def fetch_image(
        self,
        image_id: str,
        size: str = "thumb",
    ) -> Optional[bytes]:
        """``GET /img/v1/i1/{image_id}/i.jpg`` — JPEG asset bytes.

        ``size`` is the Cricbuzz ``p`` query parameter; recognised values
        are ``thumb`` (grid avatars) and ``det`` (hero renders). The
        result is **not** stored in the in-process cache — image bytes
        are large and the browser already caches them via the
        ``Cache-Control: public, max-age=86400`` response header set by
        the route handler (Requirement 5.3).
        """
        # Missing key / cooldown guards (Requirements 9.3, 9.4).
        if not self._api_key:
            return None
        if self._is_in_cooldown():
            return None

        path = f"/img/v1/i1/{image_id}/i.jpg"
        try:
            response = await self._http.get(
                f"{CRICBUZZ_BASE_URL}{path}",
                params={"p": size},
                headers=self._auth_headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            # Network error / timeout (Requirement 9.2). One WARNING line.
            logger.warning(
                "Cricbuzz image fetch (%s) failed with %s",
                image_id,
                type(exc).__name__,
            )
            return None
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Cricbuzz image fetch (%s) raised %s", image_id, type(exc).__name__
            )
            return None

        status = response.status_code
        if 200 <= status < 300:
            content = response.content
            if not content:
                return None
            return content
        # Apply the same failure matrix as the JSON path; bytes never get
        # cached but the cooldown side effect is preserved.
        self._handle_failure_status(status, path)
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_in_cooldown(self) -> bool:
        """Return ``True`` while the 60-second 429 cooldown is active."""
        if self._cooldown_until is None:
            return False
        if self._clock() < self._cooldown_until:
            return True
        # Cooldown has elapsed — clear the flag so subsequent calls don't
        # have to re-check the timestamp.
        self._cooldown_until = None
        return False

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-RapidAPI-Key": self._api_key,
            "X-RapidAPI-Host": CRICBUZZ_HOST,
        }

    async def _http_get_json(
        self,
        path: str,
        *,
        params: Optional[dict] = None,
    ) -> Optional[dict]:
        """Issue ``GET {BASE_URL}{path}`` and return the decoded JSON.

        Applies every rule in the failure-handling matrix:

        * ``CRICBUZZ_API_KEY`` empty/unset → return ``None`` without I/O.
        * Cooldown active → return ``None`` without I/O.
        * ``httpx.TimeoutException`` / ``httpx.RequestError`` → one
          WARNING log, return ``None``.
        * 401 / 403 → one ERROR log mentioning only the status code (the
          API key value is never written), return ``None``.
        * 429 → set ``_cooldown_until`` to ``now + 60s``, one WARNING log,
          return ``None``.
        * 5xx and other 4xx → one WARNING log, return ``None``.
        * 200 with empty / un-decodable body → return ``None`` (no cache).
        * 200 with non-empty body → return the decoded JSON.

        Returns the parsed JSON ``dict`` on success or ``None`` otherwise.
        Caching is the caller's responsibility (so each method can name
        its own cache key).
        """
        if not self._api_key:
            # Missing key: every call returns ``None`` without I/O. The
            # startup WARNING was emitted in ``__init__``.
            return None
        if self._is_in_cooldown():
            return None

        try:
            response = await self._http.get(
                f"{CRICBUZZ_BASE_URL}{path}",
                params=params,
                headers=self._auth_headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            # Covers connect/read timeouts and every transport-level
            # failure (DNS, TCP reset, TLS, etc.).
            logger.warning(
                "Cricbuzz request to %s failed with %s",
                path,
                type(exc).__name__,
            )
            return None
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Cricbuzz request to %s raised %s", path, type(exc).__name__
            )
            return None

        status = response.status_code
        if 200 <= status < 300:
            try:
                payload = response.json()
            except ValueError:
                # 200 but body is not valid JSON — treat as failure so the
                # resolver falls back to static data. Do not cache.
                logger.warning(
                    "Cricbuzz request to %s returned %d with invalid JSON",
                    path,
                    status,
                )
                return None
            if not payload:
                # 200 with empty body (``{}``, ``[]``, ``null``) — the
                # cricbuzz_success criterion fails. Do not cache.
                return None
            if isinstance(payload, dict):
                return payload
            if isinstance(payload, list):
                # Some endpoints might return a bare list; wrap so the
                # caller's ``not payload`` / ``payload.get`` checks can run
                # uniformly. Callers that expect a list extract via
                # :func:`_extract_first_list`.
                return {"__items__": payload}
            # Any other JSON scalar is unexpected — treat as failure.
            return None

        self._handle_failure_status(status, path)
        return None

    def _handle_failure_status(self, status: int, path: str) -> None:
        """Apply the failure-handling matrix side effects for a non-2xx response.

        Logs exactly one line per failure category and, for 429, arms the
        60-second cooldown. Never echoes the API key.
        """
        if status in (401, 403):
            # Single ERROR line containing only the status code (Requirement
            # 3.6, 9.4 — never the key value).
            logger.error(
                "Cricbuzz authentication failed for %s: HTTP %d",
                path,
                status,
            )
            return
        if status == 429:
            # Arm the cooldown so subsequent calls short-circuit.
            self._cooldown_until = self._clock() + COOLDOWN_SECONDS
            logger.warning(
                "Cricbuzz rate limit (HTTP 429) on %s; cooling down for %ds",
                path,
                int(COOLDOWN_SECONDS),
            )
            return
        if 500 <= status < 600:
            logger.warning("Cricbuzz request to %s returned HTTP %d", path, status)
            return
        # Any other 4xx (e.g. 400, 404).
        logger.warning("Cricbuzz request to %s returned HTTP %d", path, status)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _coerce_int(value: Any) -> Optional[int]:
    """Best-effort conversion of Cricbuzz numeric fields to ``int``.

    Cricbuzz occasionally emits string-encoded ids; we accept both numeric
    types and silently drop anything else.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # ``bool`` is an ``int`` subclass — guard against accidental coercion.
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_first_list(payload: dict, *keys: str) -> Optional[List[Any]]:
    """Return the first ``payload[key]`` value that is a list.

    Used by methods that expect the upstream response to wrap an array in
    a known dict key. Returns ``None`` if none of ``keys`` resolve to a
    list. The order of ``keys`` is significant.
    """
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    # Some callers may have wrapped a bare-list response via
    # :meth:`CricbuzzService._http_get_json`; surface that here.
    bare = payload.get("__items__")
    if isinstance(bare, list):
        return bare
    return None
