# Autonomous Research Audit — 2026-08-16

Audyt poprzedzający rozbudowę AI Trading Lab o autonomiczną "fabrykę
eksperymentów" (research worker, globalny trial ledger, promocja PAPER,
monitoring degradacji). Zakres: `README.md`, `docs/PROJECT_STATUS.md`,
`docs/RESEARCH_METHODOLOGY.md`, `docs/BACKTESTING.md`, `docs/DATA.md`,
`docs/ML.md`, `docs/VPS_DEPLOYMENT.md`, `docs/LIVE_READINESS_CHECKLIST.md`,
`scripts/run_walk_forward.py`, `scripts/compare_strategies.py`,
`scripts/run_paper_session.py`, `scripts/monte_carlo.py`,
`scripts/portfolio_backtest.py`, `src/backtesting/*`, `src/analytics/*`,
`src/execution/*`, `src/risk/*`, `src/strategies/*`, powiązane testy
(`tests/unit`, `tests/integration`, `tests/lookahead`, `tests/data_integrity`,
`tests/strategy`).

Środowisko audytu: `nautilus_trader`, `scikit-learn` i reszta zależności z
`pyproject.toml` zostały doinstalowane w tej sesji (nie były obecne domyślnie)
i **pełny `pytest -q` przechodzi 431/431** przed jakąkolwiek zmianą — to jest
realny, zweryfikowany baseline, nie deklaracja z dokumentacji. Rzeczywiste
dane historyczne (`/data/`) nie istnieją w tej sesji (gitignored, żyją tylko
na VPS) — sieć do `api.bybit.com` jest zablokowana z tego środowiska, więc
Etap 0 nie mógł polegać na ponownym pobraniu i przeliczeniu realnych świec;
oparto się na czytaniu kodu, testach na danych syntetycznych i przeliczeniu
analitycznym raportowanego wcześniej wyniku (patrz sekcja 1 niżej i
`docs/PROJECT_STATUS.md`).

Ważne: `README.md` jest nieaktualny — twierdzi "No data ingestion, strategy,
backtest, or ML logic exists yet" / "Phase 1 in progress", podczas gdy
`docs/PROJECT_STATUS.md` opisuje ukończone Fazy 0–15 (dane, silnik
backtestu, 7 rodzin strategii, ML, risk/portfolio, paper execution na Bybit
Demo, live-readiness gate). Napraw README w osobnym, kosmetycznym commicie
poza zakresem tego audytu bezpieczeństwa/metodologii.

---

## Co już działa dobrze

- **Podwójna, niezależna blokada LIVE**: `resolve_trading_mode()`
  (`CONFIRM_LIVE_TRADING=I_UNDERSTAND_THE_RISK` + `TRADING_MODE=LIVE`) i
  `build_paper_trading_node()`, który **strukturalnie** odrzuca każdy tryb
  poza `TradingMode.PAPER` — w repo nie ma żadnej ścieżki kodu zdolnej złożyć
  zlecenie LIVE (potwierdzone grepem: brak klienta wykonawczego mainnet).
  `live_preflight.py` to trzecia, dodatkowa bramka gotowości. Ten stan
  **nie jest zmieniany** przez niniejszą pracę.
- Framework walk-forward (`generate_windows`/`run_walk_forward`) poprawnie
  rozdziela TRAIN (dobór parametrów niedostępny) / VALIDATION (selekcja
  parametrów) / TEST (jedyne źródło raportowanych metryk) — brak
  look-ahead w samej logice okien.
- `tests/lookahead/` istnieje i faktycznie weryfikuje brak look-ahead
  strukturalnie (porównanie obciętego/pełnego szeregu) dla cech i reżimów.
- DSR (Bailey/López de Prado) i CSCV/PBO (Bailey, Borwein, López de Prado &
  Zhu 2015) są poprawnie zaimplementowane w `src/analytics/robustness.py` z
  testami sanity-check (czysty szum → PBO≈0.5, stała przewaga → PBO≈0.0).
- `ExperimentStore` to solidny fundament: append-only JSONL,
  `capture_git_commit`, `fingerprint_dataset` (na razie po
  path/size/mtime, nie po treści — patrz "błędy implementacyjne").
