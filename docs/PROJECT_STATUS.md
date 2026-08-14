# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 11)

---

## CURRENT PHASE

**PHASE 11 — ML research framework** — UKOŃCZONA.

Framework badawczy pod ML (feature engineering, etykiety, podział
czasowy/purged, kalibracja, wyjaśnialność) jest zaimplementowany i
przetestowany. **Żaden model jeszcze nie jest trenowany** — to celowe,
zgodnie z podziałem faz: Faza 11 buduje framework, Faza 12 wypełni go
pierwszymi modelami bazowymi.

---

## DONE (Faza 11)

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

---

## TESTY / WALIDACJA (Faza 11)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (62 pliki źródłowe).
- `python3 -m pytest -q` — **281/281 testów przechodzi** (232 z Faz 1-10 +
  49 nowych z Fazy 11).
- Sanity-checki przed testami (ten sam wzorzec co ADX≈100 w Fazie 8):
  `brier_score` = 0.0 dla idealnego predyktora, 0.25 dla stałego 0.5 na
  wynikach 50/50 — dokładnie zgodne z referencyjnymi wartościami z
  literatury; `permutation_importance` poprawnie przypisuje zerową ważność
  cesze ignorowanej przez model.
- **Realne uruchomienie end-to-end**: `scripts/prepare_ml_dataset.py` na
  2400 syntetycznych świecach — 2264 wiersze po odrzuceniu NaN, 5
  purgowanych foldów z sensowną liczbą odrzuconych wierszy (22-46 per
  fold).
- `detect-secrets scan` — brak nowych sekretów.

---

## KNOWN ISSUES

- `src/ml/explainability.py` implementuje tylko permutation importance —
  natywna ważność cech (`.feature_importances_`) i SHAP wymagają realnego
  wytrenowanego modelu i biblioteki `shap`, które pojawią się dopiero w
  Fazie 12. Jawnie udokumentowane jako zakres tej fazy, nie przeoczenie.
- `scikit-learn`/`lightgbm` (grupa zależności `ml`) celowo NIE
  zainstalowane — żaden kod jeszcze ich nie używa. Aktywacja w Fazie 12
  wraz z pierwszymi modelami.
- (Bez zmian od Fazy 10) Realna łączność z Bybit testnet nadal
  niezweryfikowana w tej sesji.

---

## NEXT

**PHASE 12 — ML models**, do rozpoczęcia dopiero po kolejnym wyraźnym
poleceniu. W jej zakresie docelowo: aktywacja `scikit-learn`/`lightgbm`,
pierwsze modele bazowe (Logistic Regression, Random Forest, Extra Trees)
ocenione przez framework z Fazy 11, porównanie z prostszym baseline
zanim uzasadni się cokolwiek droższego (sekcja 24 wymagań).

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę?
   Częściowo zaadresowane w Fazie 7 — natywna pętla przez `BacktestEngine`
   wystarczająco szybka jak dotąd.
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3.
3. Kiedy potrzebne będą dane tick-level/order-book? Faza 10 dodała
   konkretny powód (spread przy wykonaniu); Faza 11 nie dodała nowych.
4. Mechanizm eksperyment-trackingu — zaadresowane w Fazie 4.

---

## Decyzje projektowe podjęte w Fazie 11

- Faza 11 buduje wyłącznie framework (cechy, etykiety, splity, kalibracja,
  wyjaśnialność) — zero wytrenowanych modeli, zgodnie z dosłownym
  rozdziałem faz w briefie projektu (Faza 11 = framework, Faza 12 =
  modele). Ten sam wzorzec co w Fazie 5 (najpierw framework porównania,
  potem strategie).
- `volatility.py` reużywa wskaźników z `src.regimes.indicators` zamiast je
  duplikować — ATR i realized volatility miały już swoje sanity-checki i
  testy lookahead w Fazie 8.
- Struktura cenowa (`structure.py`) zaimplementowana jako przyczynowa
  aproksymacja (porównanie dwóch sąsiednich, nienachodzących na siebie
  okien), nie naiwna detekcja fraktalna (high/low porównywane do świec
  przed I po) — ta druga metoda jest klasyczną pułapką lookahead.
- `permutation_importance` zaimplementowany jako w pełni niezależny od
  biblioteki ML (działa na dowolnym obiekcie z `.predict()`) — gotowy do
  użycia z jakimkolwiek modelem, który pojawi się w Fazie 12, bez zmian.
- `calibration.py` napisany od zera zamiast korzystać ze scikit-learn —
  unika przedwczesnej instalacji ciężkiej zależności ML na etapie, gdzie
  jeszcze nie ma żadnego modelu do skalibrowania.

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
