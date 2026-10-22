Sei il revisore tecnico di un esperimento di forecasting crypto. Devi dare un
verdetto secco su due domande, non riscrivere il codice.

CONTESTO: usiamo Kronos (github.com/shiyu-coder/Kronos, MIT). Nel nostro script
`kronos_ensemble.py` abbiamo replicato l'inferenza originale per ottenere i path
dei singoli campioni invece della loro media, perché sospettiamo che
`KronosPredictor.predict` restituisca la MEDIA dei campioni quando
`sample_count > 1`, rendendo inutili i percentili calcolati sull'output.

DOMANDA 1: confermi che `auto_regressive_inference` (e quindi `predict`) fa la media
dei campioni prima di restituire i risultati? Cita le righe esatte.

DOMANDA 2: la nostra `forecast_paths` è identica all'originale a parte (a) la rimozione
della media finale, (b) la restituzione di tutti i campioni, (c) la de-normalizzazione
per campione? Elenca ogni differenza che trovi, anche minima (ordine delle operazioni,
normalizzazione, clip, reshaping, slicing, gestione dei buffer, timestamp). Se una
differenza può cambiare i numeri, dillo esplicitamente e spiega l'effetto atteso.

Rispondi con: VERDETTO 1 (sì/no + righe), VERDETTO 2 (identico/differenze elencate),
e una riga finale RISCHIO (basso/medio/alto) con il motivo. Massimo 400 parole.

--- CODICE ORIGINALE: auto_regressive_inference ---
def auto_regressive_inference(tokenizer, model, x, x_stamp, y_stamp, max_context, pred_len, clip=5, T=1.0, top_k=0, top_p=0.99, sample_count=5, verbose=False):
    with torch.no_grad():
        x = torch.clip(x, -clip, clip)

        device = x.device
        x = x.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(-1, x.size(1), x.size(2)).to(device)
        x_stamp = x_stamp.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(-1, x_stamp.size(1), x_stamp.size(2)).to(device)
        y_stamp = y_stamp.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(-1, y_stamp.size(1), y_stamp.size(2)).to(device)

        x_token = tokenizer.encode(x, half=True)
        
        initial_seq_len = x.size(1)
        batch_size = x_token[0].size(0)
        total_seq_len = initial_seq_len + pred_len
        full_stamp = torch.cat([x_stamp, y_stamp], dim=1)

        generated_pre = x_token[0].new_empty(batch_size, pred_len)
        generated_post = x_token[1].new_empty(batch_size, pred_len)

        pre_buffer = x_token[0].new_zeros(batch_size, max_context)
        post_buffer = x_token[1].new_zeros(batch_size, max_context)
        buffer_len = min(initial_seq_len, max_context)
        if buffer_len > 0:
            start_idx = max(0, initial_seq_len - max_context)
            pre_buffer[:, :buffer_len] = x_token[0][:, start_idx:start_idx + buffer_len]
            post_buffer[:, :buffer_len] = x_token[1][:, start_idx:start_idx + buffer_len]

        if verbose:
            ran = trange
        else:
            ran = range
        for i in ran(pred_len):
            current_seq_len = initial_seq_len + i
            window_len = min(current_seq_len, max_context)

            if current_seq_len <= max_context:
                input_tokens = [
                    pre_buffer[:, :window_len],
                    post_buffer[:, :window_len]
                ]
            else:
                input_tokens = [pre_buffer, post_buffer]

            context_end = current_seq_len
            context_start = max(0, context_end - max_context)
            current_stamp = full_stamp[:, context_start:context_end, :].contiguous()

            s1_logits, context = model.decode_s1(input_tokens[0], input_tokens[1], current_stamp)
            s1_logits = s1_logits[:, -1, :]
            sample_pre = sample_from_logits(s1_logits, temperature=T, top_k=top_k, top_p=top_p, sample_logits=True)

            s2_logits = model.decode_s2(context, sample_pre)
            s2_logits = s2_logits[:, -1, :]
            sample_post = sample_from_logits(s2_logits, temperature=T, top_k=top_k, top_p=top_p, sample_logits=True)

            generated_pre[:, i] = sample_pre.squeeze(-1)
            generated_post[:, i] = sample_post.squeeze(-1)

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
        input_tokens = [
            full_pre[:, context_start:total_seq_len].contiguous(),
            full_post[:, context_start:total_seq_len].contiguous()
        ]
        z = tokenizer.decode(input_tokens, half=True)
        z = z.reshape(-1, sample_count, z.size(1), z.size(2))
        preds = z.cpu().numpy()
        preds = np.mean(preds, axis=1)

        return preds


