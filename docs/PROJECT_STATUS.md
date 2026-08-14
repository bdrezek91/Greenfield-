# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 8)

---

## CURRENT PHASE

**PHASE 8 — Market regimes** — UKOŃCZONA.

System potrafi opisać środowisko rynkowe z prostych, audytowalnych
wskaźników technicznych (ATR, ADX, struktura średnich kroczących, realized
volatility) — bez AI/ML, zgodnie z sekcją 13 wymagań. Każda strategia może
być teraz analizowana osobno w różnych reżimach (trend/volatility).

---

## DONE (Faza 8)

- `src/regimes/indicators.py` — ATR (SMA-based), ADX (Wilder, z
  poprawnym +DM/-DM/DI/DX i wygładzaniem), realized volatility (rolling
  std log-returns), struktura średnich kroczących. Czyste funkcje
  rolling/exponential, bez leakage.
- `src/regimes/classifier.py` — `classify_regimes()`: `trend_regime`
  (UPTREND/DOWNTREND/RANGE ze struktury MA + siły ADX) i `vol_regime`
  (HIGH_VOL/LOW_VOL względem własnego trailing window) — pd.NA dla wierszy
  przed rozgrzaniem wskaźników, nigdy zgadywany reżim.
- `src/regimes/analysis.py` — `label_trades_with_regime()` (as-of backward
  merge — reżim w momencie wejścia w pozycję, nigdy przyszły) i
  `metrics_by_regime()` (metryki transakcyjne z Fazy 4 osobno per reżim).
- `scripts/analyze_regimes.py` — CLI spinające backtest strategii,
  klasyfikację reżimów i rozbicie wyników per reżim w jeden eksperyment.
- **`tests/lookahead/` — pierwszy wpis od czasu zarezerwowania katalogu w
  Fazie 1**: `test_regime_no_lookahead.py` (5 testów) strukturalnie
  dowodzi braku lookahead: klasyfikacja tego samego prefiksu danych sama i
  jako część dłuższej serii musi dawać identyczne wyniki aż do wspólnej
  granicy — jeśli jakikolwiek wskaźnik zerkałby w przyszłość, doklejenie
  danych po granicy zmieniłoby wartości sprzed niej.
- Testy: `tests/unit/test_indicators.py` (10 przypadków — ręcznie policzone
  wartości TR/ADX/MA, ADX≈100 dla czystego trendu vs ADX<20 dla szumu),
  `tests/unit/test_classifier.py` (7 przypadków — poprawna klasyfikacja
  trendu, wykrywalny skok zmienności tuż po realnej zmianie reżimu — z
  udokumentowaniem, że głęboko w jednorodnym okresie split oscyluje koło
  50/50, co jest właściwością mediany trailing-window, nie błędem),
  `tests/unit/test_regime_analysis.py` (5 przypadków).

---

## TESTY / WALIDACJA (Faza 8)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (43 pliki źródłowe).
- `python3 -m pytest -q` — **174/174 testów przechodzi** (147 z Faz 1-7 +
  27 nowych z Fazy 8).
- Sanity-check wskaźników przed napisaniem testów: ADX≈100 na czystym
  trendzie, ADX≈5 na szumie — potwierdzenie poprawności formuły przed
  utrwaleniem jej w testach.
- **Realne uruchomienie end-to-end**: `scripts/analyze_regimes.py` na
  syntetycznych danych (3600 świec 1h, ~150 dni) ze strategią
  `trend_following` — rozbicie per reżim ujawniło sensowny, interesujący
  wzorzec (strategia trend-podążająca radziła sobie najgorzej w
  DOWNTREND, najlepiej w RANGE na tych danych) — dokładnie to narzędzie
  badawcze, które Faza 8 miała dostarczyć.
- `detect-secrets scan` — brak nowych sekretów.

---

## KNOWN ISSUES

