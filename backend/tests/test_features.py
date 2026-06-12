"""Tests for the leakage-free matchup feature and chase-mode features."""

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

from features import (  # noqa: E402
    CHASE_FEATURE_COLUMNS,
    DEFAULT_MATCHUP_STRIKE_RATE,
    FEATURE_COLUMNS,
    build_matchup_index,
    build_request_features,
    empty_context,
    matchup_strike_rate_from_index,
)


class TestMatchupStrikeRate(unittest.TestCase):
    def test_default_when_no_history(self) -> None:
        rate = matchup_strike_rate_from_index({}, ["MS Dhoni"], ["JJ Bumrah"])
        self.assertEqual(rate, DEFAULT_MATCHUP_STRIKE_RATE)

    def test_aggregates_runs_and_balls_across_pairs(self) -> None:
        index = {
            ("MS Dhoni", "JJ Bumrah"): (10, 12),  # 12 runs off 10 balls
            ("RA Jadeja", "JJ Bumrah"): (5, 8),   # 8 runs off 5 balls
        }
        rate = matchup_strike_rate_from_index(
            index, ["MS Dhoni", "RA Jadeja"], ["JJ Bumrah"]
        )
        # (12 + 8) runs / (10 + 5) balls * 100 = 133.33
        self.assertAlmostEqual(rate, 20 / 15 * 100, places=2)

    def test_unknown_pair_returns_default(self) -> None:
        index = {("X", "Y"): (5, 5)}
        self.assertEqual(
            matchup_strike_rate_from_index(index, ["A"], ["B"]),
            DEFAULT_MATCHUP_STRIKE_RATE,
        )


class TestRequestFeatures(unittest.TestCase):
    def test_first_innings_columns(self) -> None:
        df = build_request_features(
            batting_team="csk",
            bowling_team="mi",
            venue="wankhede",
            toss_winner="csk",
            pitch="batting",
            weather="clear",
            playing_xi_a=["MS Dhoni"],
            playing_xi_b=["Rohit Sharma"],
            team_a="csk",
            team_b="mi",
            context=empty_context(),
        )
        self.assertEqual(list(df.columns), FEATURE_COLUMNS)
        self.assertEqual(len(df), 1)
        self.assertIn("xi_matchup_strike_rate", df.columns)

    def test_chase_columns_when_target_supplied(self) -> None:
        df = build_request_features(
            batting_team="mi",
            bowling_team="csk",
            venue="wankhede",
            toss_winner="csk",
            pitch="batting",
            weather="clear",
            playing_xi_a=[],
            playing_xi_b=[],
            team_a="csk",
            team_b="mi",
            context=empty_context(),
            target_score=180,
        )
        self.assertEqual(list(df.columns), CHASE_FEATURE_COLUMNS)
        self.assertEqual(df.iloc[0]["target_score"], 180.0)


class TestMatchupIndexLeakageFree(unittest.TestCase):
    """The training index built across the full CSV is fine for inference,
    but the per-row training feature must only see prior history."""

    def test_build_matchup_index_aggregates_all_history(self) -> None:
        raw = pd.DataFrame(
            {
                "match_id": [1, 1, 2, 2],
                "innings": [1, 1, 1, 1],
                "batter": ["MS Dhoni", "MS Dhoni", "MS Dhoni", "MS Dhoni"],
                "bowler": ["JJ Bumrah", "JJ Bumrah", "JJ Bumrah", "JJ Bumrah"],
                "runs_batter": [4, 0, 1, 2],
            }
        )
        index = build_matchup_index(raw)
        balls, runs = index[("MS Dhoni", "JJ Bumrah")]
        self.assertEqual(balls, 4)
        self.assertEqual(runs, 7)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