- Purged/embargoed walidacja (`src/ml/splits.py`) i in-sample guard w
  `MLFiltered` są zaimplementowane i przetestowane poprawnie.
- Sizing/ryzyko: `RiskEngine` (max concurrent positions, max daily loss,
  max drawdown, vol targeting, max leverage) jest spójnie używany przez
  wszystkie strategie poza Buy & Hold (który też go używa, ale tylko raz).

## Co jest tylko częściowo podłączone

1. **`src/backtesting/funding.py:estimate_funding_cost` nie jest wywoływane
   nigdzie poza własnymi testami.** `positions_report_to_trades` twardo
   ustawia `funding_cost: 0.0` na każdym wierszu, a `runner.py` i
   `scripts/portfolio_backtest.py` zapisują w eksperymencie
   `funding_assumptions={"note": "not applied in this run"}`. Perpetual
   futures bez funding to nie jest realistyczny backtest instrumentu, który
   handlujemy — patrz Błędy metodologiczne #2.
2. **PBO (`probability_of_backtest_overfitting`) nie jest wywoływane
   nigdzie w `scripts/`** — istnieje jako czysta funkcja biblioteki, zgodnie
   z tym, co `docs/RESEARCH_METHODOLOGY.md` już samo przyznaje.
3. **DSR w `compare_strategies.py` liczy `n_trials = len(names)`** — czyli
   tylko strategie porównane w *tym jednym* wywołaniu CLI, nie licznik
   globalny po całej historii `experiments.jsonl`. Każde kolejne
   uruchomienie CLI zaczyna liczenie prób od zera.
4. **`HeartbeatMonitor` zbudowany, ale niepodłączony** do żadnej sesji
   paper ani do żadnego kanału alertowego (potwierdzone w
   `docs/PROJECT_STATUS.md` Faza 14 i w kodzie — brak call site poza
   testami).
5. **Brak kompaktora plików mikrostruktury** — znany, udokumentowany dług
   (~5760 plików/dzień), zero automatycznej kompakcji.
6. `docker-compose.yml` ma tylko `research` i `tests` — `paper-session` i
   `microstructure` są uruchamiane ręcznie przez `docker compose run -d
   --name ...`, nie jako zdefiniowane usługi z `restart_policy`/
   `healthcheck`/limitami zasobów.

## Błędy metodologiczne

### M1 — Annualizacja Sharpe/Sortino/Calmar niezgodna z rzeczywistym interwałem

`compute_equity_metrics(equity, periods_per_year)` w
`src/analytics/metrics.py` poprawnie przyjmuje `periods_per_year` jako
parametr i nigdzie go sama nie zgaduje — **problem jest wyżej, w CLI**:

- `scripts/run_walk_forward.py` (linia 53-55), `scripts/compare_strategies.py`
  (linia 53-55) i `scripts/portfolio_backtest.py` (linia 55-57) mają domyślne
  `periods_per_year: float = 365.25 * 24` — annualizacja **godzinowa** — bez
  względu na jawnie podany `--timeframe`.
- `scripts/monte_carlo.py` (linia 76) ma to **na sztywno wpisane w kodzie**,
  nawet nie jako opcję CLI — nie da się tego nadpisać bez zmiany skryptu.
- W walk-forward `periods_per_year` jest wymaganym parametrem przekazywanym
  od wywołującego (nie ma w nim własnego złego domyślnego), ale skoro jedyny
  wywołujący (`scripts/run_walk_forward.py`) ma zły domyślny CLI, efekt
  końcowy jest identyczny.

**Konsekwencja**: `docs/PROJECT_STATUS.md` raportuje wyniki wieloint-
erwałowego badania (15m/1h/4h/1d) dla 5 strategii przez dokładnie ten CLI,
bez wzmianki o ręcznym `--periods-per-year` w użytych komendach. Wszystko
wskazuje, że **4h i 1d zostały zannualizowane tak, jakby to były świece
1h** — czynnik `sqrt(365.25*24)` zamiast `sqrt(365.25*6)` (4h, błąd ×2) albo
`sqrt(365.25)` (1d, błąd ×4.9). CAGR/drawdown/net_return **nie są** tym
dotknięte (nie zależą od `periods_per_year`) — tylko Sharpe/Sortino/Calmar.
Zob. sekcja "Przeliczenie kandydata momentum" niżej dla skorygowanych
liczb.

