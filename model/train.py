"""
Train the win probability model on the preprocessed dataset.

Expects data/training_data.csv produced by data/features.py.
Saves the trained model to model/saved/win_prob_model.pt.

Usage:
    python model/train.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import joblib

from model import WinProbabilityModel, INPUT_SIZE

DATA_PATH = Path(__file__).parent.parent / "data" / "training_data.csv"
SAVE_DIR = Path(__file__).parent / "saved"
MODEL_PATH = SAVE_DIR / "win_prob_model.pt"
SCALER_PATH = SAVE_DIR / "scaler.pkl"

FEATURE_COLUMNS = [
    "score_differential",
    "seconds_remaining",
    "quarter",
    "home_possession",
    "home_fouls",
    "away_fouls",
    "home_win_rate",
    "away_win_rate",
]

# Hyperparameters
BATCH_SIZE = 512
EPOCHS = 60
LEARNING_RATE = 1e-3
VALIDATION_SPLIT = 0.2
RANDOM_SEED = 42
LABEL_SMOOTHING = 0.05  # prevents overconfidence by softening hard 0/1 targets


def load_data() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    df = pd.read_csv(DATA_PATH)
    print(f"Loaded {len(df):,} rows from {DATA_PATH}")

    X = df[FEATURE_COLUMNS].values.astype(np.float32)
    y = df["home_win"].values.astype(np.float32)

    # Weight late-game close plays higher so the model learns comeback scenarios.
    # A play in Q4 with a small score diff gets up to 3x the weight of an
    # early blowout play.
    seconds = df["seconds_remaining"].values
    score_diff = df["score_differential"].abs().values

    time_weight = 1.0 + 2.0 * np.clip(1.0 - seconds / (48 * 60), 0, 1)
    closeness_weight = 1.0 + 1.5 * np.clip(1.0 - score_diff / 20.0, 0, 1)
    sample_weights = (time_weight * closeness_weight).astype(np.float32)
    # Normalize so mean weight = 1
    sample_weights /= sample_weights.mean()

    return X, y, sample_weights


def make_dataloader(
    X: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    shuffle: bool,
) -> torch.utils.data.DataLoader:
    dataset = torch.utils.data.TensorDataset(
        torch.tensor(X, dtype=torch.float32),
        torch.tensor(y, dtype=torch.float32),
        torch.tensor(weights, dtype=torch.float32),
    )
    return torch.utils.data.DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=shuffle)


def compute_accuracy(model: WinProbabilityModel, loader: torch.utils.data.DataLoader, device: torch.device) -> float:
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for X_batch, y_batch, _ in loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            preds = model(X_batch).squeeze()
            predicted_labels = (preds >= 0.5).float()
            correct += (predicted_labels == y_batch).sum().item()
            total += len(y_batch)
    return correct / total


def weighted_bce_loss(
    preds: torch.Tensor,
    targets: torch.Tensor,
    weights: torch.Tensor,
    smoothing: float = LABEL_SMOOTHING,
) -> torch.Tensor:
    # Apply label smoothing: push targets away from hard 0/1
    targets_smooth = targets * (1 - smoothing) + smoothing / 2
    bce = nn.functional.binary_cross_entropy(preds, targets_smooth, reduction='none')
    return (bce * weights).mean()


def train() -> None:
    torch.manual_seed(RANDOM_SEED)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    X, y, weights = load_data()

    X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
        X, y, weights, test_size=VALIDATION_SPLIT, random_state=RANDOM_SEED, stratify=y
    )

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_val = scaler.transform(X_val)

    joblib.dump(scaler, SCALER_PATH)
    print(f"Saved scaler to {SCALER_PATH}")

    train_loader = make_dataloader(X_train, y_train, w_train, shuffle=True)
    val_loader = make_dataloader(X_val, y_val, w_val, shuffle=False)

    model = WinProbabilityModel().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.5)

    print(f"\nTraining for {EPOCHS} epochs (batch_size={BATCH_SIZE}, label_smoothing={LABEL_SMOOTHING})...\n")

    for epoch in range(1, EPOCHS + 1):
        model.train()
        total_loss = 0.0
        num_batches = 0

        for X_batch, y_batch, w_batch in train_loader:
            X_batch = X_batch.to(device)
            y_batch = y_batch.to(device)
            w_batch = w_batch.to(device)

            optimizer.zero_grad()
            preds = model(X_batch).squeeze()
            loss = weighted_bce_loss(preds, y_batch, w_batch)
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            num_batches += 1

        scheduler.step()
        avg_loss = total_loss / num_batches
        val_acc = compute_accuracy(model, val_loader, device)

        print(f"Epoch {epoch:3d}/{EPOCHS} | loss: {avg_loss:.4f} | val_acc: {val_acc:.4f} | lr: {scheduler.get_last_lr()[0]:.2e}")

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), MODEL_PATH)
    print(f"\nModel saved to {MODEL_PATH}")


if __name__ == "__main__":
    train()
