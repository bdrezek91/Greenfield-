# Greenfield V2 — punkt przekazania do Claude Code

Status dokumentu: **CURRENT STATE / handoff**

Data audytu: **2026-08-23**

Branch przekazania: **`codex/kontynuacja-claude-code`**

Commit bazowy przed tym dokumentem: **`c1269b9`**

Nadrzędne źródło prawdy: **`docs/GREENFIELD_V2_MASTER_PLAN.md`**

Ten dokument nie zastępuje master planu. Jest krótkim, weryfikowalnym punktem
startowym dla kolejnego agenta. Wszystkie dalsze zmiany muszą zachować zasadę
**edge po kosztach, nie maksymalny backtest** oraz domyślną decyzję **WAIT**.

## 1. Stan ogólny

Szacunkowe wykonanie pełnego zakresu docelowego: **około 72%**. Jest to ocena
ważona zakresem, a nie zaliczenie faz. Fazy mają twarde kryteria wyjścia i wiele
z nich pozostaje formalnie niezamkniętych mimo istniejącego kodu.

Aktualny branch zawiera:

- deterministyczny Bronze/Silver/Gold fundament i point-in-time lineage;
- kontrakty oraz normalizację Bybit, Binance, OKX, Coinbase i Deribit;
- ATAS-like order flow, footprint, imbalance, absorption, exhaustion, sweep,
  Volume Profile, POC, VAH/VAL, VWAP i AVWAP;
- niezależną, oryginalną rodzinę Market-Cipher-like: momentum, money flow,
  Wilder RSI oraz potwierdzone dywergencje, bez kodu własnościowego;
- derivatives, options i cross-market context;
- causal regime detector i historical analog engine;
- Setup, Directional, Meta oraz Neutral/Arbitrage Engine;
- wspólny Portfolio Risk Engine z limitami ekspozycji, drawdown guard i kill
  switchem oraz atomowym, checksummed stanem;
- realistyczny PAPER fill model oraz kalibrację z causal L2;
- no-order SHADOW runtime, trwały audit chain i trwałą kolejkę event loop.

Nie istnieje żadna zgoda na realny LIVE ani użycie kapitału.

## 2. Porównanie z pierwotnym planem

| Faza | Stan | Dowód wykonania | Co pozostało do formalnego zamknięcia |
| --- | --- | --- | --- |
| Phase 0 — reprodukowalny rdzeń | **w większości wykonana** | lockfile, Docker/CI, testy, master plan, polityka branchy | potwierdzić branch protection i finalny clean-checkout CI |
| Phase 1 — Bybit raw 24/7 | **kod wykonany, odbiór trwa** | raw envelope, trades/L2/liquidations/ticker, replay, manifests, supervisor, monitoring, BTC/ETH/SOL na VPS | pełne 7 dni nieprzerwanego soaku, wszystkie recovery drills i finalny acceptance bundle |
| Phase 2 — normalized lake / feature store | **w dużej części wykonana** | Silver v2, immutable Parquet, catalog, quality, quarantine, Gold contracts | migracje schematu, cykliczne joby VPS i udokumentowany restore |
| Phase 3 — multi-exchange | **częściowa** | adaptery, normalizery i replay gates Binance/OKX/Coinbase/Deribit | produkcyjne WebSocket/REST transports 24/7, nadzór i ciągły dataset BTC/ETH/SOL |
| Phase 4 — ATAS-like / auction | **rdzeń wykonany** | CVD/delta, footprint, imbalance, sweep, absorption/exhaustion, VP/POC/VAH/VAL, VWAP/AVWAP | dłuższy dataset, pomiary dystrybucji i bogatsze statystyki cancellation/replenishment |
| Phase 5 — derivatives/options/cross-market | **rdzeń offline wykonany** | OI/funding/basis/liquidations/crowding, IV/skew/term structure, relative strength | live Deribit surface, multi-venue basis oraz później CME/ETF/macro/on-chain |
| Phase 6 — regime/analogs | **silniki wykonane, walidacja częściowa** | causal multi-domain regimes i embargoed nearest-neighbor analogs | walk-forward reports, stabilność reżimów i kalibracja niepewności |
| Phase 7 — Setup/Meta/Directional | **rdzeń wykonany** | LONG/SHORT/WAIT/ARBITRAGE, niezależne family votes, portfolio-aware Meta | pełne real-time wiring z usługami danych i długookresowa walidacja decyzji |
| Phase 8 — Neutral/Arbitrage | **research gate wykonany** | all-in adverse costs, leg/outage/borrow/transfer/liquidation gates | paper multi-leg coordinator i trwała rekonsyliacja obu nóg |
| Phase 9 — SHADOW/PAPER | **częściowa** | realistic fills, L2 calibration, no-order runtime, audit, durable event loop, immutable checksummed ShadowWork store/loader, production SHADOW service process (isolated, disabled-by-default), durable PAPER order/fill/position reconciliation engine, champion/challenger degradation monitor + dashboard + Alertmanager rules | wiring the PAPER engine to the live TradingNode/SessionRecorder path, operational research-baseline source, scheduled degradation evaluation loop, observation period, real MetaDecision producer wiring |
| Phase 10 — LIVE_SMALL | **nie rozpoczęta celowo** | brak ścieżki LIVE w SHADOW | wyłącznie po osobnej zgodzie użytkownika i po przejściu wszystkich wcześniejszych gates |
| Phase 11 — advanced context/AI | **nie rozpoczęta jako v2 production scope** | istnieją wcześniejsze moduły ML, ale nie są dowodem edge | dopiero po stabilnym baseline: macro/on-chain/ETF/CME, OOS incremental value, drift/rollback |

## 3. Ostatnia zweryfikowana sytuacja VPS

Aktywny Phase 1 collector jest przypięty do commitu
`53ed12e8140d5626212645a4133286a07a8d253e`. Ostatni odczyt wykazał:

- BTC/ETH/SOL: healthy;
- łącznie `6,070,905` zapisanych raw events;
- `87,028` części danych;
- zero zgłoszonych drops, reconnects, sequence uncertainty i errors;
- około `90.9 GiB` wolnego miejsca na wolumenie danych.

To jest ostatni zapisany pomiar, a nie deklaracja bieżącego stanu. Przed każdym
wnioskiem o zaliczeniu Phase 1 trzeba wykonać nowy read-only audit. Nie wdrażać
Phase 2 na aktywny soak i nie restartować usług bez jawnej potrzeby operacyjnej.
Multiplekser i Kalkulator są poza zakresem Greenfield i mają pozostać
nietknięte.

## 4. Ostatni ukończony cykl

