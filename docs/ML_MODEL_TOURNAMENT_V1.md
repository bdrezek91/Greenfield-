# ML MODEL TOURNAMENT V1 — prerejestracja i raport

Status: **PREREGISTERED / HOLDOUT NOT OPENED**. Ta część dokumentu została
zamrożona przed pierwszym końcowym uruchomieniem holdoutu. Zmiana protokołu po
zobaczeniu holdoutu wymaga V2 i nowego trial ledger.

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

`expected_gross = p * mean_positive_gross - (1-p) * abs(mean_negative_gross)`

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

Do uzupełnienia automatycznie po jednorazowym holdoucie. Manifest i tabela
muszą zawierać także `INSUFFICIENT_DATA`, jeżeli wspólny dataset nie pozwala
utworzyć wszystkich zamrożonych foldów i klas.
