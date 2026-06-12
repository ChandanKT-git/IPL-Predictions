"""Inference-time wrapper around the trained sklearn pipelines.

Exposes a single ``Predictor`` object that the FastAPI handler consumes.
Falls back to a heuristic when the bundle is missing or any inference
call raises, so the request handler never returns HTTP 500 due to a
model issue.

Two prediction modes are supported:

* **first-innings**: the default mode. Predicts a 20-over total when
  ``target_score`` is not supplied.
* **chase**: when ``target_score`` is provided, the chase specialists
  predict the chasing team's final total and win probability conditional
  on the target. Both gracefully fall back to the first-innings models
  if the chase models were not trained.

Each prediction also returns up to five **feature contributions** so the
"Why this prediction?" panel on the frontend can show what drove the
output. The contributions are an approximation of permutation importance
multiplied by each feature's normalised distance from the training mean,
keeping the call cheap (no online permutation pass) but informative.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from features import (
    CHASE_FEATURE_COLUMNS,
    DEFAULT_MATCHUP_STRIKE_RATE,
    FEATURE_COLUMNS,
    HistoricalContext,
    MatchupIndex,
    aggregate_xi,
    build_request_features,
    empty_context,
    matchup_strike_rate_from_index,
)
from ipl_data import get_pitch, get_team, get_venue, get_weather

logger = logging.getLogger("ipl.predictor")


# Human-readable labels for the "why this prediction" panel.
FEATURE_LABELS: dict[str, str] = {
    "batting_team": "Batting team",
    "bowling_team": "Bowling team",
    "venue": "Venue",
    "toss_won_by_batting": "Toss won by batting team",
    "toss_decision_bat": "Toss winner chose to bat",
    "home_advantage": "Home advantage",
    "batting_recent_form_runs": "Batting team — recent runs",
    "bowling_recent_form_conceded": "Bowling team — recent runs conceded",
    "batting_recent_win_rate": "Batting team — recent win rate",
    "bowling_recent_win_rate": "Bowling team — recent win rate",
    "h2h_avg_score": "Head-to-head average score",
    "h2h_batting_wins_share": "Head-to-head win share",
    "bat_xi_avg": "XI batting average",
    "bat_xi_strike_rate": "XI strike rate",
    "bowl_xi_economy": "XI economy",
    "bowl_xi_wickets": "XI wickets",
    "xi_overseas_count": "Overseas players in XI",
    "xi_matchup_strike_rate": "XI vs XI strike rate (history)",
    "venue_avg_first_innings": "Venue first-innings average",
    "pitch_modifier": "Pitch type",
    "weather_modifier": "Weather conditions",
    "target_score": "Target to chase",
}


@dataclass
class PredictionResult:
    score: int
    score_low: int
    score_high: int
    win_probability_batting: int
    expected_run_rate: float
    powerplay_runs: int
    middle_runs: int
    death_runs: int
    batting_team_strength: int
    bowling_team_strength: int
    model_version: str
    mode: str = "first-innings"
    contributions: list[dict] = field(default_factory=list)
    coverage: Optional[float] = None


class Predictor:
    def __init__(self, bundle_path: Path) -> None:
        self.bundle_path = bundle_path
        self._bundle: Optional[dict] = None
        self.context: HistoricalContext = empty_context()
        self.metrics: dict = {}
        self._matchup_index: MatchupIndex = {}
        self._feature_importances: dict[str, float] = {}
        self._feature_means: dict[str, float] = {}
        self._feature_stds: dict[str, float] = {}
        self._load()

    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        return self._bundle is not None

    @property
    def version(self) -> str:
        return (self._bundle or {}).get("version", "1.0-heuristic")

    @property
    def coverage(self) -> Optional[float]:
        conformal = (self._bundle or {}).get("score_conformal") or {}
        return conformal.get("target_coverage")

    def matchup_strike_rate(self, batters, bowlers) -> float:
        if not self._matchup_index:
            return DEFAULT_MATCHUP_STRIKE_RATE
        return matchup_strike_rate_from_index(self._matchup_index, batters, bowlers)

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.bundle_path.exists():
            logger.warning("Model bundle not found at %s; using heuristic only", self.bundle_path)
            return
        try:
            bundle = joblib.load(self.bundle_path)
            self._bundle = bundle
            ctx = bundle.get("context") or {}
            self.context = HistoricalContext(
                team_form_runs=ctx.get("team_form_runs", {}),
                team_form_win_rate=ctx.get("team_form_win_rate", {}),
                team_concede_runs=ctx.get("team_concede_runs", {}),
                team_bowl_win_rate=ctx.get("team_bowl_win_rate", {}),
                h2h_avg_score={
                    tuple(k) if isinstance(k, (list, tuple)) else k: v
                    for k, v in ctx.get("h2h_avg_score", {}).items()
                },
                h2h_batting_wins_share={
                    tuple(k) if isinstance(k, (list, tuple)) else k: v
                    for k, v in ctx.get("h2h_batting_wins_share", {}).items()
                },
                overall_avg_score=float(ctx.get("overall_avg_score", 165.0)),
            )
            self.metrics = bundle.get("metrics", {})
            self._matchup_index = bundle.get("matchup_index", {}) or {}
            self._feature_importances = bundle.get("feature_importances", {}) or {}
            self._feature_means, self._feature_stds = self._derive_feature_stats()
            test_mae = (
                (self.metrics.get("score") or {}).get("test", {}).get("mae")
                if isinstance(self.metrics.get("score"), dict)
                else None
            )
            logger.info(
                "Loaded model bundle %s (n_train=%s, test_mae=%s, coverage=%s)",
                self.version,
                self.metrics.get("n_train"),
                test_mae,
                self.coverage,
            )
        except Exception as exc:
            logger.error("Failed to load model bundle: %s", exc)

    def _derive_feature_stats(self) -> tuple[dict[str, float], dict[str, float]]:
        """Approximate per-feature mean/std from the historical context.

        Used by ``contributions`` to normalise feature deviations into a
        comparable scale across heterogeneous units. Falls back to zero
        std (which neutralises the term) when context is missing.
        """
        means: dict[str, float] = {}
        stds: dict[str, float] = {}
        ctx = self.context
        all_runs = list(ctx.team_form_runs.values()) or [ctx.overall_avg_score]
        all_concedes = list(ctx.team_concede_runs.values()) or [ctx.overall_avg_score]
        all_h2h = list(ctx.h2h_avg_score.values()) or [ctx.overall_avg_score]

        means["batting_recent_form_runs"] = float(np.mean(all_runs))
        stds["batting_recent_form_runs"] = float(np.std(all_runs)) or 1.0
        means["bowling_recent_form_conceded"] = float(np.mean(all_concedes))
        stds["bowling_recent_form_conceded"] = float(np.std(all_concedes)) or 1.0
        means["h2h_avg_score"] = float(np.mean(all_h2h))
        stds["h2h_avg_score"] = float(np.std(all_h2h)) or 1.0
        means["venue_avg_first_innings"] = ctx.overall_avg_score
        stds["venue_avg_first_innings"] = 12.0
        means["bat_xi_avg"] = 28.0
        stds["bat_xi_avg"] = 6.0
        means["bat_xi_strike_rate"] = 138.0
        stds["bat_xi_strike_rate"] = 12.0
        means["bowl_xi_economy"] = 8.5
        stds["bowl_xi_economy"] = 1.0
        means["bowl_xi_wickets"] = 60.0
        stds["bowl_xi_wickets"] = 35.0
        means["xi_overseas_count"] = 6.0
        stds["xi_overseas_count"] = 2.0
        means["xi_matchup_strike_rate"] = DEFAULT_MATCHUP_STRIKE_RATE
        stds["xi_matchup_strike_rate"] = 12.0
        means["target_score"] = ctx.overall_avg_score
        stds["target_score"] = 20.0
        for k in (
            "toss_won_by_batting",
            "toss_decision_bat",
            "home_advantage",
            "batting_recent_win_rate",
            "bowling_recent_win_rate",
            "h2h_batting_wins_share",
            "pitch_modifier",
            "weather_modifier",
        ):
            means.setdefault(k, 0.0)
            stds.setdefault(k, 1.0)
        return means, stds

    # ------------------------------------------------------------------
    def predict(
        self,
        *,
        team_a: str,
        team_b: str,
        batting_team: str,
        toss_winner: str,
        venue: str,
        pitch: str,
        weather: str,
        playing_xi_a: list[str],
        playing_xi_b: list[str],
        target_score: Optional[float] = None,
    ) -> PredictionResult:
        bowling_team = team_b if batting_team == team_a else team_a
        bat_xi = playing_xi_a if batting_team == team_a else playing_xi_b
        bowl_xi = playing_xi_b if batting_team == team_a else playing_xi_a

        bat_strength = _team_strength(batting_team, bat_xi)
        bowl_strength = _team_strength(bowling_team, bowl_xi)

        mode = "chase" if target_score is not None else "first-innings"

        if self._bundle is not None:
            try:
                features = build_request_features(
                    batting_team=batting_team,
                    bowling_team=bowling_team,
                    venue=venue,
                    toss_winner=toss_winner,
                    pitch=pitch,
                    weather=weather,
                    playing_xi_a=playing_xi_a,
                    playing_xi_b=playing_xi_b,
                    team_a=team_a,
                    team_b=team_b,
                    context=self.context,
                    matchup_resolver=self.matchup_strike_rate,
                    target_score=target_score,
                )
                score_pipeline = self._bundle.get("score_pipeline")
                low_pipeline = self._bundle.get("score_lower_pipeline")
                high_pipeline = self._bundle.get("score_upper_pipeline")
                win_pipeline = self._bundle.get("win_pipeline")

                use_chase = (
                    mode == "chase"
                    and self._bundle.get("chase_score_pipeline") is not None
                    and self._bundle.get("chase_win_pipeline") is not None
                )
                if use_chase:
                    chase_features = features  # already chase-shaped
                    chase_score_pipeline = self._bundle["chase_score_pipeline"]
                    chase_win_pipeline = self._bundle["chase_win_pipeline"]
                    score = float(chase_score_pipeline.predict(chase_features)[0])
                    win_prob = float(chase_win_pipeline.predict_proba(chase_features)[0][1])
                    # Chase-mode intervals re-use the first-innings quantile
                    # band as a conservative envelope.
                    base_features = features.drop(columns=["target_score"])
                    low = float(low_pipeline.predict(base_features)[0]) if low_pipeline else score - 12
                    high = float(high_pipeline.predict(base_features)[0]) if high_pipeline else score + 12
                else:
                    base_features = features
                    if "target_score" in base_features.columns:
                        base_features = base_features.drop(columns=["target_score"])
                    score = float(score_pipeline.predict(base_features)[0])
                    low = float(low_pipeline.predict(base_features)[0]) if low_pipeline else score - 12
                    high = float(high_pipeline.predict(base_features)[0]) if high_pipeline else score + 12
                    win_prob = float(win_pipeline.predict_proba(base_features)[0][1])

                conformal = self._bundle.get("score_conformal") or {}
                q = float(conformal.get("q", 0.0))
                low -= q
                high += q
                low, high = sorted((low, high))

                contributions = self._contributions(
                    features.iloc[0].to_dict(),
                    score=score,
                    win_prob=win_prob,
                )

                return _shape_result(
                    score=score,
                    low=low,
                    high=high,
                    win_prob=win_prob,
                    bat_strength=bat_strength,
                    bowl_strength=bowl_strength,
                    version=self.version,
                    mode=mode,
                    contributions=contributions,
                    coverage=conformal.get("target_coverage"),
                )
            except Exception as exc:
                logger.error("ML prediction failed; using heuristic fallback: %s", exc)

        return _heuristic_predict(
            team_a=team_a,
            team_b=team_b,
            batting_team=batting_team,
            toss_winner=toss_winner,
            venue=venue,
            pitch=pitch,
            weather=weather,
            bat_strength=bat_strength,
            bowl_strength=bowl_strength,
            mode=mode,
            target_score=target_score,
        )

    # ------------------------------------------------------------------
    def predict_per_over(
        self,
        *,
        overs_completed: float,
        wickets_lost: int,
        current_run_rate: float,
        baseline_per_over: float,
    ) -> float:
        bundle = self._bundle or {}
        pipeline = bundle.get("per_over_pipeline")
        if pipeline is None:
            return _heuristic_per_over(
                overs_completed=overs_completed,
                wickets_lost=wickets_lost,
                current_run_rate=current_run_rate,
                baseline_per_over=baseline_per_over,
            )
        try:
            row = pd.DataFrame(
                [
                    {
                        "overs_completed": float(overs_completed),
                        "wickets_lost": int(wickets_lost),
                        "current_run_rate": float(current_run_rate),
                    }
                ]
            )
            return float(pipeline.predict(row)[0])
        except Exception as exc:
            logger.warning("Per-over prediction failed (%s); using heuristic", exc)
            return _heuristic_per_over(
                overs_completed=overs_completed,
                wickets_lost=wickets_lost,
                current_run_rate=current_run_rate,
                baseline_per_over=baseline_per_over,
            )

    # ------------------------------------------------------------------
    def _contributions(
        self,
        feature_row: dict,
        *,
        score: float,
        win_prob: float,
        top_n: int = 5,
    ) -> list[dict]:
        """Return the top-N feature contributions for a single prediction.

        Contribution magnitude:  importance × |z-score|.
        Sign:                    sign(value − mean), so the direction tells
                                 the user whether the feature pushed the
                                 prediction up or down relative to a
                                 league-average baseline.
        Missing importance / std collapses the term to zero so it falls
        out of the top-N list.
        """
        importances = self._feature_importances
        means = self._feature_means
        stds = self._feature_stds
        if not importances:
            return []

        rows: list[dict] = []
        for name, importance in importances.items():
            if importance <= 0:
                continue
            value = feature_row.get(name)
            if value is None or isinstance(value, str):
                rows.append(
                    {
                        "feature": name,
                        "label": FEATURE_LABELS.get(name, name),
                        "value": value if isinstance(value, str) else None,
                        "importance": float(importance),
                        "magnitude": float(importance),
                        "direction": 0,
                        "z_score": 0.0,
                    }
                )
                continue
            mean = means.get(name, 0.0)
            std = stds.get(name) or 1.0
            try:
                z = (float(value) - mean) / std
            except Exception:
                z = 0.0
            magnitude = float(importance) * abs(z)
            direction = 1 if z > 0 else (-1 if z < 0 else 0)
            rows.append(
                {
                    "feature": name,
                    "label": FEATURE_LABELS.get(name, name),
                    "value": float(value),
                    "importance": float(importance),
                    "magnitude": magnitude,
                    "direction": direction,
                    "z_score": float(z),
                }
            )
        rows.sort(key=lambda r: r["magnitude"], reverse=True)
        return rows[:top_n]


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------


def _team_strength(team_id: str, players: list[str]) -> int:
    team = get_team(team_id) or {}
    base = int(team.get("rating", 75))
    aggr = aggregate_xi(team_id, players)
    composite = (
        base
        + (aggr.bat_avg - 25) * 0.6
        + ((10 - min(10.0, aggr.economy)) * 4 - 20) * 0.4 if aggr.economy > 0 else base
    )
    if not isinstance(composite, (int, float)):
        composite = base
    return int(max(60, min(100, composite)))


def _heuristic_predict(
    *,
    team_a: str,
    team_b: str,
    batting_team: str,
    toss_winner: str,
    venue: str,
    pitch: str,
    weather: str,
    bat_strength: int,
    bowl_strength: int,
    mode: str = "first-innings",
    target_score: Optional[float] = None,
) -> PredictionResult:
    venue_record = get_venue(venue) or {}
    pitch_record = get_pitch(pitch) or {}
    weather_record = get_weather(weather) or {}

    base = int(venue_record.get("avg_first_innings", 165))
    score = (
        base
        + int(pitch_record.get("score_modifier", 0))
        + int(weather_record.get("score_modifier", 0))
        + int((bat_strength - 80) * 1.6)
        - int((bowl_strength - 80) * 1.0)
    )
    if toss_winner == batting_team:
        score += 4
    seed = hash((team_a, team_b, batting_team, venue, pitch, weather, mode)) % 10_000
    score += random.Random(seed).randint(-8, 8)

    if mode == "chase" and target_score:
        # Chasing teams cap their projection at the target.
        score = min(score, int(target_score) + 2)

    diff = bat_strength - bowl_strength
    win_prob = 0.5 + diff * 0.014
    if pitch_record.get("id") == "batting":
        win_prob += 0.04
    if weather_record.get("id") == "dew":
        win_prob -= 0.05
    if toss_winner == batting_team:
        win_prob += 0.02
    if mode == "chase" and target_score:
        # Chases get harder as the target grows.
        win_prob -= max(0, (float(target_score) - 165) / 200.0)

    return _shape_result(
        score=float(score),
        low=score - 12,
        high=score + 12,
        win_prob=win_prob,
        bat_strength=bat_strength,
        bowl_strength=bowl_strength,
        version="1.0-heuristic",
        mode=mode,
        contributions=[],
        coverage=None,
    )


def _heuristic_per_over(
    *,
    overs_completed: float,
    wickets_lost: int,
    current_run_rate: float,
    baseline_per_over: float,
) -> float:
    wicket_factor = max(0.4, 1.0 - wickets_lost * 0.07)
    if overs_completed <= 0:
        return baseline_per_over
    weight_live = min(1.0, overs_completed / 12.0)
    return current_run_rate * wicket_factor * weight_live + baseline_per_over * (1 - weight_live)


def _shape_result(
    *,
    score: float,
    low: float,
    high: float,
    win_prob: float,
    bat_strength: int,
    bowl_strength: int,
    version: str,
    mode: str = "first-innings",
    contributions: Optional[list[dict]] = None,
    coverage: Optional[float] = None,
) -> PredictionResult:
    score_int = int(round(max(110, min(255, score))))
    low_int = int(round(max(100, min(score_int, low))))
    high_int = int(round(min(280, max(score_int, high))))
    win_pct = int(round(max(10, min(90, win_prob * 100 if win_prob <= 1 else win_prob))))
    rr = round(score_int / 20.0, 2)

    powerplay = int(round(score_int * 0.28))
    middle = int(round(score_int * 0.40))
    death = score_int - powerplay - middle

    return PredictionResult(
        score=score_int,
        score_low=low_int,
        score_high=high_int,
        win_probability_batting=win_pct,
        expected_run_rate=rr,
        powerplay_runs=powerplay,
        middle_runs=middle,
        death_runs=death,
        batting_team_strength=bat_strength,
        bowling_team_strength=bowl_strength,
        model_version=version,
        mode=mode,
        contributions=contributions or [],
        coverage=coverage,
    )
