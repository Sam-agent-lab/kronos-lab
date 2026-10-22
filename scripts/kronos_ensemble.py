"""Forecast a ensemble: path per campione, non la media.

Perché esiste: ``KronosPredictor.predict`` fa ``np.mean`` sui campioni prima di
restituire il DataFrame, quindi con ``sample_count > 1`` si ottiene UNA serie
(la media) e le bande calcolate su quella serie non sono bande di previsione.
Qui replico la funzione di inferenza del modello (MIT License, ShiYu 2025,
`model/kronos.py::auto_regressive_inference`) togliendo solo la media finale:
ogni campione resta un path separato, così i percentili sono veri.

Uso tipico:
    paths = forecast_paths(predictor, df, x_ts, y_ts, pred_len=24, sample_count=30)
    paths.shape  -> (30, 24, n_features)  # feature 0..3 = O/H/L/C
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "third_party" / "kronos"))

from model.kronos import calc_time_stamps, sample_from_logits  # noqa: E402


def _stamps(series: pd.Series) -> np.ndarray:
    frame = calc_time_stamps(pd.Series(series).reset_index(drop=True))
    return frame.values.astype(np.float32)


def forecast_paths(predictor, df: pd.DataFrame, x_timestamp, y_timestamp,
                   pred_len: int, T: float = 1.0, top_k: int = 0, top_p: float = 0.9,
                   sample_count: int = 30, verbose: bool = False) -> np.ndarray:
    """(sample_count, pred_len, n_features) in unità di prezzo originali."""
    price_cols = predictor.price_cols
    vol_col, amt_col = predictor.vol_col, predictor.amt_vol
    frame = df.copy()
    # stessa logica dell'originale: se manca il volume si azzerano volume E amount
    if vol_col not in frame.columns:
        frame[vol_col] = 0.0
        frame[amt_col] = 0.0
    if amt_col not in frame.columns:
        frame[amt_col] = frame[vol_col] * frame[price_cols].mean(axis=1)

    features = frame[price_cols + [vol_col, amt_col]].values.astype(np.float32)
    if not np.isfinite(features).all():
        # predict originale si ferma con ValueError: meglio fermarsi che propagare NaN
        raise ValueError("input con NaN/inf in prezzi o volumi")
    mean, std = np.mean(features, axis=0), np.std(features, axis=0)
    normalized = np.clip((features - mean) / (std + 1e-5), -predictor.clip, predictor.clip)

    device = predictor.device
    x = torch.from_numpy(normalized[None, :, :]).to(device)
    x_stamp = torch.from_numpy(_stamps(x_timestamp)[None, :, :]).to(device)
    y_stamp = torch.from_numpy(_stamps(y_timestamp)[None, :, :]).to(device)

    with torch.no_grad():
        # identico all'originale: ogni campione è un batch separato
        x_r = x.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(-1, x.size(1), x.size(2))
        x_stamp_r = x_stamp.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(
            -1, x_stamp.size(1), x_stamp.size(2))
        y_stamp_r = y_stamp.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(
            -1, y_stamp.size(1), y_stamp.size(2))

        tokenizer, model = predictor.tokenizer, predictor.model
        max_context = predictor.max_context
        x_token = tokenizer.encode(x_r, half=True)
        initial_seq_len = x_r.size(1)
        batch_size = x_token[0].size(0)
        total_seq_len = initial_seq_len + pred_len
        full_stamp = torch.cat([x_stamp_r, y_stamp_r], dim=1)

        generated_pre = x_token[0].new_empty(batch_size, pred_len)
        generated_post = x_token[1].new_empty(batch_size, pred_len)
        pre_buffer = x_token[0].new_zeros(batch_size, max_context)
        post_buffer = x_token[1].new_zeros(batch_size, max_context)
        buffer_len = min(initial_seq_len, max_context)
        if buffer_len > 0:
            start_idx = max(0, initial_seq_len - max_context)
            pre_buffer[:, :buffer_len] = x_token[0][:, start_idx:start_idx + buffer_len]
            post_buffer[:, :buffer_len] = x_token[1][:, start_idx:start_idx + buffer_len]

        for step in range(pred_len):
            current_seq_len = initial_seq_len + step
            window_len = min(current_seq_len, max_context)
            if current_seq_len <= max_context:
                input_tokens = [pre_buffer[:, :window_len], post_buffer[:, :window_len]]
            else:
                input_tokens = [pre_buffer, post_buffer]
            context_end = current_seq_len
            context_start = max(0, context_end - max_context)
            current_stamp = full_stamp[:, context_start:context_end, :].contiguous()

            s1_logits, context = model.decode_s1(input_tokens[0], input_tokens[1], current_stamp)
            sample_pre = sample_from_logits(s1_logits[:, -1, :], temperature=T, top_k=top_k,
                                            top_p=top_p, sample_logits=True)
            s2_logits = model.decode_s2(context, sample_pre)
            sample_post = sample_from_logits(s2_logits[:, -1, :], temperature=T, top_k=top_k,
                                             top_p=top_p, sample_logits=True)

            generated_pre[:, step] = sample_pre.squeeze(-1)
            generated_post[:, step] = sample_post.squeeze(-1)
            if current_seq_len < max_context:
                pre_buffer[:, current_seq_len] = sample_pre.squeeze(-1)
                post_buffer[:, current_seq_len] = sample_post.squeeze(-1)
            else:
                pre_buffer.copy_(torch.roll(pre_buffer, shifts=-1, dims=1))
                post_buffer.copy_(torch.roll(post_buffer, shifts=-1, dims=1))
                pre_buffer[:, -1] = sample_pre.squeeze(-1)
                post_buffer[:, -1] = sample_post.squeeze(-1)

        full_pre = torch.cat([x_token[0], generated_pre], dim=1)
        full_post = torch.cat([x_token[1], generated_post], dim=1)
        context_start = max(0, total_seq_len - max_context)
        tokens = [full_pre[:, context_start:total_seq_len].contiguous(),
                  full_post[:, context_start:total_seq_len].contiguous()]
        decoded = tokenizer.decode(tokens, half=True)
        # decode torna (batch*sample_count, seq, feat): rimetto il batch davanti e lo togli
        decoded = decoded.reshape(-1, sample_count, decoded.size(1), decoded.size(2))[0]
        paths = decoded[:, -pred_len:, :].cpu().numpy()

    return paths * (std + 1e-5) + mean
