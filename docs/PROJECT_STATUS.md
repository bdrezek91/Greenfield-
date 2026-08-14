# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 5)

---

## CURRENT PHASE

**PHASE 5 — Benchmark strategies** — UKOŃCZONA.

Cztery obowiązkowe benchmarki z sekcji 11 wymagań (`Buy & Hold`, `Random
Entry`, `Simple Trend Following`, `Simple Mean Reversion`) działają jako
strategie NautilusTrader, uruchamiane przez silnik z Fazy 3 i oceniane
metrykami z Fazy 4. Framework do uczciwego porównywania (ta sama wielkość
pozycji, ten sam okres trzymania, te same koszty — różni się tylko sygnał
wejścia) jest zaimplementowany i przetestowany end-to-end, łącznie z
adapterem raportów silnika do generycznego kontraktu analityki.

---

## DONE (Faza 5)

- `src/strategies/sizing.py` — sizing o stałej frakcji equity (`position_size`),
  jawnie oznaczony jako placeholder w miejsce prawdziwego Risk Engine (Faza 9).
- `src/strategies/base.py` — `HoldForBarsStrategy`: wspólna baza dla
  Random Entry/Trend Following/Mean Reversion wymuszająca identyczny sizing
  i okres trzymania pozycji — jedyna różnica między nimi to sygnał wejścia
  (`signal()`), co jest sednem uczciwego porównania.
- `src/strategies/buy_and_hold.py` — pojedyncze wejście na pierwszej świecy,
  brak wyjścia (osobna logika, nie dzieli bazy z resztą — z definicji nie ma
  reguły wyjścia).
- `src/strategies/random_entry.py` — losowy kierunek (seedowany RNG,
  powtarzalny), ten sam sizing/holding period co Trend/Mean Reversion.
- `src/strategies/trend_following.py` — kierunek zgodny z N-barowym
  momentum (prosty, bez stosu wskaźników — zgodnie z sekcją 12 wymagań:
  najpierw framework, nie dziesiątki odmian).
- `src/strategies/mean_reversion.py` — fade odchylenia od SMA o więcej niż
  próg procentowy.
- `src/strategies/registry.py` — mapowanie nazwa → (Strategy, Config) do
  wyboru strategii z CLI.
- `src/backtesting/reports.py` — adaptery `positions_report_to_trades()` i
  `account_report_to_equity()` z raportów NautilusTrader do generycznych
  kontraktów `src/analytics/metrics.py` — **zweryfikowane przez porównanie z
  `realized_pnl` silnika** (najsilniejszy możliwy test poprawności: nie
  zakłada niczego, sprawdza zgodność z wewnętrzną prawdą silnika).
- `scripts/run_backtest.py` rozszerzony o `--strategy` (wymaga `--symbol`).
- `scripts/compare_benchmarks.py` — uruchamia wszystkie cztery benchmarki na
  tych samych danych/kosztach, liczy metryki, zapisuje każdy przebieg jako
  eksperyment (`ExperimentStore`) i raport Markdown — **zweryfikowane
  realnym uruchomieniem** na syntetycznych danych (1000 świec 1h): 4 różne
  eksperymenty (`EXP-000001`..`EXP-000004`) z sensownie różniącymi się
  metrykami (trades, net_return, Sharpe, max_drawdown).
- Testy: `tests/unit/test_sizing.py`, `tests/integration/
  test_benchmark_strategies.py` (10 testów na prawdziwym silniku — Buy&Hold
  wchodzi dokładnie raz i nie wychodzi; Trend Following jest zawsze
  LONG na czystym uptrendzie / zawsze SHORT na czystym downtrendzie i
  zyskowny na uptrendzie; Mean Reversion fade'uje ostry spike; Random Entry
  jest odtwarzalny z tym samym seedem i może się różnić z innym; wszystkie
  respektują skonfigurowany holding period; sizing mieści się w rozsądnych
  granicach equity), `tests/integration/test_reports_adapter.py` (5 testów,
  w tym krzyżowa weryfikacja net_pnl względem `realized_pnl` silnika).