**Naprawiono w tej sesji**: `src/backtesting/annualization.py` — mapowanie
timeframe → periods_per_year (1m/5m/15m/1h/4h/1d), wpięte jako domyślna
wartość we wszystkich czterech skryptach; explicit `--periods-per-year`
override nadal możliwy, ale teraz **jawnie zapisywany** w
`ExperimentRecord.parameters` jako `periods_per_year_source: "override"` vs
`"timeframe_default"`, żeby żaden przyszły eksperyment nie mógł po cichu
użyć złej wartości bez śladu w rekordzie.

### M2 — Funding nie jest stosowany do żadnego rzeczywistego backtestu perpetuali

Handlujemy Bybit USDT Perpetual Futures — instrument bez terminu
wygaśnięcia, którego cena jest utrzymywana blisko spot przez okresowe
płatności funding. Backtest, który tego nie liczy, systematycznie zawyża
wynik strategii trend-followingowych trzymających pozycję przez wiele
okresów rozliczeniowych (i zaniża tych po stronie odbierającej funding).
`estimate_funding_cost()` istnieje i jest przetestowane w izolacji, ale
zero call site poza testami — potwierdzone grepem.

**Naprawiono w tej sesji**: `positions_report_to_trades` (patrz M3) teraz
przyjmuje opcjonalny `funding_assumptions` i woła `estimate_funding_cost`
per pozycja (uwzględniając stronę, wielkość, `ts_opened`/`ts_closed` —
łącznie z pozycją wciąż otwartą na koniec okna, oznaczoną `ts_closed=None`
→ do `period_end`). `runner.py`/`walk_forward.py` przekazują realne
`funding_cost` do `ExperimentRecord.funding_assumptions` zamiast napisu
`"not applied"`. Nowe pole `data_quality.funding_applied: bool` w
metadanych eksperymentu — `False` blokuje status `"realistic_backtest"`
(patrz `src/research/evaluator.py`), zgodnie z zasadą "błąd/niekompletność
danych zatrzymuje promocję, nie przepuszcza jej domyślnie". Model funding
pozostaje **przybliżeniem post-hoc** (Bybit nie ma w tym repo źródła danych
"rzeczywisty funding interval per-symbol" załadowanego automatycznie —
`FundingAssumptions.funding_hours_utc` jest konfigurowalne, ale domyślne
00/08/16 UTC to standard Bybit, nie zweryfikowany per-symbol w tej sesji);
to ograniczenie jest teraz widoczne w rekordzie eksperymentu, nie ukryte.

### M3 — Buy & Hold i każda otwarta na koniec okna pozycja: brak mark-to-market w metrykach transakcyjnych

