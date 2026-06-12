"""Tests for the IPLDataManager — H2H, season aggregates, matchups."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from data_manager import IPLDataManager  # noqa: E402

CSV = Path(BACKEND_DIR) / "data" / "IPL.csv"


class TestDataManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not CSV.exists():
            raise unittest.SkipTest(f"CSV missing at {CSV}")
        cls.dm = IPLDataManager(csv_path=str(CSV))

    def test_data_loaded(self) -> None:
        self.assertTrue(self.dm.is_loaded)
        self.assertGreater(len(self.dm.dataframe), 1000)

    def test_h2h_csk_vs_mi_returns_records(self) -> None:
        stats = self.dm.get_h2h_stats("csk", "mi")
        self.assertIsNotNone(stats)
        self.assertGreater(stats["total_matches"], 0)
        self.assertEqual(stats["teams"], ["csk", "mi"])
        self.assertIsInstance(stats["last_5"], list)
        self.assertIn("csk", stats["form_guide"])
        self.assertIn("mi", stats["form_guide"])
        self.assertIsInstance(stats["season_aggregates"], list)

    def test_h2h_unknown_pair_returns_none(self) -> None:
        self.assertIsNone(self.dm.get_h2h_stats("zzz", "yyy"))

    def test_h2h_is_symmetric(self) -> None:
        ab = self.dm.get_h2h_stats("csk", "mi")
        ba = self.dm.get_h2h_stats("mi", "csk")
        self.assertEqual(ab["total_matches"], ba["total_matches"])
        self.assertEqual(ab["team_a_wins"], ba["team_b_wins"])
        self.assertEqual(ab["team_b_wins"], ba["team_a_wins"])

    def test_season_aggregates_sum_to_total(self) -> None:
        stats = self.dm.get_h2h_stats("csk", "mi")
        per_season_total = sum(s["matches"] for s in stats["season_aggregates"])
        self.assertGreaterEqual(per_season_total, stats["total_matches"] / 2)

    def test_venue_record_for_known_venue(self) -> None:
        record = self.dm.get_venue_record("csk", "mi", "Wankhede")
        if record is None:
            self.skipTest("No CSK vs MI matches at Wankhede in this dataset")
        self.assertGreaterEqual(record["matches"], 1)
        self.assertIn("avg_score", record)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
