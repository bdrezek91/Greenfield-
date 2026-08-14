# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 4)

---

## CURRENT PHASE

**PHASE 4 — Analytics + experiment tracking** — UKOŃCZONA.

Warstwa analityczna (`src/analytics`) jest zaimplementowana i przetestowana:
mechanizm eksperyment-trackingu, pełny zestaw metryk z sekcji 18 wymagań,
pierwsza wersja diagnostyki multiple-testing (bootstrap + Deflated Sharpe
Ratio), renderowanie raportów. Żadna kolejna warstwa (benchmarki, strategie,
regimes, risk, portfolio, ML) nie istnieje.

---

## DONE

- `src/analytics/experiment.py` — `ExperimentRecord` (pełny kontrakt
  reprodukowalności: `experiment_id`, `git_commit`, `dataset_version`,
  `date_range`, `symbols`, `timeframes`, `strategy_version`, `parameters`,
  `fees`, `slippage`, `funding_assumptions`, `metrics`, `created_at`) i
  `ExperimentStore` — append-only JSON Lines (`reports/experiments/
  experiments.jsonl`, generowane, poza Git) z sekwencyjnymi ID
  `EXP-000001`, `EXP-000002`, ... `capture_git_commit()` i
  `fingerprint_dataset()` automatycznie wypełniają pola provenance.
- `src/analytics/metrics.py` — pełny zestaw metryk z sekcji 18 wymagań,
  liczony z dwóch generycznych, niezależnych od silnika kontraktów
  (`trades` DataFrame, `equity` Series — ten sam wzorzec adaptera co
  `funding.py` z Fazy 3): Trades, Net Return, Win Rate, Avg Win/Loss,
  Expectancy, Profit Factor, Sharpe, Sortino, Calmar, Max Drawdown, Ulcer
  Index, Avg/Median R (gdy dostępne `r_multiple`), Longest Losing Streak,
  Exposure, Turnover, Fees, Funding Costs, MAE/MFE (gdy dostępne).
- `src/analytics/robustness.py` — `bootstrap_metric` (generyczny resampling
  z powtarzalnym seedem — mechanizm, którego użyje pełny Monte Carlo w
  Fazie 7) i `deflated_sharpe_ratio` (Bailey & López de Prado: prawdopodobieństwo,
  że obserwowany Sharpe odzwierciedla realną przewagę, a nie jest
  artefaktem wyboru najlepszego z `n_trials` testowanych strategii;
  uwzględnia skośność i kurtozę rozkładu zwrotów).
- `src/analytics/report.py` — renderowanie `ExperimentRecord` do Markdown
  (`reports/experiments/<experiment_id>.md`).
- Dodano `scipy` do zależności core (potrzebne do `norm.ppf`/`norm.cdf` w
  Deflated Sharpe Ratio).
- Testy: `tests/unit/test_metrics.py` (13 przypadków — pnl long/short,
  znane wartości win rate/profit factor/expectancy, longest losing streak,
  exposure z mergowaniem nakładających się interwałów, equity metrics na
  rosnącym/płaskim/spadającym kapitale), `tests/unit/test_robustness.py`
  (powtarzalność bootstrapu z seedem, zbieżność do średniej próbki,
  monotoniczność DSR względem liczby prób i obserwowanego Sharpe'a,
  ograniczenie prawdopodobieństwa do [0,1]), `tests/unit/test_experiment.py`
  (sekwencja ID, round-trip zapis/odczyt, `capture_git_commit` zweryfikowany
  na **prawdziwym repozytorium** — zwraca faktyczny hash HEAD, nie mock),
  `tests/unit/test_report.py`, oraz
  `tests/integration/test_analytics_pipeline.py` — pełny przepływ
  trades/equity → metryki → `ExperimentRecord` → zapisany raport Markdown.
- `docs/RESEARCH_METHODOLOGY.md` zaktualizowany o sekcję implementacyjną.

---

## TESTY / WALIDACJA WYKONANA W TEJ FAZIE

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (26 plików źródłowych, bez błędów).
- `python3 -m pytest -q` — **83/83 testów przechodzi** (49 z Faz 1-3 + 34
  nowych z Fazy 4).
- `detect-secrets scan` — brak nowych sekretów, `.secrets.baseline`
  zregenerowany.
- `capture_git_commit()` przetestowany na realnym repozytorium (nie mocku)
  — zwraca faktyczny 40-znakowy hash `HEAD`.
