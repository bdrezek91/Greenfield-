# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 12)

---

## CURRENT PHASE

**PHASE 12 — ML baseline models** — UKOŃCZONA.

Pierwsze realne modele (Logistic Regression, Random Forest, Extra Trees)
uruchomione przez framework z Fazy 11, porównane z naiwnym baseline'em
(prior klasy) na każdym foldzie osobno, nie tylko średnio. `scikit-learn`
aktywowany; `lightgbm` zainstalowany, ale nieużywany (zgodnie z zasadą:
najpierw pokonaj prostszy baseline).

---

## DONE (Faza 12)

- `src/ml/models/naive.py` — `NaivePriorBaseline`: przewiduje stały prior
  klasy treningowej, ignorując cechy — to jest poprzeczka, którą każdy
  realny model musi pokonać out-of-sample (sekcja 24).
- `src/ml/models/sklearn_models.py` — `LogisticRegressionModel`,
  `RandomForestModel`, `ExtraTreesModel`, wszystkie zgodne z kontraktem
  `src.ml.baseline.Model`, wszystkie z `class_weight="balanced"`. Modele
  drzewiaste dodatkowo eksponują natywną ważność cech
  (`.feature_importances()`), raportowaną obok, nigdy zamiast,
  permutation importance z Fazy 11.
- `src/ml/evaluation.py` — `run_comparison()` (świeży model per fold, bez
  przenoszenia stanu), `summarize_comparison()` (ranking po średnim Brier
  Score), `beats_baseline_every_fold()` — wymaga ścisłej przewagi nad
  baseline'em na *każdym* foldzie, nie tylko średnio.
- `scripts/train_baseline_models.py` — pełny przebieg end-to-end: dane →
  cechy (Faza 11) → binarna etykieta kierunku → purged/embargo foldy →
  trening 4 modeli per fold → tabela porównawcza → krzywa kalibracji i
  permutation importance dla najlepszego modelu.
- `pyproject.toml` grupa `ml` (`scikit-learn`, `lightgbm`) aktywowana —
  zainstalowana i używana (tylko scikit-learn na razie; lightgbm celowo
  jeszcze nieużyty, zgodnie z zasadą "najpierw prostszy baseline").
