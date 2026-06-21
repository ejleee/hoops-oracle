"""
Flask + Flask-SocketIO backend for the NBA win probability model.

Security hardening applied (OWASP):
  - SECRET_KEY loaded from environment, never hardcoded
  - CORS restricted to ALLOWED_ORIGINS env var
  - Rate limiting on POST /api/predict (flask-limiter, in-memory store)
  - WebSocket rate limiting via per-connection counter
  - Strict schema validation + type coercion on all user inputs
  - Unexpected fields stripped before processing
  - Request body size capped at 4 KB
  - game_id sanitized before use in URLs (alphanumeric only)
  - Internal error details never sent to clients
  - Secrets never printed in logs

REST endpoint:
    POST /api/predict
    Body: { "score_differential": 5, "seconds_remaining": 300, ... }
    Response: { "home_win_prob": 0.73 }

WebSocket namespace /live:
    Server emits "game_update" automatically when live games are in progress.
    Client can also emit "game_state" for ad-hoc predictions (rate limited).
"""

import logging
import os
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import torch
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit

sys.path.insert(0, str(Path(__file__).parent.parent))
from model.model import WinProbabilityModel
from live_poller import LivePoller

load_dotenv()

# ── Logging ────────────────────────────────────────────────────────────────────
# Only show WARNING+ in production; never log raw request bodies or secrets.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("hoops_oracle")

# ── Config from environment (no hardcoded secrets) ─────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY or SECRET_KEY == "change-me-use-secrets-token-hex-32":
    # Fail loudly in production; allow dev fallback with a warning
    if os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("SECRET_KEY must be set in environment for production.")
    logger.warning("SECRET_KEY not set — using insecure dev default. Set it in .env.")
    SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]

RATE_LIMIT = os.environ.get("RATE_LIMIT_PER_MINUTE", "30")
# Max request body size: 4 KB — enough for our JSON payload, blocks large bomb payloads
MAX_CONTENT_LENGTH = 4 * 1024

# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# CORS restricted to explicit origins only — never wildcard in hardened mode
CORS(app, origins=ALLOWED_ORIGINS)

# Rate limiter using in-memory storage (swap to Redis URL via RATELIMIT_STORAGE_URI env var)
# To use Redis: set RATELIMIT_STORAGE_URI=redis://localhost:6379/0 in .env
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],           # no default; apply per-route
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)

socketio = SocketIO(
    app,
    cors_allowed_origins=ALLOWED_ORIGINS,
    async_mode="threading",
    # Disable engineio/socketio verbose logging — it can leak request metadata
    logger=False,
    engineio_logger=False,
)

# ── Model loading ──────────────────────────────────────────────────────────────
MODEL_PATH = Path(__file__).parent.parent / "model" / "saved" / "win_prob_model.pt"
SCALER_PATH = Path(__file__).parent.parent / "model" / "saved" / "scaler.pkl"

# Exact set of accepted feature fields — anything outside this is stripped
FEATURE_ORDER = [
    "score_differential", "seconds_remaining", "quarter", "home_possession",
    "home_fouls", "away_fouls", "home_win_rate", "away_win_rate",
]

# Per-field validation rules: (type, min, max)
FEATURE_SCHEMA: dict[str, tuple[type, float, float]] = {
    "score_differential":  (float, -100.0,  100.0),
    "seconds_remaining":   (float,    0.0, 3600.0),
    "quarter":             (int,       1,      10),
    "home_possession":     (int,       0,       1),
    "home_fouls":          (int,       0,      50),
    "away_fouls":          (int,       0,      50),
    "home_win_rate":       (float,    0.0,    1.0),
    "away_win_rate":       (float,    0.0,    1.0),
}


def load_model() -> tuple[WinProbabilityModel, object]:
    model = WinProbabilityModel()
    model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu"))
    model.eval()
    scaler = joblib.load(SCALER_PATH)
    return model, scaler


