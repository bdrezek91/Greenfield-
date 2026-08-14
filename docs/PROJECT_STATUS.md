# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 13)

---

## CURRENT PHASE

**PHASE 13 — AI-enhanced strategy** — UKOŃCZONA.

Pierwsza strategia wykorzystująca model z Fazy 12 — wyłącznie jako filtr
sygnału (trade filtering), nigdy jako samodzielny decydent. Zero LLM w
ścieżce decyzyjnej; cała logika deterministyczna i audytowalna.

---

## DONE (Faza 13)

- `src/strategies/signals.py` — `momentum_signal()`, czysta funkcja
  wydzielona z `Momentum`, współdzielona przez `Momentum` i nową
  `MLFiltered` — jedna implementacja reguły bazowej, nie dwie, które
  mogłyby się rozjechać.
- `src/ml/model_io.py` — `save_model`/`load_model`: model to plik
  `.joblib` + sidecar `.json` (`ModelMetadata`: kolumny cech,
  symbol/timeframe, okno treningowe, git commit...). Brak sidecara →
  twardy `FileNotFoundError` — artefakt modelu bez schematu i pochodzenia
  nie jest bezpieczny do użycia.
- `src/strategies/ml_filtered.py` — `MLFiltered`: `base_signal =
  momentum_signal(...)`; jeśli `None` — flat; w przeciwnym razie
  `model.predict_proba(cechy_na_tym_barze) >= probability_threshold`
  decyduje, czy wejść. Dwie bramki bezpieczeństwa egzekwowane w runtime,
  nie tylko udokumentowane:
  1. **Schema guard**: `model.feature_columns` musi być identyczne z
     `FEATURE_COLUMNS` z Fazy 11 — sprawdzane przy konstrukcji, twardy
     błąd przy niezgodności.
  2. **In-sample guard**: strategia odmawia handlu na każdym barze
     `<= metadata.train_end`, nawet jeśli okno backtestu podane przez
     wywołującego nachodzi na okres treningowy — to jest bramka
     wewnątrz strategii, nie tylko zasada w dokumentacji (zgodnie z
     `docs/RESEARCH_METHODOLOGY.md`: nigdy nie oceniaj strategii na
     danych, na których była optymalizowana).
- `scripts/export_ml_model.py` — dopasowuje finalny model na pełnym
  zakresie dat i eksportuje artefakt; celowo NIE ocenia modelu (to robi
  `src/ml/evaluation.py` z Fazy 12) — jedna odpowiedzialność.
- `scripts/run_ml_strategy.py` — dedykowany CLI dla `ml_filtered`
  (osobny od `run_backtest.py`, bo `MLFilteredConfig.model_path` nie ma
  bezpiecznej wartości domyślnej — `AI_ENHANCED_STRATEGIES` w
  `registry.py` celowo poza `ALL_STRATEGIES`).
- Testy: `tests/unit/test_signals.py` (5), `tests/unit/test_model_io.py`
  (7), `tests/integration/test_ml_filtered.py` (5 — próg
  akceptacji/odrzucenia, brak sygnału bazowego, bramka in-sample, bramka
  schematu cech — wszystkie przez prawdziwy silnik NautilusTrader).
- **Realne uruchomienie end-to-end**: eksport modelu
  `logistic_regression` na syntetycznych danych BTCUSDT (2024-01-01 do
  2024-03-31), backtest `ml_filtered` ściśle poza próbą (2024-04-02 do
  2024-06-15, próg 0.55) — 30 transakcji, Sharpe -3.95, wobec
  niefiltrowanej `momentum` na tym samym oknie: 70 transakcji, Sharpe
  -5.65. Filtr ograniczył liczbę transakcji i, w tym przebiegu,
  ograniczył straty względem strategii bez filtra — obie strategie mimo
  to tracą, czego można się spodziewać na syntetycznych danych typu
  random walk bez realnej przewagi. To walidacja poprawności działania
  (plumbing), nie dowód badawczy, że filtr pomaga — żaden model nie był
  jeszcze oceniany na realnych danych Bybit w tej sesji.

---

## TESTY / WALIDACJA (Faza 13)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (69 plików źródłowych).
- `python3 -m pytest -q` — **317/317 testów przechodzi** (302 z Faz 1-12 +
  15 nowych).
- `detect-secrets scan` — brak nowych sekretów.
- Realne uruchomienie end-to-end opisane wyżej, zapisane też w
  `docs/ML.md`.

---

## KNOWN ISSUES

