"""Feature builders for the IPL match-level models.

Two specialised models are trained against shared feature plumbing:

* **first-innings model**  — predicts the total a team will set when
  batting first. Consumes :data:`FEATURE_COLUMNS`.
* **chase model**          — predicts the chase outcome conditional on
  the target. Consumes :data:`CHASE_FEATURE_COLUMNS` (the first-innings
  set plus ``target_score``).

Both models reuse the same XI / form / H2H / venue features. The chase
model adds ``target_score`` so it can condition on what's needed.

A ``xi_matchup_strike_rate`` feature aggregates historical batter-vs-
bowler matchups for the supplied playing XIs. It is computed at training
time from the full CSV (slight leakage tolerated; the matchup
distribution moves slowly across seasons) and at inference time via the
:class:`IPLDataManager` ball-by-ball index.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional

import numpy as np
import pandas as pd

from ipl_data import (
    PITCH_TYPES,
    VENUES,
    WEATHER_TYPES,
    get_pitch,
    get_players,
    get_team,
    get_venue,
    get_weather,
)

logger = logging.getLogger("ipl.features")

FEATURE_COLUMNS: List[str] = [
    "batting_team",
    "bowling_team",
    "venue",
    "toss_won_by_batting",
    "toss_decision_bat",
    "home_advantage",
    "batting_recent_form_runs",
    "bowling_recent_form_conceded",
    "batting_recent_win_rate",
    "bowling_recent_win_rate",
    "h2h_avg_score",
    "h2h_batting_wins_share",
    "bat_xi_avg",
    "bat_xi_strike_rate",
    "bowl_xi_economy",
    "bowl_xi_wickets",
    "xi_overseas_count",
    "xi_matchup_strike_rate",
    "venue_avg_first_innings",
    "pitch_modifier",
    "weather_modifier",
]

CHASE_FEATURE_COLUMNS: List[str] = FEATURE_COLUMNS + ["target_score"]

CATEGORICAL_FEATURES: List[str] = ["batting_team", "bowling_team", "venue"]
NUMERIC_FEATURES: List[str] = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_FEATURES]
CHASE_NUMERIC_FEATURES: List[str] = NUMERIC_FEATURES + ["target_score"]

ROLLING_WINDOW = 5
H2H_LOOKBACK = 10
DEFAULT_MATCHUP_STRIKE_RATE = 135.0

INTERNAL_TEAM_TO_CSV: dict[str, list[str]] = {
    "mi":   ["Mumbai Indians"],
    "csk":  ["Chennai Super Kings"],
    "rcb":  ["Royal Challengers Bangalore", "Royal Challengers Bengaluru"],
    "kkr":  ["Kolkata Knight Riders"],
    "dc":   ["Delhi Capitals", "Delhi Daredevils"],
    "pbks": ["Punjab Kings", "Kings XI Punjab"],
    "rr":   ["Rajasthan Royals"],
    "srh":  ["Sunrisers Hyderabad", "Deccan Chargers"],
    "gt":   ["Gujarat Titans", "Gujarat Lions"],
    "lsg":  ["Lucknow Super Giants",
             "Rising Pune Supergiant", "Rising Pune Supergiants",
             "Pune Warriors", "Kochi Tuskers Kerala"],
}

CSV_TEAM_TO_INTERNAL: dict[str, str] = {
    csv_name: internal
    for internal, names in INTERNAL_TEAM_TO_CSV.items()
    for csv_name in names
}

VENUE_NAME_TO_INTERNAL: dict[str, str] = {}
for v in VENUES:
    VENUE_NAME_TO_INTERNAL[v["name"].lower()] = v["id"]
    short = v["name"].split(",")[0].lower()
    VENUE_NAME_TO_INTERNAL.setdefault(short, v["id"])


def _normalise_team(name: object) -> Optional[str]:
    if not isinstance(name, str):
        return None
    return CSV_TEAM_TO_INTERNAL.get(name.strip())


def _normalise_venue(name: object, city: object = "") -> Optional[str]:
    if not isinstance(name, str):
        return None
    cleaned = name.strip().lower()
    if cleaned in VENUE_NAME_TO_INTERNAL:
        return VENUE_NAME_TO_INTERNAL[cleaned]
    head = cleaned.split(",")[0].strip()
    if head in VENUE_NAME_TO_INTERNAL:
        return VENUE_NAME_TO_INTERNAL[head]
    for static in VENUES:
        ref = static["name"].lower()
        if head in ref or ref.split(",")[0] in head:
            if isinstance(city, str) and city.strip().lower() == static["city"].lower():
                return static["id"]
    return None


# ---------------------------------------------------------------------------
# Squad-XI aggregates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class XIAggregate:
    bat_avg: float
    strike_rate: float
    economy: float
    wickets: int
    overseas_count: int


def aggregate_xi(team_id: str, players: Optional[Iterable[str]] = None) -> XIAggregate:
    roster = get_players(team_id) or []
    if not roster:
        return XIAggregate(0.0, 0.0, 0.0, 0, 0)

    lookup = {p["name"].lower(): p for p in roster}
    if players:
        chosen = [lookup[name.lower()] for name in players if name.lower() in lookup]
        if not chosen:
            chosen = roster
    else:
        chosen = roster

    bat_avgs = [p["batting_avg"] for p in chosen if p["batting_avg"] > 0]
    strike_rates = [p["strike_rate"] for p in chosen if p["strike_rate"] > 0]
    economies = [p["economy"] for p in chosen if p["economy"] > 0]
    wickets = sum(int(p["wickets"]) for p in chosen)
    overseas = sum(1 for p in chosen if p.get("country", "IND") != "IND")

    return XIAggregate(
        bat_avg=float(np.mean(bat_avgs)) if bat_avgs else 0.0,
        strike_rate=float(np.mean(strike_rates)) if strike_rates else 0.0,
        economy=float(np.mean(economies)) if economies else 0.0,
        wickets=int(wickets),
        overseas_count=int(overseas),
    )


# ---------------------------------------------------------------------------
# Pitch / weather modifier lookups
# ---------------------------------------------------------------------------


def _pitch_modifier(pitch_id: Optional[str]) -> int:
    pitch = get_pitch(pitch_id) if pitch_id else None
    return int(pitch["score_modifier"]) if pitch else 0


def _weather_modifier(weather_id: Optional[str]) -> int:
    weather = get_weather(weather_id) if weather_id else None
    return int(weather["score_modifier"]) if weather else 0


# ---------------------------------------------------------------------------
# Matchup index (batter, bowler) → (balls, runs)
# ---------------------------------------------------------------------------


MatchupIndex = dict[tuple[str, str], tuple[int, int]]


def build_matchup_index(raw: pd.DataFrame) -> MatchupIndex:
    """Build a (batter, bowler) → (balls, runs) index from the CSV.

    Used by both the training-time feature builder and the live request
    feature builder so the feature has identical semantics in both places.
    """
    if raw is None or raw.empty:
        return {}
    sub = raw[["batter", "bowler", "runs_batter"]].dropna(subset=["batter", "bowler"])
    if sub.empty:
        return {}
    grouped = (
        sub.groupby(["batter", "bowler"])
        .agg(balls=("runs_batter", "count"), runs=("runs_batter", "sum"))
        .reset_index()
    )
    return {
        (str(r.batter), str(r.bowler)): (int(r.balls), int(r.runs))
        for r in grouped.itertuples(index=False)
    }


def matchup_strike_rate_from_index(
    index: MatchupIndex,
    batters: Iterable[str],
    bowlers: Iterable[str],
) -> float:
    """Average strike rate across batter×bowler pairs in ``index``.

    Each (batter, bowler) cell contributes its own runs/balls; the
    aggregate is total runs across the matrix divided by total balls,
    multiplied by 100. Returns :data:`DEFAULT_MATCHUP_STRIKE_RATE` when
    no pair has any history together.
    """
    bat_set = {b for b in batters if isinstance(b, str) and b}
    bowl_set = {b for b in bowlers if isinstance(b, str) and b}
    if not bat_set or not bowl_set or not index:
        return DEFAULT_MATCHUP_STRIKE_RATE
    total_balls = 0
    total_runs = 0
    for batter in bat_set:
        for bowler in bowl_set:
            balls, runs = index.get((batter, bowler), (0, 0))
            total_balls += balls
            total_runs += runs
    if total_balls == 0:
        return DEFAULT_MATCHUP_STRIKE_RATE
    return float((total_runs / total_balls) * 100)


def csv_xi_for_innings(raw: pd.DataFrame, match_id: int, innings: int) -> tuple[list[str], list[str]]:
    """Extract CSV-style batter / bowler XIs for a single innings."""
    sub = raw[(raw["match_id"] == match_id) & (raw["innings"] == innings)]
    if sub.empty:
        return [], []
    batters = (
        sub.groupby("batter")["runs_batter"]
        .count()
        .sort_values(ascending=False)
        .head(11)
        .index.tolist()
    )
    bowlers = (
        sub.groupby("bowler")["runs_batter"]
        .count()
        .sort_values(ascending=False)
        .head(11)
        .index.tolist()
    )
    return [str(b) for b in batters], [str(b) for b in bowlers]


# ---------------------------------------------------------------------------
# Training dataset builder
# ---------------------------------------------------------------------------


def build_match_dataset(raw: pd.DataFrame, matchup_index: Optional[MatchupIndex] = None) -> pd.DataFrame:
    """Aggregate the ball-by-ball CSV into per-innings feature rows.

    The output dataframe carries every column in :data:`FEATURE_COLUMNS`,
    plus ``target_score`` (used by the chase model), and three target
    columns: ``runs_total`` (regression target), ``batting_won``
    (classification target), and ``date`` (for chronological splits).
    """
    if raw is None or raw.empty:
        raise ValueError("Empty CSV dataframe")

    df = raw.copy()
    df["batting_team_id"] = df["batting_team"].map(_normalise_team)
    df["bowling_team_id"] = df["bowling_team"].map(_normalise_team)
    df["venue_id"] = df.apply(
        lambda r: _normalise_venue(r.get("venue"), r.get("city", "")), axis=1
    )
    df["winner_id"] = df["match_won_by"].map(_normalise_team)

    df = df.dropna(subset=["batting_team_id", "bowling_team_id", "venue_id"])

    grouped = (
        df.groupby(["match_id", "innings"], sort=False)
        .agg(
            runs_total=("runs_total", "sum"),
            max_over=("over", "max"),
            batting_team=("batting_team_id", "first"),
            bowling_team=("bowling_team_id", "first"),
            venue=("venue_id", "first"),
            toss_winner=("toss_winner", "first"),
            toss_decision=("toss_decision", "first"),
            winner=("winner_id", "first"),
            date=("date", "first"),
        )
        .reset_index()
    )
    grouped = grouped[grouped["max_over"] >= 18].drop(columns=["max_over"])

    grouped["date"] = pd.to_datetime(grouped["date"], errors="coerce")
    grouped = grouped.sort_values("date").reset_index(drop=True)

    grouped["toss_won_by_batting"] = (
        grouped["toss_winner"].map(_normalise_team) == grouped["batting_team"]
    ).astype(int)
    grouped["toss_decision_bat"] = (
        grouped["toss_decision"].fillna("").str.lower().eq("bat").astype(int)
    )
    grouped["home_advantage"] = grouped.apply(_home_advantage_row, axis=1)
    grouped["batting_won"] = (
        grouped["winner"].fillna("") == grouped["batting_team"]
    ).astype(int)

    grouped = _attach_form_features(grouped)
    grouped = _attach_h2h_features(grouped)
    grouped = _attach_static_features(grouped)
    grouped = _attach_matchup_feature(grouped, raw, matchup_index)
    grouped = _attach_target_score(grouped)

    keep = (
        FEATURE_COLUMNS
        + ["target_score", "runs_total", "batting_won", "date", "match_id", "innings"]
    )
    return grouped[keep].dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)


def _home_advantage_row(row: pd.Series) -> int:
    team = get_team(row["batting_team"])
    if not team:
        return 0
    return int(team.get("home_venue_id") == row["venue"])


def _attach_form_features(df: pd.DataFrame) -> pd.DataFrame:
    bat = (
        df.groupby("batting_team")
        .apply(
            lambda g: g.assign(
                batting_recent_form_runs=g["runs_total"]
                .shift(1)
                .rolling(ROLLING_WINDOW, min_periods=1)
                .mean(),
                batting_recent_win_rate=g["batting_won"]
                .shift(1)
                .rolling(ROLLING_WINDOW, min_periods=1)
                .mean(),
            )
        )
        .reset_index(drop=True)
    )
    bowl_concede = (
        bat.groupby("bowling_team")
        .apply(
            lambda g: g.assign(
                bowling_recent_form_conceded=g["runs_total"]
                .shift(1)
                .rolling(ROLLING_WINDOW, min_periods=1)
                .mean(),
                bowling_recent_win_rate=(1 - g["batting_won"])
                .shift(1)
                .rolling(ROLLING_WINDOW, min_periods=1)
                .mean(),
            )
        )
        .reset_index(drop=True)
    )
    bowl_concede["batting_recent_form_runs"] = bowl_concede["batting_recent_form_runs"].fillna(
        bowl_concede["runs_total"].mean()
    )
    bowl_concede["bowling_recent_form_conceded"] = bowl_concede["bowling_recent_form_conceded"].fillna(
        bowl_concede["runs_total"].mean()
    )
    bowl_concede["batting_recent_win_rate"] = bowl_concede["batting_recent_win_rate"].fillna(0.5)
    bowl_concede["bowling_recent_win_rate"] = bowl_concede["bowling_recent_win_rate"].fillna(0.5)
    return bowl_concede.sort_values(["date", "match_id", "innings"]).reset_index(drop=True)


def _attach_h2h_features(df: pd.DataFrame) -> pd.DataFrame:
    avg_score: List[float] = []
    win_share: List[float] = []
    history_index: dict[tuple, list[tuple[float, str]]] = {}
    for _, row in df.iterrows():
        key = tuple(sorted([row["batting_team"], row["bowling_team"]]))
        prev = history_index.get(key, [])
        recent = prev[-H2H_LOOKBACK:]
        if recent:
            avg_score.append(float(np.mean([s for s, _ in recent])))
            win_share.append(
                float(np.mean([1 if w == row["batting_team"] else 0 for _, w in recent]))
            )
        else:
            avg_score.append(np.nan)
            win_share.append(0.5)
        prev.append((row["runs_total"], row["winner"] if isinstance(row["winner"], str) else ""))
        history_index[key] = prev
    df = df.copy()
    df["h2h_avg_score"] = avg_score
    df["h2h_batting_wins_share"] = win_share
    df["h2h_avg_score"] = df["h2h_avg_score"].fillna(df["runs_total"].mean())
    return df


def _attach_static_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["venue_avg_first_innings"] = df["venue"].map(
        lambda vid: (get_venue(vid) or {}).get("avg_first_innings", 170)
    )
    df["pitch_modifier"] = df["venue"].map(
        lambda vid: _pitch_modifier((get_venue(vid) or {}).get("default_pitch"))
    )
    df["weather_modifier"] = 0
    bat_xi = df["batting_team"].map(lambda tid: aggregate_xi(tid))
    bowl_xi = df["bowling_team"].map(lambda tid: aggregate_xi(tid))
    df["bat_xi_avg"] = bat_xi.map(lambda x: x.bat_avg)
    df["bat_xi_strike_rate"] = bat_xi.map(lambda x: x.strike_rate)
    df["bowl_xi_economy"] = bowl_xi.map(lambda x: x.economy)
    df["bowl_xi_wickets"] = bowl_xi.map(lambda x: x.wickets)
    df["xi_overseas_count"] = bat_xi.map(lambda x: x.overseas_count) + bowl_xi.map(
        lambda x: x.overseas_count
    )
    return df


def _attach_matchup_feature(
    df: pd.DataFrame,
    raw: pd.DataFrame,
    matchup_index: Optional[MatchupIndex],
) -> pd.DataFrame:
    """Attach a leakage-free ``xi_matchup_strike_rate`` feature.

    For every (match_id, innings) row the feature is computed against an
    aggregate that only covers innings strictly **before** that row in
    chronological order. The cumulative aggregate is built in a single
    walk so the overall cost is ``O(rows + features)`` rather than
    ``O(rows × matches)``.
    """
    df = df.copy()
    if raw is None or raw.empty:
        df["xi_matchup_strike_rate"] = DEFAULT_MATCHUP_STRIKE_RATE
        return df

    raw_sorted = raw.copy()
    raw_sorted["_date"] = pd.to_datetime(raw_sorted.get("date"), errors="coerce")
    raw_sorted = raw_sorted.sort_values(["_date", "match_id", "innings", "over", "ball"])
    raw_groups = {
        (int(mid), int(inn)): grp.dropna(subset=["batter", "bowler"])
        for (mid, inn), grp in raw_sorted.groupby(["match_id", "innings"], sort=False)
    }

    seen_order: list[tuple[int, int]] = []
    seen_dates: list[tuple[pd.Timestamp, int, int]] = []
    for (mid, inn), grp in raw_sorted.groupby(["match_id", "innings"], sort=False):
        innings_date = pd.to_datetime(grp["_date"].iloc[0], errors="coerce")
        seen_dates.append((innings_date, int(mid), int(inn)))
    seen_dates.sort(key=lambda r: (pd.Timestamp.max if pd.isna(r[0]) else r[0], r[1], r[2]))
    seen_order = [(mid, inn) for _, mid, inn in seen_dates]

    snapshot: dict[tuple[int, int], MatchupIndex] = {}
    running: dict[tuple[str, str], list[int]] = {}
    for mid, inn in seen_order:
        snapshot[(mid, inn)] = {k: (v[0], v[1]) for k, v in running.items()}
        grp = raw_groups.get((mid, inn))
        if grp is None or grp.empty:
            continue
        for batter, bowler, runs_batter in zip(
            grp["batter"], grp["bowler"], grp["runs_batter"]
        ):
            cell = running.get((str(batter), str(bowler)))
            if cell is None:
                running[(str(batter), str(bowler))] = [1, int(runs_batter)]
            else:
                cell[0] += 1
                cell[1] += int(runs_batter)

    rates: list[float] = []
    for _, row in df.iterrows():
        snap = snapshot.get((int(row["match_id"]), int(row["innings"])), {})
        batters, bowlers = csv_xi_for_innings(raw, int(row["match_id"]), int(row["innings"]))
        rates.append(matchup_strike_rate_from_index(snap, batters, bowlers))
    df["xi_matchup_strike_rate"] = rates
    return df


def _attach_target_score(df: pd.DataFrame) -> pd.DataFrame:
    """For chase rows (innings == 2), copy the first-innings runs as target."""
    df = df.copy()
    pivot = df.pivot_table(
        index="match_id", columns="innings", values="runs_total", aggfunc="first"
    )
    target_lookup = pivot.get(1, pd.Series(dtype=float)).to_dict()
    df["target_score"] = df.apply(
        lambda r: float(target_lookup.get(r["match_id"], np.nan)) if r["innings"] == 2 else 0.0,
        axis=1,
    )
    return df


# ---------------------------------------------------------------------------
# Live request → feature frame
# ---------------------------------------------------------------------------


@dataclass
class HistoricalContext:
    team_form_runs: dict[str, float] = field(default_factory=dict)
    team_form_win_rate: dict[str, float] = field(default_factory=dict)
    team_concede_runs: dict[str, float] = field(default_factory=dict)
    team_bowl_win_rate: dict[str, float] = field(default_factory=dict)
    h2h_avg_score: dict[tuple[str, str], float] = field(default_factory=dict)
    h2h_batting_wins_share: dict[tuple[str, str], float] = field(default_factory=dict)
    overall_avg_score: float = 165.0


def empty_context() -> HistoricalContext:
    return HistoricalContext()


MatchupResolver = Callable[[Iterable[str], Iterable[str]], float]


def build_request_features(
    *,
    batting_team: str,
    bowling_team: str,
    venue: str,
    toss_winner: str,
    pitch: str,
    weather: str,
    playing_xi_a: list[str],
    playing_xi_b: list[str],
    team_a: str,
    team_b: str,
    context: HistoricalContext,
    matchup_resolver: Optional[MatchupResolver] = None,
    target_score: Optional[float] = None,
) -> pd.DataFrame:
    """Build a 1-row feature dataframe.

    When ``target_score`` is supplied, the result carries the chase-model
    feature set (:data:`CHASE_FEATURE_COLUMNS`). Otherwise it carries
    :data:`FEATURE_COLUMNS`.
    """
    bat_xi = playing_xi_a if batting_team == team_a else playing_xi_b
    bowl_xi = playing_xi_b if batting_team == team_a else playing_xi_a

    bat_aggr = aggregate_xi(batting_team, bat_xi)
    bowl_aggr = aggregate_xi(bowling_team, bowl_xi)

    bat_team = get_team(batting_team) or {}
    venue_record = get_venue(venue) or {}

    pair = tuple(sorted([batting_team, bowling_team]))
    matchup_rate = (
        float(matchup_resolver(bat_xi, bowl_xi))
        if matchup_resolver
        else DEFAULT_MATCHUP_STRIKE_RATE
    )

    row = {
        "batting_team": batting_team,
        "bowling_team": bowling_team,
        "venue": venue,
        "toss_won_by_batting": int(toss_winner == batting_team),
        "toss_decision_bat": int(toss_winner == batting_team),
        "home_advantage": int(bat_team.get("home_venue_id") == venue),
        "batting_recent_form_runs": context.team_form_runs.get(
            batting_team, context.overall_avg_score
        ),
        "bowling_recent_form_conceded": context.team_concede_runs.get(
            bowling_team, context.overall_avg_score
        ),
        "batting_recent_win_rate": context.team_form_win_rate.get(batting_team, 0.5),
        "bowling_recent_win_rate": context.team_bowl_win_rate.get(bowling_team, 0.5),
        "h2h_avg_score": context.h2h_avg_score.get(pair, context.overall_avg_score),
        "h2h_batting_wins_share": context.h2h_batting_wins_share.get(pair, 0.5),
        "bat_xi_avg": bat_aggr.bat_avg,
        "bat_xi_strike_rate": bat_aggr.strike_rate,
        "bowl_xi_economy": bowl_aggr.economy,
        "bowl_xi_wickets": bowl_aggr.wickets,
        "xi_overseas_count": bat_aggr.overseas_count + bowl_aggr.overseas_count,
        "xi_matchup_strike_rate": matchup_rate,
        "venue_avg_first_innings": venue_record.get("avg_first_innings", 170),
        "pitch_modifier": _pitch_modifier(pitch),
        "weather_modifier": _weather_modifier(weather),
    }

    if target_score is not None:
        row["target_score"] = float(target_score)
        return pd.DataFrame([row], columns=CHASE_FEATURE_COLUMNS)
    return pd.DataFrame([row], columns=FEATURE_COLUMNS)


def context_from_dataset(dataset: pd.DataFrame) -> HistoricalContext:
    if dataset is None or dataset.empty:
        return empty_context()

    overall = float(dataset["runs_total"].mean())
    form_runs: dict[str, float] = {}
    form_win: dict[str, float] = {}
    concede_runs: dict[str, float] = {}
    bowl_win: dict[str, float] = {}

    for tid, sub in dataset.groupby("batting_team"):
        last = sub.tail(ROLLING_WINDOW)
        form_runs[str(tid)] = float(last["runs_total"].mean())
        form_win[str(tid)] = float(last["batting_won"].mean())

    for tid, sub in dataset.groupby("bowling_team"):
        last = sub.tail(ROLLING_WINDOW)
        concede_runs[str(tid)] = float(last["runs_total"].mean())
        bowl_win[str(tid)] = float(1 - last["batting_won"].mean())

    h2h_avg: dict[tuple[str, str], float] = {}
    h2h_share: dict[tuple[str, str], float] = {}
    pair_groups = dataset.copy()
    pair_groups["pair"] = pair_groups.apply(
        lambda r: tuple(sorted([r["batting_team"], r["bowling_team"]])), axis=1
    )
    for pair, sub in pair_groups.groupby("pair"):
        last = sub.tail(H2H_LOOKBACK)
        h2h_avg[pair] = float(last["runs_total"].mean())
        h2h_share[pair] = float(last["batting_won"].mean())

    return HistoricalContext(
        team_form_runs=form_runs,
        team_form_win_rate=form_win,
        team_concede_runs=concede_runs,
        team_bowl_win_rate=bowl_win,
        h2h_avg_score=h2h_avg,
        h2h_batting_wins_share=h2h_share,
        overall_avg_score=overall,
    )


__all__ = [
    "FEATURE_COLUMNS",
    "CHASE_FEATURE_COLUMNS",
    "CATEGORICAL_FEATURES",
    "NUMERIC_FEATURES",
    "CHASE_NUMERIC_FEATURES",
    "DEFAULT_MATCHUP_STRIKE_RATE",
    "MatchupIndex",
    "MatchupResolver",
    "HistoricalContext",
    "XIAggregate",
    "aggregate_xi",
    "build_match_dataset",
    "build_matchup_index",
    "build_request_features",
    "context_from_dataset",
    "csv_xi_for_innings",
    "empty_context",
    "matchup_strike_rate_from_index",
    "INTERNAL_TEAM_TO_CSV",
    "CSV_TEAM_TO_INTERNAL",
]
