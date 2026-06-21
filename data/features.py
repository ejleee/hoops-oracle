"""
Feature engineering: convert raw play-by-play CSVs (PlayByPlayV3 format) into
a labeled training dataset.

Each row represents one play-by-play event and contains:
  - score_differential   : scoreHome - scoreAway at that moment
  - seconds_remaining    : seconds left in the entire game
  - quarter              : current period (1-4, or 5+ for OT)
  - home_possession      : 1 if the acting player's location is 'h', else 0
  - home_fouls           : home team personal foul count so far
  - away_fouls           : away team personal foul count so far
  - home_win_rate        : 0.5 placeholder (season-to-date not available offline)
  - away_win_rate        : 0.5 placeholder
  - home_win             : 1 if the home team won the game (label)

PlayByPlayV3 column reference (relevant fields):
  clock        – ISO 8601 duration string, e.g. "PT11M42.00S"
  period       – integer period number
  scoreHome    – running home score string (empty until first score)
  scoreAway    – running away score string
  location     – "h" (home) or "a" (away); empty for non-team events
  actionType   – e.g. "Made Shot", "Missed Shot", "Foul", "Turnover", "Jump Ball"
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd

RAW_DIR = Path(__file__).parent / "raw"
OUTPUT_PATH = Path(__file__).parent / "training_data.csv"

SECONDS_PER_QUARTER = 12 * 60   # 720 s
SECONDS_PER_OT = 5 * 60         # 300 s
QUARTERS_IN_REGULATION = 4

# V3 actionType values that indicate a personal foul on the acting team
FOUL_ACTION_TYPES = {"Foul"}


def parse_clock_v3(clock_str: str, period: int) -> float:
    """Convert ISO 8601 duration (e.g. 'PT11M42.00S') + period to total game seconds remaining."""
    if not isinstance(clock_str, str):
        return 0.0

    match = re.match(r"PT(\d+)M([\d.]+)S", clock_str)
    if not match:
        return 0.0

    minutes = int(match.group(1))
    seconds = float(match.group(2))
    period_seconds_remaining = minutes * 60 + seconds

    if period <= QUARTERS_IN_REGULATION:
        full_quarters_remaining = QUARTERS_IN_REGULATION - period
        return full_quarters_remaining * SECONDS_PER_QUARTER + period_seconds_remaining
    else:
        # OT: only the remaining time in the current OT period
        return period_seconds_remaining


def safe_score(score_val) -> int:
    """Parse a score cell that may be an empty string or NaN."""
    try:
        return int(score_val)
    except (ValueError, TypeError):
        return 0


def process_game(pbp_df: pd.DataFrame, home_win: int) -> pd.DataFrame:
    """Extract one feature row per event for a single game."""
    rows = []
    home_fouls = 0
    away_fouls = 0
    last_home_score = 0
    last_away_score = 0
    last_possession = 1  # default to home

    for _, row in pbp_df.iterrows():
        period = int(row.get("period", 1))
        clock = parse_clock_v3(row.get("clock", "PT12M00.00S"), period)

        # scoreHome / scoreAway are cumulative; carry forward when empty
        h_score = safe_score(row.get("scoreHome"))
        a_score = safe_score(row.get("scoreAway"))
        if h_score or a_score:
            last_home_score = h_score
            last_away_score = a_score

        # Possession: V3 provides 'location' = 'h' or 'a' for team events
        location = row.get("location", "")
        if location == "h":
            last_possession = 1
        elif location == "a":
            last_possession = 0

        # Foul tracking
        action_type = row.get("actionType", "")
        if action_type in FOUL_ACTION_TYPES:
            if location == "h":
                home_fouls += 1
            elif location == "a":
                away_fouls += 1

        rows.append({
            "score_differential": last_home_score - last_away_score,
            "seconds_remaining": clock,
            "quarter": period,
            "home_possession": last_possession,
            "home_fouls": home_fouls,
            "away_fouls": away_fouls,
            "home_win_rate": 0.5,   # placeholder; enrich later if desired
            "away_win_rate": 0.5,
            "home_win": home_win,
        })

    return pd.DataFrame(rows)


def determine_home_win(pbp_df: pd.DataFrame) -> int | None:
    """Return 1 if home won, 0 if away won, None if undetermined."""
    scored = pbp_df[pbp_df["scoreHome"].apply(lambda v: safe_score(v) > 0) |
                    pbp_df["scoreAway"].apply(lambda v: safe_score(v) > 0)]
    if scored.empty:
        return None

    final_row = scored.iloc[-1]
    home_final = safe_score(final_row["scoreHome"])
    away_final = safe_score(final_row["scoreAway"])

    if home_final == away_final:
        return None  # shouldn't happen in a completed game
    return 1 if home_final > away_final else 0


def build_dataset() -> pd.DataFrame:
    csv_files = sorted(RAW_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSVs found in {RAW_DIR}. Run data/collect.py first.")

    print(f"Processing {len(csv_files)} game files...")
    all_frames = []

    for idx, csv_path in enumerate(csv_files):
        pbp_df = pd.read_csv(csv_path, low_memory=False)

        if pbp_df.empty:
            continue

        home_win = determine_home_win(pbp_df)
        if home_win is None:
            continue

        game_features = process_game(pbp_df, home_win)
        if not game_features.empty:
            all_frames.append(game_features)

        if (idx + 1) % 100 == 0:
            print(f"  {idx + 1}/{len(csv_files)} games processed")

    if not all_frames:
        raise RuntimeError("No usable game data found.")

    dataset = pd.concat(all_frames, ignore_index=True)
    dataset.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved {len(dataset):,} rows to {OUTPUT_PATH}")
    return dataset


if __name__ == "__main__":
    build_dataset()
