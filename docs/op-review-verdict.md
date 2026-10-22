VERDETTO 1: sì, predict restituisce la media dei campioni.
 In auto_regressive_inference, prima del return ci sono queste due righe:
 - z = z.reshape(-1, sample_count, z.size(1), z.size(2)): separa i campioni.
 - preds = np.mean(preds, axis=1): fa la media sull'asse dei campioni.
 predict quindi riceve un solo path, la media, e lo de-normalizza. La
 de-normalizzazione è lineare: fare la media prima o dopo dà lo stesso
 risultato. Con sample_count > 1, i percentili calcolati sull'output di predict
 non misurano la dispersione dei campioni: il sospetto è confermato.
 VERDETTO 2: il ciclo autoregressivo è identico. Encode, buffer, roll, finestra
 dei timestamp, sampling s1/s2 e decode coincidono riga per riga. Ci sono però
 alcune differenze attorno al ciclo:
 1. Device. L'originale lavora sul device di x, che generate ha già spostato su
 self.device. Il vostro torch.from_numpy resta sulla CPU e manca un
 .to(predictor.device). Se il modello è sulla GPU lo script va in errore, ma i
 numeri non cambiano in silenzio.
 2. Manca il controllo dei NaN. predict si ferma con ValueError; da voi un NaN
 rende NaN media e std di quella colonna, e di conseguenza tutti i path.
 3. Volume assente con amount presente. L'originale mette a 0 sia vol sia amt;
 voi tenete l'amt esistente. In questo caso limite i numeri cambiano, perché
 cambia l'input normalizzato.
 4. Clip. L'originale fa la clip in numpy e poi di nuovo torch.clip dentro
 l'inferenza; voi solo in numpy. Con lo stesso valore (self.clip) la seconda
 clip non cambia nulla, quindi nessun effetto.
 5. Slicing. L'originale taglia [:, -pred_len:, :] dentro generate (codice non
 incluso nel brief), dopo la media; voi tagliate prima della
 de-normalizzazione. È equivalente, ma va confermato sulla vostra versione di
 generate.
 6. Selezione [0]. Con batch 1 è equivalente.
 7. Default diversi da predict: sample_count 30 invece di 1 (voluto) e verbose
 False. top_p è 0.9 in entrambi.
 8. _stamps non è nel brief e non l'ho potuta verificare. Deve restituire
 esattamente le colonne minute, hour, weekday, day, month, in quest'ordine, in
 float32. Basta un ordine diverso per sbagliare i timestamp in silenzio, ed è
 la differenza più insidiosa possibile.
 9. Il seme casuale non è fissato in nessuno dei due codici: nessun confronto
 potrà essere identico bit per bit.
 Verifiche che mancano:
 - confronto diretto: con lo stesso seed, forecast_paths(...).mean(axis=0) deve
 coincidere con predict(..., sample_count=N) a meno di errori di arrotondamento
 float, anche con max_context minore della lunghezza dell'input;
 - test sul device (.to(predictor.device)) se girate su GPU;
 - _stamps confrontato con calc_time_stamps sugli stessi timestamp.
 Approverei il ciclo così com'è. Prima di usare i percentili, chiederei di
 aggiungere .to(device), il controllo dei NaN e il test di equivalenza.
 RISCHIO: medio. Il cuore del codice è fedele, ma _stamps non è verificata e il
 caso limite del volume può alterare l'input senza alcun errore visibile.
Resume this session with:
  hermes --resume 20261022_163614_2446d9
  hermes -c "Revisione ensemble campioni Kronos predict"
Title:          Revisione ensemble campioni Kronos predict