Cykl 1 (bez nowego commitu w chwili pisania tej sekcji) dodał produkcyjny
immutable, checksummed `ShadowWork` store i bezpieczny loader
(`src/execution/shadow_store.py`):

- dozwolony, jednoznaczny schemat URI `shadow-work:<observation_id>` — brak
  `/`/`\\` w dozwolonym alfabecie identyfikatora czyni path traversal
  strukturalnie niemożliwym; każdy inny schemat (`file://`, ...) jest
  odrzucany;
- odczyt otwiera plik z `O_NOFOLLOW` (odmowa podążania za symlinkiem), zapis
  jest atomowy (`O_CREAT|O_EXCL` na tymczasowym pliku, `fsync`, `os.replace`,
  `fsync` katalogu), a po zapisie plik staje się read-only (`0o440`);
- SHA-256 checksum liczony nad kanonicznym JSON payloadu, `schema_version`
  jako obowiązkowa bramka, `written_at_utc` musi być timezone-aware i nie z
  przyszłości (fail-closed, tolerancja zegara konfigurowalna);
- zapis jest idempotentny po `observation_id`: identyczny payload zwraca ten
  sam URI bez zapisu, różny payload dla tego samego id jest odrzucany
  (immutable);
- generyczny, refleksyjny (de)serializator dataclass obsługuje cały graf
  `MetaDecision`/`SetupDecision`/`PortfolioEntryProposal` (w tym zagnieżdżone
  enumy, tuple, `Optional`) bez ręcznego mapowania pól — odrzuca nieznane
  lub brakujące pola, złe typy enumów i niepoprawny JSON;
- `enqueue_shadow_work()` łączy zapis payloadu i idempotentny `enqueue()` do
  istniejącej `DurableShadowQueue` w jedno bezpieczne do powtórzenia wywołanie;
  `ShadowWorkStore.load` pasuje bezpośrednio jako `work_loader` dla
  `ShadowEventLoop`;
- testy: restart (reopen store), duplikaty, integralność (uszkodzony
  checksum, zła wersja schematu, niezgodność observation_id), symlink escape
  na katalogu bazowym i na payloadzie, przyszły timestamp, malformed payload
  shape.

Walidacja tego punktu: Ruff pass, Mypy pass dla 161 plików źródłowych oraz
`1003 passed` w Pytest (988 + 15 nowych testów `test_shadow_store.py` minus
istniejące; patrz commit). Poprzedni cykl (`c1269b9`) dodał trwałą pętlę
SHADOW: SQLite WAL z `synchronous=FULL`, idempotent enqueue, leases i
odzyskiwanie pracy po restarcie, bounded exponential retry i dead-letter
queue, atomowy health JSON oraz metryki Prometheus, idempotent recovery gdy
audit został zapisany przed ACK kolejki, trwały portfolio safety hold po
serii błędów. Draft PR rozwojowy: GitHub PR #5.

## 4b. Cykl 2 — produkcyjny proces usługi SHADOW

Dodano `src/execution/shadow_service.py`, `src/execution/shadow_preflight.py`
i `scripts/run_shadow_service.py`:

- named preflight gate (`run_shadow_preflight`): `TRADING_MODE=SHADOW`,
  wymagane katalogi (tworzone idempotentnie), oraz zgodność
  dataset/code/config fingerprint z istniejącym audytem — odrzuca start
  *przed* wejściem w `ShadowRuntime.resume()`, z czytelnym powodem per-check
  zamiast głębokiego `ShadowAuditError`;
- prawdziwy SIGTERM/SIGINT przez istniejący `GracefulShutdown`
  (`src/research/locking.py`) — brak duplikacji logiki sygnałów;
- automatyczny wybór `resume()` vs `initialize_new()` na podstawie
  persystowanego stanu ryzyka;
- trzy jednoznaczne kody wyjścia: `0` (czyste zamknięcie), `2` (preflight
  failed), `3` (fatal loop error — safety hold nie mógł zostać zapisany);
- brak importu adaptera wykonawczego w całym grafie zależności procesu;
- izolowany, domyślnie wyłączony deployment: wpis `shadow-service` w
  `docker-compose.yml` za `profiles: ["shadow"]` — nie startuje przy zwykłym
  `docker compose up`, nie dzieli wolumenu/kontenera/restart boundary z
  aktywnym soakiem Bybit. Zweryfikowano `docker compose config --services`
  (bez profilu) i `--profile shadow config --services` (z profilem).

Walidacja: Ruff pass, Mypy pass dla 163 plików źródłowych, `1018 passed` w
Pytest, `docker compose config --quiet` czyste, secrets scan czysty.

## 4c. Cykl 3 — trwała rekonsyliacja PAPER

Dodano `src/execution/paper_reconciliation.py` (`PaperOrderStore`):

- SQLite WAL, `synchronous=FULL`; maszyna stanów
  `PENDING_SUBMIT → SUBMITTED → PARTIALLY_FILLED/FILLED` lub `→ REJECTED`,
  nielegalne przejścia odrzucane (`PaperReconciliationError`);
- idempotentny `client_order_id` (deterministyczny UUID5 z klucza
  idempotencji) generowany *przed* pierwszym submitem — retry po restarcie
  mapuje się na ten sam order zamiast ryzykować duplikat;
- `mark_submitted` zapisuje intencję przed właściwym wywołaniem adaptera
  (write-ahead); każdy order nadal `SUBMITTED` po restarcie jest z definicji
  ambiguous — `reconcile_ambiguous_order(s)` rozstrzyga go wyłącznie przez
  wstrzykniętą funkcję zapytania, nigdy przez zgadywanie (nieznany wynik
  zostaje `SUBMITTED` do kolejnego przebiegu, fail-closed);
- partial fills kumulują się do średniej ważonej ceny oraz pełnej dekompozycji
  spread/slippage/fee/funding; overfill jest odrzucany jako nielegalny;
- pozycja (`paper_positions`) aktualizowana transakcyjnie przy każdym
  zaaplikowanym fillu: open/add/partial-close (z realized PnL)/full-close/
  flip — wszystko pokryte testami z dokładnymi wartościami liczbowymi;
- multi-leg przez wspólny `leg_group_id`; `leg_group_status` zwraca
  `ORPHANED` gdy część nóg ma ekspozycję (fill/partial fill) a inne są
  odrzucone/nierozstrzygnięte — zamiast zostawiać ten stan niejawnym.

Walidacja: Ruff pass, Mypy pass dla 164 plików źródłowych, `1030 passed` w
Pytest (12 nowych testów, w tym failure-injection: restart w środku
sekwencji partial fill, ambiguous order po restarcie), secrets scan czysty.

