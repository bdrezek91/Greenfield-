# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 9)

---

## CURRENT PHASE

**PHASE 9 — Risk + portfolio** — UKOŃCZONA.

Wszystkie strategie (benchmarki i rodziny) delegują teraz decyzję o wejściu
i wielkości pozycji do osobnego, stanowego silnika ryzyka zamiast liczyć
sizing samodzielnie. Warstwa portfelowa agreguje niezależnie uruchomione
backtesty per-symbol w widok portfela (equity, korelacja, koncentracja,
drawdown, ekspozycja).

---

## DONE (Faza 9)

- `src/risk/engine.py` — `RiskEngine` (stanowy, niezależny od
  NautilusTrader): egzekwuje po kolei max concurrent positions, max daily
  loss (reset co dobę UTC), max drawdown od szczytu equity, potem liczy
  wielkość pozycji z `risk_per_trade` (lub skalowaną przez volatility
  targeting) ograniczoną pozostałym budżetem `max_portfolio_risk` i
  `max_leverage`. `open_position()`/`close_position()` śledzą stan między
  wywołaniami `evaluate()`.
- `src/strategies/base.py` (`HoldForBarsStrategy`) i
  `src/strategies/buy_and_hold.py` zrefaktoryzowane: konstruują `RiskEngine`
  z pól konfiguracji (domyślne wartości odtwarzają dokładnie stare
  zachowanie fixed-10%-of-equity dla pierwszej transakcji świeżego
  backtestu), podłączone do `on_position_closed` żeby zwalniać budżet
  ryzyka i księgować dzienny PnL.
- `src/portfolio/aggregation.py` — `combine_equity_curves()` (sumowanie PnL
  per-symbol na wspólnej osi czasu), `correlation_matrix()`,
  `concentration_hhi()` (Herfindahl-Hirschman), `portfolio_drawdown()`,
  `portfolio_exposure()` (unia interwałów otwartych pozycji między
  symbolami, reużywająca `exposure_fraction()` z Fazy 4).
- `scripts/portfolio_backtest.py` — CLI uruchamiające jedną strategię
  niezależnie na kilku symbolach i agregujące wynik w jeden eksperyment.
- Testy: `tests/unit/test_risk_engine.py` (12 przypadków — każdy limit
  osobno, reset dziennej straty na nowy dzień, zwalnianie budżetu po
  zamknięciu pozycji, volatility targeting), `tests/unit/
  test_portfolio_aggregation.py` (14 przypadków, w tym dokładnie policzona
  matematyka sklejania equity i korelacji).

---

## TESTY / WALIDACJA (Faza 9)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (45 plików źródłowych).
- `python3 -m pytest -q` — **200/200 testów przechodzi** (174 z Faz 1-8 +
  26 nowych z Fazy 9).
- **Dwa rzeczywiste błędy znalezione przez testy/realne uruchomienia (nie
  domysł):**
  1. `RiskEngine.close_position()` nie aktualizował licznika dnia — strata
     zapisana przed pierwszym wywołaniem `evaluate()` była cicho zerowana
     przy kolejnym roll-over dnia. Wykryte przez pierwszą wersję testu
     `test_rejects_when_daily_loss_breached`, naprawione dodaniem parametru
     `now` do `close_position()`.
  2. **Kolizja nazw atrybutów**: `HoldForBarsStrategy.__init__` i podklasy
     (Momentum, TrendFollowing, MeanReversion) używały tej samej nazwy
     `self._closes` do dwóch różnych celów (śledzenie zmienności w bazie
     vs. własna logika sygnału w podklasie) — podklasa cicho nadpisywała
     atrybut bazowej klasy, prowadząc do podwójnego dopisywania do tej
     samej kolejki i zerowej liczby transakcji. Wykryte przez istniejący
     test integracyjny z Fazy 5 (`test_benchmarks_use_fixed_fraction_
     sizing_relative_to_equity[MeanReversion-...]`), naprawione przez
     zmianę nazwy na `self._vol_closes` w bazie.
  3. **Duplikaty znaczników czasu w `combine_equity_curves()`**: raport
     konta NautilusTrader może mieć wiele wierszy o tym samym timestampie
     (np. złożenie zlecenia + wykonanie w tej samej chwili), co psuło
     `Series.reindex()`. Znalezione przy realnym uruchomieniu
     `scripts/portfolio_backtest.py` na 3 symbolach (nie w testach
     jednostkowych, które używały syntetycznych serii bez duplikatów).
     Naprawione: kolapsowanie duplikatów do ostatniej wartości przed
     reindeksowaniem, dodany test regresyjny.