- Zweryfikowano ręcznie, że `.gitignore` poprawnie wyklucza
  `reports/experiments/` (wzorzec `reports/*` obejmuje też podkatalogi) —
  eksperymenty nie trafią przypadkiem do repozytorium.

---

## KNOWN ISSUES

- Brak nowych ograniczeń specyficznych dla tej fazy — cała logika jest
  czystym Pythonem/pandas/scipy, bez zależności sieciowych czy Dockera, więc
  mogła zostać w pełni zweryfikowana lokalnie (w przeciwieństwie do Faz 1/2).
- `deflated_sharpe_ratio` jest wrażliwy na skalę `observed_sharpe` względem
  okresu, z którego pochodzi seria `returns` (per-period vs. annualized) —
  przy dużej liczbie obserwacji i "annualizowanym" Sharpe podanym błędnie
  jako per-period, prawdopodobieństwo saturuje do 1.0 i traci czułość na
  liczbę prób. Udokumentowane w kodzie; odpowiedzialność za spójność skali
  spoczywa na wywołującym (Faza 6+, gdy pojawią się realne strategie).
  Nie jest to błąd matematyczny, tylko właściwość funkcji CDF przy dużych
  argumentach — warte przypomnienia przy pierwszym realnym użyciu.

---

## NEXT

**PHASE 5 — Benchmark strategies**, do rozpoczęcia dopiero po kolejnym
wyraźnym poleceniu. W jej zakresie docelowo, zgodnie z sekcją 11 wymagań:

- Buy & Hold, Random Entry, Simple Trend Following, Simple Mean Reversion —
  jako pierwsze strategie w `src/strategies`, uruchamiane przez silnik z
  Fazy 3 i oceniane metrykami z Fazy 4.
- Framework do uczciwego porównywania strategii (te same koszty, ten sam
  risk engine — chociaż pełny risk engine to dopiero Faza 9, więc na razie
  uproszczony, jawnie udokumentowany position sizing).
- Aktywacja `vectorbt` w zależnościach `backtest` (eksploracyjne sweepy
  parametrów).
- Synchronizacja `configs/instruments.yaml` z realnym instrument-info
  Bybit na maszynie z dostępem do sieci — rekomendowane przed poleganiem na
  wynikach backtestów (patrz KNOWN ISSUES Fazy 3).

---

## RESEARCH QUESTIONS

(bez zmian od Fazy 3 — żadne z tych pytań nie wymagało jeszcze decyzji w
tej fazie)

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę
   (Faza 7), czy będzie potrzebny VectorBT Pro?
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3
   (patrz `docs/BACKTESTING.md`); otwarte pozostaje przejście na model
   dynamiczny i dobór rzeczywistej stawki.
3. Kiedy potrzebne będą dane tick-level/order-book?
4. Mechanizm eksperyment-trackingu — **zaadresowane w Fazie 4**: JSON Lines
   + sekwencyjne ID, bez mlflow/bazy danych na tym etapie (najniższy koszt
   wdrożenia przy pełnej zgodności z wymaganym kontraktem pól). Do
   rewizji, jeśli wolumen eksperymentów uzasadni cięższe narzędzie.

---

## Decyzje projektowe podjęte w Fazie 4

- Eksperyment-tracking jako proste, append-only JSON Lines zamiast
  mlflow/bazy danych — najniższy koszt utrzymania, pełna zgodność z
  wymaganym kontraktem pól, łatwe do zmiany później bez zmiany interfejsu
  wywołującego kodu.
- Metryki i funding (Faza 3) używają tego samego wzorca: generyczny
  kontrakt DataFrame/Series niezależny od NautilusTrader, żeby dało się je
  testować i używać bez uruchamiania silnika — spójne z zasadą modularności
  z Fazy 0.
- Deflated Sharpe Ratio i bootstrap zaimplementowane jako pierwsza (nie
  jedyna docelowo) warstwa ochrony przed multiple testing — Probability of
  Backtest Overfitting i White's Reality Check pozostają na roadmapie, bez
  sztucznego przyspieszania ich wdrożenia przed pojawieniem się realnych
  eksperymentów, które by je uzasadniły.
- `reports/experiments/` jawnie poza Git (zweryfikowane), zgodnie z zasadą
  "brak danych/artefaktów eksperymentów w repozytorium" — `git_commit` w
  każdym rekordzie eksperymentu wiąże wynik z kodem w drugą stronę.