**Nie zrobione w tym cyklu:** wpięcie do żywej ścieżki `TradingNode`/
`SessionRecorder` (`src/execution/session_recorder.py` nadal jest prostym,
nietrwałym mostkiem bez idempotentnych client order id i bez akumulacji
partial fills) — to osobna praca integracyjna, nieoznaczona tu jako gotowa.

## 4d. Cykl 4 — monitoring i degradacja (champion/challenger)

Dodano `src/research/degradation.py`:

- `evaluate_degradation()` porównuje żywe zachowanie SHADOW/PAPER
  promowanego kandydata z tymi samymi prerejestrowanymi tolerancjami, na
  których `PromotionRegistry.promote_to_champion` już bramkuje przy
  promocji (`PaperPromotionConfig.max_signal_frequency_deviation_pct`/
  `max_fill_slippage_bps`/`min_fill_rate_pct`,
  `RetirementConfig.max_paper_drawdown_pct`) — żadnych nowych progów;
- 5 wymiarów co ewaluację: data drift (fingerprint + świeżość), signal
  drift (odchylenie częstości), execution drift (fill rate, slippage),
  drawdown; brakująca/nieświeża ewidencja = DEGRADED, nigdy pominięta
  (fail-closed);
- `apply_degradation_verdict()` to "automatyczne przejście do WAIT": przy
  DEGRADED aktywuje istniejący `ShadowRuntime.activate_safety_hold`
  (idempotentnie per ewaluacja — wymusza `RISK_REJECTED` na każdej kolejnej
  decyzji Meta, więc nie ma osobnego stanu WAIT do ustawienia) i zasila
  istniejący `PromotionRegistry.mark_degraded`/auto-retire-po-N — bez
  duplikowania tej logiki. Nic w tym module nie może promować kandydata;
- `DegradationDashboardPublisher` — ten sam wzorzec co
  `ShadowHealthPublisher` (atomic JSON + `.prom`), więc trafia do
  istniejącego stosu Grafana/Prometheus bez nowej infrastruktury;
- 2 nowe reguły Alertmanager w `monitoring/prometheus/alerts.yml`
  (`GreenfieldCandidateDegraded`, `GreenfieldCandidateDashboardStale`),
  zweryfikowane `promtool check rules` w jednorazowym, izolowanym
  kontenerze (nie dotknięto działającego stosu monitoringu) — 19 reguł
  łącznie (17 istniejących + 2 nowe).

Walidacja: Ruff pass, Mypy pass dla 165 plików źródłowych, `1047 passed` w
Pytest (17 nowych testów), `promtool check rules` OK, secrets scan czysty.

**Nie zrobione w tym cyklu:** operacyjne źródło research-baseline (skąd
brać `signal_frequency_per_day`/`expected_fill_rate_pct` dla realnego
kandydata) i zaplanowana pętla wywołująca `evaluate_degradation` cyklicznie
przeciw żywym obserwacjom SHADOW/PAPER — silnik gotowy, integracja
operacyjna pozostaje.

## 4e. Cykl 5 — silniki raw collectorów OKX i Coinbase

Dodano `src/data/okx_raw_collector.py` (`RawOkxCollector`) i
`src/data/coinbase_raw_collector.py` (`RawCoinbaseCollector`) wraz z
testami:

- oba strukturalnie odzwierciedlają sprawdzony w Phase 1
  `src.data.bybit_raw_collector.RawBybitCollector` — ten sam kształt
  queue/writer/health/storage-reserve/signal-handling — ale są w pełni
  niezależnymi modułami z własnym połączeniem, symbolami i plikami health,
  więc awaria collectora jednej giełdy nie może wpłynąć na inną;
- OKX: subskrypcja per-kanał (`{"channel": ..., "instId": ...}`),
  `OkxSequenceGate` samoinicjalizujący się z pierwszego snapshotu strumienia
  (`seqId`/`prevSeqId`), keepalive jako literalna (nie-JSON) ramka
  "ping"/"pong" obsłużona jawnie przed parsowaniem envelope;
- Coinbase: pojedyncza wiadomość subskrypcji na kanał (`level2`,
  `market_trades`, `ticker`), keepalive przez standardowy WebSocket
  ping/pong (`ws.run_forever(ping_interval=...)`); `CoinbaseLevel2SequenceGate`
  celowo NIE jest podpięty — live probing rzeczywistego endpointu
  (2026-08-23) wykazał, że `sequence_num` jest globalny dla całego
  połączenia (obejmuje też automatyczne wiadomości `subscriptions`), a nie
  ciągły per produkt/kanał jak zakładała bramka; podpięcie jej na żywo dawało
  fałszywe `CoinbaseSequenceGap` i wymuszało reconnecty bez realnej utraty
  danych. Raw capture jest tym niedotknięty — każda wiadomość trafia do
  kolejki przed jakąkolwiek bramką. **Korekta (Cykl 6):** ten opis błędnie
  nazywał to źródło „w pełni bezstratnym" mimo braku działającej weryfikacji
  ciągłości sekwencji — zobacz 4f niżej; poprawny opis to „raw best-effort
  capture", nie „lossless";
- przy przeglądzie tego cyklu poprawiono w `okx_raw_collector.py` nieścisły
  docstring, który odwoływał się do nieistniejących jeszcze wpisów
  `raw-okx-*` w `docker-compose.yml`.

Walidacja: Ruff pass, Mypy pass dla 167 plików źródłowych, `1067 passed` w
Pytest (1047 + 20 nowych testów), `git diff --check` czyste, skan sekretów
czysty (bez nowych wyników; jedyny wpis w `.secrets.baseline` to istniejący,
wcześniej zaakceptowany przypadek w `test_live_preflight.py`).

**Nie zrobione w tym cyklu:** oba collectory to wyłącznie silniki — nie są
jeszcze deployowalne. Brakuje: `scripts/collect_raw_okx.py` i
`scripts/collect_raw_coinbase.py` (analogicznych do
`scripts/collect_raw_bybit.py`), izolowanych, domyślnie wyłączonych wpisów
`raw-okx-*`/`raw-coinbase-*` w `docker-compose.yml` (ten sam wzorzec
profile-gated co `shadow-service`) oraz wsparcia w
`src/data/raw_collector_config.py`, które obecnie obsługuje wyłącznie Bybit
(`INITIAL_V2_SYMBOLS` jest sztywno zakodowane dla Bybit). Nie dotknięto
aktywnego Phase 1 Bybit collectora, Multipleksera ani Kalkulatora.

## 4f. Cykl 6 — naprawczy po audycie commitów do `6d5414c`