- `docs/RESEARCH_METHODOLOGY.md` zaktualizowany o sekcję benchmarków.

---

## TESTY / WALIDACJA (Faza 5)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (34 pliki źródłowe; 5 miejsc z
  `# type: ignore[call-arg]` na `frozen=True` w subklasach `StrategyConfig`
  — znane ograniczenie mypy wobec `msgspec.Struct` kwargs, nie błąd).
- `python3 -m pytest -q` — **109/109 testów przechodzi** (90 z Faz 1-4 + 19
  nowych z Fazy 5).
- **Realne uruchomienia end-to-end** (nie tylko testy jednostkowe): każda z
  czterech strategii faktycznie handlowała przez prawdziwy silnik Nautilus
  na syntetycznych danych (BuyAndHold: 1 pozycja; pozostałe: ~20-40 pozycji
  na 500-1000 świec, zgodnie z oczekiwaniem przy holding_period=24h);
  `scripts/run_backtest.py --strategy trend_following` uruchomiony z linii
  poleceń; `scripts/compare_benchmarks.py` uruchomiony end-to-end,
  wygenerował 4 eksperymenty z poprawnym `git_commit` i raportami Markdown.
- `detect-secrets scan` — brak nowych sekretów.

---

## KNOWN ISSUES

- `vectorbt` celowo NIE dodany do zależności — żaden kod w tej fazie go nie
  używa (cztery benchmarki działają w pełni przez silnik NautilusTrader,
  framework do uczciwego porównania nie wymagał masowej eksploracji
  parametrów). Zgodnie z zasadą nieinstalowania nieużywanych zależności;
  do ponownej oceny w Fazie 6, jeśli pojawi się kod, który go potrzebuje.
- Metryki na poziomie transakcji (`trades`, `net_return` z `TradeMetrics`)
  liczą wyłącznie **zamknięte** pozycje — dla Buy & Hold (pozycja otwarta
  przez cały backtest) `trades=0` i `net_return=0.0` mimo realnej zmiany
  wartości portfela. To zamierzone, nie błąd: rzeczywisty wynik Buy & Hold
  jest widoczny w `EquityMetrics` (CAGR, Sharpe, drawdown), liczonych z
  krzywej equity, nie z transakcji — ale warto o tym pamiętać przy czytaniu
  raportów, żeby nie odczytać `trades=0` jako "strategia nic nie zrobiła".
- Krzywa equity używana do Sharpe/Sortino/CAGR pochodzi z raportu konta
  Nautilusa, próbkowanego zdarzeniowo (przy każdej zmianie salda), nie w
  stałych odstępach czasu — adnotacja o tym w `src/backtesting/reports.py`;
  wpływa to na dokładność annualizacji, nie na kierunek/sensowność metryk.
- Specyfikacje instrumentów (`configs/instruments.yaml`) nadal placeholder
  — bez zmian od Fazy 3, wciąż rekomendowana synchronizacja z realnym
  instrument-info Bybit przed poleganiem na wynikach.
- `deflated_sharpe_ratio` jest wrażliwy na skalę `observed_sharpe` względem
  okresu, z którego pochodzi seria `returns` (per-period vs. annualized) —
  patrz uwaga w kodzie (`src/analytics/robustness.py`); odpowiedzialność za
  spójność skali spoczywa na wywołującym (aktualne od pierwszego realnego
  użycia w Fazie 6+).

---

## NEXT

**PHASE 6 — Pierwsze rodziny strategii**, do rozpoczęcia dopiero po
kolejnym wyraźnym poleceniu.

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę
   (Faza 7), czy będzie potrzebny VectorBT Pro?
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3
   (patrz `docs/BACKTESTING.md`); otwarte pozostaje przejście na model
   dynamiczny i dobór rzeczywistej stawki.
3. Kiedy potrzebne będą dane tick-level/order-book?
4. Mechanizm eksperyment-trackingu — **zaadresowane w Fazie 4**: JSON Lines
   + sekwencyjne ID, bez mlflow/bazy danych na tym etapie. Do rewizji, jeśli
   wolumen eksperymentów uzasadni cięższe narzędzie.

