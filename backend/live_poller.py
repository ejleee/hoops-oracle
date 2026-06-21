"""
Background thread that polls NBA live endpoints every POLL_INTERVAL seconds,
extracts model features, runs inference, and emits game_update via SocketIO.

Live NBA API endpoints used:
  - nba_api.live.endpoints.scoreboard  → find today's live games
  - nba_api.live.endpoints.playbyplay  → recent plays + possession
  - nba_api.live.endpoints.boxscore    → fouls, scores, team names
"""

import json
import logging
import re
import threading
import time
import urllib.request
from typing import Callable

logger = logging.getLogger("hoops_oracle.poller")

import numpy as np
import torch


NBA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer': 'https://www.nba.com/',
    'Origin': 'https://www.nba.com',
}
SCOREBOARD_URL = 'https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json'
BOXSCORE_URL   = 'https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json'
PLAYBYPLAY_URL = 'https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json'


_GAME_ID_RE = re.compile(r"^[0-9]{10}$")   # NBA game IDs are exactly 10 digits

def _sanitize_game_id(game_id: str) -> str:
    """Reject any game_id that isn't exactly 10 digits — prevents URL injection."""
    if not _GAME_ID_RE.match(str(game_id)):
        raise ValueError(f"Invalid game_id format: {game_id!r}")
    return game_id


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=NBA_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

POLL_INTERVAL = 5  # seconds between NBA API calls
SECONDS_PER_QUARTER = 12 * 60
QUARTERS_IN_REGULATION = 4


def parse_live_clock(clock_str: str, period: int) -> float:
    """'PT05M30.00S' + period → total seconds remaining in game."""
    if not clock_str:
        return 0.0
    match = re.match(r"PT(\d+)M([\d.]+)S", clock_str)
    if not match:
        return 0.0
    mins = int(match.group(1))
    secs = float(match.group(2))
    period_remaining = mins * 60 + secs
    if period <= QUARTERS_IN_REGULATION:
        return (QUARTERS_IN_REGULATION - period) * SECONDS_PER_QUARTER + period_remaining
    return period_remaining  # OT