Kontrolowany cykl naprawczy odpowiadający na 8 konkretnych problemów
znalezionych przy audycie stanu na `6d5414c` (koniec Cyklu 5). Żadna
istniejąca praca nie została cofnięta; aktywny collector Bybit,
Multiplekser i Kalkulator pozostały nietknięte; SHADOW/PAPER/OKX/Coinbase
nie zostały nigdzie wdrożone na VPS; LIVE i kapitał pozostają poza
zakresem.

**1. Idempotencja filli PAPER** (`src/execution/paper_reconciliation.py`,
`src/execution/adapter.py`):

- `Fill` ma teraz opcjonalne pole `fill_id: str = ""` (domyślne puste, więc
  wszystkie pozostałe miejsca konstruujące `Fill` — backtest,
  `SimulatedExecutionAdapter`, `session_recorder.py` — są nietknięte);
  `PaperOrderStore._record_fill` wymaga niepustego `fill_id` dla
  jakiegokolwiek niezaakceptowanego (`rejected=False`) filla, fail-closed
  (`ValueError`) w przeciwnym razie;
- nowa tabela `paper_fills` (`fill_id TEXT PRIMARY KEY`) — zapis filla,
  aktualizacja `paper_orders` i aktualizacja `paper_positions` dzieją się w
  jednej transakcji `BEGIN IMMEDIATE`/`COMMIT`;
- identyczny redelivery tego samego `fill_id` (ten sam `client_order_id`,
  ilość, cena, wszystkie 4 składniki kosztu, `filled_at`) jest rozpoznawany
  jako bezpieczny replay i zwraca bieżący stan bez ponownego zastosowania;
  `fill_id` użyty ponownie z inną zawartością (także pod innym
  `client_order_id`) podnosi `PaperReconciliationError` — nic nie jest
  cicho nadpisywane;
- nowa metoda `PaperOrderStore.list_fills(client_order_id)` do inspekcji/
  audytu zapisanych filli.

**2. Konflikt idempotency_key zlecenia** (`paper_reconciliation.py`):

- `begin_order` przy istniejącym rekordzie porównuje teraz
  `idempotency_key`, `symbol`, `side`, `quantity`, `reference_price` i
  `leg_group_id`; identyczny retry pozostaje idempotentny, każda różnica
  podnosi `PaperReconciliationError` zamiast cicho zwracać stare zlecenie.

**3. Ujednolicenie jednostek procentowych** (`configs/research_protocol.yaml`,
`src/research/config.py`):

- `paper_promotion.max_signal_frequency_deviation_pct`,
  `paper_promotion.min_fill_rate_pct` i `retirement.max_paper_drawdown_pct`
  zmienione z ułamków 0–1 (`0.40`/`0.90`/`0.25`) na skalę 0–100
  (`40.0`/`90.0`/`25.0`) — tę samą, której już używały porównania w
  `src/research/degradation.py`. Poprzednio te trzy progi były efektywnie
  zawsze spełnione (np. `85.0 >= 0.90`), więc odpowiednie degradation
  metrics nigdy realnie nie mogły zadziałać;
- `_validate()` w `config.py` odrzuca teraz wartość spoza `[0, 100]` dla
  tych trzech pól (fail-closed), ale **nie wykonuje żadnej cichej
  konwersji** — nieprawidłowa (np. znów `0.40`) wartość po prostu mieści
  się formalnie w `[0, 100]` i musi zostać naprawiona ręcznie w YAML, tak
  jak zrobiono tutaj;
- `promotion_gate.max_drawdown_pct`/`max_perturbation_degradation_pct`
  celowo NIE zostały tknięte — to osobna, samospójna para porównywana
  bezpośrednio z ułamkowymi metrykami walk-forward w
  `src/research/evaluator.py`; oba miejsca (YAML i `config.py`) mają teraz
  jawny komentarz tłumaczący, dlaczego skale się różnią.

**4. `expected_fill_rate_pct` faktycznie używany** (`degradation.py`):

- nowa metryka `execution_drift_fill_rate_vs_baseline` porównuje
  zaobserwowany fill rate z `ResearchBaseline.expected_fill_rate_pct`,
  niezależnie od istniejącej `execution_drift_fill_rate` (absolutne
  minimum z `PaperPromotionConfig.min_fill_rate_pct`) — `evaluate_degradation`
  zwraca teraz 6 metryk zamiast 5. Żadna nowa tolerancja/próg nie został
  wymyślony w kodzie (zgodnie z filozofią modułu) — porównanie z baseline
  jest zero-tolerancyjne z założenia;
- dwa testy dowodzą, że oba ograniczenia wiążą niezależnie (jedno spełnione,
  drugie złamane, i odwrotnie).

**5. Spójność restartu SHADOW** (`shadow_preflight.py`, `shadow_service.py`):

- nowy check `check_risk_state_and_audit_consistency` (dodany do
  `run_shadow_preflight`, wymaga teraz też `risk_state_path`) wykrywa:
  audit istnieje/risk state nie istnieje, risk state istnieje/audit nie
  istnieje, oba istnieją ale checksum ostatniego rekordu audytu nie zgadza
  się ze stanem na dysku, oraz uszkodzony/zniekształcony plik po obu
  stronach — każdy przypadek to nazwany, udokumentowany `PreflightCheck`,
  nigdy nieobsłużony wyjątek;
- `run_shadow_service` dodatkowo owija właściwe
  `initialize_new`/`resume` w `try/except` (defense-in-depth na wypadek
  zmiany stanu między preflightem a rekonstrukcją runtime) i zwraca nowy,
  udokumentowany kod wyjścia `4` (`SHADOW_EXIT_STATE_RECONCILIATION_FAILED`)
  zamiast pozwolić wyjątkowi wypaść z `main()`.

**6. Izolacja wolumenów Docker Compose** (`docker-compose.yml`):

- `shadow-service` montuje teraz dedykowany, zarządzany przez Dockera
  named volume `shadow-service-data:/app/data` zamiast
  `${DATA_DIR:-./data}:/app/data` — czyli już nie ten sam host path co
  `raw-bybit-*`. Zweryfikowane `docker compose --profile shadow config`:
  źródła mountów `/app/data` dla `shadow-service` i `raw-bybit-btc` są
  teraz różne; profil `shadow` nadal wyłączony domyślnie;
  ścieżki/wolumeny `raw-bybit-*` nietknięte (zweryfikowane testem —
  patrz niżej).

**7. Przenośność `ShadowWorkStore`** (`shadow_store.py`):

- `os.O_NOFOLLOW` zastąpiony przez `getattr(os, "O_NOFOLLOW", 0)` — na
  Ubuntu/Linux to wciąż ta sama flaga (ochrona niezmieniona), na Windows
  (gdzie flaga nie istnieje w ogóle, także w typeshed) `_read_no_symlink`
  używa jawnego best-effort `Path.is_symlink()` przed otwarciem zamiast
  rzucać `AttributeError`;