`positions_report_to_trades` (docstring: "one still open at the end of a
backtest isn't a completed round trip yet") **odrzuca** każdą wciąż otwartą
pozycję. Dla Buy & Hold (który nigdy nie zamyka pozycji) to oznacza
`trades=0`, `net_return=0` **niezależnie od realnej zmiany ceny** — dokładnie
błąd jawnie opisany jako nienaprawiony w `docs/PROJECT_STATUS.md`
("Znane, jeszcze nie naprawione"). To czyni benchmark Buy & Hold bezużytecznym
— każda strategia "bije" 0%, nawet gdy sama traci pieniądze w rynku, który
rósł. `account_report_to_equity` (equity z konta) *pośrednio* odzwierciedla
niezrealizowany PnL poprzez saldo konta, ale metryki liczone z `trades`
(win rate, expectancy, profit factor, i przede wszystkim `net_return`
używany np. do porównania z Buy&Hold) go pomijają całkowicie.

**Naprawiono w tej sesji**: `positions_report_to_trades` przyjmuje teraz
`period_end` i `mark_prices` (ostatnia znana cena zamknięcia instrumentu na
koniec okna) i dopisuje dla każdej wciąż otwartej pozycji syntetyczny wiersz
transakcji: `exit_time=period_end`, `exit_price=mark_price`,
`quantity`/`entry_price` z pozycji, `fees=0` (pozycja nie została
faktycznie zamknięta, więc opłata zamknięcia nie została naliczona — nie
udawajmy, że była), oznaczony `is_mark_to_market=True`. Testy w
`tests/integration/test_reports_adapter.py` (istniejące) nadal przechodzą
bez zmian — nowe zachowanie jest kontrolowane osobnym, jawnym argumentem, a
istniejące wywołania bez `period_end`/`mark_prices` zachowują dokładnie
stare zachowanie (closed-only), żeby nic nie przepisywać bez potrzeby.

### M4 — Koszty: tylko jeden scenariusz (base), brak adverse/severe

`ExecutionAssumptions` (`prob_slippage=0.2`, maker/taker z instrumentu) to
jeden, stały zestaw założeń. Nie ma mechanizmu uruchomienia tej samej
strategii przez zestaw *base/adverse/severe* i wymogu przejścia adverse.
**Częściowo zaadresowane w `configs/research_protocol.yaml`** (sekcja
`costs`) w tej sesji — trzy nazwane profile z konkretnymi mnożnikami
slippage/fee/funding — ale **podłączenie realnego mnożenia kosztów wewnątrz
`ExecutionAssumptions`/silnika NautilusTrader dla scenariusza `severe`
pozostaje do zrobienia** (patrz "Znane ograniczenia" w raporcie końcowym) —
zakres tej sesji ograniczył się do bramkowania promocji, gdy adverse-cost
run nie istnieje w ledgerze dla danej hipotezy, nie do przebudowy silnika
kosztów per-scenariusz od zera.

**Update (Cykl 15, autonomiczna kontynuacja):** oba pozostałe kawałki tego
ograniczenia są teraz zamknięte. `ExecutionAssumptions.fee_multiplier`/
`slippage_multiplier`/`entry_delay_bars` faktycznie zmieniają, co silnik
nalicza (`_ScaledFeeModel`, skalowane `prob_slippage`) — to zostało dopięte
w sesji między M4 a Cyklem 15, przed moim udziałem. W Cyklu 15 dopięto
ostatni brakujący element: scenariusz `severe` jest teraz faktycznie
uruchamiany jako dodatkowy przebieg walk-forward dla każdego kandydata,
który już przeszedł bramkę `adverse` — wynik trafia do
`CandidateEvidence.aggregate_return_after_severe_costs`,
`TrialReportRow.aggregate_return_after_severe_costs` i pola `adverse_severe`
w `summary.md`. To pozostaje wyłącznie dowodem informacyjnym, nigdy nie
bramkuje promocji — `evaluate_candidate` w dalszym ciągu ocenia tylko
`adverse`, zgodnie z pierwotną decyzją zakresu opisaną wyżej.

### M5 — Monte Carlo: tylko IID bootstrap transakcji, brak block/stationary bootstrap

`run_monte_carlo` losuje transakcje **niezależnie z powtórzeniami** (IID
bootstrap po indeksach transakcji) — poprawne dla `risk_of_ruin`/rozkładu
zwrotu przy założeniu niezależności transakcji, ale **nie zachowuje
autokorelacji** (klastrów zmienności, serii strat, reżimów). Brak
moving-block/stationary bootstrap, brak osobnego losowania kosztów z
rozkładu, brak stress-testu luk cenowych. `risk_of_ruin=0.0` w
`docs/PROJECT_STATUS.md` jest raportowane jako dosłowne zero — powinno być
"0 zdarzeń na N symulacji, górna granica ufności ~3/N (regułą kciuka
Wilsona/rule-of-three)", nie prawdziwe zero prawdopodobieństwa.
**Nie naprawiono w tej sesji** — block/stationary bootstrap i
poprawiona reprezentacja `risk_of_ruin` są w planie zmian (patrz niżej),
ale wymagają nowego modułu i osobnej rundy testów, którą priorytetyzowano
niżej niż poprawność kosztowa/annualizacyjna, bo Monte Carlo obecnie *nie*
karmi żadnej automatycznej bramki promocji (bramka jeszcze nie istniała
przed tą sesją).

