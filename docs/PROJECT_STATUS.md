# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 10)

---

## CURRENT PHASE

**PHASE 10 — Paper execution** — UKOŃCZONA (z jednym udokumentowanym
ograniczeniem sieciowym).

System potrafi uruchomić dokładnie te same, niezmienione klasy strategii co
w backteście (Fazy 5-6) na żywo przeciwko Bybit testnet, przez natywny
adapter Bybit w NautilusTrader — to jest bezpośrednia realizacja decyzji
architektonicznej z Fazy 0 ("ten sam silnik, ten sam kod strategii dla
backtestu i live"). Tryb `LIVE` jest po raz pierwszy realnie zablokowany w
kodzie (nie tylko opisany w dokumentacji od Fazy 1).

---

## DONE (Faza 10)

- `src/execution/mode.py` — `resolve_trading_mode()`: pierwsza realna
  egzekwowalna bramka bezpieczeństwa `RESEARCH`/`BACKTEST`/`PAPER`/`LIVE`.
  `LIVE` wymaga dodatkowej, osobnej zmiennej środowiskowej
  `CONFIRM_LIVE_TRADING=I_UNDERSTAND_THE_RISK` — nieosiągalny przez samo
  ustawienie `TRADING_MODE=LIVE`.
- `src/execution/intent.py` / `adapter.py` — formalizacja pipeline'u z
  sekcji 31: `SIGNAL -> RISK -> ORDER INTENT -> EXECUTION -> EXCHANGE` jako
  `OrderIntent`/`ExecutionAdapter` (protokół) — wymiana adaptera nigdy nie
  wymaga dotykania kodu strategii ani risk engine.
- `src/execution/fill_tracking.py` — `compare_fill()`/`FillTracker`:
  porównanie expected vs actual z sekcji 32 — slippage (adverse-positive
  niezależnie od strony), latency, wykrywanie problemów z danymi (ujemna
  latencja, zerowe/częściowe wypełnienia).
- `src/execution/paper_node.py` — `build_paper_trading_node()`: uruchamia
  **dokładnie te same, niezmienione** klasy `Strategy` z Faz 5-6 na żywo
  przeciwko Bybit testnet przez natywny adapter Bybit w NautilusTrader
  (`nautilus_trader.adapters.bybit`) — nie własnoręcznie pisany klient.
  Odmawia budowy dla trybu innego niż `PAPER` (brak parametru pozwalającego
  wskazać venue live/mainnet — nie da się tym przypadkiem trafić w
  prawdziwe pieniądze).
- `src/execution/simulated_adapter.py` + `backtest_bridge.py` — pozwalają
  uruchomić całą maszynerię `FillTracker` w pełni offline: transakcje z
  backtestu stają się `OrderIntent`ami, odtwarzane przez seedowany,
  symulowany adapter — tryb DRY-RUN (sekcja 1 wymagań) bez zależności
  sieciowej.
- `scripts/paper_trade.py` — CLI uruchamiające sesję paper trading
  (wymusza `TRADING_MODE=PAPER` przez bramkę z `mode.py`).
- Testy: `tests/unit/test_trading_mode.py` (6), `tests/unit/
  test_fill_tracking.py` (12), `tests/unit/test_simulated_adapter.py` (6),
  `tests/unit/test_backtest_bridge.py` (4), `tests/unit/test_paper_node.py`
  (3 — budowa realnego `TradingNode` z zarejestrowaną strategią, bez
  łączenia się z siecią), `tests/integration/test_paper_dry_run.py` (1 —
  pełny pipeline: prawdziwy backtest → `OrderIntent` → symulowane
  wykonanie → `FillTracker`, w całości offline).

---

## TESTY / WALIDACJA (Faza 10)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (52 pliki źródłowe).
- `python3 -m pytest -q` — **232/232 testów przechodzi** (200 z Faz 1-9 +
  32 nowe z Fazy 10).
- **Realna weryfikacja, nie tylko testy jednostkowe**: `build_paper_trading_
  node()` uruchomiony bezpośrednio (nie przez mock) faktycznie zbudował
  kompletny, gotowy `TradingNode` NautilusTrader z zarejestrowaną
  strategią `TrendFollowing` — pełna inicjalizacja silnika (Cache,
  DataEngine, RiskEngine, ExecEngine) zakończona sukcesem, bez żadnego
  wywołania sieciowego (połączenie następuje dopiero przy `node.run()`,
  którego celowo nie wywołano). To najsilniejsza możliwa weryfikacja
  dostępna w tym środowisku bez łączności z Bybit.
- `scripts/paper_trade.py` przetestowany z linii poleceń: brak
  `TRADING_MODE` i `TRADING_MODE=LIVE` bez potwierdzenia poprawnie
  odrzucane z czytelnym komunikatem błędu.
- Pełny offline pipeline dry-run (prawdziwy backtest → bridge → symulowane
  wykonanie → porównanie) uruchomiony end-to-end na syntetycznych danych.
- `detect-secrets scan` — brak nowych sekretów.

---

## KNOWN ISSUES

- **Realna łączność z Bybit testnet nie została zweryfikowana w tej
  sesji** — polityka sieciowa blokuje `api.bybit.com` (ta sama blokada co
  w Fazie 2). Zweryfikowano wszystko, co możliwe bez sieci: poprawność
  konfiguracji klienta (`BybitDataClientConfig`/`BybitExecClientConfig`,
  `testnet=True`), pełną budowę `TradingNode` z zarejestrowaną strategią.
  **Rekomendacja**: przed poleganiem na `scripts/paper_trade.py` do
  realnego paper tradingu, zweryfikować połączenie na maszynie z
  nieograniczonym dostępem do sieci (docelowy VPS lub lokalnie) —
  udokumentowane w `docs/VPS_DEPLOYMENT.md`.
- `src/execution/fill_tracking.py` nie śledzi spreadu (bid/ask w momencie
  wykonania) — wymaga danych order-book, których jeszcze nie ma w projekcie
  (odłożone od Fazy 0, sekcja 7: dane mikrostruktury "później"). Jawnie
  udokumentowane jako ograniczenie zakresu, nie przeoczenie.
- Brak jeszcze prawdziwego trybu `LIVE` (mainnet) — `TRADING_MODE=LIVE`
  jest zablokowany w kodzie, ale nawet po odblokowaniu nie istnieje ścieżka
  wykonania dla live/mainnet (tylko `PAPER`/testnet). To celowe — sekcja 6
  wymagań blokuje LIVE do czasu osobnej, wyraźnej decyzji.

---

## NEXT

**PHASE 11 — ML research framework**, do rozpoczęcia dopiero po kolejnym
wyraźnym poleceniu.

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę?
   Częściowo zaadresowane w Fazie 7 — natywna pętla przez `BacktestEngine`
   wystarczająco szybka jak dotąd.
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3;
   otwarte pozostaje przejście na model dynamiczny i dobór rzeczywistej
   stawki.
3. Kiedy potrzebne będą dane tick-level/order-book? Faza 10 dodała
   konkretny powód: śledzenie spreadu przy wykonaniu wymaga tych danych.
4. Mechanizm eksperyment-trackingu — zaadresowane w Fazie 4 (JSON Lines +
   sekwencyjne ID).

---

## Decyzje projektowe podjęte w Fazie 10

- Użycie natywnego adaptera Bybit z NautilusTrader
  (`nautilus_trader.adapters.bybit`) zamiast własnoręcznie pisanego klienta
  na `pybit` — odkryte podczas researchu tej fazy, dokładnie realizuje
  obietnicę z Fazy 0 ("ten sam silnik i kod strategii dla backtestu i
  live") bez dodatkowego kodu do utrzymania.
- `build_paper_trading_node()` strukturalnie nie przyjmuje żadnego
  parametru wskazującego venue live/mainnet — bezpieczeństwo przez
  niemożność wyrażenia złej konfiguracji, nie tylko przez runtime-check.
- `resolve_trading_mode()` jako pojedyncze miejsce prawdy dla bramki LIVE —
  każdy przyszły punkt wejścia mogący złożyć realne zlecenie musi przez nie
  przechodzić, zamiast każdy skrypt sam sprawdzający `TRADING_MODE`.
- `FillTracker`/`SimulatedExecutionAdapter` zaprojektowane jako w pełni
  niezależne od Bybit/sieci — pozwala to przetestować i zademonstrować całą
  logikę porównania expected-vs-actual bez czekania na zweryfikowaną
  łączność, korzystając z tego samego wzorca DI co `BybitKlineClient` z
  Fazy 2.
- Spread świadomie pominięty w `fill_tracking.py` (wymaga danych
  order-book) zamiast dodawania pustego, nigdy niewypełnionego pola —
  udokumentowany jako przyszłe rozszerzenie, nie ukryty brak.

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
