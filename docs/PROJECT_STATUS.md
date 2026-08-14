# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 14)

---

## CURRENT PHASE

**PHASE 14 — Long-running paper trading** — UKOŃCZONA (z zastrzeżeniem —
zobacz KNOWN ISSUES).

Infrastruktura trwałości i obserwowalności dla długo działającej sesji
paper trading: nagrywanie realnych fillów do `FillTracker` z Fazy 10
(dotąd niepodłączone do niczego — realny brak zamknięty w tej fazie),
retry z backoff przy rozłączeniu, checkpointing stanu sesji na dysk.
Realna łączność z Bybit testnet nadal niezweryfikowana w tej sesji
(niezmienione ograniczenie sieciowe od Fazy 2).

---

## DONE (Faza 14)

- **Zamknięty realny brak z Fazy 10**: `FillTracker` istniał, ale nic go
  nie zasilało z żywej strategii — tylko z odtworzonych transakcji
  backtestu (`tests/integration/test_paper_dry_run.py`). Teraz
  `src/strategies/base.py:HoldForBarsStrategy` opcjonalnie (atrybut
  `session_recorder`, domyślnie `None`, ustawiany po konstrukcji — zero
  wpływu na istniejące strategie/testy) nagrywa `OrderIntent` tuż przed
  `submit_order()` i przekazuje realne zdarzenia `on_order_filled`/
  `on_order_rejected` do `src/execution/session_recorder.py:SessionRecorder`.
- `src/execution/session_recorder.py` — `SessionRecorder`: dopasowuje
  zdarzenia `OrderFilled`/`OrderRejected` po `client_order_id` do wcześniej
  zarejestrowanego zamiaru, karmi `FillTracker` z Fazy 10. Niedopasowany
  fill jest po cichu pomijany (np. zlecenie spoza tej strategii), nie jest
  to błąd do zgłaszania.
- `src/execution/session_state.py` — `SessionState` + `save_session_state`/
  `load_session_state` (JSON): metadane operacyjne sesji (licznik
  restartów, ostatni błąd, migawka podsumowania fillów) przetrwają pełny
  restart procesu, nie tylko wewnętrzny retry.
- `src/execution/heartbeat.py` — `HeartbeatMonitor`: wykrywanie
  "brak nowego bara od X sekund" jako ciągła wersja punktu z sekcji 32
  "data issues", nie tylko sprawdzana przy fillu.
- `src/execution/supervisor.py` — `PaperSessionSupervisor`: owija dowolne
  wywołanie (`node.run`) w pętlę retry z wykładniczym backoff, checkpointuje
  stan przed i po każdej próbie, poddaje się po `max_restarts` z
  `RestartsExhaustedError`. Wznawia licznik restartów z istniejącego
  checkpointu, jeśli taki jest (pełny restart procesu, nie tylko retry
  wewnątrz jednego wywołania).
- `scripts/run_paper_session.py` — dedykowany CLI: `paper_trade.py` +
  `SessionRecorder` podpięty do strategii + `PaperSessionSupervisor`
  wokół `node.run()` + checkpointing do `--checkpoint-path`.
- Testy: `tests/unit/test_session_state.py` (9), `tests/unit/
  test_heartbeat.py` (5), `tests/unit/test_supervisor.py` (6 — w tym retry
  z faktycznym wykładniczym backoff i wznowienie licznika restartów z
  checkpointu), `tests/unit/test_session_recorder.py` (4),
  `tests/integration/test_session_recorder_live.py` (2 — **realne
  zdarzenia `OrderFilled` z prawdziwego silnika NautilusTrader**, nie
  atrapy: liczba zarejestrowanych zamiarów dokładnie równa liczbie pozycji
  z backtestu, zero rozbieżności).

---

## TESTY / WALIDACJA (Faza 14)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (73 pliki źródłowe).
- `python3 -m pytest -q` — **343/343 testów przechodzi** (317 z Faz 1-13 +
  26 nowych).
- `detect-secrets scan` — brak nowych sekretów.
- **Realne uruchomienie**: `tests/integration/test_session_recorder_live.py`
  uruchamia `Momentum` przez prawdziwy silnik backtestu NautilusTrader z
  podpiętym `SessionRecorder` — liczba zarejestrowanych zamiarów równa
  liczbie zamkniętych pozycji z raportu backtestu, zero odrzuceń, średni
  slippage policzony poprawnie. To dowód, że `on_order_filled` faktycznie
  odbiera prawdziwe zdarzenia silnika, nie tylko że kod się kompiluje.

---

## KNOWN ISSUES

- **Nieoznaczone jako w pełni zweryfikowane**: `scripts/run_paper_session.py`
  i cała ścieżka retry/checkpoint wobec `node.run()` nie były uruchomione
  przeciw prawdziwemu Bybit testnet w tej sesji — ta sama blokada sieciowa
  `api.bybit.com`, niezmieniona od Fazy 2/10/11/12/13. Logika retry/backoff
  i nagrywanie fillów są zweryfikowane realnie (odpowiednio: przez wstrzyknięty
  `run_fn`, przez prawdziwy silnik backtestu), ale kompozycja tych trzech
  elementów wokół żywego `TradingNode.run()` jest zweryfikowana tylko
  strukturalnie (import się kompiluje, konstrukcja się udaje), nie
  end-to-end.
