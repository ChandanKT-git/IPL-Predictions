"""IPL Score Predictor — FastAPI backend.

Public surface (all under ``/api``):

* Catalog: ``/teams``, ``/teams/{id}/players``, ``/venues``,
  ``/pitch-types``, ``/weather-types``.
* Live data: ``/live-matches``, ``/live-match-xi/{id}``,
  ``/live-match-score/{id}``, ``/image/{id}``.
* Predictions: ``/predict``, ``/whatif``, ``/analysis``,
  ``/predictions/recent``, ``/predictions/{id}``,
  ``/predictions/{id}/favorite``.
* H2H: ``/head-to-head/{a}/{b}``.
* Health: ``/health``.
* Admin: ``/admin/cache/clear``, ``/admin/cache/refresh``.

Singletons live at module level so the existing test suite can
monkeypatch them without entering the FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from cache_layer import CacheLayer
from cricbuzz_service import CricbuzzService
from data_manager import IPLDataManager
from data_resolver import DataResolver
from ipl_data import (
    PITCH_TYPES,
    TEAMS,
    VENUES,
    WEATHER_TYPES,
    get_pitch,
    get_players,
    get_team,
    get_venue,
    get_weather,
)
from observability import REQUEST_ID_HEADER, RequestIdMiddleware, configure_logging
from predictor import Predictor

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

configure_logging()
logger = logging.getLogger("ipl")

CSV_PATH = ROOT_DIR / "data" / "IPL.csv"
MODEL_PATH = ROOT_DIR / "models.joblib"

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------
mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
db_name = os.environ.get("DB_NAME", "ipl_predictor")
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[db_name]

cache: CacheLayer = CacheLayer()
http_client: Optional[httpx.AsyncClient] = None
cricbuzz: Optional[CricbuzzService] = CricbuzzService(
    api_key=os.environ.get("CRICBUZZ_API_KEY"),
    cache=cache,
    http=httpx.AsyncClient(),
)
resolver: Optional[DataResolver] = DataResolver(svc=cricbuzz, cache=cache)
data_manager: IPLDataManager = IPLDataManager(csv_path=str(CSV_PATH))
predictor: Predictor = Predictor(bundle_path=MODEL_PATH)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client, cricbuzz, resolver
    try:
        await db.predictions.create_index("id", unique=True)
        await db.predictions.create_index("created_at")
        logger.info("MongoDB indexes created")
    except Exception as exc:
        logger.warning("Failed to create MongoDB indexes: %s", exc)

    http_client = httpx.AsyncClient()
    cricbuzz = CricbuzzService(
        api_key=os.environ.get("CRICBUZZ_API_KEY"),
        cache=cache,
        http=http_client,
    )
    resolver = DataResolver(svc=cricbuzz, cache=cache)
    logger.info(
        "Backend started",
        extra={
            "model_loaded": predictor.is_ready,
            "cricbuzz_key_set": cricbuzz.has_api_key,
            "csv_loaded": data_manager.is_loaded,
        },
    )
    try:
        yield
    finally:
        if http_client is not None:
            await http_client.aclose()
        mongo_client.close()


app = FastAPI(title="IPL Score Predictor API", version="2.0", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
api_router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------
class PredictRequest(BaseModel):
    team_a: str
    team_b: str
    batting_team: str
    toss_winner: str
    venue: str
    pitch: str
    weather: str
    playing_xi_a: List[str] = Field(default_factory=list)
    playing_xi_b: List[str] = Field(default_factory=list)
    target_score: Optional[float] = None


class WhatIfRequest(BaseModel):
    base_prediction: dict
    current_overs: float
    current_wickets: int
    current_runs: int
    pitch: str
    weather: str
    batting_team_rating: int = 80


class AnalysisRequest(BaseModel):
    team_a_name: str
    team_b_name: str
    batting_team_name: str
    venue_name: str
    pitch_label: str
    weather_label: str
    predicted_score: int
    win_prob_batting: int


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@api_router.get("/")
async def root() -> dict:
    return {"message": "IPL Score Predictor API", "version": app.version}


@api_router.get("/health")
async def health() -> JSONResponse:
    """Liveness + readiness probe.

    Pings Mongo with a server-info round-trip and reports the status of
    the model bundle, the Cricbuzz API key, and the historical CSV. The
    response always returns HTTP 200; individual subsystem fields tell
    the operator whether the service is degraded.
    """
    mongo_ok = False
    try:
        await mongo_client.admin.command("ping")
        mongo_ok = True
    except Exception as exc:
        logger.warning("Mongo health check failed: %s", exc)

    return JSONResponse(
        {
            "status": "ok" if mongo_ok else "degraded",
            "subsystems": {
                "mongo": mongo_ok,
                "cricbuzz_key_set": bool(cricbuzz and cricbuzz.has_api_key),
                "model_loaded": predictor.is_ready,
                "model_version": predictor.version,
                "csv_loaded": data_manager.is_loaded,
                "cache_entries": len(cache._store),
            },
        }
    )


# ---------------------------------------------------------------------------
# Catalog routes
# ---------------------------------------------------------------------------
@api_router.get("/teams")
async def get_teams():
    try:
        teams, source = await resolver.resolve_teams()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("resolve_teams crashed; serving static fallback: %s", exc)
        teams = [
            {**t, "cricbuzz_team_id": None, "cricbuzz_squad_id": None,
             "image_id": None, "source": "fallback"}
            for t in TEAMS
        ]
        source = "fallback"
    return JSONResponse(content=teams, headers={"X-Data-Source": source})


@api_router.get("/teams/{team_id}/players")
async def team_players(team_id: str):
    try:
        players, source = await resolver.resolve_players(team_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("resolve_players crashed for %s: %s", team_id, exc)
        static_roster = get_players(team_id) or []
        players = [
            {**p, "image_id": None, "cricbuzz_player_id": None, "source": "fallback"}
            for p in static_roster
        ]
        source = "fallback"
    return JSONResponse(content=players, headers={"X-Data-Source": source})


@api_router.get("/venues")
async def venues():
    try:
        venues_list, source = await resolver.resolve_venues()
    except Exception as exc:
        logger.error("resolve_venues crashed; serving static fallback: %s", exc)
        venues_list = [{**v, "cricbuzz_venue_id": None, "source": "fallback"} for v in VENUES]
        source = "fallback"
    return JSONResponse(content=venues_list, headers={"X-Data-Source": source})


@api_router.get("/pitch-types")
async def pitch_types():
    return PITCH_TYPES


@api_router.get("/weather-types")
async def weather_types():
    return WEATHER_TYPES


# ---------------------------------------------------------------------------
# Live data routes — every endpoint goes through CricbuzzService
# ---------------------------------------------------------------------------
@api_router.get("/live-matches")
async def live_matches():
    if cricbuzz is None or not cricbuzz.has_api_key:
        return {"typeMatches": []}
    payload = await cricbuzz.get_live_matches()
    return payload or {"typeMatches": []}


@api_router.get("/upcoming-matches")
async def upcoming_matches():
    if cricbuzz is None or not cricbuzz.has_api_key:
        return {"typeMatches": []}
    payload = await cricbuzz.get_upcoming_matches()
    return payload or {"typeMatches": []}


@api_router.get("/live-match-xi/{match_id}")
async def live_match_xi(match_id: int):
    if resolver is None:
        return JSONResponse(status_code=502, content={"detail": "Cricbuzz upstream error"})
    try:
        result = await resolver.resolve_live_xi(match_id)
    except Exception as exc:
        logger.error("resolve_live_xi crashed for match %s: %s", match_id, exc)
        return JSONResponse(status_code=502, content={"detail": "Cricbuzz upstream error"})

    if not isinstance(result, dict):
        return JSONResponse(
            status_code=502, content={"detail": "Cricbuzz returned an unparseable scorecard"}
        )

    if result.get("ok") is False:
        error = result.get("error")
        if error == "missing_key":
            return JSONResponse(
                status_code=503,
                content={"detail": "Cricbuzz API key not configured", "source": "fallback"},
            )
        if error == "auth_failed":
            return JSONResponse(
                status_code=503,
                content={"detail": "Cricbuzz authentication failed", "source": "fallback"},
            )
        if error == "upstream":
            return JSONResponse(
                status_code=502,
                content={"detail": "Cricbuzz upstream error", "status": result.get("status", 502)},
            )
        if error == "unparseable":
            return JSONResponse(
                status_code=502, content={"detail": "Cricbuzz returned an unparseable scorecard"}
            )
        return JSONResponse(status_code=502, content={"detail": "Cricbuzz upstream error"})
    return result


@api_router.get("/live-match-score/{match_id}")
async def live_match_score(match_id: int):
    if cricbuzz is None or not cricbuzz.has_api_key:
        raise HTTPException(status_code=503, detail="Cricbuzz API key not configured")
    payload = await cricbuzz.get_match_info(match_id)
    if payload is None:
        raise HTTPException(status_code=502, detail="Cricbuzz upstream error")
    return payload


SSE_INTERVAL_SECONDS = float(os.environ.get("LIVE_SCORE_STREAM_INTERVAL", "30"))


@api_router.get("/live-match-score/{match_id}/stream")
async def live_match_score_stream(match_id: int, request: Request):
    """Server-sent events stream of the match score.

    Pushes a fresh ``data:`` frame every :data:`SSE_INTERVAL_SECONDS`
    until either the client disconnects or three consecutive Cricbuzz
    failures arrive. Each frame is a JSON-encoded match-info payload —
    same shape as :func:`live_match_score`.

    Falls through to a single error frame and closes the stream when the
    Cricbuzz key is not configured. The endpoint never raises HTTP 500
    once the stream is open; transport errors are surfaced as ``event:
    error`` frames.
    """
    if cricbuzz is None or not cricbuzz.has_api_key:
        async def closed() -> AsyncIterator[bytes]:
            yield _sse_event(
                "error",
                {"detail": "Cricbuzz API key not configured", "source": "fallback"},
            )
        return StreamingResponse(
            closed(), media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    async def streamer() -> AsyncIterator[bytes]:
        consecutive_failures = 0
        max_failures = 3
        while True:
            if await request.is_disconnected():
                return
            try:
                payload = await cricbuzz.get_match_info(match_id)
                if payload is None:
                    consecutive_failures += 1
                    yield _sse_event(
                        "error",
                        {"detail": "Cricbuzz upstream error", "consecutive_failures": consecutive_failures},
                    )
                    if consecutive_failures >= max_failures:
                        yield _sse_event("end", {"reason": "upstream_unavailable"})
                        return
                else:
                    consecutive_failures = 0
                    yield _sse_event("score", payload)
            except Exception as exc:
                logger.warning("SSE stream error: %s", exc)
                yield _sse_event("error", {"detail": "stream error"})
                return
            try:
                await asyncio.sleep(SSE_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                return

    return StreamingResponse(
        streamer(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _sse_event(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


@api_router.get("/image/{image_id}")
async def get_cricbuzz_image(image_id: str, p: str = "thumb"):
    if cricbuzz is None:
        raise HTTPException(status_code=404, detail="Image not found")
    content = await cricbuzz.fetch_image(image_id, size=p)
    if content is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------
@api_router.post("/predict")
async def predict(req: PredictRequest):
    if req.team_a == req.team_b:
        raise HTTPException(status_code=400, detail="Teams must be different")
    if req.batting_team not in (req.team_a, req.team_b):
        raise HTTPException(status_code=400, detail="Batting team must be one of the two teams")
    if len(req.playing_xi_a) > 11 or len(req.playing_xi_b) > 11:
        raise HTTPException(status_code=400, detail="Playing XI cannot exceed 11 players")

    result = predictor.predict(
        team_a=req.team_a,
        team_b=req.team_b,
        batting_team=req.batting_team,
        toss_winner=req.toss_winner,
        venue=req.venue,
        pitch=req.pitch,
        weather=req.weather,
        playing_xi_a=req.playing_xi_a,
        playing_xi_b=req.playing_xi_b,
        target_score=req.target_score,
    )

    bowling_team_id = req.team_b if req.batting_team == req.team_a else req.team_a
    bat_team = get_team(req.batting_team) or {}
    bowl_team = get_team(bowling_team_id) or {}

    if result.win_probability_batting >= 55:
        outcome = f"{bat_team.get('short_name','?')} likely to win defending {result.score}"
    elif result.win_probability_batting <= 45:
        outcome = f"{bowl_team.get('short_name','?')} favoured to chase down {result.score}"
    else:
        outcome = f"Toss-up — could go either way around {result.score}"

    venue_name = (get_venue(req.venue) or {}).get("name", "")
    h2h = data_manager.get_h2h_stats(req.team_a, req.team_b) or None
    if h2h and venue_name:
        venue_record = data_manager.get_venue_record(req.team_a, req.team_b, venue_name)
        if venue_record:
            h2h = {**h2h, "venue_record": venue_record}

    matchups = data_manager.get_batter_vs_bowler(req.playing_xi_a, req.playing_xi_b) + \
               data_manager.get_batter_vs_bowler(req.playing_xi_b, req.playing_xi_a)

    response = {
        "predicted_score": result.score,
        "score_range_low": result.score_low,
        "score_range_high": result.score_high,
        "expected_run_rate": result.expected_run_rate,
        "win_probability_batting": result.win_probability_batting,
        "win_probability_bowling": 100 - result.win_probability_batting,
        "match_outcome": outcome,
        "batting_team_strength": result.batting_team_strength,
        "bowling_team_strength": result.bowling_team_strength,
        "phase_breakdown": {
            "powerplay_runs": result.powerplay_runs,
            "middle_overs_runs": result.middle_runs,
            "death_overs_runs": result.death_runs,
        },
        "batting_team_id": req.batting_team,
        "bowling_team_id": bowling_team_id,
        "model_version": result.model_version,
        "mode": result.mode,
        "interval_coverage": result.coverage,
        "contributions": result.contributions,
        "h2h": h2h,
        "matchups": matchups[:5],
    }

    record = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": req.model_dump(),
        "output": response,
        "is_favorite": False,
    }
    try:
        await db.predictions.insert_one(record.copy())
    except Exception as exc:
        logger.warning("Failed to persist prediction: %s", exc)
    return {"id": record["id"], **response}


@api_router.post("/whatif")
async def whatif(req: WhatIfRequest):
    base = req.base_prediction or {}
    pred = int(base.get("predicted_score", 165))
    overs = max(0.0, min(20.0, float(req.current_overs)))
    wickets = max(0, min(10, int(req.current_wickets)))
    runs = max(0, int(req.current_runs))
    remaining_overs = 20 - overs

    if overs == 0:
        projected = pred
    else:
        crr = runs / overs
        per_over = predictor.predict_per_over(
            overs_completed=overs,
            wickets_lost=wickets,
            current_run_rate=crr,
            baseline_per_over=pred / 20.0,
        )
        projected = runs + per_over * remaining_overs
        pitch = get_pitch(req.pitch)
        weather = get_weather(req.weather)
        pitch_mod = pitch["score_modifier"] if pitch else 0
        weather_mod = weather["score_modifier"] if weather else 0
        projected += (pitch_mod + weather_mod) / 6.0

    projected = int(max(runs, min(280, round(projected))))

    rrr = (projected - runs) / remaining_overs if remaining_overs > 0 else 0
    base_win = int(base.get("win_probability_batting", 50))
    momentum = (projected - pred) * 0.7 - (wickets * 4.5) + ((req.batting_team_rating - 80) * 0.3)
    win_prob = max(10, min(90, int(round(base_win + momentum))))

    return {
        "projected_score": projected,
        "current_run_rate": round(runs / overs, 2) if overs > 0 else 0,
        "required_run_rate": round(rrr, 2) if remaining_overs > 0 else 0,
        "win_probability_batting": win_prob,
        "win_probability_bowling": 100 - win_prob,
        "remaining_overs": round(remaining_overs, 1),
        "overs": overs,
        "wickets": wickets,
        "runs": runs,
    }


@api_router.post("/analysis")
async def analysis(req: AnalysisRequest):
    name_to_id = {t["name"]: t["id"] for t in TEAMS}
    team_a_id = name_to_id.get(req.team_a_name)
    team_b_id = name_to_id.get(req.team_b_name)
    h2h = data_manager.get_h2h_stats(team_a_id, team_b_id) if team_a_id and team_b_id else None
    h2h_text = ""
    if h2h:
        h2h_text = (
            f"Historical Head-to-Head: Total Matches: {h2h['total_matches']}, "
            f"{req.team_a_name} won: {h2h['team_a_wins']}, "
            f"{req.team_b_name} won: {h2h['team_b_wins']}. "
            f"Average score: {h2h['avg_score']:.1f}."
        )

    api_key = os.environ.get("GROQ_API_KEY")
    fallback = (
        f"With {req.batting_team_name} batting first at {req.venue_name} on a "
        f"{req.pitch_label.lower()} pitch under {req.weather_label.lower()} skies, the model "
        f"projects a total around {req.predicted_score}. {req.batting_team_name}'s win probability "
        f"sits at {req.win_prob_batting}% based on squad balance and venue history. {h2h_text}"
    )

    if not api_key or api_key == "your_groq_api_key_here":
        return {"analysis": fallback, "source": "fallback"}

    try:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=api_key)
        prompt = (
            f"Match: {req.team_a_name} vs {req.team_b_name}. "
            f"Batting first: {req.batting_team_name}. Venue: {req.venue_name}. "
            f"Pitch: {req.pitch_label}. Weather: {req.weather_label}. "
            f"Predicted first-innings score: {req.predicted_score}. "
            f"Win probability for {req.batting_team_name}: {req.win_prob_batting}%. "
            f"{h2h_text} "
            f"Write a punchy, broadcast-style match preview in 3-4 short sentences."
        )
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system",
                 "content": "You are an expert IPL cricket analyst providing broadcast-style previews."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=256,
        )
        text = completion.choices[0].message.content.strip() or fallback
        return {"analysis": text, "source": "llm"}
    except Exception as exc:
        logger.warning("Groq analysis failed: %s", exc)
        return {"analysis": fallback, "source": "fallback", "error": str(exc)}


# ---------------------------------------------------------------------------
# Persistence-backed routes
# ---------------------------------------------------------------------------
@api_router.get("/predictions/recent")
async def recent_predictions(limit: int = 10):
    cursor = db.predictions.find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
    return await cursor.to_list(limit)


@api_router.get("/predictions/{prediction_id}")
async def get_prediction(prediction_id: str):
    prediction = await db.predictions.find_one({"id": prediction_id}, {"_id": 0})
    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return prediction


@api_router.post("/predictions/{prediction_id}/favorite")
async def toggle_favorite(prediction_id: str):
    prediction = await db.predictions.find_one({"id": prediction_id})
    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")
    new_status = not prediction.get("is_favorite", False)
    await db.predictions.update_one(
        {"id": prediction_id}, {"$set": {"is_favorite": new_status}}
    )
    return {"id": prediction_id, "is_favorite": new_status}


class ReconcileRequest(BaseModel):
    actual_score: int
    actual_winner: Optional[str] = None
    match_id: Optional[int] = None


@api_router.post("/predictions/{prediction_id}/reconcile")
async def reconcile_prediction(prediction_id: str, body: ReconcileRequest):
    """Stamp a finished prediction with the real score and winner.

    Computes:
        * ``score_error`` = ``actual_score`` − ``predicted_score``
        * ``inside_interval`` — whether the actual fell inside ``[low, high]``
        * ``correct_winner`` — whether the model's win-prob favourite matched

    The reconciliation is persisted under ``output.actual`` so the recent
    history view can show "off by N runs" badges and an aggregated
    accuracy score.
    """
    prediction = await db.predictions.find_one({"id": prediction_id}, {"_id": 0})
    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")
    output = prediction.get("output", {}) or {}
    predicted_score = int(output.get("predicted_score", 0))
    low = int(output.get("score_range_low", predicted_score - 12))
    high = int(output.get("score_range_high", predicted_score + 12))
    win_prob = int(output.get("win_probability_batting", 50))
    favourite = output.get("batting_team_id") if win_prob >= 50 else output.get("bowling_team_id")

    actual = {
        "actual_score": int(body.actual_score),
        "actual_winner": body.actual_winner,
        "match_id": body.match_id,
        "score_error": int(body.actual_score) - predicted_score,
        "inside_interval": low <= int(body.actual_score) <= high,
        "correct_winner": (
            body.actual_winner is not None and favourite == body.actual_winner
        ),
        "reconciled_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.predictions.update_one(
        {"id": prediction_id},
        {"$set": {"output.actual": actual}},
    )
    return actual


@api_router.get("/calibration")
async def calibration():
    """Aggregate accuracy across reconciled predictions for the calibration plot.

    Returns:
        * ``count``                — total reconciled predictions.
        * ``mae``                  — mean absolute score error.
        * ``coverage``             — share of actuals inside the prediction interval.
        * ``win_accuracy``         — share with ``correct_winner`` true.
        * ``win_calibration``      — bucketed observed win rate per
          predicted-prob decile, suitable for a reliability diagram.
    """
    cursor = db.predictions.find(
        {"output.actual": {"$ne": None}},
        {"_id": 0, "output": 1},
    )
    rows = await cursor.to_list(length=1000)
    if not rows:
        return {"count": 0}

    errors: list[float] = []
    inside: list[bool] = []
    correct: list[bool] = []
    buckets: dict[int, list[bool]] = {}
    for row in rows:
        out = row.get("output") or {}
        actual = out.get("actual") or {}
        if "score_error" in actual:
            errors.append(abs(float(actual["score_error"])))
        if "inside_interval" in actual:
            inside.append(bool(actual["inside_interval"]))
        if "correct_winner" in actual:
            correct.append(bool(actual["correct_winner"]))
            prob = int(out.get("win_probability_batting", 50))
            bucket = max(0, min(9, prob // 10))
            buckets.setdefault(bucket, []).append(bool(actual["correct_winner"]))

    calibration_curve = [
        {
            "bucket": b,
            "midpoint_pct": b * 10 + 5,
            "samples": len(items),
            "observed_pct": float(sum(items) / len(items) * 100) if items else None,
        }
        for b, items in sorted(buckets.items())
    ]
    return {
        "count": len(rows),
        "mae": float(sum(errors) / len(errors)) if errors else None,
        "coverage": float(sum(inside) / len(inside)) if inside else None,
        "win_accuracy": float(sum(correct) / len(correct)) if correct else None,
        "win_calibration": calibration_curve,
    }


@api_router.get("/head-to-head/{team_a}/{team_b}")
async def head_to_head(team_a: str, team_b: str):
    cache_key = f"h2h:{':'.join(sorted([team_a, team_b]))}"
    cached, hit = cache.get(cache_key)
    if hit and cached is not None:
        return cached
    stats = data_manager.get_h2h_stats(team_a, team_b)
    if not stats:
        return {
            "teams": [team_a, team_b],
            "message": "No historical data found for this matchup",
            "last_5": [],
            "win_count": {team_a: 0, team_b: 0},
            "form_guide": {team_a: [], team_b: []},
        }
    cache.set(cache_key, stats, ttl=21600)
    return stats


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------
_ADMIN_LOCALHOSTS = {"127.0.0.1", "localhost", "::1"}
_ADMIN_REFRESH_PREFIXES = ("series:", "squads:", "squad:", "venues:", "players:", "h2h:")
_ADMIN_REFRESH_EXACT_KEYS = ("teams:resolved", "venues:resolved")


def _enforce_admin_auth(x_admin_token: Optional[str], request: Request) -> None:
    admin_token = os.environ.get("ADMIN_TOKEN")
    if admin_token:
        supplied = x_admin_token or ""
        if not hmac.compare_digest(supplied, admin_token):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return
    client_host = request.client.host if request.client else None
    if client_host not in _ADMIN_LOCALHOSTS:
        raise HTTPException(status_code=403, detail="Forbidden")


@api_router.post("/admin/cache/clear")
async def admin_cache_clear(
    request: Request,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    _enforce_admin_auth(x_admin_token, request)
    n = cache.clear()
    return {"cleared": n}


@api_router.post("/admin/cache/refresh")
async def admin_cache_refresh(
    request: Request,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    _enforce_admin_auth(x_admin_token, request)
    keys_to_evict: list[str] = []
    for prefix in _ADMIN_REFRESH_PREFIXES:
        keys_to_evict.extend(cache.keys_matching(prefix))
    keys_to_evict.extend(_ADMIN_REFRESH_EXACT_KEYS)
    for key in keys_to_evict:
        cache.set(key, None, ttl=0)

    refreshed: list[str] = []
    errors: list[str] = []

    async def _run(label: str, awaitable_factory) -> None:
        try:
            await awaitable_factory()
        except Exception as exc:
            logger.warning("admin/cache/refresh: %s failed: %s", label, exc)
            errors.append(label)
        else:
            refreshed.append(label)

    if resolver is None:
        errors.extend(
            ["/api/teams", "/api/venues"]
            + [f"/api/teams/{t['id']}/players" for t in TEAMS]
        )
        return {"refreshed": refreshed, "errors": errors}

    await _run("/api/teams", resolver.resolve_teams)
    await _run("/api/venues", resolver.resolve_venues)
    for team in TEAMS:
        team_id = team["id"]
        await _run(
            f"/api/teams/{team_id}/players",
            lambda tid=team_id: resolver.resolve_players(tid),
        )
    return {"refreshed": refreshed, "errors": errors}


app.include_router(api_router)