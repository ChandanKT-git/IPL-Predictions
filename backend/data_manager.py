"""Historical IPL CSV access — H2H, season aggregates, batter-vs-bowler.

The :class:`IPLDataManager` is loaded once at startup with the 65-column
ball-by-ball CSV and exposes pre-cached views the API consumes:

* :meth:`get_h2h_stats`           — last 5 matches, win counts, form guide.
* :meth:`get_season_aggregates`   — per-season totals for both teams.
* :meth:`get_venue_record`        — head-to-head record at a specific venue.
* :meth:`get_batter_vs_bowler`    — batter-vs-bowler matchups for the XI.

Everything is computed lazily on first read and cached on the manager
instance so the FastAPI handler stays fast.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from features import CSV_TEAM_TO_INTERNAL, INTERNAL_TEAM_TO_CSV

logger = logging.getLogger("ipl.data_manager")


class IPLDataManager:
    """Read-mostly view over the historical CSV."""

    def __init__(self, csv_path: str) -> None:
        self.csv_path = Path(csv_path)
        self.df: Optional[pd.DataFrame] = None
        self.is_loaded = False
        self._h2h_cache: dict[tuple[str, str], dict] = {}
        self._season_cache: dict[tuple[str, str], list[dict]] = {}
        self._venue_cache: dict[tuple[str, str, str], dict] = {}
        self._matchup_cache: dict[tuple[str, str], dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.csv_path.exists():
            logger.warning("IPL CSV not found at %s; H2H features disabled", self.csv_path)
            return
        try:
            df = pd.read_csv(self.csv_path, low_memory=False)
            df["batting_team_id"] = df["batting_team"].map(CSV_TEAM_TO_INTERNAL.get)
            df["bowling_team_id"] = df["bowling_team"].map(CSV_TEAM_TO_INTERNAL.get)
            df["winner_id"] = df["match_won_by"].map(CSV_TEAM_TO_INTERNAL.get)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            self.df = df
            self.is_loaded = True
            logger.info("Loaded historical IPL data: %d rows", len(df))
        except Exception as exc:
            logger.error("Failed to load CSV at %s: %s", self.csv_path, exc)

    @property
    def dataframe(self) -> pd.DataFrame:
        if self.df is None:
            return pd.DataFrame()
        return self.df

    def _names_for(self, internal_id: str) -> list[str]:
        return INTERNAL_TEAM_TO_CSV.get(internal_id.lower(), [])

    def _matches_between(self, team_a: str, team_b: str) -> pd.DataFrame:
        if not self.is_loaded:
            return pd.DataFrame()
        names_a = self._names_for(team_a)
        names_b = self._names_for(team_b)
        if not names_a or not names_b:
            return pd.DataFrame()
        df = self.df
        mask = (
            (df["batting_team"].isin(names_a) & df["bowling_team"].isin(names_b))
            | (df["batting_team"].isin(names_b) & df["bowling_team"].isin(names_a))
        )
        return df[mask]

    def get_h2h_stats(self, team_a: str, team_b: str) -> Optional[dict]:
        if not self.is_loaded:
            return None
        pair_key = tuple(sorted([team_a, team_b]))
        if pair_key not in self._h2h_cache:
            inner = self._compute_h2h(pair_key[0], pair_key[1])
            if inner is None:
                return None
            self._h2h_cache[pair_key] = inner

        inner = self._h2h_cache[pair_key]
        return {
            "teams": [team_a, team_b],
            "last_5": inner["last_5"],
            "form_guide": {
                team_a: inner["form_guide"][team_a],
                team_b: inner["form_guide"][team_b],
            },
            "win_count": {
                team_a: inner["per_team_wins"].get(team_a, 0),
                team_b: inner["per_team_wins"].get(team_b, 0),
            },
            "team_a_wins": inner["per_team_wins"].get(team_a, 0),
            "team_b_wins": inner["per_team_wins"].get(team_b, 0),
            "total_matches": inner["total_matches"],
            "avg_score": inner["avg_score"],
            "season_aggregates": self.get_season_aggregates(team_a, team_b),
            "venue_record": None,
        }

    def _compute_h2h(self, team_a: str, team_b: str) -> Optional[dict]:
        h2h_df = self._matches_between(team_a, team_b)
        if h2h_df.empty:
            return None

        match_rows = (
            h2h_df.groupby("match_id")
            .first()
            .reset_index()
            .sort_values("date", ascending=False)
        )
        recent = match_rows.head(5)

        per_team_wins = {team_a: 0, team_b: 0}
        last_5: list[dict] = []
        for _, row in recent.iterrows():
            winner = row.get("winner_id")
            if winner == team_a:
                per_team_wins[team_a] += 1
            elif winner == team_b:
                per_team_wins[team_b] += 1
            last_5.append(
                {
                    "year": int(row["year"]) if pd.notna(row.get("year")) else None,
                    "winner": winner or row.get("match_won_by") or "",
                    "margin": str(row.get("win_outcome", "")),
                    "venue": str(row.get("venue", "")),
                }
            )

        innings_totals = (
            h2h_df.groupby(["match_id", "innings"])["runs_total"].sum().reset_index()
        )
        avg_score = float(innings_totals["runs_total"].mean()) if not innings_totals.empty else 0.0

        return {
            "last_5": last_5,
            "form_guide": {
                team_a: self._team_form(team_a),
                team_b: self._team_form(team_b),
            },
            "per_team_wins": per_team_wins,
            "total_matches": int(len(match_rows)),
            "avg_score": round(avg_score, 1),
        }

    def _team_form(self, team_id: str) -> list[str]:
        if not self.is_loaded:
            return []
        names = self._names_for(team_id)
        if not names:
            return []
        df = self.df
        mask = df["batting_team"].isin(names) | df["bowling_team"].isin(names)
        matches = (
            df[mask]
            .groupby("match_id")
            .first()
            .reset_index()
            .sort_values("date", ascending=False)
            .head(5)
        )
        form: list[str] = []
        for _, row in matches.iterrows():
            winner = row.get("match_won_by")
            if pd.isna(winner):
                form.append("NR")
            elif winner in names:
                form.append("W")
            else:
                form.append("L")
        return form

    def get_season_aggregates(self, team_a: str, team_b: str) -> list[dict]:
        if not self.is_loaded:
            return []
        key = tuple(sorted([team_a, team_b]))
        if key in self._season_cache:
            return self._season_cache[key]

        h2h = self._matches_between(team_a, team_b)
        if h2h.empty:
            return []

        names_a = self._names_for(team_a)
        names_b = self._names_for(team_b)
        match_rows = h2h.groupby("match_id").first().reset_index()
        match_rows["year"] = pd.to_numeric(match_rows["year"], errors="coerce")
        aggregates: list[dict] = []
        for year, sub in match_rows.groupby("year"):
            if pd.isna(year):
                continue
            wins_a = int((sub["match_won_by"].isin(names_a)).sum())
            wins_b = int((sub["match_won_by"].isin(names_b)).sum())
            aggregates.append(
                {
                    "season": int(year),
                    "matches": int(len(sub)),
                    "team_a_wins": wins_a,
                    "team_b_wins": wins_b,
                }
            )
        aggregates.sort(key=lambda r: r["season"], reverse=True)
        self._season_cache[key] = aggregates
        return aggregates

    def get_venue_record(self, team_a: str, team_b: str, venue_name: str) -> Optional[dict]:
        if not self.is_loaded or not venue_name:
            return None
        key = (team_a, team_b, venue_name.lower())
        if key in self._venue_cache:
            return self._venue_cache[key]

        h2h = self._matches_between(team_a, team_b)
        if h2h.empty:
            return None
        venue_match = h2h["venue"].astype(str).str.lower().str.contains(venue_name.lower())
        h2h = h2h[venue_match]
        if h2h.empty:
            return None

        names_a = self._names_for(team_a)
        names_b = self._names_for(team_b)
        match_rows = h2h.groupby("match_id").first().reset_index()
        wins_a = int((match_rows["match_won_by"].isin(names_a)).sum())
        wins_b = int((match_rows["match_won_by"].isin(names_b)).sum())
        avg_score = float(
            h2h.groupby(["match_id", "innings"])["runs_total"].sum().mean()
        )

        record = {
            "venue": venue_name,
            "matches": int(len(match_rows)),
            "team_a_wins": wins_a,
            "team_b_wins": wins_b,
            "avg_score": round(avg_score, 1),
        }
        self._venue_cache[key] = record
        return record

    def get_batter_vs_bowler(
        self,
        batters: Iterable[str],
        bowlers: Iterable[str],
        limit: int = 5,
    ) -> list[dict]:
        """Return the top ``limit`` batter-vs-bowler matchups by balls faced.

        Names from the static roster (e.g. "Rohit Sharma") are mapped onto
        the CSV's "initial-plus-surname" form (e.g. "RG Sharma") via a
        per-CSV-name lookup table built lazily on first call.
        """
        if not self.is_loaded:
            return []
        bat_csv = self._resolve_csv_names(batters)
        bowl_csv = self._resolve_csv_names(bowlers)
        if not bat_csv or not bowl_csv:
            return []

        df = self.df
        sub = df[df["batter"].isin(bat_csv) & df["bowler"].isin(bowl_csv)]
        if sub.empty:
            return []

        grouped = (
            sub.groupby(["batter", "bowler"])
            .agg(
                balls=("ball_no", "count"),
                runs=("runs_batter", "sum"),
                dismissals=("wicket_kind", lambda s: s.notna().sum()),
            )
            .reset_index()
        )
        grouped["strike_rate"] = (grouped["runs"] / grouped["balls"]) * 100
        grouped = grouped.sort_values("balls", ascending=False).head(limit)
        return [
            {
                "batter": str(row.batter),
                "bowler": str(row.bowler),
                "balls": int(row.balls),
                "runs": int(row.runs),
                "dismissals": int(row.dismissals),
                "strike_rate": round(float(row.strike_rate), 1),
            }
            for row in grouped.itertuples(index=False)
        ]

    def _resolve_csv_names(self, names: Iterable[str]) -> set[str]:
        """Map roster names (full names) onto CSV ``batter``/``bowler`` strings.

        The CSV uses the cricinfo style ``"<initials> <surname>"`` (e.g.
        ``"RG Sharma"``, ``"MS Dhoni"``, ``"V Kohli"``). The static roster
        uses display names (``"Rohit Sharma"``, ``"MS Dhoni"``,
        ``"Virat Kohli"``). We bridge the two by indexing every CSV name
        once by surname and matching the supplied first-name initial, plus
        accepting an exact pass-through for cases where the static name
        already matches the CSV form.
        """
        if not isinstance(names, Iterable):
            return set()
        wanted = {n.strip() for n in names if isinstance(n, str) and n.strip()}
        if not wanted:
            return set()

        index = self._csv_name_index()
        resolved: set[str] = set()
        for raw in wanted:
            if raw in index["exact"]:
                resolved.add(raw)
                continue
            parts = raw.split()
            if len(parts) < 2:
                continue
            surname = parts[-1]
            initial = parts[0][0].upper()
            candidates = index["by_surname"].get(surname, [])
            best = None
            for csv_name in candidates:
                tokens = csv_name.split()
                if not tokens:
                    continue
                head = tokens[0]
                if head and head[0].upper() == initial:
                    if best is None or len(csv_name) < len(best):
                        best = csv_name
            if best is None and candidates:
                best = candidates[0]
            if best:
                resolved.add(best)
        return resolved

    def _csv_name_index(self) -> dict:
        """Build (and cache) a per-surname index of CSV batter/bowler names."""
        cached = getattr(self, "_name_index", None)
        if cached is not None:
            return cached
        df = self.df
        names: set[str] = set()
        for col in ("batter", "bowler"):
            names.update(s for s in df[col].dropna().unique() if isinstance(s, str))
        by_surname: dict[str, list[str]] = {}
        for name in names:
            tokens = name.split()
            if not tokens:
                continue
            by_surname.setdefault(tokens[-1], []).append(name)
        index = {"exact": names, "by_surname": by_surname}
        self._name_index = index
        return index
