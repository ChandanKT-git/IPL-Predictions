"""Train every model the API serves.

The bundle persisted to ``models.joblib`` carries:

* ``score_pipeline``                 — first-innings score regressor (MAE).
* ``score_lower_pipeline`` / ``score_upper_pipeline`` — quantile regressors
  used as the base for conformal intervals.
* ``score_conformal``                — split-conformal quantile correction
  (additive ``q``) so the [low, high] band has 80% empirical coverage on
  the validation fold.
* ``win_pipeline``                   — calibrated chase-outcome classifier
  (Brier-tuned via ``CalibratedClassifierCV(method="isotonic")``).
* ``chase_score_pipeline`` / ``chase_win_pipeline`` — second-innings
  (chase) specialists, conditional on ``target_score``.
* ``per_over_pipeline``              — runs-per-remaining-over regressor
  for ``/api/whatif``.
* ``feature_importances``            — permutation importance keyed by
  feature name; consumed by ``/api/predict`` for the "why this prediction"
  panel.
* ``context``                        — :class:`HistoricalContext`.
* ``matchup_index``                  — (batter, bowler) → (balls, runs)
  index reused at inference for the ``xi_matchup_strike_rate`` feature.
* ``metrics``                        — chronological train/val/test MAE,
  RMSE, log loss, Brier score, and conformal coverage.

The split is chronological:
* train  : earliest 70% of innings rows.
* val    : middle 15% (used to fit the conformal correction and to size
            quantile coverage).
* test   : most-recent 15% (held out for honest reporting).
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from features import (
    CATEGORICAL_FEATURES,
    CHASE_FEATURE_COLUMNS,
    CHASE_NUMERIC_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    build_match_dataset,
    build_matchup_index,
    context_from_dataset,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("train_model")

ROOT = Path(__file__).parent
CSV_PATH = ROOT / "data" / "IPL.csv"
MODEL_PATH = ROOT / "models.joblib"
METRICS_PATH = ROOT / "models_metrics.json"

RANDOM_STATE = 42
TRAIN_FRAC = 0.70
VAL_FRAC = 0.15
TARGET_COVERAGE = 0.80


def _make_preprocessor(numeric: list[str]) -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL_FEATURES,
            ),
            ("num", "passthrough", numeric),
        ]
    )


def _score_regressor(loss: str = "absolute_error", quantile: float | None = None,
                     numeric: list[str] | None = None) -> Pipeline:
    numeric = numeric or NUMERIC_FEATURES
    if loss == "quantile":
        regressor = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=quantile,
            max_iter=500,
            learning_rate=0.05,
            max_depth=6,
            random_state=RANDOM_STATE,
        )
    else:
        regressor = HistGradientBoostingRegressor(
            loss="absolute_error",
            max_iter=600,
            learning_rate=0.05,
            max_depth=6,
            random_state=RANDOM_STATE,
        )
    return Pipeline([("pre", _make_preprocessor(numeric)), ("model", regressor)])


def _win_classifier_base(numeric: list[str] | None = None) -> Pipeline:
    numeric = numeric or NUMERIC_FEATURES
    return Pipeline(
        [
            ("pre", _make_preprocessor(numeric)),
            (
                "model",
                HistGradientBoostingClassifier(
                    max_iter=400,
                    learning_rate=0.05,
                    max_depth=5,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def _chronological_split(dataset: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sorted_df = dataset.sort_values("date").reset_index(drop=True)
    n = len(sorted_df)
    train_end = int(n * TRAIN_FRAC)
    val_end = int(n * (TRAIN_FRAC + VAL_FRAC))
    return sorted_df.iloc[:train_end], sorted_df.iloc[train_end:val_end], sorted_df.iloc[val_end:]


def _eval_score(model: Pipeline, X, y) -> dict:
    pred = model.predict(X)
    return {
        "mae": float(mean_absolute_error(y, pred)),
        "rmse": float(np.sqrt(mean_squared_error(y, pred))),
        "n": int(len(y)),
    }


def _conformal_correction(
    score_low: Pipeline,
    score_high: Pipeline,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    target_coverage: float = TARGET_COVERAGE,
) -> dict:
    """Split-conformal correction for a quantile regression interval.

    For each validation row, score the residual that would have been
    needed to put the true value back inside the interval. Take the
    ``target_coverage``-quantile of those residuals as the additive
    correction ``q``. The serving path then returns
    ``[low - q, high + q]`` so the empirical coverage on the validation
    distribution matches ``target_coverage``.
    """
    low_pred = score_low.predict(X_val)
    high_pred = score_high.predict(X_val)
    nonconformity = np.maximum(low_pred - y_val.to_numpy(), y_val.to_numpy() - high_pred)
    nonconformity = np.maximum(nonconformity, 0.0)
    q = float(np.quantile(nonconformity, target_coverage))
    coverage_low = low_pred - q
    coverage_high = high_pred + q
    inside = (y_val.to_numpy() >= coverage_low) & (y_val.to_numpy() <= coverage_high)
    return {
        "q": q,
        "target_coverage": float(target_coverage),
        "empirical_coverage": float(inside.mean()),
        "mean_width": float((coverage_high - coverage_low).mean()),
    }


def _eval_win(model: Pipeline | CalibratedClassifierCV, X, y) -> dict:
    proba = model.predict_proba(X)[:, 1]
    return {
        "log_loss": float(log_loss(y, proba, labels=[0, 1])),
        "brier": float(brier_score_loss(y, proba)),
        "accuracy": float(model.score(X, y)),
        "n": int(len(y)),
    }


def _build_per_over_dataset(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    rows: list[dict] = []
    dates: list[pd.Timestamp] = []
    for (mid, inn), grp in raw.groupby(["match_id", "innings"], sort=False):
        grp = grp.sort_values(["over", "ball"])
        innings_date = pd.to_datetime(grp["date"].iloc[0], errors="coerce")
        per_over = (
            grp.groupby("over")
            .agg(runs=("runs_total", "sum"), wickets=("wicket_kind", lambda s: s.notna().sum()))
            .reset_index()
        )
        cumulative_runs = 0
        cumulative_wkts = 0
        for _, row in per_over.iterrows():
            over = int(row["over"])
            if over <= 0 or over > 20:
                continue
            crr = cumulative_runs / over if over > 0 else 0
            rows.append(
                {
                    "overs_completed": over - 1,
                    "wickets_lost": cumulative_wkts,
                    "current_run_rate": crr,
                    "runs_in_over": int(row["runs"]),
                }
            )
            dates.append(innings_date)
            cumulative_runs += int(row["runs"])
            cumulative_wkts += int(row["wickets"])

    df = pd.DataFrame(rows)
    return df.drop(columns=["runs_in_over"]), df["runs_in_over"], pd.Series(dates)


def _per_over_pipeline() -> Pipeline:
    return Pipeline(
        [
            (
                "model",
                HistGradientBoostingRegressor(
                    loss="absolute_error",
                    max_iter=400,
                    learning_rate=0.05,
                    max_depth=5,
                    random_state=RANDOM_STATE,
                ),
            )
        ]
    )


def _permutation_importance(
    model: Pipeline,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    feature_names: list[str],
    n_repeats: int = 5,
) -> dict[str, float]:
    """Permutation importance for each feature, normalised to sum to 1."""
    if X_test.empty:
        return {name: 0.0 for name in feature_names}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = permutation_importance(
            model,
            X_test[feature_names],
            y_test,
            n_repeats=n_repeats,
            random_state=RANDOM_STATE,
            scoring="neg_mean_absolute_error",
        )
    means = np.maximum(result.importances_mean, 0.0)
    if means.sum() == 0:
        return {name: 0.0 for name in feature_names}
    weights = means / means.sum()
    return {name: float(w) for name, w in zip(feature_names, weights)}


def train() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"IPL CSV not found at {CSV_PATH}")

    logger.info("Loading ball-by-ball CSV from %s", CSV_PATH)
    raw = pd.read_csv(CSV_PATH, low_memory=False)
    logger.info("Loaded %d rows", len(raw))

    logger.info("Building matchup index")
    matchup_index = build_matchup_index(raw)
    logger.info("Indexed %d (batter, bowler) pairs", len(matchup_index))

    logger.info("Building per-innings feature dataset")
    dataset = build_match_dataset(raw, matchup_index=matchup_index)
    logger.info("Innings rows: %d", len(dataset))

    train_df, val_df, test_df = _chronological_split(dataset)
    logger.info(
        "Chronological split — train=%d (≤%s), val=%d (%s..%s), test=%d (≥%s)",
        len(train_df), train_df["date"].max().date() if not train_df.empty else "—",
        len(val_df),
        val_df["date"].min().date() if not val_df.empty else "—",
        val_df["date"].max().date() if not val_df.empty else "—",
        len(test_df), test_df["date"].min().date() if not test_df.empty else "—",
    )

    # ----- First-innings score regressor -----
    first_innings = train_df[train_df["innings"] == 1]
    first_val = val_df[val_df["innings"] == 1]
    first_test = test_df[test_df["innings"] == 1]
    X_train, y_train = first_innings[FEATURE_COLUMNS], first_innings["runs_total"]
    X_val, y_val = first_val[FEATURE_COLUMNS], first_val["runs_total"]
    X_test, y_test = first_test[FEATURE_COLUMNS], first_test["runs_total"]

    logger.info("Training first-innings score regressor on %d rows", len(X_train))
    score_pipeline = _score_regressor()
    score_pipeline.fit(X_train, y_train)
    score_metrics = {
        "train": _eval_score(score_pipeline, X_train, y_train),
        "val":   _eval_score(score_pipeline, X_val, y_val),
        "test":  _eval_score(score_pipeline, X_test, y_test),
    }
    logger.info(
        "Score regressor — val MAE %.2f / test MAE %.2f",
        score_metrics["val"]["mae"], score_metrics["test"]["mae"],
    )

    logger.info("Training quantile regressors (P10 / P90)")
    score_lower = _score_regressor(loss="quantile", quantile=0.1)
    score_upper = _score_regressor(loss="quantile", quantile=0.9)
    score_lower.fit(X_train, y_train)
    score_upper.fit(X_train, y_train)

    logger.info("Computing conformal correction on the validation fold")
    conformal = _conformal_correction(score_lower, score_upper, X_val, y_val)
    logger.info(
        "Conformal q=%.2f, empirical coverage=%.2f%% (target %.0f%%)",
        conformal["q"], conformal["empirical_coverage"] * 100,
        conformal["target_coverage"] * 100,
    )

    # ----- Calibrated win classifier (Brier) -----
    logger.info("Training calibrated win-probability classifier")
    win_X_train, win_y_train = train_df[FEATURE_COLUMNS], train_df["batting_won"]
    win_X_val, win_y_val = val_df[FEATURE_COLUMNS], val_df["batting_won"]
    win_X_test, win_y_test = test_df[FEATURE_COLUMNS], test_df["batting_won"]
    base_win = _win_classifier_base()
    base_win.fit(win_X_train, win_y_train)
    win_pipeline = CalibratedClassifierCV(
        base_win, method="isotonic", cv="prefit"
    )
    win_pipeline.fit(win_X_val, win_y_val)
    win_metrics = {
        "train": _eval_win(win_pipeline, win_X_train, win_y_train),
        "val":   _eval_win(win_pipeline, win_X_val, win_y_val),
        "test":  _eval_win(win_pipeline, win_X_test, win_y_test),
    }
    logger.info(
        "Win classifier — val Brier %.3f / test Brier %.3f",
        win_metrics["val"]["brier"], win_metrics["test"]["brier"],
    )

    # ----- Chase-only specialists -----
    chase_train = train_df[train_df["innings"] == 2]
    chase_val = val_df[val_df["innings"] == 2]
    chase_test = test_df[test_df["innings"] == 2]
    chase_metrics: dict = {}
    chase_score_pipeline: Optional[Pipeline] = None
    chase_win_pipeline: Optional[CalibratedClassifierCV] = None
    if len(chase_train) >= 100 and len(chase_val) >= 30:
        logger.info("Training chase score regressor on %d rows", len(chase_train))
        chase_X_train = chase_train[CHASE_FEATURE_COLUMNS]
        chase_X_val = chase_val[CHASE_FEATURE_COLUMNS]
        chase_X_test = chase_test[CHASE_FEATURE_COLUMNS]
        chase_score_pipeline = _score_regressor(numeric=CHASE_NUMERIC_FEATURES)
        chase_score_pipeline.fit(chase_X_train, chase_train["runs_total"])
        chase_metrics["score"] = {
            "train": _eval_score(chase_score_pipeline, chase_X_train, chase_train["runs_total"]),
            "val":   _eval_score(chase_score_pipeline, chase_X_val, chase_val["runs_total"]),
            "test":  _eval_score(chase_score_pipeline, chase_X_test, chase_test["runs_total"]),
        }
        logger.info(
            "Chase score regressor — val MAE %.2f / test MAE %.2f",
            chase_metrics["score"]["val"]["mae"],
            chase_metrics["score"]["test"]["mae"],
        )

        logger.info("Training calibrated chase win classifier")
        base_chase_win = _win_classifier_base(numeric=CHASE_NUMERIC_FEATURES)
        base_chase_win.fit(chase_X_train, chase_train["batting_won"])
        chase_win_pipeline = CalibratedClassifierCV(
            base_chase_win, method="isotonic", cv="prefit"
        )
        chase_win_pipeline.fit(chase_X_val, chase_val["batting_won"])
        chase_metrics["win"] = {
            "train": _eval_win(chase_win_pipeline, chase_X_train, chase_train["batting_won"]),
            "val":   _eval_win(chase_win_pipeline, chase_X_val, chase_val["batting_won"]),
            "test":  _eval_win(chase_win_pipeline, chase_X_test, chase_test["batting_won"]),
        }
        logger.info(
            "Chase win classifier — val Brier %.3f / test Brier %.3f",
            chase_metrics["win"]["val"]["brier"],
            chase_metrics["win"]["test"]["brier"],
        )
    else:
        logger.warning(
            "Skipping chase models: not enough samples (train=%d, val=%d)",
            len(chase_train), len(chase_val),
        )

    # ----- Per-over progression model -----
    logger.info("Training per-over progression model")
    per_over_X, per_over_y, per_over_dates = _build_per_over_dataset(raw)
    per_over_metrics: dict = {"samples": int(len(per_over_X))}
    per_over_pipeline: Optional[Pipeline] = None
    if len(per_over_X) >= 1000:
        order = per_over_dates.argsort()
        per_over_X = per_over_X.iloc[order].reset_index(drop=True)
        per_over_y = per_over_y.iloc[order].reset_index(drop=True)
        po_split = int(len(per_over_X) * 0.85)
        po_train_x, po_test_x = per_over_X.iloc[:po_split], per_over_X.iloc[po_split:]
        po_train_y, po_test_y = per_over_y.iloc[:po_split], per_over_y.iloc[po_split:]
        per_over_pipeline = _per_over_pipeline()
        per_over_pipeline.fit(po_train_x, po_train_y)
        per_over_metrics.update(
            {
                "test_mae": float(
                    mean_absolute_error(po_test_y, per_over_pipeline.predict(po_test_x))
                ),
            }
        )
        logger.info(
            "Per-over model — test MAE %.2f over %d samples",
            per_over_metrics["test_mae"], per_over_metrics["samples"],
        )
    else:
        logger.warning("Skipping per-over model: insufficient samples")

    # ----- Permutation importance for the score regressor (test fold) -----
    logger.info("Computing permutation importance on the test fold")
    feature_importances = _permutation_importance(
        score_pipeline, X_test, y_test, FEATURE_COLUMNS
    )
    top_three = sorted(feature_importances.items(), key=lambda kv: kv[1], reverse=True)[:3]
    logger.info("Top features: %s", top_three)

    context = context_from_dataset(dataset)

    bundle = {
        "version": "5.0-chronological-calibrated",
        "feature_columns": FEATURE_COLUMNS,
        "chase_feature_columns": CHASE_FEATURE_COLUMNS,
        "score_pipeline": score_pipeline,
        "score_lower_pipeline": score_lower,
        "score_upper_pipeline": score_upper,
        "score_conformal": conformal,
        "win_pipeline": win_pipeline,
        "chase_score_pipeline": chase_score_pipeline,
        "chase_win_pipeline": chase_win_pipeline,
        "per_over_pipeline": per_over_pipeline,
        "feature_importances": feature_importances,
        "matchup_index": matchup_index,
        "context": asdict(context),
        "metrics": {
            "score": score_metrics,
            "win": win_metrics,
            "chase": chase_metrics,
            "conformal": conformal,
            "per_over": per_over_metrics,
            "n_train": int(len(train_df)),
            "n_val": int(len(val_df)),
            "n_test": int(len(test_df)),
            "split": {
                "train_end": str(train_df["date"].max().date()) if not train_df.empty else None,
                "val_end": str(val_df["date"].max().date()) if not val_df.empty else None,
                "test_end": str(test_df["date"].max().date()) if not test_df.empty else None,
            },
        },
    }

    joblib.dump(bundle, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(bundle["metrics"], indent=2))
    logger.info("Saved bundle to %s and metrics to %s", MODEL_PATH, METRICS_PATH)


if __name__ == "__main__":
    os.chdir(ROOT)
    train()
