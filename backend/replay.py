"""
Replay a historical game CSV through the live dashboard for testing.

Reads a raw play-by-play CSV from data/raw/, reconstructs game state
play-by-play, runs model inference, and emits game_update events via
WebSocket exactly like the live poller does — but on a timer so you
can watch the dashboard animate in real time.

Usage:
    python backend/replay.py                         # picks a random game
    python backend/replay.py 0022000001              # specific game ID
    python backend/replay.py 0022000001 --speed 2   # 2x speed (default 1x)

Keep the backend (flask run --port 5001) running in another terminal.
"""

import argparse
import re
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import socketio

DATA_DIR = Path(__file__).parent.parent / "data" / "raw"
PLAY_INTERVAL = 1.0   # seconds between plays at 1x speed
SOCKET_URL = "http://localhost:5001"

SECONDS_PER_QUARTER = 12 * 60
QUARTERS_IN_REGULATION = 4


def parse_clock(clock_str: str, period: int) -> float:
    if not isinstance(clock_str, str):
        return 0.0
    match = re.match(r"PT(\d+)M([\d.]+)S", clock_str)
    if not match:
        return 0.0
    mins = int(match.group(1))
    secs = float(match.group(2))
    period_remaining = mins * 60 + secs
    if period <= QUARTERS_IN_REGULATION:
        return (QUARTERS_IN_REGULATION - period) * SECONDS_PER_QUARTER + period_remaining
    return period_remaining


def safe_int(val, default: int = 0) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def build_game_states(df: pd.DataFrame) -> list[dict]:
    """Convert raw play-by-play DataFrame into a list of game state dicts."""
    # Identify home team: location == 'h' most frequently
    home_tricode = None
    away_tricode = None
    loc_h = df[df["location"] == "h"]["teamTricode"].dropna()
    loc_a = df[df["location"] == "a"]["teamTricode"].dropna()
    if not loc_h.empty:
        home_tricode = loc_h.mode()[0]
    if not loc_a.empty:
        away_tricode = loc_a.mode()[0]

    home_tricode = home_tricode or "HOME"
    away_tricode = away_tricode or "AWAY"

    home_team_ids = df[df["teamTricode"] == home_tricode]["teamId"].dropna()
    home_team_id = int(home_team_ids.mode()[0]) if not home_team_ids.empty else -1

    states = []
    home_fouls = 0
    away_fouls = 0
    last_home_score = 0
    last_away_score = 0
    last_possession = 1
    recent_plays: list[dict] = []

    for _, row in df.iterrows():
        period = safe_int(row.get("period"), 1)
        clock_str = row.get("clock", "PT12M00.00S")
        seconds_remaining = parse_clock(clock_str, period)

        h = safe_int(row.get("scoreHome"))
        a = safe_int(row.get("scoreAway"))
        if h or a:
            last_home_score = h
            last_away_score = a

        location = row.get("location", "")
        if location == "h":
            last_possession = 1
        elif location == "a":
            last_possession = 0

        action_type = str(row.get("actionType", "")).lower()
        if "foul" in action_type:
            if location == "h":
                home_fouls += 1
            elif location == "a":
                away_fouls += 1

        desc = str(row.get("description", "")).strip()
        if desc and desc not in ("nan", ""):
            recent_plays.append({
                "clock": clock_str,
                "period": period,
                "description": desc,
                "teamTricode": row.get("teamTricode", ""),
            })
            if len(recent_plays) > 8:
                recent_plays.pop(0)

        states.append({
            # Model features
            "score_differential": last_home_score - last_away_score,
            "seconds_remaining": seconds_remaining,
            "quarter": period,
            "home_possession": last_possession,
            "home_fouls": home_fouls,
            "away_fouls": away_fouls,
            "home_win_rate": 0.5,
            "away_win_rate": 0.5,
            # Display
            "game_id": "replay",
            "home_team": home_tricode,
            "home_team_name": home_tricode,
            "home_team_city": "",
            "away_team": away_tricode,
            "away_team_name": away_tricode,
            "away_team_city": "",
            "home_score": last_home_score,
            "away_score": last_away_score,
            "clock": clock_str,
            "recent_plays": list(recent_plays),
        })

    return states


def pick_game(game_id: str | None) -> Path:
    csvs = list(DATA_DIR.glob("*.csv"))
    if not csvs:
        print(f"No CSVs found in {DATA_DIR}. Run data/collect.py first.")
        sys.exit(1)

    if game_id:
        path = DATA_DIR / f"{game_id}.csv"
        if not path.exists():
            print(f"Game {game_id} not found in {DATA_DIR}")
            sys.exit(1)
        return path

    return random.choice(csvs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("game_id", nargs="?", help="Game ID to replay (e.g. 0022000001)")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier")
    args = parser.parse_args()

    csv_path = pick_game(args.game_id)
    game_id = csv_path.stem
    print(f"Replaying game {game_id} at {args.speed}x speed...")

    df = pd.read_csv(csv_path, low_memory=False)
    states = build_game_states(df)
    print(f"  {len(states)} plays to replay.")

    sio = socketio.SimpleClient()
    sio.connect(SOCKET_URL, namespace="/live")
    print(f"  Connected to {SOCKET_URL}/live\n")

    interval = PLAY_INTERVAL / args.speed

    for i, state in enumerate(states):
        # Emit as game_state so the server runs model inference and replies with home_win_prob
        sio.emit("game_state", state)

        # Print progress every 50 plays
        if (i + 1) % 50 == 0:
            diff = state["score_differential"]
            secs = int(state["seconds_remaining"])
            print(f"  Play {i+1}/{len(states)} | Q{state['quarter']} | {state['away_team']} {state['away_score']} - {state['home_team']} {state['home_score']} | {secs}s left")

        time.sleep(interval)

    print("\nReplay complete.")
    sio.disconnect()


if __name__ == "__main__":
    main()
