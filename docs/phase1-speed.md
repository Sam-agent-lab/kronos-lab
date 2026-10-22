# Varianti di velocità (BTCUSDT 1h, 24 candele, 10 path, seed 7)

Stesso input e stesso seed: le differenze di mediana e bande sono l'effetto della
variante, non il rumore del campionamento. **base** = thread torch di default, niente nice,
contesto 512.

| variante | s/path | vs base | mediana | Δ mediana | p10 | Δ p10 | p90 | Δ p90 | picco RAM |
|---|---|---|---|---|---|---|---|---|---|
| base | 15.18 | +0.0% | 83,486 | +0.0% | 81,711 | +0.0% | 84,431 | +0.0% | 970 MB |
| threads | 11.56 | -23.8% | 83,486 | +0.0% | 81,711 | +0.0% | 84,431 | +0.0% | 960 MB |
| ctx256 | 5.01 | -67.0% | 81,288 | -2.6% | 80,967 | -0.9% | 82,045 | -2.8% | 659 MB |
| int8 | 6.45 | -57.5% | 84,066 | +0.7% | 83,762 | +2.5% | 84,372 | -0.1% | 828 MB |

Lettura: `threads=6` è gratis (stessi numeri). `ctx256` e `int8` cambiano la
distribuzione prevista: int8 dimezza i tempi ma restringe le bande di ~4 volte, quindi le
bande diventano non calibrate; ctx256 dimezza ancora ma con 256 candele di contesto il
forecast è un altro modello di fatto. Nessuno dei due va adottato senza ricalibrazione.