- `vol_regime` jest detektorem **zmiany** zmienności względem własnego
  trailing window, nie klasyfikatorem bezwzględnym — głęboko w jednym,
  jednorodnym pod względem zmienności okresie naturalnie oscyluje koło
  50/50 (własność mediany, nie błąd). Udokumentowane wprost w docstringu
  `_vol_regime()` i w `docs/RESEARCH_METHODOLOGY.md`. Jeśli w przyszłości
  potrzebny będzie bezwzględny gauge "cały ten miesiąc był spokojny",
  wymaga to innego podejścia (np. porównania do stałego, długoterminowego
  baseline zamiast trailing window).
- (Bez zmian od Faz 5-7) `configs/instruments.yaml` nadal placeholder;
  metryki na poziomie transakcji liczą tylko zamknięte pozycje; sizing w
  oknach walk-forward liczony względem świeżego salda każdego okna.

---

## NEXT

**PHASE 9 — Risk + portfolio**, do rozpoczęcia dopiero po kolejnym
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

## Decyzje projektowe podjęte w Fazie 8

- Reżimy budowane wyłącznie z prostych wskaźników technicznych (ATR, ADX,
  struktura MA, realized volatility) — zero AI/ML, zgodnie wprost z
  sekcją 13 wymagań ("nie zaczynaj od AI").
- `vol_regime` jako detektor zmiany (trailing window), nie klasyfikator
  bezwzględny — świadoma decyzja projektowa po tym, jak pierwsza wersja
  testu ujawniła tę właściwość; udokumentowana zamiast ukryta.
- Reżimy dołączane do transakcji przez `merge_asof` z kierunkiem
  `backward` — ta sama zasada "brak lookahead", którą już stosowaliśmy w
  `funding.py` (Faza 3), teraz zastosowana na granicy transakcja↔reżim.
- Pierwszy realny wpis w `tests/lookahead/`, zarezerwowanym od Fazy 1 —
  katalog wreszcie ma zawartość odpowiadającą swojej nazwie, z testem
  strukturalnym (nie statystycznym) na dowód braku leakage.

---

## Faza 7 — Walk-forward + robustness (zakończona)

Framework walk-forward (`src/backtesting/walk_forward.py` — przesuwane
okna TRAIN/VALIDATION/TEST, selekcja parametrów wyłącznie na VALIDATION,
equity sklejany przez łączenie zwrotów okien TEST). Pełnowymiarowy Monte
Carlo (`src/analytics/monte_carlo.py` — w pełni zwektoryzowany, 10 000+
symulacji na sekwencji transakcji). Diagnostyka stabilności parametrów
(`flag_isolated_spikes()`, sekcja 20). 29 testów. Błąd znaleziony przy
realnym uruchomieniu: DSR liczony na Sharpe annualizowanym zamiast
per-okres (naprawiony w Fazie 6, potwierdzony ponownie jako wzorzec
"testuj realnym uruchomieniem, nie tylko unit testami").

---

## Faza 6 — Pierwsze rodziny strategii (zakończona)

Trzy rodziny poza benchmarkami (`momentum`, `breakout`,
`volatility_expansion`), dzielące bazę `HoldForBarsStrategy` z Fazy 5.
`src/backtesting/runner.py` (pierwsza wersja) i `scripts/compare_strategies.py`
(zastępujący `compare_benchmarks.py`) — porównanie dowolnego zestawu
strategii z Deflated Sharpe Ratio per rodzina. 9 nowych testów.

---

## Faza 5 — Benchmark strategies (zakończona)

Cztery obowiązkowe benchmarki (`buy_and_hold`, `random_entry`,
`trend_following`, `mean_reversion`) jako strategie NautilusTrader ze
wspólną bazą wymuszającą identyczny sizing i holding period. Adapter
`src/backtesting/reports.py` (positions/account report → generyczny
kontrakt trades/equity) zweryfikowany krzyżowo względem `realized_pnl`
silnika. 19 testów.

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
