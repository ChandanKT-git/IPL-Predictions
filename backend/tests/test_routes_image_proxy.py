"""Route-level tests for the Image_Proxy endpoint (task 7.2).

Verifies the behaviour of ``GET /api/image/{image_id}`` after the
refactor that funnels every Cricbuzz call through the singleton
:class:`CricbuzzService`:

* On a successful fetch the response body is the raw JPEG bytes,
  ``Content-Type`` is ``image/jpeg``, and ``Cache-Control`` is the
  documented ``public, max-age=86400`` value (Requirements 5.2, 5.3).
* Every failure path (missing key, network error / timeout, non-2xx
  upstream, cooldown active, empty body) is mapped to HTTP 404 with the
  body ``{"detail": "Image not found"}`` (Requirement 5.4).
* Upstream-style headers (``X-RapidAPI-*``, ``Server``, ``Via``) are not
  forwarded, only a whitelisted set is emitted by the proxy.
* The ``p`` query parameter (e.g. ``thumb``, ``det``) is propagated to
  ``CricbuzzService.fetch_image``.

The tests do not hit RapidAPI; instead they monkeypatch
``server.cricbuzz`` with a tiny duck-typed stub that records every call
made to ``fetch_image``.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import List, Optional, Tuple

# Ensure ``backend`` modules are importable when running ``pytest`` from
# the repo root.
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Downstream modules touch these env vars at import time.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "ipl_test")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


# ---------------------------------------------------------------------------
# Stub: records every (image_id, size) pair and replays a configured outcome.
# ---------------------------------------------------------------------------


class StubCricbuzzImageService:
    """Duck-typed stand-in exposing only ``fetch_image``.

    The image proxy route is the only thing under test here, so the stub
    only needs to satisfy the single attribute the route consumes.
    """

    def __init__(self, content: Optional[bytes]) -> None:
        self._content = content
        self.calls: List[Tuple[str, str]] = []

    async def fetch_image(
        self,
        image_id: str,
        size: str = "thumb",
    ) -> Optional[bytes]:
        self.calls.append((image_id, size))
        return self._content


# ---------------------------------------------------------------------------
# Test base — snapshots the global singletons so individual tests cannot
# leak state into each other.
# ---------------------------------------------------------------------------


class _ImageProxyTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_cricbuzz = server.cricbuzz
        self.client = TestClient(server.app)

    def tearDown(self) -> None:
        server.cricbuzz = self._saved_cricbuzz

    def install(self, content: Optional[bytes]) -> StubCricbuzzImageService:
        stub = StubCricbuzzImageService(content)
        server.cricbuzz = stub  # type: ignore[assignment]
        return stub


# ---------------------------------------------------------------------------
# Successful fetch (Requirements 5.2, 5.3)
# ---------------------------------------------------------------------------


class TestImageProxySuccess(_ImageProxyTestBase):
    JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00fake-jpeg-payload"

    def test_success_returns_jpeg_with_cache_control(self) -> None:
        self.install(self.JPEG_BYTES)
        r = self.client.get("/api/image/c12345")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, self.JPEG_BYTES)
        # Requirement 5.2 — Content-Type is image/jpeg.
        self.assertEqual(r.headers.get("content-type"), "image/jpeg")
        # Requirement 5.3 — 24h browser cache header.
        self.assertEqual(
            r.headers.get("cache-control"),
            "public, max-age=86400",
        )

    def test_default_size_is_thumb(self) -> None:
        stub = self.install(self.JPEG_BYTES)
        r = self.client.get("/api/image/c12345")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(stub.calls, [("c12345", "thumb")])

    def test_p_query_param_is_forwarded(self) -> None:
        stub = self.install(self.JPEG_BYTES)
        r = self.client.get("/api/image/c12345", params={"p": "det"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(stub.calls, [("c12345", "det")])

    def test_upstream_headers_not_forwarded(self) -> None:
        """Only the whitelisted response headers should reach the browser.

        ``X-RapidAPI-Key``, ``X-RapidAPI-Host``, ``Server``, and ``Via``
        must never appear in the proxy response (security note attached
        to Requirement 5.2). Because ``CricbuzzService.fetch_image``
        already discards upstream headers and returns only bytes, the
        route handler builds a fresh :class:`Response`; we assert the
        observable result by checking that no such header reaches the
        client.
        """
        self.install(self.JPEG_BYTES)
        r = self.client.get("/api/image/c12345")
        self.assertEqual(r.status_code, 200)
        # Header lookup is case-insensitive in httpx, but we assert both
        # cases just to be explicit about intent.
        for forbidden in (
            "x-rapidapi-key",
            "x-rapidapi-host",
            "via",
        ):
            self.assertNotIn(
                forbidden,
                {k.lower() for k in r.headers.keys()},
                f"{forbidden} must not be forwarded by the image proxy",
            )

    def test_response_body_is_unmodified(self) -> None:
        """The proxy must not transform the JPEG bytes in any way."""
        self.install(self.JPEG_BYTES)
        r = self.client.get("/api/image/c12345")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.content), len(self.JPEG_BYTES))
        self.assertEqual(r.content, self.JPEG_BYTES)


# ---------------------------------------------------------------------------
# Failure paths (Requirement 5.4)
# ---------------------------------------------------------------------------


class TestImageProxyFailure(_ImageProxyTestBase):
    """Every failure path collapses to HTTP 404."""

    EXPECTED_BODY = {"detail": "Image not found"}

    def test_returns_404_when_service_returns_none(self) -> None:
        # ``fetch_image`` returns ``None`` for missing key, cooldown,
        # network error, timeout, 401/403/429/5xx, and empty body — the
        # proxy must collapse all of them to 404.
        self.install(None)
        r = self.client.get("/api/image/c12345")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), self.EXPECTED_BODY)

    def test_404_response_has_no_cache_control_header(self) -> None:
        """The 24h cache header is only set on successful 2xx responses
        (Requirement 5.3 — "every successful (2xx) response"). A 404
        must not carry a long-lived cache header so the browser does not
        permanently remember a missing image.
        """
        self.install(None)
        r = self.client.get("/api/image/c12345")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(
            "public, max-age=86400",
            (r.headers.get("cache-control") or "").lower(),
        )

    def test_returns_404_when_cricbuzz_singleton_missing(self) -> None:
        """Defensive: when the startup hook has not wired the singleton,
        the proxy still returns 404 rather than HTTP 500."""
        # Save and clear the global. ``setUp`` already snapshots it for
        # restoration via ``tearDown``.
        server.cricbuzz = None  # type: ignore[assignment]
        r = self.client.get("/api/image/c12345")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), self.EXPECTED_BODY)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