**Update (Cykl 16, autonomiczna kontynuacja):** oba opisane braki zamknięte.
`run_monte_carlo` (`src/analytics/monte_carlo.py`) zyskała opcjonalny
`block_size` — circular moving-block bootstrap zachowujący kolejność
oryginalnych transakcji w losowanych blokach (zamiast losować każdą
transakcję niezależnie), w pełni zwektoryzowany; domyślne zachowanie
(`block_size=None`) pozostaje identyczne jak wcześniej (IID), więc
`scripts/monte_carlo.py` i wszystkie istniejące wywołania działają bez
zmian. `MonteCarloResult.summary()` zwraca teraz `risk_of_ruin_events`
oraz `risk_of_ruin_upper_bound_ci95` (dokładny wzór Wilsona, nie tylko
przybliżenie rule-of-three) obok punktowego oszacowania — konsument już
nie widzi mylącego samego `risk_of_ruin=0.0` bez żadnej miary
niepewności. Wpięcie do cyklu workera: `run_monte_carlo` jest teraz
faktycznie wywoływana w `src/research/orchestrator.py::_run_hypothesis()`
dla każdego kandydata, który już przeszedł bramkę `adverse`
(`block_size = round(sqrt(n_trades))`, `n_simulations=10_000`), z wynikiem
w `CandidateEvidence.monte_carlo_risk_of_ruin`/
`monte_carlo_risk_of_ruin_upper_bound_ci95` — nadal wyłącznie dowód
informacyjny, zgodnie z pierwotną decyzją, że Monte Carlo nie bramkuje
promocji. Osobne losowanie kosztów z rozkładu i stress-test luk cenowych
z tego akapitu **pozostają nie zaimplementowane** — to odrębny,
nierozpoczęty zakres pracy, nie objęty Cyklem 16.

## Błędy implementacyjne

- `fingerprint_dataset` w `src/analytics/experiment.py` odciska dane po
  `(nazwa pliku, rozmiar, mtime)`, nie po treści — dwa różne zestawy danych
  o tym samym rozmiarze i przypadkowo zbieżnym mtime dają ten sam
  fingerprint; `touch` bez zmiany treści zmienia fingerprint niepotrzebnie.
  Zadanie wymaga fingerprintu "opartego na treści, nie wyłącznie mtime" dla
  nowego workera — zaadresowane w `src/research/ledger.py` (SHA-256 po
  zawartości plików Parquet, nie po metadanych systemu plików), ale
  **istniejący `fingerprint_dataset` pozostawiono nietknięty** (używany przez
  działające skrypty, zmiana jego kontraktu byłaby przepisywaniem działającej
  części bez potrzeby — nowy kod research-workera używa nowej funkcji).
- `check_experiment_history` (`live_preflight.py`) liczy tylko wpisy
  BACKTEST — sesje PAPER nie są w ogóle rejestrowane jako wpisy w
  `ExperimentStore`. Poza zakresem tej sesji (LIVE pozostaje i tak
  zablokowane niezależnie), ale odnotowane jako realny dług.
- `scripts/monte_carlo.py` nie ma flagi `--periods-per-year` w ogóle — przy
  okazji naprawy M1 dodano ją i domyślne mapowanie z timeframe.

## Ryzyka data leakage

- Brak zamrożonego, jednorazowego holdoutu — `run_walk_forward.py` można
  uruchomić dowolną liczbę razy na tym samym zakresie dat z innymi
  parametrami/strategią, obserwując wynik za każdym razem i "próbując
  ponownie" — to jest data leakage przez wielokrotne obserwowanie tego
  samego okna testowego (nie przez samą logikę okna, która jest poprawna,
  ale przez brak mechanizmu poza-kodowego, który by to blokował).
  **Zaadresowane w `configs/research_protocol.yaml`** (`holdout` sekcja,
  zamrożone daty) i `src/research/ledger.py` (`holdout_used` — twardy błąd
  przy drugim użyciu tego samego `(hypothesis_family, holdout_id)`).
