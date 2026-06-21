"""
Collect historical NBA play-by-play data via nba_api and save to data/raw/.

Pulls seasons 2020-21 through 2023-24. For each game, saves the play-by-play
log as a CSV so feature engineering can run offline without hitting the API again.
"""

import time
import os
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder, playbyplayv3
from nba_api.stats.static import teams

RAW_DIR = Path(__file__).parent / "raw"
SEASONS = ["2020-21", "2021-22", "2022-23", "2023-24"]
# nba_api is rate-limited; 0.6 s between requests stays well under the limit
REQUEST_DELAY_SECONDS = 0.6


def fetch_game_ids(season: str) -> list[str]:
    """Return all regular-season game IDs for the given season string."""
    finder = leaguegamefinder.LeagueGameFinder(
        season_nullable=season,
        season_type_nullable="Regular Season",
    )
    games_df = finder.get_data_frames()[0]
    # Each game appears twice (home + away), so deduplicate
    return games_df["GAME_ID"].unique().tolist()


def fetch_play_by_play(game_id: str) -> pd.DataFrame:
    """Return the play-by-play DataFrame for a single game."""
    pbp = playbyplayv3.PlayByPlayV3(game_id=game_id)
    return pbp.get_data_frames()[0]


def save_game(game_id: str, df: pd.DataFrame) -> None:
    path = RAW_DIR / f"{game_id}.csv"
    df.to_csv(path, index=False)


def already_collected(game_id: str) -> bool:
    return (RAW_DIR / f"{game_id}.csv").exists()


def collect_all() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for season in SEASONS:
        print(f"Fetching game IDs for {season}...")
        game_ids = fetch_game_ids(season)
        time.sleep(REQUEST_DELAY_SECONDS)
        print(f"  Found {len(game_ids)} games.")

        for idx, game_id in enumerate(game_ids):
            if already_collected(game_id):
                continue

            try:
                pbp_df = fetch_play_by_play(game_id)
                save_game(game_id, pbp_df)
            except Exception as exc:
                print(f"  [WARN] Failed to fetch {game_id}: {exc}")

            # Progress log every 50 games
            if (idx + 1) % 50 == 0:
                print(f"  Processed {idx + 1}/{len(game_ids)} games in {season}")

            time.sleep(REQUEST_DELAY_SECONDS)

        print(f"  Done with {season}.")


if __name__ == "__main__":
    collect_all()
