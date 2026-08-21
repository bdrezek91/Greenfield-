# PROJECT STATUS — ai-trading-lab

> **Status historyczny.** Nadrzędnym źródłem prawdy dla bieżącego stanu,
> architektury, kolejności prac i Definition of Done jest
> [GREENFIELD_V2_MASTER_PLAN.md](GREENFIELD_V2_MASTER_PLAN.md).
>
> **Bieżący etap: Greenfield Market Intelligence v2 — Phase 1.**
> Wybrany pełny rdzeń zachowano na codex/stable-greenfield-v1-core, a rozwój
> jest prowadzony przez codex/greenfield-market-intelligence-v2. Techniczny
> zakres Phase 0 jest zakończony i potwierdzony zielonym CI oraz testem obrazu
> Docker. Phase 1 buduje lossless raw collector v2 dla BTC, ETH i SOL — bez
> dodawania nowych strategii lub AI. Włączenie ochrony branchy pozostaje
> administracyjnym zadaniem w ustawieniach GitHub.

Ostatnia aktualizacja: 2026-08-17 (rodzina C funding/OI, pełne cykle
badawcze na realnych danych VPS, eksperyment z ATR-exit, orienting check
mikrostruktury, rodzina F price-action confluence, kolektor long/short
ratio, sesja PAPER zatrzymana)

---

## Sesja PAPER zatrzymana

Kandydat `momentum-BTCUSDT-4h` uruchomiony 2026-08-16 był wybrany starą
metodą (walk-forward Sharpe + Monte Carlo), zanim wdrożono pełny protokół
DSR/PBO. Ten sam wariant (lookback=20, threshold=0.005) przetestowany
później przez `HYP-momentum_trend-000001` w obu cyklach 22-hipotezowych
jednoznacznie nie przeszedł bramki (DSR=0.061, PBO=0.93). Sesja PAPER
zatrzymana `2026-08-17` - nie ma sensu trzymać w PAPER strategii, którą
własny protokół by odrzucił. Żaden kandydat obecnie nie jest w PAPER.

## Research na temat realnych źródeł edge'u + nowe zbieranie danych

Web research (nie z pamięci) przed budową kolejnej rodziny:
- **Funding rate carry (delta-neutral spot+perp)**: historycznie realny
  edge (Sharpe ~6.45 2020-2025), ale wyraźnie się psuje (~4.06 od 2024,
  ujemny w 2025 wg jednego źródła) - wymaga hedgowanej egzekucji
  spot+perp, której silnik obecnie nie ma. Niezaimplementowane.
- **Arbitraż międzygiełdowy**: udokumentowane, realne rozbieżności cenowe
  (>=0.5%, tysiące razy dziennie), ale wymaga multi-exchange infra, której
  nie mamy. Niezaimplementowane.
- **Kaskady likwidacji jako sygnał**: ostrzegawczy precedens znaleziony w
  sieci - strategia wyglądająca na +299%/Sharpe 3.58 okazała się po
  dekompozycji beta w 54% zwykłą ekspozycją na BTC, nie realną alfą.
  Dokładnie ten typ złudzenia, przed którym chroni nasz DSR/PBO.
- **Long/short account ratio**: Bybit nie udostępnia głębokiego backfillu
  (tylko krótkie bieżące okno) - jak mikrostruktura, trzeba zbierać na
  żywo. Dodano `long-short-ratio-collector` (poll co 60s,
  `src/data/long_short_ratio_collector.py`) - **NIEZWERYFIKOWANE w tej
  sesji** (blokada sieciowa do api.bybit.com/docs), nazwy pól odpowiedzi
  (buyRatio/sellRatio) trzeba potwierdzić na VPS.

## Rodzina F: price-action confluence (liquidity sweep + OI)

Zbudowana na podstawie researchu, nie zgadywania: mechaniczna, w pełni
deterministyczna wersja popularnego setupu "smart money concepts" - knot
świecy wybija poprzedni N-barowy swing high/low, ale zamknięcie wraca do
środka zakresu (nieudany breakout, dokładne odwrócenie warunku
`Breakout`), potwierdzone rosnącym OI (ta sama rola co w
`funding_contrarian`). Świadomie sformułowana jako falsyfikowalna reguła,
nie subiektywna analiza wykresu, żeby przejść przez ten sam gate
DSR/PBO co wszystko inne. Budżet cyklu podniesiony 22->28.