- `param_grid` w walk-forward jest dozwolony bez górnego ograniczenia liczby
  kombinacji — nic nie stoi na przeszkodzie przekazaniu siatki 10 000
  kombinacji z linii poleceń. **Zaadresowane**: `research_protocol.yaml`
  (`max_variants_per_hypothesis`) + walidacja w `src/research/queue.py`.
- Brak globalnego licznika prób (patrz M-częściowe #3) jest samo w sobie
  formą ukrytego data-snoopingu na poziomie meta: każde ponowne
  uruchomienie CLI "zapomina", ile hipotez już przetestowano.

## Ryzyka overfittingu

- Brak wymogu wielu niezależnych instrumentów/reżimów przed promocją —
  `docs/PROJECT_STATUS.md`'s wybrany kandydat (momentum BTCUSDT 4h) bazuje
  na jednym symbolu, jednym interwale, jednym oknie dat. Zaadresowane w
  `research_protocol.yaml`'s promotion gate (`min_symbols_positive: 2`).
- Brak testu wrażliwości na przesunięcie parametrów ±10–20% i brak testu
  "opóźnienie wejścia o 1 bar" — obecnie żadna strategia w repo nie jest
  automatycznie sprawdzana pod tym kątem. Zaadresowane strukturalnie w
  `src/research/evaluator.py` (`ParameterPerturbationCheck`,
  `EntryLagCheck`) — zaimplementowane jako wywoływalne funkcje z testami,
  ale **nie były uruchomione na strategii momentum na realnych danych** w
  tej sesji (brak danych, patrz nagłówek).
- PBO niepodłączone (patrz wyżej) oznacza, że obecny kandydat nigdy nie
  przeszedł przez CSCV.

## Elementy blokujące wiarygodną ocenę obecnego momentum BTCUSDT 4h

1. Sharpe 4.42 (4h) i Sharpe 16.91/3.60 (1d) niemal na pewno zannualizowane
   błędnym czynnikiem (M1) — patrz przeliczenie niżej.
2. Brak funding (M2) — pozycje trend-followingowe trzymane godzinami/dniami
   przez wiele rozliczeń funding, koszt niepoliczony.
3. Zero DSR/PBO liczonych globalnie po całej historii prób (5 strategii ×
   4 interwały × wielokrotne powtórzenia w trakcie sesji badawczej = dużo
   więcej niż "1 próba" sugerowana przez lokalny `n_trials`).
4. Brak testu adverse/severe cost, brak block-bootstrap, brak
   parameter-perturbation, brak drugiego symbolu/reżimu.
5. Kandydat trafił od razu do PAPER (uruchomiony ręcznie na VPS) bez
   przejścia przez żadną z powyższych bramek, bo te bramki wcześniej nie
   istniały w kodzie.

**Wniosek**: obecny kandydat momentum BTCUSDT 4h jest **obiecującym punktem
wyjścia do dalszych badań, nie zweryfikowaną, wiarygodną hipotezą** w
rozumieniu tego briefu. Nie należy go traktować jako "sprawdzoną strategię"
— dokładnie to zjawisko (promocja po samym Sharpe z jednego backtestu) ten
brief każe wykluczyć.

## Przeliczenie kandydata momentum BTCUSDT (annualizacja)

Analityczne przeliczenie (nie nowy backtest — brak danych w tej sesji, patrz
nagłówek): Sharpe skaluje się `sqrt(periods_per_year)`, więc przy tym samym
`mean/std` zwrotów per-bar, stary błędny wynik i poprawny wynik są związane
stałym mnożnikiem `sqrt(periods_per_year_correct) / sqrt(periods_per_year_wrong)`.
CAGR/max drawdown/net_return/liczba transakcji **nie są dotknięte** — tylko
Sharpe/Sortino/Calmar.

| Strategia / interwał | Sharpe raportowany (`docs/PROJECT_STATUS.md`, annualizacja 1h) | Mnożnik korekty | **Sharpe poprawny** |
| --- | --- | --- | --- |
| momentum, BTCUSDT, 4h | 4.42 | ×0.5 (`sqrt(2191.5/8766)`) | **≈2.21** |
| volatility_expansion, BTCUSDT, 1d | 16.91 | ×0.2041 (`sqrt(365.25/8766)`) | **≈3.45** |
| momentum, BTCUSDT, 1d | 3.60 | ×0.2041 | **≈0.73** |

Kandydat momentum BTCUSDT 4h pozostaje dodatni po korekcie (Sharpe ≈2.21,
wciąż wyraźnie ponad zero), ale to **około połowa** wartości, na podstawie
której wybrano go ręcznie do PAPER — nie jest to już wynik "wyjątkowo
dobry", tylko "obiecujący, wymagający pełnej weryfikacji przez bramkę
promocji" (funding, DSR/PBO globalne, adverse costs, drugi symbol/reżim,
block bootstrap — żadne z tego nie zostało jeszcze na nim uruchomione).
`volatility_expansion` 1d spada z "spektakularnego" 16.91 do umiarkowanego
~3.45 — wciąż potencjalnie interesujące, ale ta strategia miała już
udokumentowane w `docs/PROJECT_STATUS.md` ostrzeżenie o małej próbie (39
transakcji, 5. percentyl Monte Carlo ujemny) niezależnie od annualizacji.