- fsync katalogu wydzielony do `_fsync_directory`, no-op na Windows
  (`os.name == "nt"`, przez lokalną flagę `_IS_WINDOWS` — nie mutuje
  globalnego `os.name`, bo `pathlib` sam z niego korzysta i mutacja
  globalna psuje nawet wewnętrzne działanie pytest);
  na Ubuntu/VPS zachowanie niezmienione;
- testy tworzące symlinki używają teraz `_symlink_or_skip`, które pomija
  test (`pytest.skip`) zamiast go wywalać, gdy platforma/uprawnienia nie
  pozwalają stworzyć symlinka (Windows bez Developer Mode/uprawnień
  administratora);
- dodane testy jawnie wymuszają ścieżkę „Windows-style" (brak
  `O_NOFOLLOW`, no-op fsync katalogu) na tej samej maszynie Linux przez
  monkeypatch lokalnych flag modułu, więc ta gałąź kodu ma pokrycie testami
  bez potrzeby maszyny Windows.

**8. Uczciwość collectora Coinbase** (`coinbase_raw_collector.py`,
`collector_health.py`):

- opis w module i klasie zmieniony z „fully lossless" na „raw best-effort
  capture, NOT verified-lossless", z wyjaśnieniem różnicy: żadna wiadomość
  faktycznie odebrana nie jest tracona *po odbiorze* (trafia do kolejki
  przed jakąkolwiek bramką), ale bez działającej weryfikacji ciągłości
  sekwencji nie ma sposobu wykryć/udowodnić braku utraty *przed* odbiorem
  (np. zgubiony segment TCP nieodtworzony przed reconnectem);
- `CollectorHealth` ma nowe pole `sequence_continuity_verified: bool`
  (domyślnie `True`, więc Bybit/OKX — które mają działające bramki — są
  nietknięte), widoczne w health JSON i jako
  `greenfield_collector_sequence_continuity_verified` w Prometheus;
  `RawCoinbaseCollector` jawnie ustawia je na `False`;
  connection-global sequence gate (lub osobne połączenie per produkt) NIE
  został zaimplementowany w tym cyklu — pozostaje udokumentowanym
  blockerem, nie ukończoną pracą;
- collector pozostaje niedeployowalny: wciąż brak
  `scripts/collect_raw_coinbase.py`, wpisu w `docker-compose.yml` i
  wsparcia w `raw_collector_config.py` (jak OKX — patrz 4e).

Walidacja: `uv sync --all-extras` czyste, Ruff pass, Mypy pass dla 167
plików źródłowych (bez zmian w liczbie plików — cykl naprawczy nie dodał
nowych modułów), `1099 passed` w Pytest (1067 + 32 nowe/zmodyfikowane
testy), `git diff --check` czyste, skan sekretów czysty (bez nowych
wyników — jedyny wpis w `.secrets.baseline` to istniejący,
wcześniej zaakceptowany przypadek w `test_live_preflight.py`),
`docker compose config --quiet` i `docker compose -f docker-compose.yml
-f docker-compose.monitoring.yml --profile monitoring config --quiet`
(z `GRAFANA_ADMIN_PASSWORD` jak w CI) czyste.

**Nie zrobione w tym cyklu (świadomie odłożone, nie ukończone):**

- prawdziwy connection-global sequence gate dla Coinbase (punkt 8) —
  udokumentowany blocker, collector pozostaje raw best-effort i
  niedeployowalny;
- wpięcie `PaperOrderStore`/`Fill.fill_id` do żywej ścieżki
  `TradingNode`/`SessionRecorder` — silnik idempotentny gotowy, integracja
  z realnym producentem fill_id (np. execution/trade id z giełdy) to
  osobna praca, jak zapisano już w Cyklu 3;
  `src/execution/session_recorder.py` nadal konstruuje `Fill` bez
  `fill_id` (dopuszczalne — trafia do `FillTracker`, nie do
  `PaperOrderStore`), ale wpięcie realnego PAPER wymaga, by producent na
  tej ścieżce zaczął dostarczać `fill_id`;
- scheduled evaluation loop dla `evaluate_degradation` i operacyjne źródło
  `ResearchBaseline` dla realnego kandydata — jak zapisano w Cyklu 4,
  nadal nieukończone;
- pozostałe punkty z Cyklu 5 (`scripts/collect_raw_okx.py`/
  `collect_raw_coinbase.py`, wpisy `docker-compose.yml`, wsparcie w
  `raw_collector_config.py` dla OKX) — nadal nieukończone, poza zakresem
  tego cyklu naprawczego.

## 4g. Cykl 7 — produkcyjne wdrożenie OKX raw collectora (niedeployowane)

Po zielonym CI dla `f921c2c` (wszystkie 8 check-runs: lint-type-test,
docker-build-test, monitoring-config, secret-scan — `success`), zgodnie z
priorytetem "solidny 24/7 raw market collector, nie nowe strategie ani AI",
ten cykl dociąga `RawOkxCollector` (silnik gotowy od Cyklu 5) do tego
samego poziomu deployowalności co Bybit — bez wdrażania czegokolwiek na
VPS.

- `src/data/raw_collector_config.py`: nowy `OkxRawCollectorConfig` +
  `load_okx_raw_collector_config()`, ten sam wzorzec walidacji co Bybit
  (dokładnie 3 zweryfikowane `inst_ids`, dodatnie wartości timing/capacity,
  `reconnect_min_secs <= reconnect_max_secs`). Sekcja `okx:` dodana do
  `configs/raw_collectors.yaml` obok istniejącej `bybit:` — plik ma
  `schema_version: 1` i był od początku zaprojektowany pod wiele sekcji per
  giełda; sekcja `bybit:` jest bit-identyczna z tym, co czytał dotychczasowy
  loader (test to potwierdza);
- `scripts/collect_raw_okx.py`: nowy entrypoint, strukturalnie identyczny z
  `scripts/collect_raw_bybit.py` — ten sam `validate_raw_collector_start`
  (wymaga własnego soak markera autoryzującego `collector_id` OKX; nie
  może wystartować pod istniejącym markerem Bybit nawet przez pomyłkę);
- `scripts/check_raw_collector_health.py` uogólniony o `EXCHANGE`/
  `MARKET_TYPE` (domyślnie `bybit`/`linear` — dokładnie zachowanie sprzed
  tego cyklu, więc healthcheck Bybit nie zmienia się w żaden sposób);