- `MLFiltered` przelicza cechy na każdym barze przez pełne przeliczenie
  `build_feature_matrix()` na ograniczonym oknie (`feature_warmup_bars`,
  domyślnie 150) — wystarczające do backtestu, ale nie jest to sposób, w
  jaki produkcyjne (paper/live) obliczanie cech powinno działać
  (potrzebne przyrostowe obliczanie cech, nie pełny przelicz-od-nowa co
  bar) — do adresowania, gdy pojawi się faza z realnym long-running paper
  trading.
- Żaden model AI-enhanced nie był oceniany na realnych danych Bybit —
  tylko na danych syntetycznych (blokada sieciowa `api.bybit.com`,
  niezmieniona od Fazy 2/10/11/12).
- `MLFilteredConfig` udostępnia tylko domyślny `FeatureConfig` z Fazy 11
  (lookbacki cech nie są konfigurowalne przez CLI/config strategii) —
  wystarczające na ten etap, rozszerzenie trywialne, gdy zajdzie potrzeba
  badawcza.

---

## NEXT

Framework (Faza 11), pierwsze modele (Faza 12) i pierwsza strategia
AI-enhanced (Faza 13) są gotowe. Kolejne kroki (do rozpoczęcia dopiero po
wyraźnym poleceniu): **PHASE 14 — długo działający paper trading**
(wymaga realnej łączności z Bybit testnet, obecnie zablokowanej w tej
sesji) lub rozszerzenie Fazy 13 o dodatkowe strategie bazowe filtrowane
przez ML (breakout, volatility_expansion) i porównanie z ich
niefiltrowanymi wersjami na realnych danych.

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę?
   Częściowo zaadresowane w Fazie 7 — natywna pętla przez `BacktestEngine`
   wystarczająco szybka jak dotąd.
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3.
3. Kiedy potrzebne będą dane tick-level/order-book? Faza 10 dodała
   konkretny powód (spread przy wykonaniu); Fazy 11-13 nie dodały nowych.
4. Mechanizm eksperyment-trackingu — zaadresowane w Fazie 4.
5. Czy prosty model liniowy (logistic regression) systematycznie pokonuje
   modele drzewiaste na tego typu cechach, czy to artefakt syntetycznych
   danych z Fazy 12? Wymaga potwierdzenia na realnych danych.
6. Czy filtr ML rzeczywiście poprawia wyniki strategii bazowej na realnych
   danych, czy różnica z Fazy 13 (30 vs 70 transakcji, lepszy Sharpe) jest
   artefaktem syntetycznych danych? Wymaga potwierdzenia poza tą sesją.

---

## Decyzje projektowe podjęte w Fazie 13

- Model filtruje sygnał wejścia z reguły deterministycznej
  (`momentum_signal`), nie generuje go samodzielnie — zgodnie z zasadą
  "trade filtering / setup scoring", nie "next-candle prediction", z
  sekcji 22 wymagań, i z zasadą "LLM/ML nigdy nie podejmuje decyzji
  handlowej przez prompt" (tu nawet nie ma LLM — jest zamrożony,
  wersjonowany artefakt scikit-learn).
- Bramka in-sample (`train_end`) zaimplementowana WEWNĄTRZ strategii, nie
  tylko jako zasada proceduralna — błąd w wyborze dat backtestu przez
  operatora nie może po cichu zanieczyścić wyniku danymi treningowymi.
- `AI_ENHANCED_STRATEGIES` celowo POZA `ALL_STRATEGIES` — generyczne
  skrypty (`compare_strategies.py`, `monte_carlo.py`, ...) konstruują
  config bez dodatkowych argumentów; `MLFilteredConfig.model_path` bez
  wartości domyślnej rozwaliłby je w mylący sposób. Dedykowany
  `run_ml_strategy.py` zamiast tego.
- `momentum_signal()` wydzielony do `src/strategies/signals.py` i
  reużyty przez `Momentum` — ten sam wzorzec DRY co reużycie
  `src.regimes.indicators` przez `src/features/volatility.py` w Fazie 11.
- `scripts/export_ml_model.py` nie ocenia modelu — jedna
  odpowiedzialność (eksport), ocena zostaje w `src/ml/evaluation.py` z
  Fazy 12, żeby uniknąć dwóch rozjeżdżających się implementacji tej samej
  logiki.

---

## Faza 12 — ML baseline models (zakończona)

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

Walidacja: ruff/mypy clean, pytest 302/302 (281 + 21 nowych). Trzeci
błąd tej samej klasy co Fazy 2 `.gitignore` — nieprzykotwiczony wzorzec
`models/` przesłaniał `src/ml/models/`, naprawiony przez zakotwiczenie do
`/reports/models/`.

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
