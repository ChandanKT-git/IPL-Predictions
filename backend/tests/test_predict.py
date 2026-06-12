"""Unit tests for the prediction adapter and POST /api/predict."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import pandas as pd

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "ipl_test")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from features import FEATURE_COLUMNS, build_request_features, empty_context  # noqa: E402
from predictor import Predictor, PredictionResult  # noqa: E402


class TestFeatureBuilder(unittest.TestCase):
    def test_request_features_has_expected_columns(self) -> None:
        df = build_request_features(
            batting_team="csk",
            bowling_team="mi",
            venue="wankhede",
            toss_winner="csk",
            pitch="batting",
            weather="clear",
            playing_xi_a=["MS Dhoni", "Ruturaj Gaikwad"],
            playing_xi_b=["Rohit Sharma", "Jasprit Bumrah"],
            team_a="csk",
            team_b="mi",
            context=empty_context(),
        )
        self.assertEqual(list(df.columns), FEATURE_COLUMNS)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["batting_team"], "csk")
        self.assertEqual(df.iloc[0]["bowling_team"], "mi")

    def test_features_categorical_dtype_is_object_or_string(self) -> None:
        df = build_request_features(
            batting_team="rcb",
            bowling_team="kkr",
            venue="chinnaswamy",
            toss_winner="kkr",
            pitch="balanced",
            weather="cloudy",
            playing_xi_a=[],
            playing_xi_b=[],
            team_a="rcb",
            team_b="kkr",
            context=empty_context(),
        )
        for col in ("batting_team", "bowling_team", "venue"):
            self.assertEqual(df[col].dtype, object)


class TestPredictorHeuristicFallback(unittest.TestCase):
    """When the joblib bundle is missing the predictor must serve heuristic."""

    def setUp(self) -> None:
        self.predictor = Predictor(bundle_path=Path("/nonexistent.joblib"))

    def test_predictor_reports_not_ready(self) -> None:
        self.assertFalse(self.predictor.is_ready)
        self.assertEqual(self.predictor.version, "1.0-heuristic")

    def test_heuristic_predict_returns_valid_shape(self) -> None:
        result = self.predictor.predict(
            team_a="csk",
            team_b="mi",
            batting_team="csk",
            toss_winner="csk",
            venue="wankhede",
            pitch="batting",
            weather="clear",
            playing_xi_a=[],
            playing_xi_b=[],
        )
        self.assertIsInstance(result, PredictionResult)
        self.assertGreaterEqual(result.score, 110)
        self.assertLessEqual(result.score, 255)
        self.assertLessEqual(result.score_low, result.score)
        self.assertGreaterEqual(result.score_high, result.score)
        self.assertGreaterEqual(result.win_probability_batting, 10)
        self.assertLessEqual(result.win_probability_batting, 90)
        self.assertEqual(
            result.powerplay_runs + result.middle_runs + result.death_runs,
            result.score,
        )

    def test_heuristic_is_deterministic_for_same_input(self) -> None:
        kwargs = dict(
            team_a="csk", team_b="mi",
            batting_team="csk", toss_winner="csk",
            venue="wankhede", pitch="batting", weather="clear",
            playing_xi_a=[], playing_xi_b=[],
        )
        r1 = self.predictor.predict(**kwargs)
        r2 = self.predictor.predict(**kwargs)
        self.assertEqual(r1.score, r2.score)
        self.assertEqual(r1.win_probability_batting, r2.win_probability_batting)


class TestPredictorMlPath(unittest.TestCase):
    """When the joblib bundle exists, the ML path must be exercised."""

    def setUp(self) -> None:
        self.bundle_path = Path(BACKEND_DIR) / "models.joblib"
        if not self.bundle_path.exists():
            self.skipTest("models.joblib not built — run train_model.py first")
        self.predictor = Predictor(bundle_path=self.bundle_path)

    def test_predictor_is_ready(self) -> None:
        self.assertTrue(self.predictor.is_ready)

    def test_ml_predict_uses_pipeline_version(self) -> None:
        result = self.predictor.predict(
            team_a="csk", team_b="mi",
            batting_team="csk", toss_winner="csk",
            venue="wankhede", pitch="batting", weather="clear",
            playing_xi_a=[], playing_xi_b=[],
        )
        self.assertNotEqual(result.model_version, "1.0-heuristic")


class TestPredictRoute(unittest.TestCase):
    """End-to-end /api/predict via FastAPI TestClient."""

    def setUp(self) -> None:
        self.client = TestClient(server.app)

    def _payload(self, **over):
        base = dict(
            team_a="csk", team_b="mi",
            batting_team="csk", toss_winner="csk",
            venue="wankhede", pitch="batting", weather="clear",
            playing_xi_a=[], playing_xi_b=[],
        )
        base.update(over)
        return base

    def test_predict_returns_expected_keys(self) -> None:
        r = self.client.post("/api/predict", json=self._payload())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in (
            "id", "predicted_score", "score_range_low", "score_range_high",
            "expected_run_rate", "win_probability_batting",
            "match_outcome", "phase_breakdown", "model_version",
        ):
            self.assertIn(key, body)

    def test_same_team_returns_400(self) -> None:
        r = self.client.post("/api/predict", json=self._payload(team_b="csk"))
        self.assertEqual(r.status_code, 400)

    def test_batting_team_outside_pair_returns_400(self) -> None:
        r = self.client.post("/api/predict", json=self._payload(batting_team="rcb"))
        self.assertEqual(r.status_code, 400)

    def test_too_many_xi_returns_400(self) -> None:
        twelve = [f"P{i}" for i in range(12)]
        r = self.client.post("/api/predict", json=self._payload(playing_xi_a=twelve))
        self.assertEqual(r.status_code, 400)

    def test_predict_is_deterministic_per_input(self) -> None:
        payload = self._payload()
        r1 = self.client.post("/api/predict", json=payload).json()
        r2 = self.client.post("/api/predict", json=payload).json()
        self.assertEqual(r1["predicted_score"], r2["predicted_score"])

    def test_request_id_round_trips_through_header(self) -> None:
        r = self.client.post(
            "/api/predict",
            json=self._payload(),
            headers={"X-Request-Id": "abc-123"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("X-Request-Id"), "abc-123")


class TestWhatIfRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(server.app)

    def test_overs_zero_returns_base(self) -> None:
        base = self.client.post(
            "/api/predict",
            json={
                "team_a": "csk", "team_b": "mi",
                "batting_team": "csk", "toss_winner": "csk",
                "venue": "wankhede", "pitch": "batting", "weather": "clear",
                "playing_xi_a": [], "playing_xi_b": [],
            },
        ).json()
        r = self.client.post(
            "/api/whatif",
            json={
                "base_prediction": base,
                "current_overs": 0,
                "current_wickets": 0,
                "current_runs": 0,
                "pitch": "batting",
                "weather": "clear",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["projected_score"], base["predicted_score"])


class TestHealthRoute(unittest.TestCase):
    def test_health_reports_subsystems(self) -> None:
        client = TestClient(server.app)
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("status", body)
        self.assertIn("subsystems", body)
        for key in ("mongo", "cricbuzz_key_set", "model_loaded", "csv_loaded"):
            self.assertIn(key, body["subsystems"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
