# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 6)

---

## CURRENT PHASE

**PHASE 6 — Pierwsze rodziny strategii** — UKOŃCZONA.

Trzy pierwsze rodziny strategii poza obowiązkowymi benchmarkami
(`momentum`, `breakout`, `volatility_expansion`) działają przez ten sam
silnik i ten sam framework uczciwego porównania co benchmarki z Fazy 5.
`scripts/compare_strategies.py` uruchamia dowolny zestaw zarejestrowanych
strategii na tych samych danych/kosztach i liczy Deflated Sharpe Ratio dla
każdej rodziny względem liczby porównywanych strategii — pierwsze,
konkretne zastosowanie ochrony przed multiple testing z Fazy 4.

---

## DONE (Faza 6)

- `src/strategies/momentum.py` — jak Trend Following, ale z martwą strefą:
  brak sygnału, dopóki N-barowa zmiana ceny nie przekroczy progu
  procentowego (domyślnie 1%/10 barów).
- `src/strategies/breakout.py` — wejście przy zamknięciu poza poprzednim
  N-barowym high/low (kanał w stylu Donchiana) — strukturalnie inny sygnał
  niż momentum/trend (reakcja na nowe ekstremum, nie na dryf).
- `src/strategies/volatility_expansion.py` — wejście w kierunku świecy,
  której zakres (high-low) gwałtownie przekracza średni zakres z ostatnich
  N barów (rozstrzygnięcie "squeeze'u" w kierunkowy ruch) — sygnał oparty
  o zmianę reżimu zmienności, nie o cenę czy dryf.
- Wszystkie trzy dzielą bazę `HoldForBarsStrategy` z Fazy 5 (ten sam sizing,
  ten sam holding period) — framework uczciwego porównania rozszerza się
  bez zmian na nowe rodziny.
- `src/strategies/registry.py` — rozdzielone `BENCHMARK_STRATEGIES` (4
  obowiązkowe) / `STRATEGY_FAMILIES` (3 nowe) / `ALL_STRATEGIES` (suma).
- `src/backtesting/runner.py` — `run_and_record()`: wspólna orkiestracja
  silnik→metryki→eksperyment, wydzielona, żeby `scripts/run_backtest.py` i
  `scripts/compare_strategies.py` nie duplikowały tej logiki (refaktor,
  DRY — poprzednio ten kod żył tylko w `compare_benchmarks.py`).
- `scripts/run_backtest.py` — `--strategy` przyjmuje teraz dowolną z 7
  zarejestrowanych strategii; uruchomienie ze strategią automatycznie
  zapisuje eksperyment (wcześniej robił to tylko `compare_benchmarks.py`).
- `scripts/compare_strategies.py` (zastępuje `compare_benchmarks.py`) —
  `--strategies` (domyślnie wszystkie), dla każdej strategii spoza
  obowiązkowych benchmarków liczy i loguje Deflated Sharpe Ratio względem
  `n_trials` = liczba porównywanych strategii, oraz jawne porównanie
  Sharpe'a każdej rodziny względem Random Entry.
- Testy: `tests/integration/helpers.py` (wydzielone z `test_benchmark_
  strategies.py`, żeby nie duplikować fixture'ów danych syntetycznych
  między plikami testowymi), `tests/integration/test_strategy_families.py`
  (9 testów na prawdziwym silniku — momentum pozostaje płaski poniżej
  progu i wchodzi we właściwym kierunku powyżej; breakout pozostaje płaski
  wewnątrz zakresu i wchodzi na nowym high/low; volatility expansion
  pozostaje płaski przy jednolitych zakresach świec i wchodzi w kierunku
  świecy ze skokiem zakresu).

---

## TESTY / WALIDACJA (Faza 6)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (38 plików źródłowych).
- `python3 -m pytest -q` — **118/118 testów przechodzi** (109 z Faz 1-5 + 9
  nowych z Fazy 6).
- **Realne uruchomienie end-to-end**: `scripts/compare_strategies.py` na
  syntetycznych danych (1500 świec 1h) ze wszystkimi 7 strategiami —
  wygenerował 7 eksperymentów, poprawnie policzył metryki i DSR.