def get_live_games() -> list[dict]:
    """Return list of games currently in progress today."""
    try:
        req = urllib.request.Request(SCOREBOARD_URL, headers=NBA_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        games = data.get("scoreboard", {}).get("games", [])
        return [g for g in games if g.get("gameStatus") == 2]
    except Exception:
        # Don't log the exception detail — it can contain URLs with internal tokens
        logger.debug("Scoreboard fetch failed.")
        return []


def get_team_win_rate(team_id: int, standings_cache: dict) -> float:
    """Look up win rate from cached standings; default 0.5 if unavailable."""
    return standings_cache.get(team_id, 0.5)


def fetch_game_state(game_id: str, standings_cache: dict) -> dict | None:
    """
    Fetch live box score + play-by-play for one game and return a unified
    state dict ready for feature extraction and WebSocket broadcast.
    """
    try:
        game_id = _sanitize_game_id(game_id)   # prevent URL injection
        game_data = _fetch_json(BOXSCORE_URL.format(game_id=game_id))["game"]

        home = game_data["homeTeam"]
        away = game_data["awayTeam"]

        home_score = int(home.get("score", 0) or 0)
        away_score = int(away.get("score", 0) or 0)
        period = int(game_data.get("period", 1) or 1)
        clock_str = game_data.get("gameClock", "PT12M00.00S") or "PT12M00.00S"
        seconds_remaining = parse_live_clock(clock_str, period)

        home_fouls = sum(
            int(p.get("statistics", {}).get("foulsPersonal", 0) or 0)
            for p in home.get("players", [])
        )
        away_fouls = sum(
            int(p.get("statistics", {}).get("foulsPersonal", 0) or 0)
            for p in away.get("players", [])
        )

        home_team_id = home.get("teamId")
        away_team_id = away.get("teamId")
        home_win_rate = get_team_win_rate(home_team_id, standings_cache)
        away_win_rate = get_team_win_rate(away_team_id, standings_cache)

    except Exception:
        logger.debug("Boxscore fetch failed for a game.")
        return None

    # Play-by-play for recent plays + possession
    recent_plays = []
    home_possession = 1
    try:
        pbp_data = _fetch_json(PLAYBYPLAY_URL.format(game_id=game_id))
        plays = pbp_data.get("game", {}).get("actions", [])
        if plays:
            # possession = last play where 'possession' field matches a team
            for play in reversed(plays):
                poss_id = play.get("possession")
                if poss_id:
                    home_possession = 1 if poss_id == home_team_id else 0
                    break

            for play in plays[-8:]:
                desc = play.get("description", "").strip()
                if desc:
                    recent_plays.append({
                        "clock": play.get("clock", ""),
                        "period": play.get("period", period),
                        "description": desc,
                        "teamTricode": play.get("teamTricode", ""),
                    })
    except Exception:
        logger.debug("Play-by-play fetch failed for a game.")

    return {
        # Model features
        "score_differential": home_score - away_score,
        "seconds_remaining": seconds_remaining,
        "quarter": period,
        "home_possession": home_possession,
        "home_fouls": home_fouls,
        "away_fouls": away_fouls,
        "home_win_rate": home_win_rate,
        "away_win_rate": away_win_rate,
        # Display info
        "game_id": game_id,
        "home_team": home.get("teamTricode", "HOME"),
        "home_team_name": home.get("teamName", ""),
        "home_team_city": home.get("teamCity", ""),
        "away_team": away.get("teamTricode", "AWAY"),
        "away_team_name": away.get("teamName", ""),
        "away_team_city": away.get("teamCity", ""),
        "home_score": home_score,
        "away_score": away_score,
        "clock": clock_str,
        "recent_plays": recent_plays,
    }


class LivePoller:
    """
    Spawns a daemon thread that polls NBA live data every POLL_INTERVAL seconds.

    Each cycle:
      1. Emits "games_list" with a summary of all live games (for the selector UI).
      2. Emits "game_update" for every live game, keyed by game_id.

    The frontend filters game_update events to whichever game the user selected.
    """

    def __init__(self, model: torch.nn.Module, scaler, emit_fn: Callable, list_emit_fn: Callable) -> None:
        self.model = model
        self.scaler = scaler
        self.emit_fn = emit_fn          # broadcast one game's full state
        self.list_emit_fn = list_emit_fn  # broadcast the games list
        self.standings_cache: dict = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _predict(self, state: dict) -> float:
        feature_order = [
            "score_differential", "seconds_remaining", "quarter",
            "home_possession", "home_fouls", "away_fouls",
            "home_win_rate", "away_win_rate",
        ]
        raw = np.array([[state[k] for k in feature_order]], dtype=np.float32)
        scaled = self.scaler.transform(raw)
        with torch.no_grad():
            prob = self.model(torch.tensor(scaled)).item()
        # Clamp to [0.01, 0.99] — model is overconfident at extremes
        return round(max(0.01, min(0.99, prob)), 4)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            live_games = get_live_games()

            if not live_games:
                # Debug only — would spam logs at WARNING level during off-season
                logger.debug("No live games right now.")
                self.list_emit_fn([])
            else:
                game_summaries = []
                for game in live_games:
                    game_id = game.get("gameId")
                    state = fetch_game_state(game_id, self.standings_cache)
                    if state is None:
                        continue

                    state["home_win_prob"] = self._predict(state)
                    self.emit_fn(state)

                    game_summaries.append({
                        "game_id": game_id,
                        "home_team": state["home_team"],
                        "away_team": state["away_team"],
                        "home_score": state["home_score"],
                        "away_score": state["away_score"],
                        "quarter": state["quarter"],
                        "clock": state["clock"],
                        "home_win_prob": state["home_win_prob"],
                    })

                self.list_emit_fn(game_summaries)

            self._stop_event.wait(timeout=POLL_INTERVAL)