---

## Mikrostruktura: orienting check na realnych danych (rodzina E, dalej wyłączona)

Zbieranie mikrostruktury (`microstructure-collector`, od 2026-08-16) dało
do 2026-08-17 ~27h ciągłych danych BTCUSDT (2.77M wierszy orderbooka, 0
luk >5s; 1.26M transakcji, dobra jakość). `scripts/explore_microstructure.py`
(orienting check, NIE backtest, poza `src/research/`) porównał trzy
kandydackie cechy 60-sekundowych barów vs. korelacja z następnym zwrotem:

- top-of-book imbalance (poziom): **+0.06 do +0.09** w kolejnych pomiarach
  na rosnącej próbce — słaby, ale spójny kierunkowo.
- imbalance momentum (zmiana imbalance): +0.024 — słabszy niż poziom.
- trade-flow imbalance (agresja z `trades`, kto faktycznie płacił spread):
  **-0.013** — praktycznie zero, nie potwierdza niczego.

Jednorazowy test naiwnej strategii progowej na poziomie imbalance
(`scripts/hypothetical_microstructure_strategy.py`, jawnie oznaczony jako
niepromowalny) stracił -70% do -159% netto po realnych kosztach (taker fee
+ spread) w zależności od progu — surowy edge (~0.06-0.09 korelacji) jest
o rząd wielkości za słaby, żeby pokryć koszt transakcyjny na tej
częstotliwości. **Wniosek: żadna z trzech sprawdzonych cech nie daje
sygnału wartego budowy strategii na obecnej próbce.** Rodzina E zostaje
wyłączona w `configs/research_protocol.yaml`; dane dalej się zbierają w
tle, można wrócić z dużo większą próbką i/lub inną cechą później, ale nie
przez dalsze przeszukiwanie wariantów na tej samej ~27h próbce (to już
byłby data mining, nie orientacyjny test).

---

## Iteracja badawcza 2026-08-17: rodzina C, pełne cykle na realnych danych, ATR-exit

Wykonane na VPS, prawdziwe dane Bybit (BTCUSDT/ETHUSDT/SOLUSDT, 2020-2026):

- **Rodzina C (funding/OI contrarian)** zaimplementowana
  (`src/strategies/funding_contrarian.py`): ekstremalny z-score funding
  rate jako sygnał kontrariański, potwierdzany rosnącym open interest.
  Budżet cyklu podniesiony do 22 (pokrywa rodziny A+B+C w całości).
- **Dwa pełne cykle 22-hipotezowe uruchomione na realnych danych**
  (`CYCLE-20260817T094556Z`, `CYCLE-20260817T101846Z`) — oba
  `NO_CANDIDATE`. Żadna hipoteza (momentum, trend_following,
  cross_asset_momentum, funding_contrarian) nie osiągnęła DSR>=0.95 ani
  dodatniego zwrotu na >=2 niezależnych symbolach jednocześnie po
  kosztach adverse. Konsekwentny wzorzec: PBO bliskie/równe 1.0,
  parametry wyglądające jak izolowany szpic (nie plateau), degradacja
  >=100% przy perturbacji parametrów +/-10-20%.