- **Błąd znaleziony i naprawiony podczas tego uruchomienia** (nie w
  testach jednostkowych, tylko przy realnym użyciu skryptu): pierwsza
  wersja `compare_strategies.py` przekazywała do `deflated_sharpe_ratio()`
  Sharpe **annualizowany**, podczas gdy seria `returns` była **per-okres**
  (godzinowa) — dokładnie niedopasowanie skali udokumentowane już w Fazie 4
  jako potencjalne ryzyko (`src/analytics/robustness.py`). Efekt: DSR
  saturował do ~1.0 niezależnie od liczby prób, tracąc sens. Naprawione:
  skrypt liczy teraz Sharpe per-okres bezpośrednio z `returns` do wywołania
  DSR, zachowując Sharpe annualizowany osobno do raportowania. Po
  poprawce DSR dla momentum/breakout w tym samym przebiegu: 0.31/0.94 —
  sensowne, nie zsaturowane wartości.
- `detect-secrets scan` — brak nowych sekretów.

---

## KNOWN ISSUES

- Testowa fabryka danych syntetycznych używana w większości testów
  integracyjnych (`tests/integration/helpers.py`) generuje świece o stałym
  zakresie high-low (`close ± 0.5`) — to sprawia, że `volatility_expansion`
  nigdy nie wyzwala sygnału na tych danych (brak wariancji zakresu do
  wykrycia). Nie jest to błąd strategii — dedykowane testy tej rodziny
  (`test_strategy_families.py`) celowo wstrzykują świecę o poszerzonym
  zakresie. Warto pamiętać o tym ograniczeniu przy pisaniu przyszłych
  testów/demek na syntetycznych danych.
- (Bez zmian od Fazy 5) `configs/instruments.yaml` nadal placeholder;
  krzywa equity do Sharpe/Sortino/CAGR próbkowana zdarzeniowo, nie w
  stałych odstępach; metryki na poziomie transakcji liczą tylko zamknięte
  pozycje (Buy & Hold pokazuje `trades=0` mimo realnej zmiany equity).

---

## NEXT

**PHASE 7 — Walk-forward + robustness**, do rozpoczęcia dopiero po
kolejnym wyraźnym poleceniu. W jej zakresie docelowo:

- Automatyczny framework walk-forward (TRAIN/VALIDATION/TEST, przesuwane
  okno), equity curve składany z kolejnych okresów TEST.
- Pełnowymiarowy Monte Carlo (min. 10 000 symulacji) na bazie
  `bootstrap_metric` z Fazy 4 (odnotowana potrzeba wektoryzacji przy tej
  skali).
- Stable parameter regions zamiast pojedynczych "najlepszych" parametrów
  (sekcja 20 wymagań) — wymaga uruchamiania tej samej rodziny z siatką
  parametrów, czego jeszcze nie ma.
- Rozważenie aktywacji `vectorbt` do masowej eksploracji parametrów, jeśli
  natywna pętla przez `BacktestEngine` okaże się za wolna przy siatkach
  parametrów × walk-forward × Monte Carlo.

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę
   (Faza 7), czy będzie potrzebny VectorBT Pro?
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3;
   otwarte pozostaje przejście na model dynamiczny i dobór rzeczywistej
   stawki.
3. Kiedy potrzebne będą dane tick-level/order-book?
4. Mechanizm eksperyment-trackingu — zaadresowane w Fazie 4 (JSON Lines +
   sekwencyjne ID). Do rewizji, jeśli wolumen eksperymentów uzasadni
   cięższe narzędzie.

---

## Decyzje projektowe podjęte w Fazie 6

- Trzy nowe rodziny (nie więcej) — zgodnie z sekcją 12 wymagań: framework
  do porównywania budujemy raz, rodzin strategii nie mnożymy przedwcześnie.
  Pozostałe rodziny z listy referencyjnej (Pullback, Volatility
  Compression, Relative Strength, Cross-sectional momentum) i strategie
  regime-based pozostają na roadmapie — te ostatnie wprost czekają na
  Fazę 8 (Market regimes), której jeszcze nie ma.
- Wydzielenie `run_and_record()` do `src/backtesting/runner.py` zamiast
  duplikowania orkiestracji silnik→metryki→eksperyment w dwóch skryptach —
  realna duplikacja (nie przedwczesna abstrakcja), bo drugi punkt użycia
  faktycznie powstał w tej fazie.
- Deflated Sharpe Ratio liczony na Sharpe per-okres, nie annualizowanym —
  poprawka wynikła z realnego uruchomienia, nie z teoretycznej analizy;
  utrzymuje to zasadę projektu, żeby nie polegać wyłącznie na testach
  jednostkowych izolowanych od faktycznego użycia.
- `compare_benchmarks.py` zastąpiony przez `compare_strategies.py` (nie
  dodany obok) — zakres skryptu faktycznie się rozszerzył (benchmarki +
  rodziny), zachowanie starej nazwy byłoby mylące.

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