def calc_time_stamps(x_timestamp):
    time_df = pd.DataFrame()
    time_df['minute'] = x_timestamp.dt.minute
    time_df['hour'] = x_timestamp.dt.hour
    time_df['weekday'] = x_timestamp.dt.weekday
    time_df['day'] = x_timestamp.dt.day
    time_df['month'] = x_timestamp.dt.month
    return time_df

--- CODICE ORIGINALE: predict ---
def predict(self, df, x_timestamp, y_timestamp, pred_len, T=1.0, top_k=0, top_p=0.9, sample_count=1, verbose=True):

        if not isinstance(df, pd.DataFrame):
            raise ValueError("Input must be a pandas DataFrame.")

        if not all(col in df.columns for col in self.price_cols):
            raise ValueError(f"Price columns {self.price_cols} not found in DataFrame.")

        df = df.copy()
        if self.vol_col not in df.columns:
            df[self.vol_col] = 0.0  # Fill missing volume with zeros
            df[self.amt_vol] = 0.0  # Fill missing amount with zeros
        if self.amt_vol not in df.columns and self.vol_col in df.columns:
            df[self.amt_vol] = df[self.vol_col] * df[self.price_cols].mean(axis=1)

        if df[self.price_cols + [self.vol_col, self.amt_vol]].isnull().values.any():
            raise ValueError("Input DataFrame contains NaN values in price or volume columns.")

        x_time_df = calc_time_stamps(x_timestamp)
        y_time_df = calc_time_stamps(y_timestamp)

        x = df[self.price_cols + [self.vol_col, self.amt_vol]].values.astype(np.float32)
        x_stamp = x_time_df.values.astype(np.float32)
        y_stamp = y_time_df.values.astype(np.float32)

        x_mean, x_std = np.mean(x, axis=0), np.std(x, axis=0)

        x = (x - x_mean) / (x_std + 1e-5)
        x = np.clip(x, -self.clip, self.clip)

        x = x[np.newaxis, :]
        x_stamp = x_stamp[np.newaxis, :]
        y_stamp = y_stamp[np.newaxis, :]

        preds = self.generate(x, x_stamp, y_stamp, pred_len, T, top_k, top_p, sample_count, verbose)

        preds = preds.squeeze(0)
        preds = preds * (x_std + 1e-5) + x_mean

        pred_df = pd.DataFrame(preds, columns=self.price_cols + [self.vol_col, self.amt_vol], index=y_timestamp)
        return pred_df

--- NOSTRO CODICE: forecast_paths ---
def forecast_paths(predictor, df: pd.DataFrame, x_timestamp, y_timestamp,
                   pred_len: int, T: float = 1.0, top_k: int = 0, top_p: float = 0.9,
                   sample_count: int = 30, verbose: bool = False) -> np.ndarray:
    """(sample_count, pred_len, n_features) in unità di prezzo originali."""
    price_cols = predictor.price_cols
    vol_col, amt_col = predictor.vol_col, predictor.amt_vol
    frame = df.copy()
    if vol_col not in frame.columns:
        frame[vol_col] = 0.0
    if amt_col not in frame.columns:
        frame[amt_col] = frame[vol_col] * frame[price_cols].mean(axis=1)

    features = frame[price_cols + [vol_col, amt_col]].values.astype(np.float32)
    mean, std = np.mean(features, axis=0), np.std(features, axis=0)
    normalized = np.clip((features - mean) / (std + 1e-5), -predictor.clip, predictor.clip)

    x = torch.from_numpy(normalized[None, :, :])
    x_stamp = torch.from_numpy(_stamps(x_timestamp)[None, :, :])
    y_stamp = torch.from_numpy(_stamps(y_timestamp)[None, :, :])

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