- **Eksperyment: ATR-based exit zamiast stałej liczby barów**
  (`src/strategies/base.py`'s `use_atr_exit`) — hipoteza: sztywny hold
  czasowy dokłada szum niezwiązany z jakością sygnału. Zmierzone, nie
  założone: na 4h liczba transakcji wzrosła ~2x (np. momentum BTCUSDT
  142->305), bo stop 2x ATR jest zbyt ciasny na tych aktywach/interwałach
  i łapie zwykły szum, generując dużo więcej round-tripów i prowizji.
  Każda metryka pogorszyła się, nie poprawiła (DSR bliżej zera, dzienne
  próbki funding_contrarian spadły do 4-6 transakcji, daleko poniżej
  progu 30). **Wniosek: hipoteza się nie potwierdziła** — cofnięte do
  domyślnego stałego exitu w `src/research/queue.py`; `use_atr_exit`
  zostaje w kodzie (przetestowany, gotowy) dla przyszłego eksperymentu z
  innym mnożnikiem, ale nie jest stosowany domyślnie.
- Wniosek na ten moment: proste, rule-based sygnały (momentum,
  potwierdzenie reżimu cross-asset, funding/OI contrarian) na tym
  universum i tych interwałach (4h/1d) nie mają edge'u po realistycznych
  kosztach Bybit. `global_trial_count` (DSR) = 78 po tych cyklach.

---

## CURRENT PHASE

**PHASE 15 — Przygotowanie do LIVE** — UKOŃCZONA (bramka gotowości, NIE
ścieżka wykonania LIVE — patrz niżej). Wszystkie 15 faz z oryginalnego
briefu ukończone; poniżej pierwsza pozycja iteracji badawczej po Fazie 15.

Druga, niezależna od `CONFIRM_LIVE_TRADING`, bramka bezpieczeństwa:
automatyczne sprawdzenie gotowości (tryb, poświadczenia, parametry ryzyka,
historia eksperymentów) plus pisemna checklista operacyjna
(`docs/LIVE_READINESS_CHECKLIST.md`) dla wszystkiego, czego nie da się
sprawdzić w kodzie. **Świadomie NIE zbudowano ścieżki składania zleceń
LIVE** — `src/execution/paper_node.py` nadal obsługuje wyłącznie
`TradingMode.PAPER`; ta decyzja pozostaje osobna, przyszła, wymagająca
wyraźnego polecenia człowieka, nie efektem ubocznym "przygotowania".

---

## Iteracja badawcza 2026-08-16: VPS, Bybit Demo, wielointerwałowe badanie strategii, nowe warstwy danych

### Paper trading na Bybit Demo — od zera do działającej sesji live

`src/execution/paper_node.py` przebudowany, żeby wspierać backend
`"demo"` (Bybit Demo Trading) obok istniejącego `"testnet"` — konieczne,
bo rejestracja na testnet.bybit.com jest zablokowana geograficznie dla
kont z UE. Po drodze znalezione i naprawione na żywo na VPS (nie w
sandboxie — sesja deweloperska ma zablokowany `api.bybit.com`) pięć
kolejnych, realnych błędów, każdy odkryty dopiero przy faktycznym
uruchomieniu:

1. Publiczny WebSocket danych rynkowych błędnie kierowany na
   `stream-demo.bybit.com` (który obsługuje tylko kanały prywatne) zamiast
   `stream.bybit.com` — 404.
2. `BybitInstrumentProvider` domyślnie ładuje zero instrumentów
   (`load_all=False`) — trzeba jawnie ustawić `InstrumentProviderConfig(load_all=True)`.
3. Klient danych demo uderzał w `api-demo.bybit.com` dla publicznych
   endpointów rynkowych, które tam nie działają ("Demo trading are not
   supported.") — klient danych w trybie demo jest teraz zwykłym klientem
   mainnet z osobnym, prawdziwym kluczem `BYBIT_API_KEY` (wystarczy
   uprawnienie tylko-do-odczytu).
4. `scripts/paper_trade.py`/`run_paper_session.py` budowały ID
   instrumentu jako `<SYMBOL>-PERP.BYBIT` (konwencja tylko-backtestowa) —
   żywy katalog instrumentów Bybit używa `<SYMBOL>-LINEAR.BYBIT`; strategia
   cicho nigdy nie subskrybowała świec pod złym ID.
5. **Najpoważniejszy**: nieudana rekoncyliacja stanu wykonania przy
   starcie (stare zlecenie stop-loss na koncie, którego kombinacji
   parametrów nie rozpoznaje parser enumów NautilusTradera) powodowała, że
   `kernel.start_async()` robił `return` **przed** wywołaniem
   `trader.start()` — strategia nigdy nie dostawała `on_start()`, węzeł
   mimo to logował "RUNNING" i wyglądał na żywy. Naprawione przez
   wyłączenie rekoncyliacji startowej dla PAPER
   (`LiveExecEngineConfig(reconciliation=False)`) — świeża sesja paper nie
   ma własnego stanu do uzgadniania.

Dodano też logowanie subskrypcji i każdej odebranej świecy w
`src/strategies/base.py` (`on_start`/`on_bar`) — bez tego brak logów przy
poprawnie działającej strategii jest nie do odróżnienia od zawieszenia
(NautilusTrader nie loguje pojedynczych barów domyślnie).

### Wielointerwałowe badanie strategii (walk-forward, nie in-sample)

Dla BTCUSDT, 5 strategii (`trend_following`, `momentum`, `breakout`,
`mean_reversion`, `volatility_expansion`) przez `scripts/run_walk_forward.py`
(dobór parametrów na oknie walidacyjnym, ocena tylko na oknie testowym):

- **15m** — wszystkie strategie ujemne (Sharpe -4.9 do -6.6, zwrot -14%
  do -34%). Koszty transakcyjne (realny model opłat Bybit) dominują przy
  tej częstotliwości.
- **1h** — wszystkie ujemne lub blisko zera (najlepszy: trend_following
  Sharpe -1.73).
- **4h** — **momentum Sharpe 4.42** (zwrot +19.9%), trend_following Sharpe
  1.42 — pierwsze realnie dodatnie wyniki.
- **1d** — volatility_expansion Sharpe 16.91 (ale tylko 39 transakcji —
  mała próba, Monte Carlo pokazuje 5. percentyl zwrotu ujemny, -12.3%);
  momentum Sharpe 3.60 — **potwierdza przewagę momentum na dwóch
  niezależnych interwałach**.

Wybrany kandydat do live paper: **momentum, BTCUSDT, 4h,
lookback_bars=20, threshold=0.005**. Monte Carlo (10 000 symulacji na
zrealizowanej sekwencji 555 transakcji): `risk_of_ruin=0.0`, zwrot nawet w
5. percentylu dodatni (+1.0%). Działa teraz jako długoterminowa sesja
`docker compose run -d --name paper-session` na koncie Demo.

Dwa dodatkowe, świadomie odrzucone kierunki:

- **Day trading (15m)** — odrzucony jednoznacznie (patrz wyżej).
- **Filtr sesji EU/US** (`session_start_hour`/`session_end_hour` w
  `BenchmarkStrategyConfig`, `src/strategies/base.py`) — zaimplementowany
  poprawnie (wymusza zamknięcie pozycji poza oknem sesji, przetestowany
  jednostkowo), ale walk-forward na 1h pokazał **pogorszenie** wyniku
  (trend_following: Sharpe -1.73 → -5.52; momentum: -4.60 → -5.87) — BTC
  handluje się 24/7, więc odcinanie sesji azjatyckiej tylko ucina zyskowne
  ruchy bez usuwania realnie gorszego okresu. Zostaje w kodzie jako
  domyślnie wyłączona opcja, nieużywana.
- **ML na standardowych cechach technicznych** — żaden model (logistic
  regression, random forest, extra trees) nie pobił naiwnego baseline'u na
  żadnym foldzie walidacji krzyżowej (`scripts/train_baseline_models.py`);
  ROC-AUC ~0.50-0.52. Brak sygnału w tym zestawie cech dla horyzontu 24h.

### Nowe warstwy danych

Historyczne (do backfillowania przez REST, ten sam wzorzec co świece):

- `src/data/funding_client.py`, `src/data/open_interest_client.py`,
  `src/data/ingest_funding.py`, `src/data/ingest_open_interest.py`,
  `scripts/download_funding_oi.py` — funding rate i open interest,
  przechowywane w Parquet równolegle do klines.
- `src/features/pipeline.py`: `build_feature_matrix()` przyjmuje opcjonalne
  `funding`/`open_interest` → kolumny `funding_rate`/`oi_change`
  (`EXTENDED_FEATURE_COLUMNS`) — domyślnie `None`, zero wpływu na
  istniejące modele/wywołania.

Nie do backfillowania (Bybit nie udostępnia historii — tylko żywy stream):

- `src/data/orderbook_state.py` (książka zleceń klient-side z protokołu
  snapshot/delta, zredukowana do podsumowania top-N poziomów: best
  bid/ask, imbalance), `src/data/microstructure_parser.py` (czyste
  parsowanie wiadomości, testowalne bez sieci),
  `src/data/microstructure_writer.py` (każdy flush to osobny plik Parquet
  — unika kosztownego wzorca odczyt-scal-zapis przy częstotliwości
  update'ów order booka), `src/data/microstructure_collector.py`,
  `scripts/collect_microstructure.py`.
- Na żywo na VPS: zweryfikowana realna częstotliwość ~22 aktualizacje
  order booka/s i ~25 transakcji/s na BTCUSDT. Po drodze znaleziony i
  naprawiony na żywo: `pybit` usunął `liquidation_stream()` na rzecz
  `all_liquidation_stream()` (inny, zbiorczy kształt wiadomości), oraz
  brak obsługi SIGTERM w `run_forever()` — `docker stop` (normalny sposób
  zatrzymania długo działającego kolektora) zabijał proces przed
  `finally: self.flush()`, cicho gubiąc niezapisany bufor.
- Kolektor działa teraz w tle na VPS (`docker compose run -d --name
  microstructure`), zbiera dane od 2026-08-16 — za wcześnie na test
  order-book-imbalance jako sygnału, potrzeba dni/tygodni historii.

### Znane, jeszcze nie naprawione

- Metryka `net_return` dla `buy_and_hold` liczy tylko zamknięte
  transakcje — pozycja Buy&Hold nigdy się nie zamyka, więc raport pokazuje
  0 transakcji / 0% zwrotu mimo realnej zmiany ceny w okresie. Czyni to
  porównanie "czy bijemy trzymanie" bezużytecznym, dopóki nienaprawione.
- Brak kompaktowania plików mikrostruktury — przy obecnym tempie to
  ~5 760 plików/dzień; potrzebny okresowy job łączący pliki jednego dnia,
  zanim liczba plików zacznie realnie spowalniać odczyt.
- Walidacja: `pytest` 431/431, `ruff` clean po każdej zmianie w tej
  iteracji.

---

## Iteracja badawcza po Fazie 15: Probability of Backtest Overfitting

Domknięcie luki jawnie nazwanej w oryginalnym briefie (sekcja o
multiple-hypothesis-testing: DSR, PBO, White's Reality Check, bootstrap) —
DSR i bootstrap były gotowe od Fazy 4/6, PBO brakowało.

- `src/analytics/robustness.py:probability_of_backtest_overfitting` —
  Combinatorially Symmetric Cross-Validation (Bailey, Borwein, López de
  Prado & Zhu, 2015). Dzieli macierz wyników T okresów × N prób na
  `n_partitions` bloków, rozważa każdy sposób przydziału połowy bloków do
  treningu/testu (C(S, S/2) kombinacji), i zwraca ułamek podziałów, w
  których próba najlepsza in-sample wypadła w dolnej połowie
  out-of-sample.
- **Optymalizacja wydajności znaleziona przed napisaniem testów** (ten sam
  wzorzec co sanity-check przed testami w Fazie 8/11): naiwna
  implementacja (rekonstrukcja train/test przez `pd.concat` i
  `DataFrame.apply` osobno dla każdej z C(16,8)=12870 kombinacji przy
  standardowym S=16) zajmowała **47 sekund** przy realistycznym rozmiarze
  (T=224, N=30). Naprawione przez policzenie `metric_fn` raz na blok
  (S×N wywołań, nie C(S,S/2)×N) i redukcję kombinacji przez czyste numpy
  zamiast pandas — **2.3 sekundy**, identyczny wynik liczbowy (zweryfikowane
  bit-for-bit dla domyślnej metryki średniej).
- Sanity-checki przed testami: próba z realną, stałą przewagą we
  wszystkich blokach → PBO≈0.0; czysty szum (bez żadnej przewagi,
  uśrednione po 20 seedach) → PBO≈0.48, blisko teoretycznych 0.5.
- Testy: `tests/unit/test_robustness.py` — 10 nowych (walidacja
  parametrów, liczba kombinacji zgodna ze wzorem dwumianowym, granice
  prawdopodobieństwa, oba sanity-checki jako asercje, dokładna zgodność
  szybkiej ścieżki z metodą "wprost" dla domyślnej metryki, niestandardowa
  `metric_fn`).
- `docs/RESEARCH_METHODOLOGY.md` zaktualizowany w trzech miejscach —
  PBO nie jest już "na roadmapie", tylko zaimplementowane; jawnie
  odnotowane, że NIE jest jeszcze podłączone do
  `scripts/compare_strategies.py` (per-run zwroty strategii nie są tam
  naturalnie ułożone jako wyrównana macierz T×N bez dodatkowej pracy) —
  dostępne na razie jako funkcja biblioteki.
- Walidacja: ruff/mypy clean, pytest **369/369** (359 + 10 nowych),
  detect-secrets clean.

---

## DONE (Faza 15)

- `src/execution/live_preflight.py` — `run_preflight()`: cztery
  automatyczne sprawdzenia, każde niezależne, wszystkie raportowane (nie
  tylko pierwszy błąd):
  1. **`check_trading_mode`** — `TRADING_MODE=LIVE` I
     `CONFIRM_LIVE_TRADING` ustawione (przez `resolve_trading_mode` z
     Fazy 10).
  2. **`check_api_credentials`** — `BYBIT_API_KEY`/`BYBIT_API_SECRET`
     niepuste.
  3. **`check_risk_config`** — parametry ryzyka mieszczą się w
     konserwatywnych granicach (`LiveRiskBounds`). Realny przypadek, który
     to łapie: domyślne wartości `BenchmarkStrategyConfig` z Fazy 9
     (`risk_per_trade=0.1`, `max_leverage=10.0`) — sensowne do backtestu w
     piaskownicy, nierozsądne dla prawdziwego kapitału. Test
     `test_fails_for_backtest_default_style_config` odtwarza dokładnie te
     wartości.
  4. **`check_experiment_history`** — co najmniej jeden zarejestrowany
     eksperyment istnieje (dowód testowania, nie dowód dobrej strategii).
- `scripts/live_preflight_check.py` — CLI: uruchamia wszystkie sprawdzenia,
  wypisuje wynik per punkt, kod wyjścia 1 przy jakimkolwiek niepowodzeniu.
  **Zweryfikowane realnie oboma ścieżkami**: bez zmiennych środowiskowych
  → 3 błędy, kod wyjścia 1; z poprawnymi zmiennymi i konserwatywnym
  ryzykiem → wszystko OK, kod wyjścia 0.
- `docs/LIVE_READINESS_CHECKLIST.md` — checklista operacyjna: co
  faktycznie istnieje w repo (i czego nie ma — brak ścieżki LIVE), dwie
  niezależne bramki, oraz lista manualnych punktów niesprawdzalnych w
  kodzie (walidacja strategii out-of-sample, realny paper trading przez
  sensowny okres, zweryfikowana łączność z testnet, decyzja o alokacji
  kapitału, procedura kill-switch, monitoring/alerting, plan reagowania na
  incydenty, plan rollbacku, klucze mainnet ≠ klucze testnet).
- Testy: `tests/unit/test_live_preflight.py` (16 — każde sprawdzenie
  osobno plus `run_preflight()` łącznie, w tym granica "dokładnie na
  limicie przechodzi").

---

## TESTY / WALIDACJA (Faza 15)

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (74 pliki źródłowe).
- `python3 -m pytest -q` — **359/359 testów przechodzi** (343 z Faz 1-14 +
  16 nowych).
- `detect-secrets scan` — brak nowych sekretów.
- **Realne uruchomienie CLI** (nie tylko testy jednostkowe): `scripts/
  live_preflight_check.py` bez zmiennych środowiskowych → 3/4 sprawdzeń
  nieudanych, kod wyjścia 1; z `TRADING_MODE=LIVE`,
  `CONFIRM_LIVE_TRADING`, kluczami API i jednym zarejestrowanym
  eksperymentem → wszystkie 4 sprawdzenia przechodzą, kod wyjścia 0.

---

## KNOWN ISSUES

- **Brak ścieżki wykonania LIVE — to celowe, nie luka do domknięcia w
  następnej fazie bez wyraźnej decyzji.** Ta bramka gotowości nie ma
  jeszcze niczego do bramkowania: `build_paper_trading_node` odrzuca
  wszystko poza `TradingMode.PAPER`. Zbudowanie realnej ścieżki LIVE
  (klient wykonawczy Bybit mainnet) to osobna decyzja z realnym ryzykiem
  finansowym — nie zostanie podjęta bez wyraźnego polecenia.
- `check_api_credentials` sprawdza tylko obecność kluczy, nie czy są to
  faktycznie klucze mainnet (w odróżnieniu od testnet) — nie ma
  niezawodnego sposobu odróżnienia ich programowo; to pozycja manualnej
  checklisty (`docs/LIVE_READINESS_CHECKLIST.md`).
- `check_experiment_history` sprawdza istnienie wpisów w
  `experiments.jsonl` (Faza 4, tylko BACKTEST), nie istnienie
  wystarczającej historii PAPER-tradingu (Faza 14) — `ExperimentStore`
  obecnie nie rejestruje sesji paper tradingowych jako osobnych wpisów;
  naturalne rozszerzenie, gdyby zaszła taka potrzeba.

---

## NEXT

Wszystkie zaplanowane fazy (0–15) z oryginalnego briefu są ukończone w
zakresie badawczo-infrastrukturalnym. Realna praca do wykonania POZA tą
sesją: (1) walidacja łączności sieciowej z Bybit testnet na maszynie bez
blokady, (2) faktyczne, wielodniowe uruchomienie `run_paper_session.py`
i przegląd `FillTracker`, (3) przejście checklisty manualnej z
`docs/LIVE_READINESS_CHECKLIST.md` przez człowieka. Dalsze kroki w tym
repozytorium — do rozpoczęcia dopiero po wyraźnym poleceniu — to najpewniej
iteracja badawcza (więcej rodzin strategii, ocena ML na realnych danych,
rozszerzenie porównania modeli o regresję) niż nowa "faza" w sensie
oryginalnej numeracji.

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę?
   Częściowo zaadresowane w Fazie 7 — natywna pętla przez `BacktestEngine`
   wystarczająco szybka jak dotąd.
2. Model przybliżenia funding rate — zaadresowane częściowo w Fazie 3.
3. Kiedy potrzebne będą dane tick-level/order-book? Faza 10 dodała
   konkretny powód (spread przy wykonaniu); Fazy 11-15 nie dodały nowych.
4. Mechanizm eksperyment-trackingu — zaadresowane w Fazie 4.
5. Czy prosty model liniowy (logistic regression) systematycznie pokonuje
   modele drzewiaste na tego typu cechach, czy to artefakt syntetycznych
   danych z Fazy 12? Wymaga potwierdzenia na realnych danych.
6. Czy filtr ML rzeczywiście poprawia wyniki strategii bazowej na realnych
   danych, czy różnica z Fazy 13 (30 vs 70 transakcji, lepszy Sharpe) jest
   artefaktem syntetycznych danych? Wymaga potwierdzenia poza tą sesją.
7. Ile realnie trwa bezpieczny `max_gap_seconds` dla `HeartbeatMonitor` na
   danym timeframe? Patrz Faza 14.

---

## Decyzje projektowe podjęte w Fazie 15

- **Najważniejsza decyzja tej fazy**: NIE budować ścieżki wykonania LIVE
  razem z jej własną bramką bezpieczeństwa. Zbudowanie działającego
  klienta live w tym samym oddechu co bramka, która ma go bramkować,
  unieważniłoby sens posiadania bramki. To osobna, przyszła decyzja.
- Bramka gotowości (`live_preflight.py`) zaprojektowana jako NIEZALEŻNA od
  bramki `CONFIRM_LIVE_TRADING` z Fazy 10 (dwie osobne warstwy), zamiast
  rozszerzać `resolve_trading_mode()` — różne odpowiedzialności: "czy
  operator świadomie poprosił o LIVE" vs "czy konfiguracja jest
  bezpieczna, nawet jeśli poprosił".
- `LiveRiskBounds` jako osobny, konserwatywny zestaw granic, nie reużycie
  domyślnych wartości `RiskConfig` — nawet domyślne `RiskConfig` (już
  konserwatywne) powinny być jawnie sprawdzane przeciw jawnej, czytelnej
  liście granic dla LIVE, a nie „ufane” tylko dlatego, że to wartości
  domyślne klasy.
- `run_preflight()` zwraca wszystkie niepowodzenia naraz (nie
  fail-fast na pierwszym) — operator poprawiający konfigurację przed LIVE
  chce zobaczyć całą listę problemów za jednym uruchomieniem, nie naprawiać
  jeden po drugim przez wielokrotne odpalanie skryptu.
- Manualna checklista (`docs/LIVE_READINESS_CHECKLIST.md`) jawnie
  oddzielona od automatycznej bramki — rzeczy takie jak "czy zdefiniowano
  procedurę kill-switch" nie da się sprawdzić w kodzie, i udawanie że się
  da (np. fikcyjny automatyczny check, który zawsze przechodzi) byłoby
  gorsze niż jawne pozostawienie tego jako punktu do ręcznego podpisania.

---

## Faza 14 — Long-running paper trading (zakończona)

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

Walidacja: ruff/mypy clean, pytest 343/343 (317 + 26 nowych). Znany limit:
`HeartbeatMonitor` zbudowany, ale niepodłączony; cała kompozycja
retry/checkpoint/recording wokół żywego `TradingNode.run()` zweryfikowana
tylko strukturalnie, nie end-to-end na prawdziwej sieci.

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
