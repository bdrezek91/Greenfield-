# ML MODEL TOURNAMENT V1 — prerejestracja i raport

Status: **CLOSED / REJECT**. Protokół poniżej został zamrożony przed pierwszym
końcowym uruchomieniem holdoutu. Holdout został otwarty 2026-08-28 i nie wolno
już użyć go do strojenia tej hipotezy; zmiana protokołu wymaga V2, nowego
holdoutu i osobnych wpisów globalnego trial ledger.

## Hipoteza

Klasyczny gradient boosting może lepiej niż Logistic Regression, Random
Forest i ExtraTrees oceniać `P(win)` istniejącego setupu Breakout, ale tylko
jeżeli przewaga utrzymuje się chronologicznie OOS, po kosztach i na BTC, ETH
oraz SOL. Celem jest próba obalenia tej hipotezy, nie maksymalizacja accuracy.

## Zamrożony eksperyment

- Universe: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, Bybit linear, świece `1h`.
- Wspólny okres zaczyna się od najpóźniejszej pierwszej obserwacji w universe
  i kończy na najwcześniejszej ostatniej obserwacji. Każdy dataset oraz pliki
  wejściowe są hashowane w manifeście.
- Setup: istniejący Donchian `Breakout`, `lookback_bars=20`, dokładnie względem
  **poprzednich** 20 high/low. Model nie generuje wejść; ocenia tylko istniejące
  kandydaty. Po kandydacie następne 24 bary nie mogą utworzyć nakładającego się
  trade'u.
- Wejście: close bara sygnałowego. Wyjście: close po 24 pełnych barach.
  Kierunek long/short pochodzi wyłącznie z Breakout.
- Meta-label: 1, gdy kierunkowy zwrot po zamrożonym koszcie bazowym jest > 0;
  0 w przeciwnym przypadku. Ostatnie 24 bary bez kompletnego labelu odpadają.
- Feature schema: istniejące `FEATURE_COLUMNS` z
  `src.features.pipeline.build_feature_matrix`, wyłącznie wartości dostępne
  as-of bara decyzji. Brak dowolnej wymaganej cechy = kandydat wykluczony /
  `WAIT`, bez imputacji z przyszłości.
- Modele: Logistic Regression, Random Forest, ExtraTrees, XGBoost, LightGBM.
  Wszystkie dostają identyczne wiersze, kolumny, labele, splity i koszty.
- Seed: 42. Modele drzewiaste mają limit jednego wątku w turnieju, aby wynik
  był odtwarzalny i nie zakłócał collectorów.

## Koszty i decyzja

Koszt bazowy round-trip w bps notional: fee 11 (2 × taker 5.5), spread 2,
slippage 4, funding 3 = **20 bps**. Adverse: fee ×1.5, spread ×1.5,
slippage ×2, funding ×1.5. Severe: fee ×2, spread ×2, slippage ×4,
funding ×2. Safety margin gate = dodatkowe **5 bps**.

Kalibrowane `p` nie wywołuje trade'u przy samym `p > 0.5`. Payoff win/loss
jest estymowany wyłącznie z odpowiedniej części treningowej:

`expected_gross = p * mean_gross_if_win + (1-p) * mean_gross_if_loss`

`TRADE` tylko gdy `expected_gross - scenario_cost > safety_margin`; inaczej
`WAIT`. Nie ma obowiązku wykonania minimalnej liczby trade'ów.

## Splity, kalibracja i trial budget

- Końcowe 20% chronologicznych setupów każdego symbolu to jednorazowy,
  zamrożony holdout. Nie służy do wyboru modelu ani parametrów.
- Pozostałe 80%: 5-fold expanding walk-forward. Train jest zawsze przed test,
  z purge równym 24 barom i embargo 24 godziny.
- Ostatnie 20% każdego fold-train jest oddzielnym chronologicznym calibration
  window; bazowy model nie jest na nim dopasowany. Platt/sigmoid calibration
  jest dopasowana tylko tam. Fold bez obu klas = fail-closed.
- Zamrożony mały budżet: Logistic 2 warianty C; RF 2 warianty depth/leaf;
  ExtraTrees 2; XGBoost 4; LightGBM 4. Łącznie 14 triali. Żadnego Optuna.
  Każdy wynik, również przegrany/błędny, trafia do manifestu trial ledger.
- Parametr wybiera mediana foldowego net Sharpe z karą za niestabilność;
  tie-break: niższy Brier, potem prostszy model. Holdout nie bierze udziału.