- Testy: `tests/unit/test_ml_models.py` (12 — w tym sanity-check "modele
  drzewiaste/liniowy pokonują naiwny baseline na w pełni separowalnych
  syntetycznych danych"), `tests/unit/test_ml_evaluation.py` (9).
- **Trzeci błąd, ten sam typ co w Fazie 2**: `.gitignore` miał
  nieprzykotwiczony wzorzec `models/` (przeznaczony dla katalogów z
  wytrenowanymi artefaktami), który przesłaniał `src/ml/models/` — cały
  nowy pakiet modeli był niewidoczny dla `git status`. Naprawione przez
  zakotwiczenie do `/reports/models/`, dokładnie ten sam wzorzec naprawy
  co `/data/` w Fazie 2.
- **Realne uruchomienie end-to-end** na syntetycznych danych OHLCV (3000
  świec 1h, łagodny autoskorelowany dryf, 5 purgowanych foldów):
  `logistic_regression` miał ściśle niższy Brier Score niż `naive_prior`
  na *każdym* z 5 foldów (średnio 0.2487 vs 0.2506), natomiast
  `random_forest` i `extra_trees` **nie pokonały** baseline'u na tych
  danych. To dokładnie ten typ wyniku, który framework ma uwidaczniać —
  nie każdy model przechodzi próg, i to jest widoczne wprost w tabeli
  porównawczej, a nie ukryte w średniej. To nie jest wniosek badawczy o
  prawdziwym rynku — dane są syntetyczne (random walk), żaden model nie
  był jeszcze oceniany na realnych świecach Bybit w tej sesji.

---

## TESTY / WALIDACJA (Faza 12)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (66 plików źródłowych).
- `python3 -m pytest -q` — **302/302 testów przechodzi** (281 z Faz 1-11 +
  21 nowych).
- `detect-secrets scan` — brak nowych sekretów.
- Realne uruchomienie `scripts/train_baseline_models.py` opisane wyżej —
  wynik zapisany też w `docs/ML.md`.

---

## KNOWN ISSUES

- Żaden model nie był oceniany na realnych danych Bybit — tylko na danych
  syntetycznych (blokada sieciowa do `api.bybit.com`, niezmieniona od Fazy
  2/10/11).
- `lightgbm` zainstalowany, ale nieużyty — świadomie odłożony do momentu,
  gdy prostszy baseline zostanie realnie pokonany na prawdziwych danych.
- Etykieta użyta w Fazie 12 to prosta binarna klasyfikacja kierunku
  (`forward_return > 0`) — `expected_r_label` (uwzględniająca ATR) i
  regresja `forward_return_label` jako cel liczbowy nie są jeszcze
  włączone do porównania modeli; to naturalne rozszerzenie frameworku
  `src/ml/evaluation.py`, gdy pojawi się taka potrzeba badawcza.

---

## NEXT

Framework badawczy (Faza 11) i pierwsze modele bazowe (Faza 12) są
gotowe. Kolejne kroki (do rozpoczęcia dopiero po wyraźnym poleceniu) — do
wyboru zależnie od priorytetu: rozszerzenie porównania modeli o regresję/
`expected_r_label`, ocena na realnych danych Bybit (gdy dostępna będzie
sieć), lub PHASE 13 — AI-enhanced strategies (wykorzystanie modelu z Fazy
12 jako filtra sygnału w strategii z Fazy 6, nie jako samodzielnego
decydenta — zgodnie z zasadą "LLM/ML nigdy nie podejmuje decyzji
handlowej przez prompt").

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę?
   Częściowo zaadresowane w Fazie 7 — natywna pętla przez `BacktestEngine`
   wystarczająco szybka jak dotąd.
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3.
3. Kiedy potrzebne będą dane tick-level/order-book? Faza 10 dodała
   konkretny powód (spread przy wykonaniu); Fazy 11-12 nie dodały nowych.
4. Mechanizm eksperyment-trackingu — zaadresowane w Fazie 4.
5. Czy prosty model liniowy (logistic regression) systematycznie pokonuje
   modele drzewiaste na tego typu cechach, czy to artefakt syntetycznych
   danych z Fazy 12? Wymaga potwierdzenia na realnych danych.

---

## Decyzje projektowe podjęte w Fazie 12

- `beats_baseline_every_fold()` wymaga przewagi na *każdym* foldzie, nie
  tylko średnio — spójne z zasadą stabilności parametrów z Fazy 7
  (odrzucaj wyniki niestabilne, nawet jeśli średnia wygląda dobrze).
- `class_weight="balanced"` używany domyślnie we wszystkich modelach
  scikit-learn — etykiety handlowe rzadko są 50/50, a model bez tej wagi
  nauczyłby się przewidywać klasę większościową, co naiwny baseline i tak
  już demaskuje za darmo.
- Natywna ważność cech modeli drzewiastych (`.feature_importances()`)
  zaimplementowana jako metoda dodatkowa, nie zamiast, permutation
  importance z Fazy 11 — zgodnie z zasadą "brak modelu czarnej skrzynki
  bez diagnostyki" z `docs/ML.md`.
- Etykieta w `scripts/train_baseline_models.py` to prosta klasyfikacja
  binarna (`forward_return > 0`), nie `expected_r_label` — najprostszy
  możliwy cel na pierwsze uruchomienie porównania modeli; rozszerzenie do
  R-multiple jest naturalnym następnym krokiem, nie wymaga zmian we
  frameworku.
- `lightgbm` pozostaje zainstalowany, ale nieużyty w tej fazie — aktywacja
  dopiero gdy prostszy baseline (drzewa/regresja logistyczna) faktycznie
  zostanie pokonany na realnych danych, zgodnie z zasadą "baseline-first"
  z sekcji 24.

---

## Faza 11 — ML research framework (zakończona)

- `src/features/` — cechy z sekcji 23 wymagań: `price.py` (returns,
  momentum, distance from high/low, trend slope), `volatility.py`
  (reużywa ATR/realized volatility z `src.regimes.indicators` z Fazy 8,
  nie duplikuje), `volume.py` (relative volume, volume trend),
  `structure.py` (higher-high/lower-low, breakout/breakdown — celowo
  przyczynowa aproksymacja struktury swing, bez naiwnej detekcji
  fraktalnej, która wymagałaby przyszłych świec), `pipeline.py`
  (`build_feature_matrix()` — jeden punkt złożenia wszystkich cech).
- `src/ml/labels.py` — `forward_return_label`, `direction_label`,
  `expected_r_label`. Etykiety świadomie patrzą w przyszłość (to jest ich
  rola jako celu, nie cechy) — każda zwraca też `label_end_time`, potrzebny
  do purgingu.
- `src/ml/splits.py` — `time_series_split` (czysto chronologiczny) i
  `purged_kfold_split` (usuwa z treningu wiersze, których okno etykiety
  nachodzi na fold testowy, plus embargo) — nigdy losowy
  `train_test_split`, zgodnie z sekcją 25.
- `src/ml/calibration.py` — `brier_score`, `calibration_curve`,
  zaimplementowane od zera (bez zależności ML).
- `src/ml/explainability.py` — `permutation_importance`, niezależny od
  konkretnego modelu (działa na dowolnym obiekcie z `.predict()`).
- `src/ml/baseline.py` — protokół `Model` (`fit`/`predict`/
  `predict_proba`) jako kontrakt dla Fazy 12.
- `scripts/prepare_ml_dataset.py` — demonstracja całego frameworku
  end-to-end na realnych danych: dane → cechy → etykieta → purged split,
  bez trenowania modelu.
- **Pierwszy realny błąd znaleziony przez sanity-check przed napisaniem
  testów**: `time_series_split()` w pierwszej wersji zwracał pusty zbiór
  treningowy dla pierwszego folda (błąd w matematyce granic okien).
  Naprawione przed dodaniem testów, nie po.
- **Drugi błąd znaleziony przez testy**: `relative_volume()` liczyła
  średnią z oknem obejmującym bieżący bar, co go rozwadniało — zmieniono
  na standardową definicję (średnia z *poprzednich* N barów).
- Testy: `tests/unit/test_features_price.py` (8), `tests/unit/
  test_features_other.py` (9), `tests/unit/test_labels.py` (6),
  `tests/unit/test_splits.py` (10 — w tym silna weryfikacja "żaden wiersz
  treningowy nie nachodzi na swój fold testowy"), `tests/unit/
  test_calibration.py` (9), `tests/unit/test_explainability.py` (6),
  `tests/lookahead/test_feature_no_lookahead.py` (1 — cały pipeline cech
  na raz, ta sama metoda strukturalna co w Fazie 8).

Walidacja: ruff/mypy clean, pytest 281/281 (232 + 49 nowych), sanity-checki
`brier_score` (0.0/0.25 zgodne z literaturą), realne uruchomienie
`scripts/prepare_ml_dataset.py` na 2400 syntetycznych świecach (2264
wiersze po dropna, 5 purgowanych foldów).

---

## Faza 10 — Paper execution (zakończona)

`src/execution/mode.py` (realna bramka `LIVE`, egzekwowana od tej fazy),
`intent.py`/`adapter.py` (formalizacja SIGNAL→RISK→ORDER INTENT→EXECUTION),
`fill_tracking.py` (expected vs actual: slippage, latency, rejected,
data issues), `paper_node.py` (natywny adapter Bybit z NautilusTrader —
te same, niezmienione klasy strategii co w backteście, uruchamiane na
Bybit testnet). 32 testy. Realna łączność z Bybit testnet niezweryfikowana
w tej sesji (blokada sieciowa `api.bybit.com`) — zweryfikowano maksimum
możliwego: pełną budowę `TradingNode` bez łączenia się z siecią.

---

## Faza 9 — Risk + portfolio (zakończona)

`src/risk/engine.py` (`RiskEngine`, stanowy: max concurrent positions, max
daily loss, max drawdown, risk per trade / volatility targeting, max
portfolio risk, max leverage) — wszystkie strategie z Faz 5-6
zrefaktoryzowane, by delegować sizing do risk engine. `src/portfolio/
aggregation.py` (agregacja post-hoc: equity, korelacja, koncentracja HHI,
drawdown, ekspozycja). 26 testów. **Trzy realne błędy** znalezione przez
testy/rzeczywiste uruchomienia: brak roll-over dnia w `close_position()`,
kolizja nazw atrybutów `self._closes` między klasą bazową a podklasami
(zerowa liczba transakcji), duplikaty znaczników czasu psujące
`reindex()` w agregacji portfelowej.

---

## Faza 8 — Market regimes (zakończona)

`src/regimes/indicators.py` (ATR, ADX, realized volatility, struktura MA —
bez AI/ML), `classifier.py` (`trend_regime`, `vol_regime`), `analysis.py`
(rozbicie metryk per reżim, as-of backward merge). Pierwszy realny wpis w
`tests/lookahead/`, zarezerwowanym od Fazy 1. 27 testów.

---

## Faza 7 — Walk-forward + robustness (zakończona)

Framework walk-forward (`src/backtesting/walk_forward.py`), pełnowymiarowy
Monte Carlo (`src/analytics/monte_carlo.py`, w pełni zwektoryzowany),
diagnostyka stabilności parametrów (`flag_isolated_spikes()`). 29 testów.

---

## Faza 6 — Pierwsze rodziny strategii (zakończona)

Trzy rodziny poza benchmarkami (`momentum`, `breakout`,
`volatility_expansion`). `src/backtesting/runner.py` i
`scripts/compare_strategies.py` — porównanie z Deflated Sharpe Ratio. 9
testów.

---

## Faza 5 — Benchmark strategies (zakończona)

Cztery obowiązkowe benchmarki jako strategie NautilusTrader ze wspólną
bazą wymuszającą identyczny sizing i holding period. 19 testów.

---

## Faza 4 — Analytics + experiment tracking (zakończona)

`ExperimentRecord`/`ExperimentStore`, pełny zestaw metryk z sekcji 18,
bootstrap i Deflated Sharpe Ratio. 34 testy.

### Walidacja Faz 1-4 (audyt przed Fazą 5)

Niezależny audyt znalazł i naprawił 3 błędy: podwójne liczenie funding na
granicy rozliczenia, nietypowy mianownik downside deviation w Sortino,
brak walidacji CLI (ryzyko path traversal). `pytest` 90/90 po poprawkach.

---

## Wcześniejsze fazy (1-3) — skrót

- **Faza 1**: szkielet repo, Docker, CI, dokumentacja bazowa.
- **Faza 2**: warstwa danych (`src/data`) — pobieranie klines Bybit,
  walidacja integralności, storage Parquet.
- **Faza 3**: silnik backtestu (`src/backtesting`) — instrumenty, adapter
  danych, koszty (fee/slippage/funding), `BacktestEngine`.

Pełne szczegóły tych faz — w historii commitów i wcześniejszych wersjach
tego dokumentu (git log).
