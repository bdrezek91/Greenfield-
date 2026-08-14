# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 7)

---

## CURRENT PHASE

**PHASE 7 — Walk-forward + robustness** — UKOŃCZONA.

Framework walk-forward (TRAIN/VALIDATION/TEST, przesuwane okno, equity
złożony z kolejnych okresów TEST), pełnowymiarowy Monte Carlo (10 000+
symulacji, w pełni zwektoryzowany) i diagnostyka stabilności parametrów
(sekcja 20 wymagań) są zaimplementowane, przetestowane i zweryfikowane
realnymi uruchomieniami end-to-end.

---

## DONE (Faza 7)

- `src/backtesting/walk_forward.py` — `generate_windows()` generuje okna
  TRAIN/VALIDATION/TEST przesuwane o długość TEST (kolejne okresy TEST są
  ciągłe, bez luk i nakładania); `run_walk_forward()` uruchamia każde okno
  i — gdy podano `param_grid` — wybiera najlepszego kandydata **wyłącznie
  na VALIDATION**, nigdy na TEST, wg konfigurowalnej metryki selekcji.
  Finalna krzywa equity i zbiór transakcji pochodzą wyłącznie z okresów
  TEST, sklejonych w jedną ciągłą krzywą przez łączenie zwrotów
  poszczególnych okien (nie surowych sald — to dawałoby sztuczne skoki na
  granicach okien). Udokumentowane, świadome ograniczenie: każde okno TEST
  startuje z nowym, świeżym saldem początkowym silnika (position sizing w
  oknie nie jest liczony względem jednej, ciągle kapitalizującej się
  krzywej) — patrz docstring modułu.
- `src/analytics/monte_carlo.py` — `run_monte_carlo()`: resampling
  sekwencji transakcji (nie zwrotów krzywej equity) z powtórzeniami,
  **w pełni zwektoryzowany** (10 000+ symulacji w ułamku sekundy dla
  realistycznej liczby transakcji), zwraca rozkład zwrotu, rozkład
  drawdown, rozkład najdłuższej serii strat i risk of ruin — dokładnie
  zestaw z sekcji 19 wymagań.