- `HeartbeatMonitor` zaimplementowany, ale nie podłączony jeszcze do
  żadnego źródła zdarzeń (np. `on_bar` strategii) — czysta, przetestowana
  logika gotowa do podłączenia, ale nie jest jeszcze aktywnie używana w
  `run_paper_session.py`. Naturalne rozszerzenie: wywoływać
  `heartbeat.record(now)` w `on_bar` i logować alert przy `is_stale()`.
- Checkpointing stanu sesji nie obejmuje pozycji/otwartych zleceń — to
  celowo poza zakresem (NautilusTrader ma własną trwałość cache/bazy
  danych, patrz `docs/VPS_DEPLOYMENT.md`); `SessionState` to wyłącznie
  metadane operacyjne sesji (restarty, błędy, podsumowanie fillów).

---

## NEXT

Cała infrastruktura od Fazy 11 do 14 jest gotowa poza jednym twardym
ograniczeniem: zerowa weryfikacja na realnej sieci Bybit w tej sesji.
Naturalne kolejne kroki (do rozpoczęcia dopiero po wyraźnym poleceniu):
walidacja `scripts/run_paper_session.py` na maszynie z realnym dostępem
sieciowym (VPS lub lokalnie) — to jest w praktyce warunek wstępny do
sensownego zamknięcia Fazy 14 jako w pełni zweryfikowanej; alternatywnie
**PHASE 15 — przygotowanie do LIVE** (kolejna bramka bezpieczeństwa ponad
`CONFIRM_LIVE_TRADING`, checklista operacyjna) może zacząć się równolegle,
skoro i tak zależy od tej samej niedostępnej w tej sesji sieci.

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę?
   Częściowo zaadresowane w Fazie 7 — natywna pętla przez `BacktestEngine`
   wystarczająco szybka jak dotąd.
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3.
3. Kiedy potrzebne będą dane tick-level/order-book? Faza 10 dodała
   konkretny powód (spread przy wykonaniu); Fazy 11-14 nie dodały nowych.
4. Mechanizm eksperyment-trackingu — zaadresowane w Fazie 4.
5. Czy prosty model liniowy (logistic regression) systematycznie pokonuje
   modele drzewiaste na tego typu cechach, czy to artefakt syntetycznych
   danych z Fazy 12? Wymaga potwierdzenia na realnych danych.
6. Czy filtr ML rzeczywiście poprawia wyniki strategii bazowej na realnych
   danych, czy różnica z Fazy 13 (30 vs 70 transakcji, lepszy Sharpe) jest
   artefaktem syntetycznych danych? Wymaga potwierdzenia poza tą sesją.
7. Ile realnie trwa bezpieczny `max_gap_seconds` dla `HeartbeatMonitor` na
   danym timeframe, zanim "brak bara" faktycznie oznacza problem, a nie
   tylko normalną przerwę w handlu (np. weekend na rynkach, gdzie to ma
   znaczenie)? Kryptowaluty handlują 24/7, więc mniej istotne dla BTCUSDT,
   ale warte ustalenia przed podłączeniem do prawdziwego alertingu.

---

## Decyzje projektowe podjęte w Fazie 14

- `session_recorder` dodany jako zwykły, opcjonalny atrybut na
  `HoldForBarsStrategy` (nie pole `BenchmarkStrategyConfig`) — msgspec
  `Struct` nie może przechowywać dowolnego obiektu Pythona, a wartość
  domyślna `None` nie zmienia zachowania żadnej z Faz 5-13 istniejących
  strategii ani ich testów.
- `SessionRecorder` po cichu pomija fill bez odpowiadającego zarejestrowanego
  zamiaru, zamiast rzucać wyjątek — brak dopasowania to nie błąd
  programistyczny (np. recorder podpięty w trakcie działania, zlecenie
  spoza tej strategii), tylko sytuacja, której nie da się ocenić.
- `PaperSessionSupervisor` przyjmuje `sleep_fn`/`now_fn` przez wstrzyknięcie
  zależności — ten sam wzorzec co wstrzykiwalny transport w Fazie 2 —
  dzięki czemu logika retry/backoff jest testowana natychmiastowo i
  deterministycznie, bez prawdziwego oczekiwania.
- `SessionState` traktowany jako niemutowalna migawka (`checkpoint()`/
  `bump_restart()` zwracają nowy obiekt) — zapobiega przypadkowemu
  zapisaniu częściowo zaktualizowanego stanu.
- `HeartbeatMonitor` zbudowany, ale świadomie NIE podłączony jeszcze do
  `run_paper_session.py` w tej fazie — samodzielna, przetestowana
  jednostka logiki, której podłączenie do konkretnego źródła zdarzeń to
  osobna, mała decyzja do podjęcia razem z realną walidacją sieciową.

---

## Faza 13 — AI-enhanced strategy (zakończona)

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

Walidacja: ruff/mypy clean, pytest 317/317 (302 + 15 nowych). Znany
limit z tej fazy (przeliczanie cech na pełnym oknie co bar, nie
przyrostowo) pozostaje aktualny — patrz `docs/ML.md`.

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