try:
    _model, _scaler = load_model()
    logger.warning("Model loaded successfully.")   # WARNING level so it shows in prod logs
    print("Model loaded successfully.")
except FileNotFoundError:
    _model, _scaler = None, None
    print("[WARN] Model not found — run model/train.py first.")


# ── Input validation ───────────────────────────────────────────────────────────

def validate_features(data: dict) -> tuple[dict | None, str | None]:
    """
    Validate and coerce feature dict against FEATURE_SCHEMA.

    Returns (clean_dict, None) on success or (None, error_message) on failure.
    Strips any fields not in FEATURE_ORDER to prevent unexpected input.
    """
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object."

    # Strip unexpected fields — never process what we didn't ask for
    clean: dict = {}
    for field, (expected_type, min_val, max_val) in FEATURE_SCHEMA.items():
        if field not in data:
            return None, f"Missing required field: '{field}'"

        raw = data[field]

        # Type coercion with strict bounds
        try:
            value = expected_type(raw)
        except (TypeError, ValueError):
            return None, f"Field '{field}' must be a {expected_type.__name__}."

        if not (min_val <= value <= max_val):
            return None, f"Field '{field}' out of range [{min_val}, {max_val}]."

        clean[field] = value

    return clean, None


def run_predict(features: dict) -> float:
    raw = np.array([[features[col] for col in FEATURE_ORDER]], dtype=np.float32)
    scaled = _scaler.transform(raw)
    with torch.no_grad():
        prob = _model(torch.tensor(scaled)).item()
    return round(max(0.01, min(0.99, prob)), 4)


# ── Broadcasting ───────────────────────────────────────────────────────────────

def broadcast_game_update(state: dict) -> None:
    socketio.emit("game_update", state, namespace="/live")


def broadcast_games_list(games: list) -> None:
    socketio.emit("games_list", games, namespace="/live")


# ── Live poller ────────────────────────────────────────────────────────────────
_poller: LivePoller | None = None
if _model is not None:
    _poller = LivePoller(_model, _scaler, broadcast_game_update, broadcast_games_list)
    _poller.start()


# ── REST endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/predict", methods=["POST"])
@limiter.limit(f"{RATE_LIMIT} per minute")   # e.g. 30/min per IP
def api_predict():
    if _model is None:
        return jsonify({"error": "Model not available."}), 503

    data = request.get_json(silent=True)   # silent=True — never raise on bad JSON
    if data is None:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    clean, err = validate_features(data)
    if err:
        return jsonify({"error": err}), 400

    return jsonify({"home_win_prob": run_predict(clean)})


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "Too many requests. Please slow down."}), 429


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "Request body too large."}), 413


# ── WebSocket ──────────────────────────────────────────────────────────────────

# Simple per-connection rate limiter for game_state events
_ws_last_call: dict[str, float] = {}   # sid → timestamp
WS_MIN_INTERVAL = 1.0                  # minimum seconds between game_state events per client


@socketio.on("connect", namespace="/live")
def on_connect():
    # Don't log the SID or IP — no PII in logs
    pass


@socketio.on("disconnect", namespace="/live")
def on_disconnect():
    # Clean up rate-limit tracker for this connection
    _ws_last_call.pop(request.sid, None)


@socketio.on("game_state", namespace="/live")
def on_game_state(data):
    if _model is None:
        emit("error", {"message": "Model not available."})
        return

    # WebSocket rate limit: max 1 event per second per connection
    sid = request.sid
    now = time.monotonic()
    last = _ws_last_call.get(sid, 0.0)
    if now - last < WS_MIN_INTERVAL:
        emit("error", {"message": "Too many requests."})
        return
    _ws_last_call[sid] = now

    # Validate input — same schema as REST endpoint
    if not isinstance(data, dict):
        emit("error", {"message": "Payload must be a JSON object."})
        return

    clean, err = validate_features(data)
    if err:
        emit("error", {"message": err})
        return

    prob = run_predict(clean)
    emit("game_update", {"home_win_prob": prob, **clean}, broadcast=True)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001, debug=False)