- `src/analytics/robustness.py:flag_isolated_spikes()` — diagnostyka
  stabilnych regionów parametrów z sekcji 20: flaguje punkt jako
  podejrzany, gdy jest lokalnym maksimum znacznie przewyższającym średnią
  swoich najbliższych sąsiadów (wzorzec "działa dla RSI=51.382, ale nie dla
  50 czy 52").
- `src/backtesting/runner.py` zrefaktoryzowany: wydzielona
  `run_backtest_window()` (silnik → trades/equity/metryki, bez zapisu
  eksperymentu) używana teraz zarówno przez `run_and_record()` jak i przez
  `walk_forward.py` — unika duplikacji orkiestracji silnika.
- `scripts/run_walk_forward.py` — CLI uruchamiające walk-forward (z
  opcjonalną siatką parametrów przez `--param-grid` jako JSON), zapisuje
  wynik jako jeden eksperyment.
- `scripts/monte_carlo.py` — CLI: backtest strategii → Monte Carlo na jej
  sekwencji transakcji, z ostrzeżeniem, jeśli `--n-simulations` < 10 000.
- Testy: `tests/unit/test_monte_carlo.py` (9 przypadków — deterministyczne
  serie transakcji z dokładnie policzonym oczekiwanym wynikiem: same
  wygrane → zero risk of ruin, same przegrane → risk of ruin=1.0 i seria
  strat = pełna długość; powtarzalność z seedem), `tests/unit/
  test_parameter_stability.py` (7 przypadków, w tym dokładnie wzorzec
  RSI=51.382 z sekcji 20), `tests/unit/test_walk_forward.py` (10
  przypadków — generowanie okien, ciągłość okresów TEST, matematyka
  sklejania krzywych equity z dokładnie policzonym oczekiwanym wynikiem),
  `tests/integration/test_walk_forward.py` (3 przypadki na prawdziwym
  silniku — bez siatki parametrów i z siatką, walidacja że selekcja
  parametrów faktycznie dzieje się na VALIDATION).

---

## TESTY / WALIDACJA (Faza 7)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (40 plików źródłowych).
- `python3 -m pytest -q` — **147/147 testów przechodzi** (118 z Faz 1-6 +
  29 nowych z Fazy 7).
- **Realne uruchomienia end-to-end** (nie tylko testy jednostkowe): na
  syntetycznych danych (4800 świec 1h, ~200 dni):
  - `scripts/run_walk_forward.py --strategy trend_following` (bez siatki
    parametrów): 14 okien, spójna krzywa equity, eksperyment zapisany.
  - `scripts/run_walk_forward.py --strategy momentum --param-grid '[...]'`
    (3 kandydaci × 14 okien = 56 przebiegów silnika): zakończone w ~5s,
    selekcja parametrów per-okno działa.
  - `scripts/monte_carlo.py --strategy trend_following --n-simulations
    10000`: 10 000 symulacji na 190 transakcjach — zwrócone natychmiast
    (potwierdzenie wektoryzacji), sensowne rozkłady zwrotu/drawdown/serii
    strat.
- `detect-secrets scan` — brak nowych sekretów.

---

## KNOWN ISSUES

- Sizing pozycji w oknach walk-forward liczony jest względem świeżego
  salda każdego okna TEST, nie względem jednej, ciągle kapitalizującej się
  krzywej equity — udokumentowane wprost jako świadome przybliżenie
  badawcze w `src/backtesting/walk_forward.py`, nie próba symulacji
  realnego, ciągłego wdrożenia.
- `flag_isolated_spikes()` zakłada dodatnie wartości metryki (np. Sharpe,
  profit factor) — przy ujemnym lub zerowym sąsiedztwie punkt jest
  pomijany (nieflagowany), nie błędnie interpretowany. Nie jest jeszcze
  podłączony do zautomatyzowanego workflow sweep-and-plot — to wymaga
  konkretnej rodziny strategii z aktywnie badanym zakresem parametrów.
- (Bez zmian od Faz 5-6) `configs/instruments.yaml` nadal placeholder;
  metryki na poziomie transakcji liczą tylko zamknięte pozycje.

---

## NEXT

**PHASE 8 — Market regimes**, do rozpoczęcia dopiero po kolejnym wyraźnym
poleceniu.

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę,
   czy będzie potrzebny VectorBT Pro? **Częściowo zaadresowane w Fazie 7**:
   natywna pętla przez `BacktestEngine` (bez VectorBT) obsłużyła 56
   przebiegów silnika (14 okien × 3 kandydatów + testy) w ~5s na
   syntetycznych danych — na razie wystarczająco szybkie. Do ponownej
   oceny przy większych siatkach parametrów/dłuższych zakresach dat.
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3;
   otwarte pozostaje przejście na model dynamiczny i dobór rzeczywistej
   stawki.
3. Kiedy potrzebne będą dane tick-level/order-book?
4. Mechanizm eksperyment-trackingu — zaadresowane w Fazie 4 (JSON Lines +
   sekwencyjne ID).

---

## Decyzje projektowe podjęte w Fazie 7

- Monte Carlo resampluje **sekwencję transakcji**, nie zwroty krzywej
  equity — zgodne z konwencyjnym znaczeniem "risk of ruin" i "losing
  streak" w ocenie systemów tradingowych (path-dependency na poziomie
  transakcji, nie okresów czasowych).
- Krzywa equity walk-forward sklejana przez łączenie **zwrotów**
  poszczególnych okien TEST, nie surowych sald — surowa konkatenacja
  dawałaby sztuczny "reset" salda na każdej granicy okna (każde okno
  startuje od nowa w silniku). Jawnie udokumentowane jako przybliżenie:
  sizing pozycji w oknie nadal liczony względem świeżego salda tego okna,
  nie względem sklejonej krzywej.