## Kryteria i raport

Raportujemy classification diagnostics (AUC, Brier, reliability) oddzielnie
od ekonomii: net PnL, Sharpe, Sortino, max DD, Calmar, expectancy, trades,
turnover, average trade, win rate, profit factor, fee/slippage/funding impact,
wyniki per symbol i aggregate, cost sensitivity, fold/parameter stability,
DSR i PBO tam, gdzie liczba obserwacji pozwala.

`PROMISING` wymaga jednocześnie: dodatniego aggregate holdout net PnL w base i
adverse, dodatniej mediany per-symbol net PnL (co najmniej 2/3 symboli), co
najmniej 30 holdout trades aggregate, DSR > 0.95, PBO < 0.25, brak dominacji
jednego symbolu > 70% dodatniego PnL oraz Brier lepszy od prior baseline.
Brak któregokolwiek warunku = `INCONCLUSIVE` lub `REJECT`; nigdy automatyczna
promocja. Wynik pozostaje wyłącznie RESEARCH/BACKTEST — zero PAPER/LIVE.

## Wyniki

Definitywny przebieg wykonano na VPS na commicie `2b67727`. Dataset zawierał
3337 nienakładających się setupów (`BTC=1084`, `ETH=1097`, `SOL=1156`) ze
wspólnego okresu 2021-10-15–2026-08-26. Końcowy holdout miał 666 setupów z
okresu 2025-08-29 15:00 UTC–2026-08-24 23:00 UTC. Jego identyfikator to
`c58baab7671a373d5ebf`. Wszystkie 14 zamrożonych prób zakończyły obliczenia i
zostały zapisane jako `TRIAL-000101`–`TRIAL-000114` w globalnym ledgerze.

| Model | Brier | AUC | Base net PnL | Base Sharpe | Base trades | Adverse net PnL | Adverse trades | DSR (114 trials) | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| ExtraTrees | 0.248661 | 0.495840 | 0.000000 | 0.000 | 0 | 0.000000 | 0 | 0.004992 | FAIL |
| Logistic Regression | 0.248915 | 0.510342 | 0.000000 | 0.000 | 0 | 0.000000 | 0 | 0.004992 | FAIL |
| LightGBM | 0.249028 | 0.488231 | 0.000000 | 0.000 | 0 | 0.000000 | 0 | 0.004992 | FAIL |
| Random Forest | 0.249139 | 0.488885 | +0.019885 | 0.788 | 4 | 0.000000 | 0 | 0.042420 | FAIL |
| XGBoost | 0.250156 | 0.481930 | -0.115067 | -0.569 | 19 | +0.016760 | 5 | 0.000594 | FAIL |

`PBO` pozostaje `null`, ponieważ pięć expanding folds nie tworzy dostatecznej
liczby poprawnych partycji CSCV; raport nie zastępuje tego braku zerem ani
korzystnym domysłem. Random Forest wykonał tylko cztery transakcje base
(`BTC=3`, `ETH=1`, `SOL=0`) i żadnej adverse, więc jego dodatni wynik nie ma
wymaganej liczebności ani odporności kosztowej. XGBoost był ujemny aggregate w
base; dodatni wynik SOL nie skompensował strat BTC i ETH. Pozostałe modele
poprawnie wybrały `WAIT` dla całego holdoutu, ale nie dowiodły edge.

Żaden model nie przeszedł minimalnej bramki dodatniego base i adverse oraz 30
transakcji w obu scenariuszach. `winner=null`, a werdykt brzmi **REJECT**.
XGBoost i LightGBM nie pokonały istniejących baseline'ów. Pełny, strict-JSON
manifest (243411 B) pozostaje artefaktem VPS pod
`reports/ml-model-tournament-v1/manifest.json`; SHA-256:
`8f0b6e63fe570cc31af540e2c93efa42e687ee0e8a4a3b66e8481f73467c0054`.
Generated reports nie są commitowane zgodnie z polityką repo.

## Następny najlepszy eksperyment

**B — Triple Barrier labels.** Pierwszy turniej obalił tezę, że sam bardziej
złożony klasyfikator naprawi stały 24-godzinny meta-label. Najwyższą wartość ma
teraz prerejestrowane sprawdzenie etykiety zależnej od ścieżki ceny (zamrożone
profit-take, stop-loss i vertical barrier), na tych samych kandydatach i bez
ponownego użycia holdoutu V1. Nie należy rozszerzać search space modeli ani
stroić gate'u V1.
