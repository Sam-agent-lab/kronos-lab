"""Test di equivalenza: la media dei nostri path deve coincidere con `predict`.

Opus ha chiesto esattamente questo confronto. Se `forecast_paths(...).mean(axis=0)`
non torna con `KronosPredictor.predict(..., sample_count=N)` a parità di seed, la
nostra replica ha una differenza che cambia i numeri.

Eseguito con `python scripts/parity_test.py` (non è pytest: serve il modello, ~1 minuto).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "third_party" / "kronos"))

from forecast_demo import load_candles, load_predictor  # noqa: E402
from kronos_ensemble import _stamps, forecast_paths  # noqa: E402


def check_stamps() -> None:
    from model.kronos import calc_time_stamps

    candles = load_candles("BTCUSDT", "1h")
    series = candles["open_time"].reset_index(drop=True)
    ours = _stamps(series)
    theirs = calc_time_stamps(series).values.astype(np.float32)
    same = np.array_equal(ours, theirs)
    print(f"[stamps] identici: {same}  (shape {ours.shape} vs {theirs.shape})")
    if not same:
        diff = np.abs(ours - theirs).max()
        print(f"[stamps] differenza massima {diff}")
        raise SystemExit("timestamp diversi: la replica non è equivalente")


def check_mean(horizon: int = 6, samples: int = 4, seed: int = 7) -> None:
    candles = load_candles("BTCUSDT", "1h")
    step = pd.Timedelta(hours=1)
    y_ts = pd.Series(pd.date_range(candles["open_time"].iloc[-1] + step,
                                   periods=horizon, freq=step))
    predictor = load_predictor()
    frame = candles[["open", "high", "low", "close", "volume"]]
    x_ts = candles["open_time"].reset_index(drop=True)

    torch.manual_seed(seed)
    np.random.seed(seed)
    paths = forecast_paths(predictor, frame, x_ts, y_ts, pred_len=horizon,
                           T=1.0, top_p=0.9, sample_count=samples)
    torch.manual_seed(seed)
    np.random.seed(seed)
    reference = predictor.predict(df=frame, x_timestamp=x_ts, y_timestamp=y_ts,
                                  pred_len=horizon, T=1.0, top_p=0.9,
                                  sample_count=samples, verbose=False)

    ours = paths.mean(axis=0)          # (horizon, features)
    close_ours = ours[:, 3]
    close_ref = reference["close"].to_numpy(dtype=float)
    rel = np.abs(close_ours - close_ref) / np.abs(close_ref)
    print(f"[mean] close: differenza relativa massima {rel.max():.2e} "
          f"(media {rel.mean():.2e})")
    if rel.max() > 5e-3:
        raise SystemExit("la media dei path non coincide con predict")


def main() -> int:
    check_stamps()
    check_mean()
    print("OK: replica equivalente a meno della media finale dei campioni")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
