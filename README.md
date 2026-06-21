# 🏀 Hoops Oracle — Live NBA Win Probability Tracker

A real-time NBA win probability tracker powered by a PyTorch neural network. Trained on 4,500+ historical games of play-by-play data, it streams live predictions to a React dashboard that updates every 5 seconds during live games.

![Dashboard Preview](https://img.shields.io/badge/status-live-brightgreen) ![Python](https://img.shields.io/badge/python-3.13-blue) ![React](https://img.shields.io/badge/react-18-61dafb) ![PyTorch](https://img.shields.io/badge/pytorch-2.6-ee4c2c)

---

## How It Works

1. **Data** — Historical play-by-play data collected from the NBA Stats API across 4 seasons (2020–2024)
2. **Features** — 8 game-state features extracted per play: score differential, time remaining, quarter, possession, fouls, and team win rates
3. **Model** — A 3-layer MLP trained with label smoothing and late-game sample weighting to produce calibrated probabilities
4. **Backend** — Flask + Flask-SocketIO server polls the NBA CDN every 5 seconds during live games, runs inference, and broadcasts updates via WebSocket
5. **Frontend** — React dashboard displays team colors, live score, win probability, a chart over game time, and a real-time play feed

---

## Features

- Live win probability updated every 5 seconds during NBA games
- Team colors automatically matched to each matchup
- Win probability chart that builds throughout the game (persists across page refreshes)
- Play-by-play feed with probability deltas per play
- Game selector when multiple games are live simultaneously
- Replay mode for testing with historical games

---

## Tech Stack

| Layer | Tech |
|---|---|
| Data | nba_api, pandas, numpy |
| Model | PyTorch (MLP), scikit-learn |
| Backend | Flask, Flask-SocketIO, Flask-Limiter |
| Frontend | React, Recharts, Socket.IO client |
| Security | Rate limiting, input validation, env-based secrets |

---

## Setup

### Prerequisites
- Python 3.10+
- Node 18+

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Collect historical data
```bash
python data/collect.py
```
This pulls play-by-play CSVs for the 2020–21 through 2023–24 seasons. Takes a few hours due to API rate limiting.

### 3. Build the training dataset
```bash
python data/features.py
```

### 4. Train the model
```bash
python model/train.py
```
Trains for 60 epochs with label smoothing and late-game weighting. Saves model to `model/saved/`.

### 5. Configure environment
```bash
cp .env.example .env
```
Edit `.env` and set a strong `SECRET_KEY`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 6. Start the backend
```bash
cd backend && python -m flask run --port 5001
```

### 7. Start the frontend
```bash
cd frontend && npm install && npm start
```

Open [http://localhost:3000](http://localhost:3000). The dashboard activates automatically when a live NBA game is in progress.

---

## Testing with Replay Mode

No live game? Replay any historical game through the dashboard:

```bash
# Random game
python backend/replay.py

# Specific game at 10x speed
python backend/replay.py 0022000001 --speed 10
```

---

## Project Structure

```
hoops-oracle/
├── data/
│   ├── collect.py        # NBA API data collection
│   └── features.py       # Feature extraction from play-by-play
├── model/
│   ├── model.py          # MLP architecture
│   ├── train.py          # Training pipeline
│   └── saved/            # Trained weights (gitignored)
├── backend/
│   ├── app.py            # Flask + SocketIO server
│   ├── live_poller.py    # NBA CDN polling thread
│   └── replay.py         # Historical game replay tool
├── frontend/
│   └── src/
│       ├── WinProbabilityDashboard.js   # Main UI
│       ├── useGameSocket.js             # WebSocket hook
│       └── teamColors.js               # Team color lookup
├── .env.example
└── requirements.txt
```

---

## Model Details

- **Architecture**: 3-layer MLP (64 → 32 → 16 → sigmoid)
- **Input features**: score differential, seconds remaining, quarter, possession, home fouls, away fouls, home win rate, away win rate
- **Training**: Binary cross-entropy with label smoothing (ε=0.05), sample weights boosting late-game close plays up to 3×, learning rate decay every 20 epochs
- **Validation accuracy**: ~74%

---

## Security

- Rate limiting on all public endpoints (30 req/min per IP)
- Strict schema validation on all user inputs with type coercion and bounds checking
- Secrets loaded from environment variables — never hardcoded
- Request body size capped at 4 KB
- Game IDs sanitized before use in external URLs
- CORS restricted to configured origins

---

## Deployment

- **Frontend**: Vercel
- **Backend**: AWS Elastic Beanstalk

*Deployment guide coming soon.*