- `docker-compose.yml`: nowy anchor `x-raw-okx-common` i usługi
  `raw-okx-btc/eth/sol`, pod **nowym profilem `["okx"]`, wyłączonym
  domyślnie** (w przeciwieństwie do `raw-bybit-*`, które nie ma profilu i
  jest aktywnym, już zaakceptowanym soakiem). Współdzielą
  `${DATA_DIR:-./data}:/app/data` z `raw-bybit-*` — to zamierzone (to samo
  Bronze jezioro danych dla wielu giełd, inaczej niż wyodrębniony stan
  SHADOW z Cyklu 6) i bezpieczne (nierozłączne podścieżki per
  exchange/collector_id). Blok `raw-bybit-*` pozostaje bit-identyczny —
  `git diff` na `docker-compose.yml` w tym cyklu to wyłącznie dodania,
  zero usunięć/zmian (zweryfikowane), potwierdzone też testem.

Walidacja: Ruff pass, Mypy pass dla 167 plików źródłowych (plus
`scripts/collect_raw_okx.py` i `scripts/check_raw_collector_health.py`
jawnie sprawdzone), `1111 passed` w Pytest (1099 + 12 nowych), `git diff
--check` czyste, skan sekretów czysty (bez nowych wyników), `docker
compose config` czyste w wariantach: bazowym, `+monitoring`, `--profile
okx`, `--profile shadow`.

**Nie zrobione w tym cyklu:** OKX collector nadal NIE jest wdrożony
nigdzie — brak nowego soak markera go autoryzującego (to celowa, osobna
decyzja operacyjna spoza zakresu tego repo-only cyklu); Binance i Deribit
raw collectory jeszcze nie rozpoczęte; Coinbase pozostaje zablokowany na
brakującym connection-global sequence gate (Cykl 6, punkt 8) — jego
wdrożenie wymaga osobnej pracy projektowej, nie zostało dotknięte w tym
cyklu; normalizacja Silver dla OKX (poza zakresem raw/Bronze) pozostaje
przyszłą pracą.

## 4h. Cykl 8 — connection-global sequence gate dla Coinbase

Po zielonym CI dla `175bb13` (wszystkie 8 check-runs `success`), zamyka
blocker udokumentowany w Cyklu 6 (punkt 8): Coinbase nie miał żadnego
działającego wykrywania sequence gap. Zaprojektowano i wdrożono właściwy
gate, bez wdrażania czegokolwiek na VPS.

**Projekt** (`src/data/coinbase_adapter.py`,
`CoinbaseConnectionSequenceGate`):

- śledzi dokładnie **jeden** licznik `sequence_num` **per połączenie**,
  współdzielony przez wszystkie kanały i produkty — zgodnie ze
  zweryfikowanym na żywo zachowaniem Coinbase (Cykl 5/6: `sequence_num`
  jest globalny dla całego połączenia, łącznie z automatycznym
  komunikatem `subscriptions`), a nie osobny per produkt/kanał, jak
  zakładał stary `CoinbaseLevel2SequenceGate` (pozostawiony, nieużywany —
  jego założenie jest błędne dla tego protokołu);
- **nie zakłada startu od zera** — `last_sequence` jest `None` do
  pierwszego zaobserwowanego `sequence_num`, ta wartość staje się punktem
  bootstrap, niezależnie jaka jest;
- obserwuje **wyłącznie** komunikaty faktycznie posiadające
  `sequence_num` — `observe()` zwraca `False` (nie podnosi wyjątku) dla
  komunikatu bez tego pola, zamiast traktować brak jako dowód gapu;
- zmiana `connection_id` to legalny reconnect, nie cofnięcie — stan resetuje
  się i bootstrapuje od nowa z pierwszego `sequence_num` nowego połączenia;
- każda inna nieciągłość podnosi odrębny, nazwany wyjątek i resetuje stan
  (fail-closed): `CoinbaseSequenceGap` (skok w przód), `CoinbaseSequenceDuplicate`
  (dokładny powtórz), `CoinbaseSequenceRollback` (cofnięcie niebędące
  duplikatem) — wszystkie dziedziczą po `CoinbaseReplayError`.

**Wpięcie w collector** (`src/data/coinbase_raw_collector.py`):

- `handle_raw_message` wywołuje `self._sequence_gate.observe(event)` **po**
  zakolejkowaniu i zapisaniu zdarzenia do health — surowy zapis pozostaje
  nienaruszony nawet gdy gate wykryje anomalię (dane nie giną, tylko flaga
  niepewności idzie w górę i połączenie jest zamykane wymuszając reconnect
  — dokładnie ten sam wzorzec co `OkxSequenceGate`/Bybit order-book replay);
- `_prepare_connection()` tworzy świeżą instancję gate'a i czyści
  `_sequence_uncertain` przy każdym (re)connect — bez przecieku stanu
  między połączeniami;
- `self.health` teraz konstruowany z `sequence_continuity_verified=True`.

**Testy** (17 nowych w `test_coinbase_adapter.py` +
`test_coinbase_raw_collector.py`, pokrywające dokładnie żądane scenariusze):
poprawna sekwencja przez różne kanały/produkty; start od dowolnego
`sequence_num`; wykrycie gapu (z poprawnym komunikatem
`expected X, observed Y (N missing)`); duplikat; cofnięcie; reconnect z
czystym resetem stanu (niska wartość na nowym połączeniu nie jest cofnięciem);
aktualizacja health JSON i metryk Prometheus po wykryciu anomalii;
zachowanie fail-closed po utracie ciągłości (kolejne komunikaty na tym samym
połączeniu nie są ponownie sprawdzane, ale wciąż trafiają do kolejki) oraz
odzyskanie przez świeżą instancję gate'a po restarcie/reconnect.

Walidacja: Ruff pass, Mypy pass dla 167 plików źródłowych, `1126 passed` w
Pytest (1111 + 15 nowych), `git diff --check` czyste, skan sekretów czysty
(bez nowych wyników), `docker compose config --quiet` czyste (ten cykl nie
dotyka `docker-compose.yml`).

**Uczciwość:** `sequence_continuity_verified` zmienione na `true` **dopiero
po** kompletnej walidacji projektu i testów — zgodnie z instrukcją cyklu.
To NIE jest deklaracja "fully lossless" — oznacza, że działający gate
istnieje i wymusza ciągłość; faktyczna bezstratność danego okna danych
nadal wynika z dowodów operacyjnych (health/audit, `sequence_uncertainty_count
== 0` w oknie obserwacji), dokładnie jak już działa dla Bybit/OKX. Collector
NIE jest wdrożony: nadal brak `scripts/collect_raw_coinbase.py`, wpisu w
`docker-compose.yml` i wsparcia w `raw_collector_config.py` — to świadomie
poza zakresem tego cyklu (cykl dotyczył wyłącznie poprawności sequence
gate).