---

## Decyzje projektowe podjęte w Fazie 5

- Wspólna baza (`HoldForBarsStrategy`) dla trzech z czterech benchmarków
  wymusza identyczny sizing i holding period — to jest cały mechanizm
  "uczciwego porównania" wymagany przez sekcję 11: różni się tylko sygnał.
  Buy & Hold świadomie nie dzieli tej bazy (z definicji nie ma reguły
  wyjścia).
- Sizing jako jawny, tymczasowy placeholder (`src/strategies/sizing.py`),
  nie próba przedwczesnego zbudowania Risk Engine — ten przypada na Fazę 9.
- Adapter `src/backtesting/reports.py` zweryfikowany przez porównanie z
  `realized_pnl` silnika, a nie tylko przez odizolowane testy jednostkowe —
  najsilniejsza dostępna forma weryfikacji poprawności bez zakładania
  niczego o wewnętrznej logice Nautilusa.
- `vectorbt` pozostaje celowo nieaktywowany — konsekwentne stosowanie
  zasady "nie instaluj zależności, zanim powstanie kod, który jej używa"
  (ta sama zasada co przy `pybit`/`ccxt` w Fazie 2 i `nautilus_trader` w
  Fazie 3).

---

## Faza 4 — Analytics + experiment tracking (zakończona, zwalidowana)

`src/analytics/experiment.py` — `ExperimentRecord` (pełny kontrakt
reprodukowalności: `experiment_id`, `git_commit`, `dataset_version`,
`date_range`, `symbols`, `timeframes`, `strategy_version`, `parameters`,
`fees`, `slippage`, `funding_assumptions`, `metrics`, `created_at`) i
`ExperimentStore` — append-only JSON Lines (`reports/experiments/
experiments.jsonl`, generowane, poza Git) z sekwencyjnymi ID. `src/analytics/
metrics.py` — pełny zestaw metryk z sekcji 18 wymagań. `src/analytics/
robustness.py` — bootstrap i Deflated Sharpe Ratio. `src/analytics/report.py`
— renderowanie do Markdown. 34 testy dodane w tej fazie.

### Walidacja Faz 1-4 (audyt przed Fazą 5)

Przed rozpoczęciem Fazy 5 przeprowadzono pełny audyt kodu z Faz 1-4
(niezależny przegląd `src/`, `scripts/`, `configs/`, Docker/CI, `.gitignore`,
zgodności dokumentacji z kodem). Znaleziono i naprawiono 3 rzeczywiste błędy:

1. **`src/backtesting/funding.py` — podwójne liczenie funding na granicy
   rozliczenia.** `funding_timestamps()` używał przedziału domkniętego
   `[start, end]`; jeśli jedna pozycja zamykała się dokładnie w momencie
   rozliczenia (np. 08:00:00 UTC), a kolejna pozycja na tym samym
   instrumencie otwierała się w tej samej chwili, obie były obciążane tym
   samym rozliczeniem. Naprawione przez przedział półotwarty `[start, end)`.
2. **`src/analytics/metrics.py` — nietypowy mianownik odchylenia downside
   w Sortino.** Odchylenie liczono jako `std()` tylko po stratnych okresach
   zamiast przez **całkowitą** liczbę okresów (standardowa definicja). Błąd
   systematycznie zaniżał downside deviation i zawyżał Sortino Ratio.
   Naprawione; dodano test z ręcznie policzoną wartością oczekiwaną.
3. **Brak walidacji `--symbol`/`--timeframe` na granicy CLI** — teoretyczne
   ryzyko path traversal (`--symbol ../../etc`) trafiającego bezpośrednio do
   ścieżek plików. Dodano `SymbolUniverse.validate_symbol()`/
   `validate_timeframe()` i podłączono w obu CLI.

Wynik po poprawkach: `pytest` 90/90 (było 83, +7 nowych testów). Wszystkie
pozostałe sprawdzone elementy (formuły metryk, Deflated Sharpe Ratio,
wykrywanie luk, paginacja, okablowanie silnika, zgodność dokumentacji z
kodem) — bez zastrzeżeń.

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