- Wybór parametrów w walk-forward dzieje się wyłącznie na VALIDATION,
  wynik raportowany wyłącznie z TEST — podstawowa zasada z sekcji 16
  wymagań ("nigdy nie oceniaj strategii na tych samych danych, na których
  była optymalizowana") wymuszona strukturalnie w kodzie, nie tylko
  opisana w dokumentacji.
- `flag_isolated_spikes()` jako samodzielna, ogólnego przeznaczenia
  funkcja analityczna (nie wbudowana w konkretną rodzinę strategii) —
  gotowa do użycia, gdy tylko pojawi się pierwsza faktyczna siatka
  parametrów do zbadania.

---

## Faza 6 — Pierwsze rodziny strategii (zakończona)

Trzy rodziny poza benchmarkami (`momentum`, `breakout`,
`volatility_expansion`), dzielące bazę `HoldForBarsStrategy` z Fazy 5.
`src/backtesting/runner.py` (pierwsza wersja) i `scripts/compare_strategies.py`
(zastępujący `compare_benchmarks.py`) — porównanie dowolnego zestawu
strategii z Deflated Sharpe Ratio per rodzina. 9 nowych testów. Błąd
znaleziony przy realnym uruchomieniu: DSR liczony na Sharpe annualizowanym
zamiast per-okres (naprawiony).

---

## Faza 5 — Benchmark strategies (zakończona)

Cztery obowiązkowe benchmarki (`buy_and_hold`, `random_entry`,
`trend_following`, `mean_reversion`) jako strategie NautilusTrader ze
wspólną bazą wymuszającą identyczny sizing i holding period. Adapter
`src/backtesting/reports.py` (positions/account report → generyczny
kontrakt trades/equity) zweryfikowany krzyżowo względem `realized_pnl`
silnika. 19 testów dodanych w tej fazie, wszystkie na prawdziwym silniku.

---

## Faza 4 — Analytics + experiment tracking (zakończona)

`src/analytics/experiment.py` — `ExperimentRecord`/`ExperimentStore`
(JSON Lines, sekwencyjne ID, `git_commit`/`dataset_version` automatyczne).
`src/analytics/metrics.py` — pełny zestaw metryk z sekcji 18 wymagań.
`src/analytics/robustness.py` — bootstrap i Deflated Sharpe Ratio.
`src/analytics/report.py` — renderowanie do Markdown. 34 testy.

### Walidacja Faz 1-4 (audyt przed Fazą 5)

Niezależny audyt znalazł i naprawił 3 błędy: podwójne liczenie funding na
granicy rozliczenia (`funding.py`), nietypowy mianownik downside deviation
w Sortino (`metrics.py`), brak walidacji `--symbol`/`--timeframe` na
granicy CLI (ryzyko path traversal). `pytest` 90/90 po poprawkach.

---

## Wcześniejsze fazy (1-3) — skrót

- **Faza 1**: szkielet repo, Docker, CI, dokumentacja bazowa.
- **Faza 2**: warstwa danych (`src/data`) — pobieranie klines Bybit,
  walidacja integralności, storage Parquet. Zweryfikowana jednostkowo na
  zamockowanym transporcie (blokada sieciowa `api.bybit.com` w tej sesji).
- **Faza 3**: silnik backtestu (`src/backtesting`) — instrumenty, adapter
  danych, koszty (fee/slippage/funding), `BacktestEngine` uruchamiany z
  zerem strategii jako kryterium akceptacji. Zweryfikowana realnym
  uruchomieniem end-to-end (nie zablokowana siecią/Dockerem).

Pełne szczegóły tych faz — w historii commitów i wcześniejszych wersjach
tego dokumentu (git log).