- **Realne uruchomienia end-to-end**: potwierdzono, że ciasny
  `max_daily_loss`/`max_drawdown` faktycznie ogranicza liczbę transakcji w
  prawdziwym backteście (95 → 12 transakcji, zaobserwowany max_drawdown
  ~-1.06% przy limicie 1%); `scripts/portfolio_backtest.py` na 3 symbolach
  (BTC/ETH/SOL) zwrócił sensowną korelację (~-0.05) i koncentrację bliską
  1/3 (równomierny podział).

---

## KNOWN ISSUES

- `max_concurrent_positions`/`max_portfolio_risk` widzą tylko pozycje
  otwarte przez TĘ SAMĄ instancję `RiskEngine` danej strategii — brak
  współdzielonego budżetu ryzyka między strategiami/symbolami działającymi
  jednocześnie. Jawnie udokumentowane jako granica zakresu w
  `src/risk/engine.py`.
- `src/portfolio/aggregation.py` agreguje **niezależnie uruchomione**
  backtesty per-symbol (każdy z własnym kontem/saldem początkowym), nie
  jedną symulację wielu instrumentów jednocześnie w jednym koncie — ta sama
  granica zakresu co w risk engine, udokumentowana w module.
- (Bez zmian od Faz 5-8) `configs/instruments.yaml` nadal placeholder;
  metryki na poziomie transakcji liczą tylko zamknięte pozycje.

---

## NEXT

**PHASE 10 — Paper execution**, do rozpoczęcia dopiero po kolejnym
wyraźnym poleceniu.

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę?
   Częściowo zaadresowane w Fazie 7 — natywna pętla przez `BacktestEngine`
   wystarczająco szybka jak dotąd.
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3;
   otwarte pozostaje przejście na model dynamiczny i dobór rzeczywistej
   stawki.
3. Kiedy potrzebne będą dane tick-level/order-book?
4. Mechanizm eksperyment-trackingu — zaadresowane w Fazie 4 (JSON Lines +
   sekwencyjne ID).

---

## Decyzje projektowe podjęte w Fazie 9

- Domyślne wartości pól risk engine w konfiguracjach strategii dobrane tak,
  by dokładnie odtworzyć stare zachowanie (fixed 10% equity) dla pierwszej
  transakcji świeżego backtestu — minimalizuje ryzyko regresji przy
  refaktorze, jednocześnie dając prawdziwą maszynerię risk-engine dla
  kolejnych transakcji w tym samym przebiegu.
- Risk engine jawnie stanowy i jawnie ograniczony do jednej instancji
  strategii — nie udawanie współdzielonego portfelowego budżetu ryzyka,
  którego jeszcze nie ma infrastruktura do obsłużenia (brak jednoczesnego
  wielo-instrumentowego wykonania w jednym koncie).
- Portfolio jako agregacja post-hoc niezależnych backtestów, nie próba
  symulacji jednego wspólnego konta wielu instrumentów — uczciwe wobec
  aktualnych możliwości silnika, jawnie udokumentowane jako uproszczenie
  (ta sama zasada co przy sklejaniu krzywych equity w walk-forward, Faza 7).
- `concentration_hhi()` i `portfolio_exposure()` reużywają istniejącą
  logikę (`exposure_fraction()` z Fazy 4) zamiast duplikować obliczenia
  interwałów — ta sama matematyka, ten sam poziom zaufania.

---

## Faza 8 — Market regimes (zakończona)

`src/regimes/indicators.py` (ATR, ADX, realized volatility, struktura MA —
bez AI/ML), `classifier.py` (`trend_regime`, `vol_regime`), `analysis.py`
(rozbicie metryk per reżim, as-of backward merge). Pierwszy realny wpis w
`tests/lookahead/`, zarezerwowanym od Fazy 1. 27 testów. Realne
uruchomienie ujawniło sensowny wzorzec badawczy (trend following gorszy w
DOWNTREND, lepszy w RANGE).

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