**Nie zrobione w tym cyklu:** deployment wiring dla Coinbase (script/
compose/config — analogicznie do Cyklu 7 dla OKX); Binance i Deribit raw
collectory nadal nie rozpoczęte; żywy test przeciw prawdziwemu
endpointowi Coinbase (obecna walidacja jest w pełni syntetyczna/jednostkowa,
zgodnie z zasadą braku wdrożeń na VPS w tym cyklu) — realna, wielogodzinna
weryfikacja ciągłości wymaga przyszłego, jawnie autoryzowanego kroku
operacyjnego.

## 4i. Cykl 9 — produkcyjne wdrożenie Coinbase raw collectora (niedeployowane)

Tryb pracy zmieniony na ciągły, autonomiczny (użytkownik: "pracuj teraz od
Cyklu 9 i kontynuuj kolejne cykle bez oczekiwania na moje odpowiedzi").
Po zielonym CI dla `6e5f57f` ten cykl dociąga `RawCoinbaseCollector`
(silnik + working sequence gate gotowe od Cyklu 8) do tego samego poziomu
deployowalności co OKX (Cykl 7) — bez wdrażania czegokolwiek na VPS.

- `src/data/raw_collector_config.py`: nowy `CoinbaseRawCollectorConfig` +
  `load_coinbase_raw_collector_config()` (dodatkowo waliduje
  `ping_timeout_secs < ping_interval_secs`, zgodnie z konstruktorem
  `RawCoinbaseCollector`). Sekcja `coinbase:` dodana do
  `configs/raw_collectors.yaml` obok `bybit:`/`okx:` — sekcje `bybit:`/
  `okx:` bit-identyczne (test to potwierdza);
- `scripts/collect_raw_coinbase.py`: nowy entrypoint, strukturalnie
  identyczny z `scripts/collect_raw_okx.py` — ten sam
  `validate_raw_collector_start` (wymaga własnego soak markera);
- `docker-compose.yml`: nowy anchor `x-raw-coinbase-common` i usługi
  `raw-coinbase-btc/eth/sol` pod profilem `["coinbase"]`, wyłączonym
  domyślnie. `scripts/check_raw_collector_health.py` już generyczny od
  Cyklu 7 (`EXCHANGE=coinbase MARKET_TYPE=spot`) — bez zmian. Bloki
  `raw-bybit-*`/`raw-okx-*` bit-identyczne — `git diff` na
  `docker-compose.yml` to wyłącznie dodania (zweryfikowane).

Walidacja: Ruff pass, Mypy pass dla 167 plików źródłowych + entrypoint,
`1135 passed` w Pytest (1126 + 9 nowych), `git diff --check` czyste, skan
sekretów czysty, `docker compose config` czyste (bazowy i
`--profile coinbase`).

**Nie zrobione w tym cyklu:** OKX i Coinbase nadal NIE wdrożone nigdzie —
brak nowych soak markerów je autoryzujących (celowa, osobna decyzja
operacyjna). Binance i Deribit raw collectory jeszcze nie rozpoczęte —
priorytet następnego cyklu.

## 4j. Cykl 10 — Binance USDT-M Futures raw collector (niedeployowany)

Tryb pracy: ciągła, autonomiczna realizacja całego master planu (użytkownik,
po Cyklu 9: "pracuj teraz od Cyklu 9 i kontynuuj kolejne cykle bez
oczekiwania na moje odpowiedzi" — rozszerzone na pełny plan po zielonym CI
dla `5e09c90`). Priorytet: fundament danych — Binance raw collector
(trades, L2/order book, sequence continuity, funding, liquidations gdzie
protokół na to pozwala), bez wdrażania na VPS.

**Ważna korekta w trakcie tego cyklu:** `src/data/binance_adapter.py` i
`tests/unit/test_binance_adapter.py` już istniały w repo (commit `fd487ca`,
sprzed serii cykli Greenfield) — kontrakt `parse_binance_message`/
`BinanceDepthSequenceGate` z poprawną implementacją oficjalnej procedury
REST-snapshot-bridge (`U/u/pu`, bootstrap ze snapshotu). Pierwsza wersja
tego cyklu omyłkowo *nadpisała* oba pliki przez `Write` bez wcześniejszego
odczytu — naruszenie własnej zasady "sprawdź przed nadpisaniem". Błąd
wykryty natychmiast przez czerwone testy (`test_binance_normalized_event.py`,
`test_normalization_pipeline.py`), oba pliki przywrócone przez
`git checkout -- <path>` przed jakimkolwiek commitem — **żadna praca nie
została utracona**. `RawBinanceCollector` przeprojektowany, by poprawnie
korzystać z istniejącego, bardziej rygorystycznego kontraktu zamiast go
zastępować.

**`src/data/binance_raw_collector.py`** (nowy, silnik):

- struktura jak `RawOkxCollector` (queue/writer/health/storage-reserve/
  signal-handling), niezależne połączenie/symbole/pliki health;
- subskrypcja przez `{"method":"SUBSCRIBE","params":[...],"id":N}` na
  `wss://fstream.binance.com/stream` — zweryfikowane na żywo w tej sesji
  (2026-08-23): kombinowana koperta `{"stream":..,"data":{...}}`, kształt
  `trade` i `depthUpdate` (łącznie z polem `pu`) zgodne z dokumentacją;
  `markPriceUpdate`/`forceOrder` NIE zostały zaobserwowane na żywo mimo
  wielokrotnych prób (subskrypcja potwierdzona ackiem, `trade`/`depthUpdate`
  na tym samym połączeniu płynęły normalnie) — udokumentowane jako
  niezweryfikowane, oparte wyłącznie o publiczną dokumentację, nie
  przedstawione jako sprawdzone;
- ciągłość L2 przez **oficjalną procedurę REST-snapshot-bridge**: po
  `_on_open` (po wysłaniu subskrypcji) collector pobiera
  `GET /fapi/v1/depth?symbol=X&limit=1000` (publiczny, bez kluczy) dla
  każdego symbolu i wywołuje `BinanceDepthSequenceGate.bootstrap()` —
  `WebSocketApp` doręcza `on_message` dopiero po powrocie z `on_open`, więc
  blokujące zapytanie REST nie może wyścigować się z przychodzącymi
  eventami na tym samym połączeniu; zdarzenia sprzed snapshotu są przez
  gate cicho pomijane (`return False`), zgodnie z oficjalną regułą, a nie
  traktowane jako błąd;
- błąd pobrania snapshotu (sieć) NIE jest fatalny dla połączenia — bramka
  dla tego symbolu pozostaje niezainicjalizowana i pierwszy event orderbook
  podniesie `BinanceSnapshotRequired` (fail-closed, wymusi reconnect i
  ponowną próbę snapshotu przy następnym połączeniu);
- keepalive przez standardowy `ws.run_forever(ping_interval=...,
  ping_timeout=...)` (jak Coinbase), nie JSON ping;
- `self.health` z `sequence_continuity_verified=True` — uzasadnione:
  bramka to już istniejący, rygorystyczny kontrakt, nie uproszczona wersja
  własna.

**Deployment wiring** (`scripts/collect_raw_binance.py`,
`src/data/raw_collector_config.py` → `BinanceRawCollectorConfig`,
`configs/raw_collectors.yaml` sekcja `binance:`, `docker-compose.yml` →
`raw-binance-btc/eth/sol` pod nowym, domyślnie wyłączonym profilem
`["binance"]`) — dokładnie ten sam wzorzec co Cykl 7/9. Bloki
`raw-bybit-*`/`raw-okx-*`/`raw-coinbase-*` bit-identyczne (same dodania,
zweryfikowane).

**Znana, uczciwie udokumentowana luka:** `forceOrder` (liquidations) jest
subskrybowany i trafia bezstratnie do Bronze, ale mapowanie kanałów w
istniejącym `binance_adapter.py` nie klasyfikuje jeszcze `forceOrder`
(spada do `"control"`, które `normalize_binance_event` pomija) — dane
likwidacji nie docierają jeszcze do Silver. To realne ograniczenie
zakresu, nie ukończona praca; rozszerzenie adaptera/normalizera o
`forceOrder` to osobne zadanie.

Walidacja: Ruff pass, Mypy pass dla 168 plików źródłowych + entrypoint,
`1161 passed` w Pytest (1135 + 26 nowych, w tym potwierdzenie że
`test_binance_normalized_event.py`/`test_normalization_pipeline.py` nadal
przechodzą po przywróceniu adaptera), `git diff --check` czyste, skan
sekretów czysty, `docker compose config` czyste (bazowy i
`--profile binance`).

**Nie zrobione w tym cyklu:** Binance nie wdrożony nigdzie (brak nowego
soak markera); klasyfikacja `forceOrder` w adapterze/normalizerze (patrz
wyżej); open interest i long/short account ratio dla Binance — to REST-only
(brak WS push), poza zakresem tego kolektora WS, analogicznie do
oddzielnych modułów Bybit (`open_interest_client.py`,
`long_short_ratio_client.py`, `funding_client.py`) — świadomie odłożone
jako osobne zadanie, nie ukończone tutaj. Deribit raw collector — priorytet
następnego cyklu.

## 5. Następna zalecana kolejność prac

1. ~~Dodać immutable, checksummed `ShadowWork` store oraz loader~~ — GOTOWE
   (Cykl 1).
2. ~~Dodać proces usługi SHADOW z kontrolowanym SIGTERM, heartbeat i
   preflightem zgodności dataset/code/config fingerprint~~ — GOTOWE (Cykl 2,
   ale bez wpiętego producenta realnych `MetaDecision` — patrz niżej).
3. ~~Zbudować trwałą rekonsyliację PAPER order/position/fill~~ — GOTOWE
   (Cykl 3, silnik gotowy; wpięcie do żywego `TradingNode` pozostaje).
4. ~~Dodać champion/challenger dashboard oraz automatyczne degradation/
   retirement gates~~ — GOTOWE (Cykl 4, silnik i dashboard gotowe; brakuje
   operacyjnego źródła baseline i scheduled evaluation loop).
5. Uruchomić failure injection i wielodniowy SHADOW/PAPER observation period.
6. Równolegle, ale bez naruszania Bybit soak, dodać osobne produkcyjne
   collectory Binance, OKX, Coinbase i Deribit.
   - **OKX GOTOWE do wdrożenia** (Cykl 5 silnik + Cykl 7 script/config/
     compose wiring — patrz 4g; brakuje tylko operacyjnego kroku: nowy soak
     marker autoryzujący OKX `collector_id`, poza zakresem repo-only cyklu).
   - **Coinbase GOTOWE do wdrożenia** (Cykl 5 silnik, Cykl 8
     connection-global sequence gate, Cykl 9 script/config/compose wiring —
     patrz 4i); brakuje tylko tego samego operacyjnego kroku co OKX (nowy
     soak marker).
   - **Binance GOTOWE do wdrożenia** (kontrakt adaptera sprzed serii
     cykli + Cykl 10 silnik collectora z REST-snapshot-bridge i pełne
     script/config/compose wiring — patrz 4j); brakuje tego samego kroku
     operacyjnego (nowy soak marker) oraz klasyfikacji `forceOrder` w
     adapterze/normalizerze i REST-pollerów OI/long-short (osobne zadania).
   - Deribit raw collector jeszcze nie rozpoczęty — priorytet Cyklu 11.
7. Domknąć walk-forward/OOS/Monte Carlo/bootstrap, multiple-testing controls i
   parameter-stability reports na własnym zgromadzonym datasecie.

## 6. Niezmienne ograniczenia dla kontynuacji

- Nie scalać bezpośrednio do `main`; używać feature branchy i draft PR.
- Po każdym udanym, pełnym cyklu wykonać testy, skan sekretów, commit i push.
- Nie usuwać ani nie nadpisywać historycznych branchy.
- Nie liczyć skorelowanych wskaźników jako niezależnych potwierdzeń.
- Missing, stale, future, conflicting lub low-quality evidence musi prowadzić
  do WAIT albo fail-closed.
- Backtest/PAPER zawsze uwzględnia fees, spread, slippage, latency, partial
  fills i funding przy realnych założeniach.
- Żadnego realnego LIVE, kluczy tradingowych ani kapitału bez nowej, wyraźnej
  autoryzacji użytkownika.
- Przed napisaniem nowego pliku modułu (np. `src/data/<exchange>_adapter.py`)
  ZAWSZE sprawdzić `ls`/`git log -- <path>`, czy plik już istnieje — Cykl 10
  omyłkowo nadpisał istniejący, bardziej rygorystyczny `binance_adapter.py`
  przez `Write` bez wcześniejszego odczytu; błąd wykryty i naprawiony przez
  `git checkout` przed commitem, ale nie powinien się powtórzyć.

## 7. Szybkie odtworzenie i walidacja

Z katalogu repozytorium:

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy src
uv run pytest -q
git diff --check
```

Przed publikacją sprawdzić `git status --short`, stage'ować wyłącznie nazwane
pliki oraz wykonać skan sekretów. Aktualny punkt przekazania ma pozostać
draftem, dopóki twarde kryteria odpowiednich faz nie są spełnione.