**Wymagany następny krok** (poza zakresem tej sesji — brak dostępu do
realnych danych Bybit tutaj): ponowne, pełne uruchomienie
`scripts/run_walk_forward.py` na VPS z tym kodem (annualizacja teraz
poprawna automatycznie, funding i mark-to-market teraz aktywne domyślnie)
dla obu kandydatów, zanim którykolwiek z nich zostanie potraktowany jako
zweryfikowany kandydat w rozumieniu tego briefu.

## Dokładny plan zmian (zrealizowany w tej sesji, w kolejności)

1. `src/backtesting/annualization.py` + wpięcie do 4 skryptów CLI (M1).
2. `positions_report_to_trades`/`runner.py`/`walk_forward.py`: funding (M2)
   + mark-to-market otwartych pozycji (M3), oba za jawnymi, opcjonalnymi
   argumentami żeby nie zepsuć istniejących wywołań/testów.
3. Przeliczenie Sharpe momentum BTCUSDT 4h / 1d z poprawną annualizacją
   (analityczne, bez ponownego backtestu — brak danych w tej sesji).
4. `configs/research_protocol.yaml` — wersjonowany protokół badawczy.
5. `src/research/` — moduł workera: `config.py`, `hypothesis.py`,
   `ledger.py` (rozszerza wzorzec `ExperimentStore` o `hypothesis_id`,
   `parent_hypothesis_id`, `rationale`, status, i licznik globalny dla
   DSR), `queue.py` (ograniczone rodziny hipotez A/B z briefu), `evaluator.py`
   (bramka promocji z `research_protocol.yaml`), `promotion.py` (maszyna
   stanów REJECTED→...→PAPER_CHAMPION, wymaga ręcznej zgody człowieka na
   ostatnim kroku), `reporting.py`, `locking.py`, `orchestrator.py`.
6. `scripts/run_research_cycle.py` / `scripts/run_research_daemon.py`.
7. Jeden mały end-to-end cykl na danych syntetycznych.
8. `docker-compose.yml`: `research-worker`, `paper-session`,
   `microstructure-collector`, `data-compactor` jako właściwe usługi z
   `restart_policy`/`healthcheck`/limitami.
9. Testy dla wszystkiego powyżej.
10. `ruff`/`mypy`/`pytest`/`detect-secrets`, commit, raport końcowy.

Elementy z briefu **świadomie odłożone poza tę sesję** (i dlaczego) są
wymienione w "Znane ograniczenia" raportu końcowego — cost-scenario engine
wiring (severe cost multiplier wewnątrz silnika), block/stationary
bootstrap w Monte Carlo, pełny system alertów zewnętrznych (Slack/e-mail),
i realny, wielotygodniowy PAPER monitoring (wymaga czasu, nie tylko kodu).
