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
| Phase 9 — SHADOW/PAPER | **częściowa** | realistic fills, L2 calibration, no-order runtime, audit, durable event loop, immutable checksummed ShadowWork store/loader, production SHADOW service process (isolated, disabled-by-default), fail-closed MetaDecision-to-ShadowWork producer, durable PAPER order/fill/position reconciliation engine, champion/challenger degradation monitor + dashboard + Alertmanager rules | wiring the PAPER engine to the live TradingNode/SessionRecorder path, operational research-baseline source, scheduled degradation evaluation loop, observation period, live feature/evidence orchestration feeding the producer |
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

## 4k. Cykl 11 — Deribit perpetuals raw collector (niedeployowany)

Po zielonym CI dla `dad9170` (wszystkie 8 check-runs `success`). Tym razem
przed pisaniem czegokolwiek sprawdzono `git log -- src/data/deribit_*` —
lekcja z Cyklu 10 zastosowana od razu: `deribit_adapter.py`/
`deribit_normalized_event.py` już istniały (commit `4595827`),
`deribit_raw_collector.py` i `scripts/collect_raw_deribit.py` — nie.
Kontrakt (`parse_deribit_message`, `DeribitBookSequenceGate`) odczytany w
całości przed napisaniem silnika; zero nadpisań.

**Weryfikacja zakresu instrumentów (na żywo, publiczne REST):**
`GET /public/get_instruments?currency=SOL&kind=future` i `kind=option`
zwróciły **zero** wyników — Deribit nie oferuje żadnych instrumentów SOL
(SOL istnieje tam tylko jako waluta/zabezpieczenie). Zgodnie z instrukcją
"SOL tylko tam, gdzie dane są faktycznie dostępne i sensowne" — SOL
świadomie wykluczony, nie pominięty przez przeoczenie. Zakres tego cyklu:
**wyłącznie BTC-PERPETUAL i ETH-PERPETUAL**. Datowane futures BTC/ETH
(~12 aktywnych kontraktów per waluta, rolujących co kwartał) i opcje
(znacznie większy, częściej zmieniający się łańcuch) wymagają
dynamicznego mechanizmu odkrywania instrumentów (polling
`public/get_instruments` + resubskrypcja) — celowo NIE zaimplementowanego
w tym cyklu; udokumentowane jako osobne zadanie, nie ukończone.
IV/skew/term-structure są pochodną wyłącznie opcji, więc też nie są
jeszcze zbierane — ale `_ticker_records` w istniejącym normalizerze już
przepuszcza KAŻDE pole tickera generycznie, więc gdy lista instrumentów
opcji pojawi się w przyszłości, IV/greeks popłyną do Silver bez zmian w
normalizerze.

**`src/data/deribit_raw_collector.py`** (nowy, silnik):

- struktura jak `RawOkxCollector`; gate self-bootstrapujący się z
  pierwszego `"snapshot"` per instrument na połączeniu (jak OKX
  `seqId`/`prevSeqId`), NIE REST-bridge jak Binance — dokładnie kontrakt
  już istniejącego `DeribitBookSequenceGate` (`change_id`/`prev_change_id`);
- zweryfikowane na żywo (2026-08-23) przeciw `wss://www.deribit.com/ws/api/v2`:
  koperta JSON-RPC `public/subscribe`, kształt `book.*` snapshot/change
  (dokładnie zgodny z założeniami adaptera), `ticker.*`, oraz pełny cykl
  `public/set_heartbeat` → okresowy `{"method":"heartbeat","params":
  {"type":"test_request"}}` → odpowiedź `public/test` (połączenie
  pozostało otwarte przez cały test) — to jest mechanizm keepalive tego
  collectora, nie surowy WS ping/pong ani JSON ping jak inne giełdy;
  `trades.*` zasubskrybowane, ale bez zaobserwowanej wiadomości w oknie
  testowym (brak transakcji na BTC-PERPETUAL w tym momencie, nie problem
  schematu — obsługa trades w adapterze ma już własne, wcześniejsze testy);
- odpowiedź na `test_request` wysyłana DOPIERO po zakolejkowaniu
  wiadomości heartbeat do surowego zapisu (ten sam wzorzec: żadny efekt
  uboczny przed trwałym zapisem);
- `self.health` z `sequence_continuity_verified=True` — uzasadnione
  ponownym użyciem już istniejącego, rygorystycznego kontraktu.

**Deployment wiring** (`scripts/collect_raw_deribit.py`,
`DeribitRawCollectorConfig` w `raw_collector_config.py`, sekcja
`deribit:` w `configs/raw_collectors.yaml`, `raw-deribit-btc/eth` pod
nowym, domyślnie wyłączonym profilem `["deribit"]` w `docker-compose.yml`)
— ten sam wzorzec co Cykle 7/9/10. Bloki pozostałych giełd bit-identyczne
(same dodania, zweryfikowane).

Walidacja: Ruff pass, Mypy pass dla 169 plików źródłowych + entrypoint,
`1184 passed` w Pytest (1161 + 23 nowych), `git diff --check` czyste, skan
sekretów czysty, `docker compose config` czyste (bazowy i
`--profile deribit`).

**Nie zrobione w tym cyklu:** Deribit nie wdrożony nigdzie (brak nowego
soak markera); datowane futures BTC/ETH; opcje (i całe pochodne IV/skew/
term-structure) — wymagają dynamicznego odkrywania instrumentów, osobne
zadanie; SOL — świadomie wykluczony (zweryfikowane: brak instrumentów).
Punkt 4 master planu (doprowadzenie OKX/Coinbase/Binance/Deribit do tego
samego kontraktu jakości co Bybit) pozostaje częściowo otwarty — wszystkie
cztery mają teraz working sequence/change-id continuity i pełne
reconnect/backoff/health/storage-reserve, ale żaden nie przeszedł
wielodniowego soaku (wymaga wdrożenia, poza zakresem bez zgody
użytkownika).

## 4l. Cykl 12 — dataset catalog dla wszystkich giełd (nie tylko Bybit)

Po zielonym CI dla `9ccd1cc`. Priorytet 4 master planu: "doprowadzenie
OKX, Coinbase, Binance i Deribit do tego samego kontraktu jakości danych
co Bybit." Przegląd `src/data/normalization_pipeline.py` pokazał, że
normalizacja multi-exchange (priorytet 5) była już w pełni gotowa —
`normalize_raw_lake()` dysponuje registrem normalizerów dla wszystkich 5
giełd od PRZED serii cykli Greenfield. `src/data/data_quality.py` (raporty
jakości, kwarantanna) jest już exchange-agnostyczny (odkrywa manifesty bez
filtra giełdy). Ale `src/data/dataset_catalog.py`
(`build_dataset_snapshot` — reprodukowalne point-in-time snapshoty Silver)
miał **`exchange="bybit"`, `market_type="linear"` zahardkodowane** w dwóch
miejscach — żadna inna giełda nie miała wsparcia snapshotów, mimo że jej
dane Silver już istniały. Prawdziwa, nieudokumentowana luka w "tym samym
kontrakcie co Bybit", znaleziona przez przegląd kodu, nie przez zgadywanie.

Zmiana: `build_dataset_snapshot()` przyjmuje teraz `exchange: str =
"bybit"` i `market_type: str = "linear"` — domyślne wartości zachowują
dokładnie poprzednie zachowanie dla wszystkich istniejących wywołań
(zweryfikowane: cztery istniejące testy przechodzą bez zmian).
`scripts/snapshot_silver_dataset.py` dostał odpowiadające opcje
`--exchange`/`--market-type`. Nowy test buduje snapshot dla danych OKX
(`exchange="okx", market_type="swap"`) i potwierdza zarówno że działa, jak
i że wywołanie bez tych parametrów nadal oznacza Bybit.

Walidacja: Ruff pass, Mypy pass dla 169 plików źródłowych + skrypt,
`1185 passed` w Pytest (1184 + 1 nowy), `git diff --check` czyste, skan
sekretów czysty, `docker compose config` czyste (ten cykl nie dotyka
Compose).

**Nie zrobione w tym cyklu:** pozostałe pod-elementy priorytetu 6 (data
lake/feature store) nie zostały jeszcze systematycznie zweryfikowane per
giełda poza dataset catalog — konkretnie "wykrywanie luk" jako
ogólnodostępne narzędzie post-hoc (poza sequence gate'ami collectorów,
które wykrywają luki tylko na żywo) oraz "retencja"/"kontrola miejsca na
dysku" jako scentralizowany mechanizm ponad per-collector
`minimum_runtime_free_gib` — kandydaci na kolejny cykl, wymagają dalszego
przeglądu kodu przed implementacją, nie zgadywania.

## 4m. Cykl 13 — raport zajętości dysku Bronze (wyłącznie odczyt)

Po zielonym CI dla `c662a7e`. Priorytet 6 master planu (data lake/feature
store) — konkretnie "kontrola miejsca na dysku". Przegląd kodu pokazał, że
istniejące zabezpieczenie (`minimum_runtime_free_gib` w każdym
collectorze) odpowiada tylko na "czy jest miejsce, żeby TEN collector
działał dalej" — nic nie agregowało zajętości całego jeziora Bronze per
giełda/kanał/data ani nie pokazywało wieku najstarszych partycji.

`src/data/raw_storage_report.py` (nowy): `build_raw_storage_report()`
agreguje wszystkie manifesty raw (`discover_manifests`) po (exchange,
market_type, channel, symbol), licząc part_count, row_count, sumę bajtów
(via `stat()` plików części — bez pełnej weryfikacji checksumów, więc
bezpieczne do uruchomienia na żywo zapisywanym jeziorze) oraz wiek
najstarszej partycji w dniach. `scripts/report_raw_storage.py` zapisuje to
jako JSON (`data/reports/raw_storage.json`, atomowo, nadpisywalny — to
regenerowalny raport, nie niezmienna ewidencja jak manifesty/quality).

**Świadomie NIE zaimplementowano w tym cyklu:** żadnej faktycznej
retencji/archiwizacji/usuwania danych. `src/data/raw_compactor.py` już to
jawnie zastrzegał we własnym docstringu: "archival or retention is a
later, explicit storage-policy action." Zbudowanie mechanizmu USUWANIA
danych wymaga osobnej, przemyślanej polityki zatwierdzonej przez
użytkownika (ile dni, czy wymagany zweryfikowany kompaktowany mirror i
przechodzący raport jakości Silver, itd.) oraz znacznie większej
inżynierii bezpieczeństwa — łączenie tego z narzędziem raportującym
ryzykowałoby dokładnie ten typ pośpiesznej, niedostatecznie zweryfikowanej
zdolności destrukcyjnej, przed którą ostrzegają własne zasady projektu.
Ten cykl daje wyłącznie widoczność (odczyt), nie podejmuje decyzji.

Walidacja: Ruff pass, Mypy pass dla 170 plików źródłowych + skrypt,
`1193 passed` w Pytest (1185 + 8 nowych), `git diff --check` czyste, skan
sekretów czysty, `docker compose config` czyste (ten cykl nie dotyka
Compose).

## 4n. Cykl 14 — Binance `forceOrder` (likwidacje) do Silver

Po zielonym CI dla `6996199`. Zamyka konkretną, jawnie udokumentowaną w
Cyklu 10 lukę: `forceOrder` był subskrybowany i trafiał bezstratnie do
Bronze, ale `src/data/binance_adapter.py`'s `_channel()` nie klasyfikował
go (spadał do `"control"`, pomijane przez normalizację) — dane likwidacji
nie docierały do Silver mimo że collector je zbierał.

- `binance_adapter.py`: `_channel()` mapuje teraz `"forceOrder"` →
  `"liquidations"`; nowy `_symbol()` helper poprawnie wyciąga symbol z
  zagnieżdżonego obiektu `o` (`data.o.s`), bo `forceOrder` — w
  przeciwieństwie do każdego innego typu eventu Binance — nie ma `s` na
  najwyższym poziomie;
- `binance_normalized_event.py`: nowa `_liquidation_records()` — dokładnie
  ten sam kształt rekordu co Bybit (`record_type="liquidation"`, `side`,
  `price`, `size`, `event_ts_ms`), więc istniejący
  `data_quality.py::_record_contract_check` waliduje je bez żadnych zmian;
- docstring `binance_raw_collector.py` zaktualizowany — nie twierdzi już,
  że to luka.

Walidacja: Ruff pass, Mypy pass dla 170 plików źródłowych, `1196 passed`
w Pytest (1193 + 3 nowe — wliczając potwierdzenie, że istniejące testy
depth/trade/ticker/normalization-pipeline przechodzą bez zmian), `git
diff --check` czyste, skan sekretów czysty, `docker compose config`
czyste (ten cykl nie dotyka Compose).

**Nie zrobione w tym cyklu:** pozostałe resztkowe luki z Cyklu 10 (REST
pollery OI/long-short dla Binance) i Cyklu 11 (Deribit datowane futures/
opcje/IV) nadal otwarte; per-giełda odpowiedniki `bybit_replay.py` (pełna
rekonstrukcja order booka z checksumami) dla OKX/Coinbase/Binance/Deribit
nadal nie istnieją.

## 4o. Cykl 15 — scenariusz kosztowy `severe` jako dodatkowy dowód (nie bramka)

Po zielonym CI dla `a86bdac`. Zamyka ostatni realnie otwarty kawałek M4 z
`docs/AUTONOMOUS_RESEARCH_AUDIT.md`. Fork-agent uruchomiony między cyklami
znalazł, że moduł `src/research/orchestrator.py` sam przyznawał w
docstringu i w tekście `summary.md` ("adverse_severe"), że scenariusz
`severe` nigdy nie jest realnie odpalany. Weryfikacja pokazała, że część
M4 była już nieaktualna: `ExecutionAssumptions.fee_multiplier`/
`slippage_multiplier`/`entry_delay_bars` (`src/backtesting/costs.py`) i
`_execution_for_scenario()` już faktycznie zmieniają, co silnik nalicza —
to zostało dopięte w sesji między napisaniem audytu a tym cyklem. Jedyna
realna luka: `protocol.costs.severe` był parsowany z
`configs/research_protocol.yaml`, ale nigdzie nie wywoływany.

- `src/research/evaluator.py`: `CandidateEvidence` zyskała
  `aggregate_return_after_severe_costs: float | None = None` — jedyne
  pole z domyślną wartością w tej klasie (świadomie, bo nigdy nie
  bramkuje decyzji, w przeciwieństwie do reszty pól, które celowo nie
  mają defaultów);
- `src/research/reporting.py`: `TrialReportRow` zyskała to samo pole (bez
  defaultu — renderowane generycznie do CSV przez istniejący mechanizm
  `__dataclass_fields__`, zero dodatkowego kodu renderującego);
- `src/research/orchestrator.py`: w `_run_hypothesis()`, tylko dla
  kandydata który już przeszedł bramkę `adverse` (`status == "PASSED"`),
  odpalany jest drugi `run_walk_forward()` z
  `_funding_for_scenario(protocol.costs.severe)`/
  `_execution_for_scenario(protocol.costs.severe)`. Błąd tego przebiegu
  jest łapany i logowany jako ostrzeżenie ("nie policzono"), nigdy nie
  wywraca triala, który już przeszedł realną bramkę. `evaluate_candidate`
  w dalszym ciągu ocenia wyłącznie `adverse` — to świadoma decyzja
  zakresu z oryginalnej sesji M4, nie luka. Zaktualizowano też tekst
  `adverse_severe` w `_render_notes()` (raport `summary.md`), żeby
  faktycznie opisywał policzone wartości adverse/severe per kandydat,
  zamiast twierdzić że severe nie jest wpięty; oraz docstring modułu.
  Dodatkowo naprawiono czwarte, wcześniej pominięte miejsce konstrukcji
  `TrialReportRow` (early-reject przy wyczerpanym budżecie czasowym cyklu)
  — wykryte przez `mypy`, nie przez przegląd ręczny.
- `docs/AUTONOMOUS_RESEARCH_AUDIT.md`: dopisano do sekcji M4 notatkę
  "Update (Cykl 15...)" potwierdzającą zamknięcie obu pozostałych
  kawałków tego ograniczenia, bez przepisywania historycznego zapisu
  audytu.

Walidacja: Ruff pass, Mypy pass dla 170 plików źródłowych (po naprawie
czwartego miejsca konstrukcji `TrialReportRow`), `1196 passed` w Pytest
(bez zmiany liczby testów — rozszerzono istniejące helpery zamiast dodawać
nowe testy jednostkowe; `tests/integration/test_research_cycle_e2e.py`
osobno zweryfikowany — 4 passed w 9.78s, brak zauważalnego spowolnienia
mimo podwójnego walk-forward dla PASSED trials), `git diff --check` czyste,
skan sekretów czysty (kosmetyczny diff `.secrets.baseline` odrzucony jak
zawsze), `docker compose config` pominięte (ten cykl nie dotyka Compose).

**Nie zrobione w tym cyklu:** Monte Carlo block bootstrap nadal nie jest
uruchamiany w cyklu workera (M5, poza zakresem tego cyklu — patrz punkt 8
niżej); `src/backtesting/engine.py`/`instruments.py` nadal hardkodują
`BYBIT_VENUE` — zbyt duży zakres na jeden cykl, zidentyfikowany przez
fork-agenta jako kandydat #3, odłożony.

## 4p. Cykl 16 — Monte Carlo moving-block bootstrap wpięty do cyklu workera

Po zielonym CI dla `222c44c` (Cykl 15). Zamyka pozostałą część M5 z
`docs/AUTONOMOUS_RESEARCH_AUDIT.md`: `run_monte_carlo` istniał wyłącznie
jako ręczne narzędzie CLI (`scripts/monte_carlo.py`), nigdy nie był
wywoływany w automatycznym cyklu badawczym, a resampling był czysto IID
(bez zachowania autokorelacji między transakcjami), a `risk_of_ruin=0.0`
było raportowane jako dosłowne zero zamiast górnej granicy ufności przy
zero zaobserwowanych zdarzeń.

- `src/analytics/monte_carlo.py`: `run_monte_carlo` zyskała opcjonalny
  `block_size` — circular moving-block bootstrap (losuje ciągłe,
  zawijające się bloki oryginalnej kolejności transakcji zamiast losować
  każdą transakcję niezależnie), w pełni zwektoryzowany. Domyślnie
  (`block_size=None`) zachowanie identyczne jak wcześniej (IID) — zero
  zmian dla istniejących wywołań. Dodano `_wilson_upper_bound()` (Wilson
  score interval) — `MonteCarloResult.summary()` zwraca teraz
  `risk_of_ruin_events` (surowa liczba) i
  `risk_of_ruin_upper_bound_ci95` obok punktowego oszacowania, więc
  `risk_of_ruin=0.0` nie jest już mylące — konsument widzi też górną
  granicę 95% CI (redukuje się do znanej heurystyki "3/n" przy zero
  zdarzeń, ale liczone dokładnym wzorem Wilsona dla dowolnej liczby
  zdarzeń, nie tylko zera).
- `src/research/evaluator.py`: `CandidateEvidence` zyskała
  `monte_carlo_risk_of_ruin`/`monte_carlo_risk_of_ruin_upper_bound_ci95`
  (oba z defaultem `None`, tym samym wzorem co pole `severe` z Cyklu 15 —
  nigdy nie bramkują promocji);
- `src/research/reporting.py`: `TrialReportRow` zyskała te same dwa pola
  (bez defaultu, generyczne renderowanie CSV bez zmian);
- `src/research/orchestrator.py`: w `_run_hypothesis()`, zaraz po
  przebiegu `severe`, tylko dla kandydata `status == "PASSED"`, odpalane
  jest `run_monte_carlo()` z `block_size = max(2, round(sqrt(n_trades)))`
  (udokumentowana heurystyka, nie twierdzenie o optymalności) i
  `n_simulations=10_000` (minimum z `docs/RESEARCH_METHODOLOGY.md`
  sekcja 19). Błąd łapany i logowany jako ostrzeżenie ("nie policzono"),
  nigdy nie wywraca triala. Tekst `bootstrap` w `_render_notes()`
  (`summary.md`) zaktualizowany, by opisywać faktyczne wartości zamiast
  "poza zakresem worker"; docstring modułu zaktualizowany. Naprawiono
  wszystkie cztery miejsca konstrukcji `TrialReportRow` (te same co w
  Cyklu 15, plus jedno dodatkowe w ścieżce budget-exhausted, które
  wcześniej umknęło aż do wykrycia przez `mypy` — powtórzono tę samą
  kontrolę `grep -n "TrialReportRow(" src/research/orchestrator.py` przed
  uznaniem cyklu za kompletny, tym razem znajdując wszystkie cztery od
  razu).

Walidacja: Ruff pass, Mypy pass dla 170 plików źródłowych, `1203 passed`
w Pytest (1196 + 7 nowych testów Monte Carlo — block bootstrap, Wilson
bound, reprodukowalność z seedem, walidacja `block_size`),
`tests/integration/test_research_cycle_e2e.py` osobno zweryfikowany — 4
passed w 9.74s, brak zauważalnego spowolnienia mimo dodatkowych 10 000
symulacji Monte Carlo per PASSED trial (w pełni zwektoryzowane w numpy),
`git diff --check` czyste, skan sekretów czysty (kosmetyczny diff
odrzucony jak zawsze), `docker compose config` pominięte (bez zmian
Compose).

**Nie zrobione w tym cyklu:** `src/backtesting/engine.py`/
`instruments.py` nadal hardkodują `BYBIT_VENUE` w wielu miejscach —
zidentyfikowane przez wcześniejszy fork-agent jako zbyt duży zakres na
jeden cykl, wciąż odłożone; historyczny wpis `risk_of_ruin=0.0` w
`docs/PROJECT_STATUS.md` (linia ~207, z wcześniejszej ręcznej sesji CLI)
świadomie NIE nadpisany — to zapis tego, co faktycznie zostało wtedy
powiedziane/zrobione, a nie aktualny stan silnika; nowe, poprawne
zachowanie dotyczy tylko przyszłych uruchomień.

## 4q. Cykl 17 — Binance REST pollery open interest i long/short ratio (niedeployowane)

Po zielonym CI dla `f508b36` (Cykl 16). Zamyka jedną z ostatnich
resztkowych luk data-foundation zapisanych w punkcie 7 niżej: Bybit ma
REST pollery/backfill dla open interest i long/short ratio
(`src/data/long_short_ratio_collector.py`,
`src/data/ingest_open_interest.py`), Binance miał wyłącznie WS trades/
depth/markPrice/forceOrder (Cykl 10/14) — brak jakiegokolwiek źródła OI/
long-short.

Odkrycie przed implementacją: istniejący `src/data/storage.py`
(`write_open_interest`/`write_long_short_ratio`, katalogi `open_interest/`
`long_short_ratio/`) **nie ma wymiaru giełdy w ogóle** — to starszy,
przed-multi-exchange podsystem. Dodanie Binance przez retrofit tych
funkcji wymagałoby migracji istniejących ścieżek (ryzyko kolizji symboli
identycznych na obu giełdach, np. BTCUSDT) — zbyt inwazyjne i ryzykowne
dla autonomicznego cyklu bez zgody człowieka. Zamiast tego: **nowe,
osobne moduły i osobne katalogi najwyższego poziomu**
(`binance_open_interest/`, `binance_long_short_ratio/`), zero zmian w
`src/data/storage.py` — brak jakiegokolwiek ryzyka dla działającego kodu
Bybit.

Live-zweryfikowane w tej sesji przez realne, publiczne, nieautoryzowane
GET-y do `https://fapi.binance.com`: `GET /futures/data/openInterestHist`
(pola `sumOpenInterest`/`sumOpenInterestValue`/`timestamp`) i
`GET /futures/data/globalLongShortAccountRatio` (pola `longAccount`/
`shortAccount`/`longShortRatio`/`timestamp`) — oba wspierają
`startTime`/`endTime` w oknie ~30 dni, potem tylko żywe zbieranie idzie
naprzód (ta sama sytuacja co Bybit long/short).

- `src/data/schema_binance_derivatives.py`: dwa niezależne schematy —
  Binance raportuje `longAccount`/`shortAccount`/`longShortRatio`
  (liczbowo od kont, nie od wolumenu zleceń jak Bybit `buyRatio`/
  `sellRatio`) — świadomie NIE wymuszone na nazewnictwo Bybit, żeby nie
  zafałszować, co faktycznie zmierzono; OI ma dodatkowo
  `open_interest_value` (notional), którego schemat Bybit nie ma;
- `src/data/binance_derivatives_client.py`: `BinanceOpenInterestClient`/
  `BinanceLongShortRatioClient`, bezzależnościowe (`urllib.request`, ten
  sam wzorzec co `binance_raw_collector.py`'s
  `default_depth_snapshot_fetcher` z Cyklu 10), injectable fetcher dla
  testów;
- `src/data/binance_derivatives_storage.py`: `write_binance_open_interest`/
  `write_binance_long_short_ratio`/czytniki, merge-not-overwrite jak
  `src/data/storage.py`, ale całkowicie osobny plik/katalogi;
- `src/data/binance_derivatives_collector.py`: `BinanceOpenInterestCollector`/
  `BinanceLongShortRatioCollector`, poll-loop z dedup po ostatnim
  zapisanym timestampie, SIGTERM→KeyboardInterrupt (ten sam wzorzec co
  `LongShortRatioCollector`), współdzielą jeden `_run_polling_loop()`
  helper zamiast duplikować pętlę dwa razy;
- `scripts/collect_binance_open_interest.py`/
  `scripts/collect_binance_long_short_ratio.py`: typer CLI, walidacja
  symbolu przeciw `INITIAL_V2_BINANCE_SYMBOLS` (Cykl 10) i okresu przeciw
  `VALID_PERIODS`;
- `docker-compose.yml`: dwa nowe serwisy
  `binance-open-interest-collector`/`binance-long-short-ratio-collector`
  pod nowym, domyślnie wyłączonym profilem `["binance-derivatives"]` —
  ten sam wzorzec co `long-short-ratio-collector` (obraz `ai-trading-lab:dev`,
  nie `greenfield-phase1:collector` — to nie jest część soak-gated
  Bronze WS pipeline, więc nie przechodzi przez
  `validate_raw_collector_start`).

Walidacja: Ruff pass, Mypy pass dla 222 plików źródłowych (`src`+`scripts`),
`1224 passed` w Pytest (1203 + 21 nowych testów: storage roundtrip/merge/
brak-kolizji-z-Bybit, client params/walidacja okresu, collector dedup,
CLI walidacja symbolu/okresu), `git diff --check` czyste, skan sekretów
czysty (kosmetyczny diff odrzucony jak zawsze), `docker compose config
--quiet` czyste (nowe serwisy poprawnie sparsowane pod nowym profilem).

**Nie zrobione w tym cyklu:** brak wdrożenia na VPS (repo-only, jak
wszystkie poprzednie cykle nowych kolektorów — wymaga osobnej zgody);
Deribit datowane futures/opcje/IV nadal otwarte (Cykl 11); per-giełda
odpowiedniki `bybit_replay.py` dla OKX/Coinbase/Binance/Deribit nadal nie
istnieją; `src/backtesting/engine.py`/`instruments.py` nadal hardkodują
`BYBIT_VENUE`.

## 4r. Cykl 18 — OKX REST pollery open interest i long/short ratio (niedeployowane)

Po zielonym CI dla `13dfe00` (Cykl 17). Ta sama luka co Cykl 17, teraz dla
OKX: WS raw collector (Cykl 5/7) zbiera trades/book/ticker, ale nie ma
źródła OI/long-short. Coinbase świadomie POMINIĘTY dla tego wzorca —
`INITIAL_V2_COINBASE_PRODUCT_IDS` to produkty spot (`BTC-USD` itd., Cykl
9), open interest/long-short nie ma sensu dla spot, więc nie ma tu luki
do zamknięcia.

Live-zweryfikowane w tej sesji przez realne, publiczne GET-y do
`https://www.okx.com`: `GET /api/v5/public/open-interest` (pola `oi`/
`oiCcy`/`oiUsd`/`ts`, envelope `{code,data,msg}`, TYLKO bieżący snapshot —
brak parametru okna czasowego, w przeciwieństwie do Binance
`openInterestHist`) i `GET /api/v5/rubik/stat/contracts/long-short-account-ratio-contract`
(zwraca `[timestamp, ratio]` pary — SUROWE dwuelementowe listy, nie
obiekty jak Binance/Bybit; brak osobnego rozbicia long_account/
short_account, więc schemat OKX celowo ma tylko jedno pole
`long_short_ratio`, żeby nie zmyślać danych, których OKX nie podaje).

Refaktor przy okazji: wydzielono `src/data/rest_poller.py`
(`run_polling_loop()`) z `binance_derivatives_collector.py` (Cykl 17), bo
trzeci poller (OKX) duplikowałby tę samą ~15-liniową pętlę SIGTERM→
KeyboardInterrupt po raz trzeci. `BinanceOpenInterestCollector`/
`BinanceLongShortRatioCollector.run_forever()` zaktualizowane, by używać
wspólnej funkcji — zero zmian w zachowaniu, zweryfikowane ponownym
przejściem testów Binance przed kontynuacją. Bybit's
`long_short_ratio_collector.py` świadomie NIE zretrofitowany do
wspólnego helpera — poza zakresem, już działa.

- `src/data/schema_okx_derivatives.py`: OI ma `open_interest`/
  `open_interest_ccy`/`open_interest_usd` (trzy jednostki, bogatszy
  kształt niż Binance); long/short ma tylko `long_short_ratio` (patrz
  wyżej);
- `src/data/okx_derivatives_client.py`: `OkxOpenInterestClient`/
  `OkxLongShortRatioClient`, bezzależnościowe (`urllib.request`),
  odpakowuje envelope `{code,data,msg}`, podnosi `RuntimeError` na
  `code != "0"`;
- `src/data/okx_derivatives_storage.py`: `write_okx_open_interest`
  (bez wymiaru `period` — endpoint snapshot go nie ma) /
  `write_okx_long_short_ratio` (z wymiarem `period`) + czytniki, osobne
  katalogi `okx_open_interest/`/`okx_long_short_ratio/`, zero zmian w
  `storage.py`;
- `src/data/okx_derivatives_collector.py`: `OkxOpenInterestCollector`/
  `OkxLongShortRatioCollector`, ten sam poll-and-dedup-by-timestamp wzorzec,
  używa wspólnego `run_polling_loop()`;
- `scripts/collect_okx_open_interest.py`/
  `scripts/collect_okx_long_short_ratio.py`: typer CLI, `--inst-id` (nie
  `--symbol` — konwencja z `collect_raw_okx.py`), walidacja przeciw
  `INITIAL_V2_OKX_INST_IDS` (Cykl 5/7);
- `docker-compose.yml`: dwa nowe serwisy `okx-open-interest-collector`/
  `okx-long-short-ratio-collector` pod nowym, domyślnie wyłączonym
  profilem `["okx-derivatives"]`.

Walidacja: Ruff pass, Mypy pass dla 229 plików źródłowych (`src`+`scripts`;
złapał i naprawiony błąd typu w `okx_derivatives_client.py` —
`RawFetcher`/zwracany typ był błędnie zadeklarowany jako
`list[dict[str, Any]]`, ale long/short-ratio zwraca `list[list[str]]`,
nie listę obiektów — poprawione na `list[Any]`), `1246 passed` w Pytest
(1224 + 22 nowe testy: storage roundtrip/merge/brak-kolizji, client
params/error-envelope/walidacja okresu, collector dedup w tym test na
"ten sam snapshot powtórzony" specyficzny dla OKX, CLI walidacja, plus 2
nowe testy `rest_poller.py` samego w sobie), `git diff --check` czyste,
skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze), `docker
compose config --quiet` czyste.

**Nie zrobione w tym cyklu:** brak wdrożenia na VPS (repo-only); Deribit
datowane futures/opcje/IV nadal otwarte (Cykl 11); per-giełda
odpowiedniki `bybit_replay.py` nadal nie istnieją; `BYBIT_VENUE`
hardkodowanie w `src/backtesting/` nadal odłożone; Coinbase OI/long-short
świadomie pominięty (produkty spot, nie derywaty — patrz wyżej).

## 4s. Cykl 19 — REST snapshot Binance order booka trwale trafia do Bronze

Po zielonym CI dla `65ea811` (Cykl 18). Zbadano `BYBIT_VENUE` (kandydat
odkładany od kilku cykli) i `bybit_replay.py` (post-hoc order-book replay
dla innych giełd) jako kandydaci na ten cykl — oba okazały się faktycznie
zbyt duże/ryzykowne na jeden cykl z konkretnych, teraz udokumentowanych
powodów (patrz niżej), więc świadomie odłożone ponownie, tym razem z
uzasadnieniem opartym na realnym zbadaniu kodu, nie tylko powtórzeniem
wcześniejszej oceny fork-agenta.

**Zbadane i odłożone:**
- `BYBIT_VENUE` (`src/backtesting/instruments.py`/`engine.py`): faktyczny
  zasięg to tylko 6 odwołań w 3 plikach — mniejszy niż sugerowała nazwa
  "hardcoded throughout". Ale generalizacja jest bezwartościowa bez
  równoległego rozwiązania osobnego problemu: `src/data/storage.py`'s
  `read_klines()`/`write_klines()` (używane przez `build_engine()`) to
  TAKŻE starszy, przed-multi-exchange podsystem bez wymiaru giełdy —
  identyczny problem kolizji symboli jak przy OI/long-short (Cykl 17), ale
  o wyższej stawce (dane cenowe karmiące silnik backtestu, nie tylko
  metadane). Samo sparametryzowanie venue bez źródła klines dla innych
  giełd dałoby fasadową, niedziałającą "obsługę" — dokładnie ten rodzaj
  "half-finished implementation", którego reguły tej sesji zabraniają.
  Realny fix wymaga też decyzji, jak REST-kline-downloader per giełda ma
  współistnieć z Bronze/Silver WS pipeline (agregacja trades→OHLC z
  Silver, czy osobny REST poller jak Cykl 17/18) — osobna, większa praca.
- `bybit_replay.py` dla innych giełd: przeczytano cały plik (359 linii).
  Wzorzec jest przenaszalny, ale dla Binance konkretnie odkryto strukturalną
  lukę: `default_depth_snapshot_fetcher` (Cykl 10) pobierał pełny REST
  snapshot (`lastUpdateId`, `bids`, `asks`) tylko po to, by odrzucić
  wszystko poza `lastUpdateId` — prawdziwe poziomy cen nigdy nie trafiały
  do Bronze. Bez tego żaden post-hoc replay tool nie mógłby zrekonstruować
  faktycznego stanu booka, tylko zweryfikować ciągłość sekwencji `U`/`u`/
  `pu`. To właśnie ta luka została zamknięta w tym cyklu (patrz niżej) —
  sam tool `binance_replay.py` pozostaje do zrobienia w kolejnym cyklu,
  teraz gdy ma na czym faktycznie działać.

**Zrobione:** `src/data/binance_adapter.py` zyskał
`synthesize_binance_depth_snapshot_event()` — pakuje pełną odpowiedź
`GET /fapi/v1/depth` (live-zweryfikowaną ponownie w tej sesji) jako
syntetyczny event Bronze (`channel="orderbook"`, `message_type="snapshot"`,
`update_id=lastUpdateId`), bezstratnie, tym samym wzorcem co
`parse_binance_message` dla realnych wiadomości WS — ale NIE przez
`parse_binance_message` (REST response nie ma pól `e`/`s`, kształt jest
płaski, bez `{"stream":..,"data":{...}}`). `src/data/binance_raw_collector.py`:
`default_depth_snapshot_fetcher` zwraca teraz pełny słownik zamiast samego
`int`; `_bootstrap_depth_gates()` po fetchu snapshotu enqueue'uje
syntetyczny event PRZED bootstrapem bramki (kolejność zachowana — `_on_open`
kończy się przed pierwszym `_on_message`, jak opisano w docstringu modułu).
`src/data/binance_normalized_event.py`: `normalize_binance_event()` pomija
`message_type == "snapshot"` (jak "control") — snapshot nie jest deltą i
wstrzyknięcie go do strumienia `book_level` upsert/delete zniekształciłoby
znaczenie tych rekordów (snapshot to "book JEST tymi poziomami", nie
"dodaj/zaktualizuj te konkretne poziomy"); `skipped_control_count`
uogólniony na "raw event nie wyprodukował żadnego wiersza Silver" zamiast
tylko "channel == control", żeby nie zaniżać liczby po pojawieniu się
snapshotów w strumieniu.

Walidacja: Ruff pass, Mypy pass dla 229 plików źródłowych, `1253 passed`
w Pytest (1246 + 7 nowych testów: synteza eventu/determinizm/odrzucenie
brakującego `lastUpdateId` w adapterze, trwałość snapshotu do Bronze z
realnymi poziomami cen w kolektorze, pominięcie w normalizacji +
poprawne liczenie w raporcie). Naprawiono też 5 istniejących testów
kolektora, których asercje `qsize()` nie uwzględniały nowego
syntetycznego eventu (fake fetcher w testach zwracał wcześniej `int`,
teraz zwraca pełny słownik zgodnie z nowym kontraktem) — wykryte przez
pełne przejście testów przed commitem, nie przeoczone. `git diff --check`
czyste, skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze),
`docker compose config` pominięte (ten cykl nie dotyka Compose).

**Nie zrobione w tym cyklu:** `binance_replay.py` (post-hoc order-book
replay tool) sam w sobie — ten cykl zamknął tylko prerekwizyt (dane teraz
istnieją w Bronze), narzędzie konsumujące je pozostaje do zrobienia;
`BYBIT_VENUE`/multi-exchange backtest engine nadal odłożone (patrz wyżej,
teraz z jaśniejszym uzasadnieniem); Deribit datowane futures/opcje/IV
nadal otwarte.

## 4t. Cykl 20 — `binance_replay.py`: post-hoc order-book replay dla Binance

Po zielonym CI dla `ca3f592` (Cykl 19). Zamyka narzędzie, dla którego Cykl
19 zamknął prerekwizyt. Strukturalnie odzwierciedla `src/data/bybit_replay.py`
(przeczytany w całości w Cyklu 19), ale NIE dzieli z nim kodu (osobny plik,
zero zmian w module Bybit) i różni się w dwóch miejscach:

- ciągłość sekwencji ponownie używa `BinanceDepthSequenceGate`
  (`src/data/binance_adapter.py`) wprost zamiast reimplementować kontrakt
  `U`/`u`/`pu` — to już przetestowane źródło prawdy używane przez żywy
  kolektor. Zdarzenie `message_type == "snapshot"` (Cykl 19) bootstrapuje
  jednocześnie bramkę i realne poziomy cen booka; bez niego replay rzuca
  `BinanceSnapshotRequired` na pierwszej delcie — dokładnie jak żywy
  kolektor, i dokładnie to, co dane sprzed Cyklu 19 nadal będą robić
  (nie da się tego cofnąć, tylko dane zebrane od teraz są odtwarzalne);
- tylko kanał `orderbook` jest rekonstruowany. Kanał `ticker` Binance
  (markPrice/24hrTicker/bookTicker) to seria niezależnych pełnych
  snapshotów bez kontraktu delta/sekwencji — w przeciwieństwie do Bybit
  (snapshot+delta+`cs`), nie ma tam nic do zreplikowania/zweryfikowania,
  więc świadomie poza zakresem (nadal liczony w `channel_counts`);
  zdarzenia stale (na/przed `lastUpdateId` snapshotu) są cicho odrzucane
  zgodnie z udokumentowaną procedurą Binance (nie błąd, w przeciwieństwie
  do modelu Bybit, gdzie każdy nie-rosnący update to twardy błąd).

`src/data/binance_replay.py`: `BinanceOrderBook` (dokładny stan L2 z
Decimal), `BinanceReplaySession` (per-symbol bramka+book, agreguje
`ReplayReport` z `replay_checksum`), `replay_binance`/`replay_binance_stream`.
`scripts/replay_raw_binance.py`: CLI mirror `scripts/replay_raw_bybit.py`
(reużywa generyczny `iter_raw_events(..., exchange="binance", ...)` bez
zmian).

Walidacja: Ruff pass, Mypy pass dla 231 plików źródłowych, `1264 passed`
w Pytest (1253 + 11 nowych testów: snapshot+delta rebuduje dokładny book,
delta przed snapshotem odrzucona, replay bez zdarzenia snapshot rzuca
błąd, gap po bootstrapie rzuca, stale event cicho odrzucony, crossed book
odrzucony, zmiana connection_id wymaga świeżego snapshotu, luka jednego
symbolu nie wpływa na drugi, kanały inne niż orderbook liczone ale nie
wpływają na book, determinizm, sortowanie po receive_ts nie kolejności
wstawienia), `git diff --check` czyste, skan sekretów czysty (kosmetyczny
diff odrzucony jak zawsze), bez zmian Compose.

**Nie zrobione w tym cyklu:** analogiczny replay tool dla OKX/Coinbase/
Deribit nadal nie istnieje (OKX/Deribit mają snapshot-w-strumieniu jak
Bybit, więc powinny być prostsze — Coinbase ma inny model sekwencji,
connection-global, może wymagać więcej pracy); `BYBIT_VENUE`/multi-exchange
backtest engine nadal odłożone; Deribit datowane futures/opcje/IV nadal
otwarte.

## 4u. Cykl 21 — `okx_replay.py`: post-hoc order-book replay dla OKX

Po zielonym CI dla `653555a` (Cykl 20). Jak przewidziano w Cyklu 20 —
OKX self-bootstrapuje się z własnej wiadomości `"snapshot"` w strumieniu
(`action="snapshot"`), więc — w przeciwieństwie do Binance — nie było
żadnego prerekwizytu do zamknięcia: KAŻDY istniejący plik Bronze OKX
(stary i nowy) jest już w pełni odtwarzalny, bez żadnej zmiany w
kolektorze/adapterze.

`src/data/okx_replay.py` strukturalnie odzwierciedla `bybit_replay.py`/
`binance_replay.py`, ponownie używając `OkxSequenceGate`
(`src/data/okx_adapter.py`) wprost dla ciągłości `seqId`/`prevSeqId` —
zero duplikacji logiki sekwencji. Różnice specyficzne dla OKX:
poziomy booka to 4-elementowe listy `[price, size, liquidated_orders,
order_count]` (nie 2-elementowe jak Bybit/Binance) — reużyto tolerancji
`len(level) < 2` już ustalonej w `okx_normalized_event.py`; pola to
`bids`/`asks` (nie `b`/`a`); `OkxSequenceGate.apply()` już klasyfikuje
czyste heartbeaty (ten sam `seqId`, puste `bids`/`asks`) jako no-op
(`return False`) — replay session to respektuje bez dodatkowej logiki.

`scripts/replay_raw_okx.py`: CLI mirror `scripts/replay_raw_bybit.py`/
`replay_raw_binance.py`, reużywa generyczny `iter_raw_events(...,
exchange="okx", market_type="swap", ...)` bez zmian.

Walidacja: Ruff pass, Mypy pass dla 233 plików źródłowych, `1274 passed`
w Pytest (1264 + 10 nowych testów: snapshot+delta rebuduje dokładny book,
delta przed snapshotem odrzucona, gap po bootstrapie rzuca, heartbeat nie
zmienia stanu booka, crossed book odrzucony, zmiana connection_id wymaga
świeżego snapshotu, luka jednego symbolu nie wpływa na drugi, kanały inne
niż orderbook liczone ale nie wpływają na book, determinizm, sortowanie
po receive_ts nie kolejności wstawienia — dokładnie ten sam zestaw co dla
Binance w Cyklu 20, dostosowany do protokołu OKX), `git diff --check`
czyste, skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez
zmian Compose.

**Nie zrobione w tym cyklu:** replay tool dla Coinbase (inny model
sekwencji — connection-global, nie per-symbol jak OKX/Bybit/Binance —
prawdopodobnie wymaga więcej pracy niż OKX) i Deribit (ma
snapshot-w-strumieniu jak OKX, powinien być podobnie prosty, ale nadal
nie zrobiony) nadal nie istnieją; `BYBIT_VENUE`/multi-exchange backtest
engine nadal odłożone; Deribit datowane futures/opcje/IV nadal otwarte.

## 4v. Cykl 22 — `coinbase_replay.py`: post-hoc replay z bramką connection-global

Po zielonym CI dla `9a729d0` (Cykl 21). Jak przewidziano — Coinbase
wymagał więcej pracy niż OKX, bo jego `sequence_num` jest globalny dla
całego połączenia (każdy kanał, każdy produkt, łącznie z automatycznym
`subscriptions` ack), nie per-produkt/per-kanał jak u każdej innej giełdy
w tym repo. `CoinbaseLevel2SequenceGate` (per-produkt) był już wcześniej
(Cykl 8) na żywo zweryfikowany jako BŁĘDNY dla tego protokołu — produkował
fałszywe luki — i żywy kolektor świadomie go nie używa. Replay tool
musiał to samo świadomie uszanować: użycie `CoinbaseLevel2SequenceGate`
tutaj odtworzyłoby dokładnie ten sam błąd w trybie offline.

Projekt `src/data/coinbase_replay.py`: JEDNA instancja
`CoinbaseConnectionSequenceGate` na CAŁĄ sesję replay (nie per-symbol jak
u każdej innej giełdy) — luka na dowolnym kanale/produkcie unieważnia
CAŁĄ sesję (fail-closed, propaguje wyjątek, tak jak inne narzędzia replay
w tym repo), nie tylko book jednego produktu. Rekonstrukcja L2 per-produkt
(`CoinbaseOrderBook`) stosuje snapshot/delta w kolejności odbioru BEZ
własnej kontroli sekwencji — ciągłość w całości deleguje do jedynej,
globalnej bramki. Przy okazji naprawiono nieaktualny akapit w
`src/data/coinbase_raw_collector.py`'s docstring, który twierdził, że nie
ma wdrożenia (`scripts/collect_raw_coinbase.py`, serwisy Compose) — to
zostało dodane w Cyklu 9, ale docstring z Cyklu 8 nigdy nie został
zaktualizowany; poprawiono, żeby odzwierciedlał rzeczywisty stan (repo-only,
za soak-marker gate, jak każdy inny nowy kolektor).

`scripts/replay_raw_coinbase.py`: CLI mirror, ale CELOWO BEZ `--symbol`
filtra (w przeciwieństwie do Bybit/Binance/OKX) — odfiltrowanie jednego
produktu przed replay sprawiłoby, że globalna bramka zobaczy "lukę" tam,
gdzie po prostu odfiltrowano cudze wiadomości, fałszywy alarm zamiast
poprawy bezpieczeństwa. Zawsze replayuje wszystkie produkty z połączenia
razem.

Walidacja: Ruff pass, Mypy pass dla 235 plików źródłowych, `1284 passed`
w Pytest (1274 + 10 nowych testów: snapshot+delta rebuduje dokładny book,
delta przed snapshotem odrzucona, luka na NIEZWIĄZANYM kanale (heartbeat)
unieważnia całą sesję — kluczowy test demonstrujący różnicę od innych
giełd, wiadomości bez `sequence_num` nie psują ciągłości, crossed book
odrzucony, reconnect resetuje bramkę bez wyjątku, dwa produkty dzielą
jedną bramkę połączenia — luka jednego psuje oba, wieloproduktowa
pojedyncza wiadomość odrzucona, determinizm, sortowanie po receive_ts),
`git diff --check` czyste, skan sekretów czysty (kosmetyczny diff
odrzucony jak zawsze), bez zmian Compose.

**Nie zrobione w tym cyklu:** replay tool dla Deribit (ma
snapshot-w-strumieniu jak OKX, powinien być prosty) nadal nie istnieje;
`BYBIT_VENUE`/multi-exchange backtest engine nadal odłożone; Deribit
datowane futures/opcje/IV nadal otwarte.

## 4w. Cykl 23 — `deribit_replay.py`: post-hoc order-book replay dla Deribit

Po zielonym CI dla `06f4a66` (Cykl 22). Domyka priorytet 3 z listy
użytkownika ("replay dla Deribit, jeśli istnieją już wymagane collectory
i snapshoty") — Deribit self-bootstrapuje się z własnej wiadomości
`type: "snapshot"` w strumieniu, jak OKX, więc jak przewidziano: brak
prerekwizytu do zamknięcia (w przeciwieństwie do Binance w Cyklu 19).

`src/data/deribit_replay.py` strukturalnie odzwierciedla `okx_replay.py`,
ponownie używając `DeribitBookSequenceGate` (`src/data/deribit_adapter.py`)
wprost dla ciągłości `change_id`/`prev_change_id`. Jedyna realna różnica
protokołu: poziomy booka to trójki `[action, price, amount]` z jawnym
polem `action` (`"new"`/`"change"`/`"delete"`), NIE para `[price, size]`
gdzie `size == 0` oznacza usunięcie jak u każdej innej giełdy — `"delete"`
musi mieć `amount == 0` (zwalidowane, zgodnie z istniejącą walidacją w
`deribit_normalized_event.py`, tu odzwierciedloną). `DeribitBookSequenceGate.apply()`
nigdy nie zwraca `False` (w przeciwieństwie do heartbeatu OKX czy stale
Binance) — każde wywołanie albo się udaje, albo rzuca, więc replay session
nie potrzebuje gałęzi "zaakceptowane ale pomiń".

`scripts/replay_raw_deribit.py`: CLI mirror `scripts/replay_raw_okx.py`,
reużywa generyczny `iter_raw_events(..., exchange="deribit",
market_type="option", ...)` bez zmian.

Walidacja: Ruff pass, Mypy pass dla 237 plików źródłowych, `1295 passed`
w Pytest (1284 + 11 nowych testów: snapshot+delta rebuduje dokładny book,
delta przed snapshotem odrzucona, gap po bootstrapie rzuca, `delete`
usuwa poziom niezależnie od wcześniejszego rozmiaru, `delete` z
niezerowym `amount` odrzucone, crossed book odrzucony, zmiana
connection_id wymaga świeżego snapshotu, luka jednego symbolu nie wpływa
na drugi, kanały inne niż orderbook liczone ale nie wpływają na book,
determinizm, sortowanie po receive_ts), `git diff --check` czyste, skan
sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian
Compose.

**Replay tool coverage teraz kompletny dla wszystkich 5 giełd**: Bybit
(pre-istniejący), Binance (Cykl 20), OKX (Cykl 21), Coinbase (Cykl 22),
Deribit (ten cykl) — każdy dostępny przez `scripts/replay_raw_<exchange>.py`.

**Nie zrobione w tym cyklu:** `BYBIT_VENUE`/multi-exchange backtest engine
nadal odłożone (kolejny priorytet użytkownika po replay tools — pkt 6:
"jako jeden kompletny, działający cykl"); Deribit datowane futures/opcje/IV
nadal otwarte (wymagają dynamicznego odkrywania instrumentów).

## 4x. Cykl 24 — Deribit dated futures/opcje/IV przez REST market-summary poller

Po zielonym CI dla `479d9cc` (Cykl 23). Domyka priorytet 4 z listy
użytkownika. Przed implementacją zweryfikowano na żywo skalę problemu:
`GET /public/get_instruments?currency=BTC&kind=option&expired=false` →
**998 aktywnych instrumentów**, ETH → **886**. To o 2-3 rzędy wielkości
więcej niż architektura per-symbol sequence-gate/health/queue (2
instrumenty, `INITIAL_V2_DERIBIT_INSTRUMENTS`) zakłada wszędzie w tym
repo. Rozszerzenie WS raw collectora o pełne L2 booki dla ~2000 serii
opcji byłoby operacyjnie niepraktyczne — i niepotrzebne: cel master planu
("options: IV, skew i term structure") nie wymaga pełnego booka per
strike, tylko zagregowanych metryk.

Zamiast tego: **REST poller** (ten sam wzorzec co Cykl 17/18 OI/
long-short), używający `GET /public/get_book_summary_by_currency` —
JEDNO wywołanie zwraca `mark_iv` (implied vol), `underlying_price`/
`underlying_index` (nazwa kontraktu bazowego — per-expiry dla opcji),
`open_interest`, `bid/ask/mark_price` dla WSZYSTKICH instrumentów danej
waluty+rodzaju naraz. `kind=future` zwraca też PERPETUAL (nieodfiltrowany
świadomie — to zagregowane statystyki, materialnie inny kształt danych
niż surowy L2 book z WS collectora, nie duplikat).

- `src/data/schema_deribit_market_summary.py`: jeden wspólny schemat dla
  future+option; pola tylko-dla-opcji (`mark_iv`/`underlying_price`/
  `underlying_index`) są `None` dla wiersza future/perpetual, nigdy nie
  zmyślone jako zero;
- `src/data/deribit_market_summary_client.py`: `DeribitMarketSummaryClient`,
  bezzależnościowy, live-zweryfikowany envelope `{jsonrpc,result,usIn,...}`;
- `src/data/deribit_market_summary_storage.py`: KAŻDY poll to pełny,
  niezależnie oznaczony czasem batch (nie "tylko nowsze niż ostatnie" jak
  OI/long-short — każdy poll pokrywa ten sam zestaw instrumentów na nowo)
  — dedup na dokładnym `(timestamp, instrument_name)` czyni powtórzony
  poll no-opem, nie duplikatem;
- `src/data/deribit_market_summary_collector.py`: poll loop używający
  wspólnego `rest_poller.py` (Cykl 18);
- `scripts/collect_deribit_market_summary.py`: CLI, `--currency` (BTC/ETH)
  `--kind` (future/option), domyślny interwał 5 minut (dłuższy niż
  OI/long-short — dane IV zmieniają się wolniej, a batch ma ~1000-2000
  wierszy);
- `docker-compose.yml`: 4 nowe serwisy (BTC/ETH × future/option) pod
  nowym profilem `["deribit-market-summary"]`, wspólny anchor
  `x-deribit-market-summary-common` — POPRAWNIE umieszczony na najwyższym
  poziomie pliku (przed `services:`), zgodnie ze wzorcem
  `x-raw-*-common`; wykryto i naprawiono własny błąd umieszczenia go
  wewnątrz `services:` przed walidacją `docker compose config`.

Walidacja: Ruff pass, Mypy pass dla 242 plików źródłowych, `1309 passed`
w Pytest (1295 + 14 nowych testów: client params/walidacja waluty i
rodzaju, storage roundtrip/każdy-poll-pełnym-batchem/idempotentny
powtórzony poll/osobne partycje currency+kind, collector zapisuje pełny
batch z poprawnym tagiem `kind`/nie zmyśla pól tylko-dla-opcji dla
future/CLI walidacja), `git diff --check` czyste, skan sekretów czysty
(kosmetyczny diff odrzucony jak zawsze), `docker compose config --quiet`
czyste, `docker compose --profile deribit-market-summary config`
zweryfikowane ręcznie — wszystkie 4 serwisy poprawnie sparsowane.

**Nie zrobione w tym cyklu:** `BYBIT_VENUE`/multi-exchange backtest engine
— ostatni punkt z listy użytkownika (pkt 6), świadomie odłożony jako
jeden kompletny cykl (nie fasadowa częściowa obsługa) — wymaga
jednoczesnego rozwiązania venue ORAZ multi-exchange klines/storage (patrz
4s, ten sam problem kolizji symboli jak OI/long-short, ale wyższa
stawka — dane cenowe karmiące silnik backtestu).

## 4y. Cykl 25 — multi-exchange backtest engine: Binance klines + usunięcie hardkodowania `BYBIT_VENUE`

Po zielonym CI dla `489f2a0` (Cykl 24). Zamyka ostatni punkt z listy
użytkownika (pkt 6) — **jako jeden kompletny cykl, zgodnie z wyraźnym
wymogiem "bez fasadowej częściowej obsługi"**. Zbadano oba powiązane
problemy naraz, zamiast robić samą parametryzację venue bez źródła
danych (co dałoby fasadę — silnik "obsługujący" Binance, ale bez
żadnych klines do wczytania).

**Część 1 — źródło klines dla Binance** (nowe, w pełni izolowane od
istniejącego kodu Bybit, ten sam wzorzec "osobny katalog najwyższego
poziomu" co każdy moduł Cyklu 17+):
- `src/data/binance_klines_client.py`: `BinanceKlineClient`,
  bezzależnościowy, live-zweryfikowany kształt odpowiedzi (`GET
  /fapi/v1/klines` — tablica tablic, nie obiektów jak Bybit);
- `src/data/ingest_binance_klines.py`: `fetch_binance_klines()` —
  paginacja W PRZÓD (Binance zwraca strony rosnąco od `startTime`), w
  przeciwieństwie do `src/data/ingest.py`'s paginacji WSTECZ dla Bybit
  (`end` malejąco) — realna, udokumentowana różnica protokołu, nie
  pomyłka. Reużywa `src.data.schema.COLUMNS`/`TIMEFRAME_MS` bez zmian
  (już generyczne);
- `src/data/binance_klines_storage.py`: `write_binance_klines`/
  `read_binance_klines`, katalog `binance_klines/` — zero zmian w
  `src/data/storage.py`, zero ryzyka kolizji symboli (np. BTCUSDT
  istnieje na obu giełdach z różną ceną);
- `scripts/download_binance_klines.py`: CLI mirror
  `scripts/download_data.py`, reużywa `src.data.validate.validate_dataset`
  BEZ ZMIAN (już generyczne — operuje na kanonicznym schemacie, nie na
  niczym specyficznym dla Bybit).

**Część 2 — generalizacja `instruments.py`/`engine.py`**:
- `configs/instruments_binance.yaml`: nowy plik, REALNA opłata Binance
  USDT-M futures standard tier (maker 0.02%/taker 0.05%, publicznie
  udokumentowana), `price_increment`/`size_increment` live-zweryfikowane
  (`GET /fapi/v1/exchangeInfo` dla BTC/ETH/SOL) — świadomie ta sama
  uproszczona "jeden wspólny increment dla wszystkich symboli" architektura
  co istniejący `configs/instruments.yaml` (rozszerzanie `InstrumentSpecs`
  o precyzję per-symbol byłoby osobną, większą zmianą we WSPÓLNYM,
  działającym kodzie), ale w kierunku bezpiecznym (drobniejszy niż realny
  tick, nigdy nie zezwala na grubszy fill niż realna giełda);
- `src/backtesting/instruments.py`: `venue_for_exchange(exchange) ->
  Venue`, `DEFAULT_INSTRUMENTS_CONFIG_PATHS` (mapa exchange→plik
  config). `load_instrument_specs`/`instrument_id_for`/
  `build_crypto_perpetual` zyskały `exchange: str = "bybit"` —
  DOMYŚLNA WARTOŚĆ ZACHOWUJE DOKŁADNIE POPRZEDNIE ZACHOWANIE każdego
  istniejącego wywołania (zweryfikowane: żaden istniejący test/kod nie
  przekazuje jawnej ścieżki, więc zmiana sygnatury `path: Path =
  DEFAULT...` → `path: Path | None = None` jest w pełni bezpieczna);
- `src/backtesting/engine.py`: `BacktestRunSpec` zyskała `exchange: str
  = "bybit"`. `build_engine()` deleguje venue/specs/czytnik klines przez
  `spec.exchange` — nowa `_KLINE_READERS` mapa (`"bybit"→read_klines,
  "binance"→read_binance_klines`).

**Realna, na żywo zweryfikowana weryfikacja end-to-end (nie tylko testy
syntetyczne)**: pobrano 49 realnych świec godzinowych BTCUSDT z Binance
(2024-06-01 do 2024-06-03, realne ceny ~67.5-68k USD) przez
`scripts/download_binance_klines.py` do katalogu scratchpad, następnie
uruchomiono PRAWDZIWY `run_backtest(BacktestRunSpec(..., exchange=
"binance"))` przeciwko tym danym — silnik NautilusTrader faktycznie
wystartował z venue `BINANCE`, konto zaczęło płasko od 100 000 zgodnie z
oczekiwaniem (brak strategii). To bezpośredni dowód, że to NIE jest
fasada — cała ścieżka (REST download → storage → engine → venue →
instrument → konto) faktycznie działa end-to-end na prawdziwych danych,
nie tylko w testach jednostkowych z syntetycznymi fixture'ami.

Walidacja: Ruff pass, Mypy pass dla 246 plików źródłowych, `1330 passed`
w Pytest (1309 + 21 nowych testów: 15 jednostkowych — client params,
paginacja w przód z dedup/granicami start-end, storage roundtrip/merge/
brak-kolizji-z-Bybit, CLI walidacja — oraz 6 integracyjnych w NOWYM,
osobnym pliku `test_backtest_engine_multi_exchange.py` — celowo osobnym
od istniejącego `test_backtest_engine.py`, żeby zero ryzyka dotknięcia
już przechodzącego zestawu testów Bybit: `venue_for_exchange` rozróżnia
BYBIT/BINANCE i odrzuca nieznaną giełdę, `instrument_id_for` domyślnie
nadal daje dokładnie `BTCUSDT-PERP.BYBIT`, specyfikacje Binance ładują
się z właściwego pliku, PEŁNY przebieg silnika przeciwko realnej ścieżce
storage Binance, dowód izolacji — zapisanie TYLKO do storage Binance nie
daje żadnych danych domyślnemu (Bybit) `BacktestRunSpec`, nieznana
giełda w `BacktestRunSpec` jest odrzucona). `git diff --check` czyste,
skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian
Compose (to zmiana silnika badawczego, nie infrastruktury kolektorów —
brak implikacji VPS).

**Nie zrobione w tym cyklu:** OKX/Coinbase/Deribit nadal nie mają
odpowiednika `configs/instruments_<exchange>.yaml`/klines source/
`venue_for_exchange` wpisu — `venue_for_exchange("okx")` świadomie rzuca
`ValueError` zamiast fasadowo zwracać coś nieprawidłowego; rozszerzenie
na kolejne giełdy to naturalne, dobrze zdefiniowane rozszerzenie tego
samego wzorca w przyszłym cyklu, nie wymaga nowego projektu.

**Wszystkie 6 punktów z jawnej listy priorytetów użytkownika (OKX/
Coinbase/Deribit replay, Deribit datowane futures/opcje/IV, oraz
multi-exchange klines + `BYBIT_VENUE`) są teraz GOTOWE.** Od Cyklu 26
agent samodzielnie wybiera kolejne priorytety z `docs/GREENFIELD_V2_MASTER_PLAN.md`
zgodnie ze standing instruction ("kontynuuj aż do wyczerpania planu albo
limitu użycia").

## 4z. Cykl 26 — order-flow/L2-imbalance features wpięte do `build_feature_matrix`

Po zielonym CI dla `c4ca1aa` (Cykl 25). Pierwszy cykl po wyczerpaniu
jawnej listy priorytetów użytkownika — wybrany samodzielnie po survey'u
fork-agenta obejmującym `src/features`, `src/engines`, `src/regimes`,
`src/risk`, `src/backtesting`, `src/research`, `src/analytics` (celowo
pominięto `src/data`, już dogłębnie pokryte, i `src/execution`, już
zbadane i utwardzone we wcześniejszym Cyklu 6).

**Znalezisko fork-agenta (zweryfikowane grep-em przed zaufaniem, jak
zawsze w tej sesji):** 9 z 13 modułów w `src/features/` (`order_flow.py`,
`momentum_flow.py`, `divergence.py`, `auction.py`, `cross_market.py`,
`cross_venue.py`, `derivatives.py`, `options.py`, `interaction.py`) są
kompletnie osierocone — zaimportowane wyłącznie przez własne testy,
NIGDZIE indziej w repo. Jedyny konsument `src.features` w całym
kodzie to `src.strategies.ml_filtered`, który importuje tylko
`price`/`structure`/`volatility`/`volume` z `pipeline.py`. Oznacza to,
że master-planowe pozycje "order flow: CVD, delta, footprint, imbalance,
absorption, exhaustion", niezależna rodzina Market-Cipher-like
(momentum_flow+divergence), cross-market/cross-venue, derivatives/options
features są NAPISANE i PRZETESTOWANE, ale produkcyjnie odłączone — nie
wpływają na żaden sygnał, silnik ani strategię badawczą.

**Zakres tego cyklu (świadomie ograniczony):** wpięto TYLKO warstwę
obliczania cech (`build_feature_matrix`) dla `order_flow.py` — NIE
zbudowano nowej strategii faktycznie konsumującej te cechy (to osobna,
większa decyzja projektowa/badawcza, nie plumbing). `src/features/pipeline.py`:
`build_feature_matrix()` zyskała dwa NIEZALEŻNE opcjonalne parametry
`trade_flow`/`l2_imbalance` (frames z `order_flow.py`'s
`trade_flow_frame`/`l2_imbalance_frame`, budowane z znormalizowanych
wierszy Silver — same nie są tu liczone, tylko as-of joinowane na
timestampy barów, tym samym wzorcem co istniejące `funding`/
`open_interest`). W przeciwieństwie do `funding`/`open_interest`
(traktowane jako para wszystko-albo-nic), te dwa nowe extra są
NIEZALEŻNE — inny strumień źródłowy Silver (trades vs order book), więc
wywołujący może mieć dane trade bez L2 lub odwrotnie. Nowe kolumny:
`cvd`/`trade_delta` (z `TRADE_FLOW_FEATURE_COLUMNS`),
`book_imbalance`/`spread` (z `L2_IMBALANCE_FEATURE_COLUMNS`). Domyślne
zachowanie (`trade_flow=None, l2_imbalance=None`) daje dokładnie
`FEATURE_COLUMNS` bez zmian — `ml_filtered.py` (jedyny istniejący
konsument) niezmieniony.

Walidacja: Ruff pass, Mypy pass dla 246 plików źródłowych (`src`), `1335
passed` w Pytest (1330 + 5 nowych testów w
`test_order_flow_pipeline_features.py`: pominięcie obu extra zostawia
wyjście bez zmian, trade_flow i l2_imbalance są prawdziwie niezależne
(jeden bez drugiego), oba naraz dodają oba zestawy kolumn, `cvd` przed
pierwszym odczytem to NaN a nie przyszła wartość, `book_imbalance`
as-of joinowane nigdy z przyszłości), `git diff --check` czyste, skan
sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian
Compose.

**Nie zrobione w tym cyklu (świadomie, uczciwie udokumentowane):** żadna
strategia/silnik faktycznie NIE konsumuje jeszcze `cvd`/`trade_delta`/
`book_imbalance`/`spread` — obliczalne teraz, ale nadal nie użyte w
żadnym sygnale. To nie jest "order flow wpięty w strategie", tylko
"order flow obliczalny w pipeline" — pierwszy, mniejszy krok. Pozostałe
8 osieroconych modułów (`momentum_flow.py`, `divergence.py`, `auction.py`
[Volume Profile/POC/VAH/VAL], `cross_market.py`, `cross_venue.py`,
`derivatives.py`, `options.py`, `interaction.py`) wciąż nieosiągalne z
`pipeline.py` — naturalne kandydatury na kolejne cykle, ten sam wzorzec.
Audit doc's M1-M3 (annualizacja, funding-nie-zastosowany, brak
mark-to-market) nie mają notatki "Update" jak M4/M5 — fork zasugerował
szybkie sprawdzenie, że nadal są zamknięte i dopisanie potwierdzenia;
odłożone jako osobna, mała, dokumentacyjna praca.

## 4aa. Cykl 27 — Volume Profile (POC/VAH/VAL, rolling) i AVWAP wpięte do `build_feature_matrix`

Po zielonym CI dla `7deb6dc` (Cykl 26). Kontynuacja tego samego wzorca —
kolejny osierocony moduł z listy Cyklu 26: `auction.py` (Volume Profile/
POC/VAH/VAL/VWAP/AVWAP — bezpośrednia pozycja master planu). W
przeciwieństwie do `order_flow.py` (Cykl 26), `volume_profile()` w
`auction.py` liczy JEDEN zagregowany profil dla ręcznie wybranego okna —
nie pasuje do prostego wzorca as-of-join użytego dla `cvd`/`book_imbalance`
bez dodatkowej pracy. Żeby uniknąć fasady (wymuszenia niepasującego
projektu tylko żeby "odhaczyć" pozycję), zbudowano najpierw brakujący
element: prawdziwą, przyczynowo poprawną serię czasową POC/VAH/VAL.

`src/features/auction.py`:
- `footprint_frame()`: dodano kolumnę `bucket_start_ms` do wyniku
  (zmieniono `.drop(columns="bucket")` na `.rename(columns={"bucket":
  "bucket_start_ms"})` — ADDYTYWNE, żadna istniejąca kolumna nie została
  usunięta/przemianowana, zweryfikowano brak asercji dokładnego zbioru
  kolumn w istniejących testach przed zmianą). Potrzebne, bo `timestamp`
  w tej ramce jest PER-PRICE-LEVEL (może się różnić między poziomami w
  tym samym bucketcie przez różny `receive_ns`), więc niewiarygodne jako
  klucz grupowania dla okna kroczącego;
- nowa `rolling_volume_profile_frame(footprint, *, window_buckets,
  value_area_fraction=0.70)`: dla każdego bucketa z pełnym oknem
  kroczącym `window_buckets` (włącznie) liczy `volume_profile()` na
  zagregowanych danych z tego okna — pierwsze `window_buckets - 1`
  bucketów świadomie NIE emitowane (nigdy wartość z niepełnego okna
  udająca pełne), analogicznie do "brak historii funding = NaN".

`src/features/pipeline.py`: `build_feature_matrix()` zyskała
`volume_profile`/`vwap` (frames z `rolling_volume_profile_frame`/
`anchored_vwap_frame`), NIEZALEŻNE od siebie i od wszystkich
wcześniejszych extra. W przeciwieństwie do `cvd`/`book_imbalance`
(joinowane wprost), surowe poziomy cen (`poc`/`vah`/`val`/`vwap`) NIE są
stacjonarne/porównywalne między aktywami/reżimami cenowymi, więc
przekonwertowane na cechy względem `close`, skalo-niezmiennicze:
`poc_distance = (close-poc)/close`, `value_area_width = (vah-val)/close`,
`in_value_area` (flaga 0/1, NaN gdy profil jeszcze niedostępny —
jawnie zamaskowane, bo porównanie z NaN dałoby fałszywe `False` zamiast
brakującej wartości), `vwap_distance = (close-vwap)/close`.

Walidacja: Ruff pass, Mypy pass dla 246 plików źródłowych, `1346 passed`
w Pytest (1335 + 11 nowych testów: `bucket_start_ms` obecne w wyniku
footprint, rolling profile pomija bucket bez pełnego okna, rolling
profile UŻYWA TYLKO okna kroczącego — nie całej historii (test z
dominującym wolumenem w bucket 0, który "wypada" z okna po jego
przesunięciu), timestamp emitowanego wiersza odpowiada WŁASNEMU
timestampowi bieżącego bucketa, odrzucenie window_buckets<=0, oraz w
pipeline: pominięcie zostawia wyjście bez zmian, oba extra niezależne,
poc_distance jest względny do close (nie surową ceną), in_value_area
poprawnie flaguje wewnątrz/na-zewnątrz [val,vah], NaN przed pierwszym
dostępnym profilem, vwap_distance względny do close), `git diff --check`
czyste, skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez
zmian Compose.

**Nie zrobione w tym cyklu:** jak w Cyklu 26 — żadna strategia nie
konsumuje jeszcze `poc_distance`/`in_value_area`/`vwap_distance`
("obliczalne", nie "użyte w sygnale"). Pozostałe 7 osieroconych modułów
(`momentum_flow.py`, `divergence.py`, `cross_market.py`, `cross_venue.py`,
`derivatives.py`, `options.py`, `interaction.py`) wciąż nieosiągalne z
`pipeline.py`.

## 4bb. Cykl 28 — niezależna rodzina Market-Cipher-like (`momentum_flow.py`) wpięta do `build_feature_matrix`

Po zielonym CI dla `f944429` (Cykl 27). Kontynuacja tej samej listy —
`momentum_flow.py` (niezależna rodzina momentum/money-flow/dywergencje,
bez własnościowego kodu — bezpośrednia pozycja master planu). W
przeciwieństwie do KAŻDEGO wcześniejszego extra (Cykle 26-27), które są
PRE-COMPUTED frames budowanymi przez wywołującego z danych Silver,
`momentum_money_flow_frame()` potrzebuje tylko `high/low/close/volume` —
dokładnie to, co `df` już ma. Dlatego nowy parametr to `momentum_flow:
bool = False` (flaga, nie frame) — `build_feature_matrix` liczy go
wewnętrznie z `df` samego w sobie.

`df` nie ma osobnego znacznika pochodzenia jak znormalizowane wiersze
Silver (`max_source_timestamp`), więc ustawiono go równym własnemu
`timestamp` bara — świece SĄ źródłem tutaj, nie zmyślona wartość.
Parametry okien `momentum_money_flow_frame` (channel_span/momentum_span/
signal_window/money_flow_window/rsi_window/pivot_left/pivot_right)
wystawione jako nowe pola `FeatureConfig` (`momentum_flow_*`), z
domyślnymi wartościami identycznymi jak funkcja sama w sobie.

**Znaleziony i naprawiony realny edge case przed napisaniem testów:**
`momentum_money_flow_frame()` CAŁKOWICIE POMIJA kolumny dywergencji w
wyniku (nie: obecne z zerami, tylko: nieobecne) gdy w danym oknie nie
było ŻADNEGO potwierdzonego pivota — inaczej niż gdy dywergencja istnieje
częściowo (wtedy brakujące wiersze są `fillna(0)`). Bez obsłużenia tego,
`build_feature_matrix` rzuciłby `KeyError` dla krótkich ramek. Naprawiono:
sprawdzenie `if column in momentum_result.columns` przed `.map()`, z
fallbackiem na `0` (nie `NaN`) dla brakujących kolumn dywergencji —
zgodnie z własną konwencją `momentum_money_flow_frame` "brak dywergencji
= zero, nie nieznane".

Walidacja: Ruff pass, Mypy pass dla 246 plików źródłowych, `1351 passed`
w Pytest (1346 + 5 nowych testów w `test_momentum_flow_pipeline_features.py`:
pominięcie zostawia wyjście bez zmian, `momentum_flow=True` dodaje
wszystkie kolumny, kolumny dywergencji są 0 (nie NaN) dokładnie tam gdzie
`momentum_wave` już dostępne, zbyt mało barów daje NaN/0 a nie crash —
bezpośredni test na edge case opisany wyżej, config respektuje
niestandardowe okna), `git diff --check` czyste, skan sekretów czysty
(kosmetyczny diff odrzucony jak zawsze), bez zmian Compose.

**Nie zrobione w tym cyklu:** jak w Cyklach 26-27 — żadna strategia nie
konsumuje jeszcze `momentum_wave`/`rsi`/dywergencji. `price_cvd_divergence_frame`
(`divergence.py` — dywergencja cena-vs-CVD, wymaga JEDNOCZEŚNIE `trade_flow`
z Cyklu 26 i własnej logiki dywergencji) świadomie NIE wpięty w tym
cyklu — łączy dwie już-wpięte koncepcje, zasługuje na osobny, przemyślany
projekt integracji, nie pospieszne dołączenie. Pozostałe osierocone
moduły: `cross_market.py`, `cross_venue.py`, `derivatives.py`, `options.py`,
`interaction.py` wciąż nieosiągalne z `pipeline.py`.

## 4cc. Cykl 29 — `derivatives.py` (funding/basis/OI/crowding/likwidacje) wpięty do `build_feature_matrix`

Po zielonym CI dla `9242ffd` (Cykl 28). Kontynuacja tej samej listy —
`derivatives_context_frame()` (funding, basis, OI, pozycjonowanie,
likwidacje — bezpośrednia pozycja master planu "derivatives: OI, funding,
basis, liquidations i crowding"). Wraca do wzorca Cyklu 26
(pre-computed frame budowany przez wywołującego), nie Cyklu 28
(wewnętrzne liczenie) — `derivatives_context_frame()` wymaga
`mark_price`/`index_price`/`open_interest`/`funding_rate` już
zestawionych point-in-time przez wywołującego (i opcjonalnie
`long_short_ratio`/wolumeny likwidacji), czego `build_feature_matrix`'s
`df` (surowe klines) nie dostarcza samo w sobie.

Świadomie wpięto TYLKO już znormalizowane/pochodne kolumny wyniku
(`funding_zscore`, `basis_zscore`, `derivatives_crowding_score`,
`oi_price_confirmation`, `liquidation_imbalance`) — pominięto surowe
`mark_return`/`oi_change`/`basis_bps`/`funding_rate`/
`funding_annualized_pct`, bo albo pokrywają się z tym, co `funding`/
`open_interest` (już wpięte, sprzed Cyklu 26) dają, albo są mniej
gotowe pod ML niż ich znormalizowane odpowiedniki w tej samej ramce.

`src/features/pipeline.py`: nowy parametr `derivatives_context:
pd.DataFrame | None = None`, ten sam wzorzec as-of-join co `trade_flow`/
`l2_imbalance`. Nowa stała `DERIVATIVES_CONTEXT_FEATURE_COLUMNS`.

Walidacja: Ruff pass, Mypy pass dla 246 plików źródłowych, `1355 passed`
w Pytest (1351 + 4 nowe testy w `test_derivatives_pipeline_features.py`:
pominięcie zostawia wyjście bez zmian, wpięcie dodaje TYLKO
znormalizowane kolumny (surowe jawnie sprawdzone jako nieobecne),
`funding_zscore` NaN przed dojrzeniem rollingu wewnątrz
`derivatives_context_frame` samej w sobie, as-of join nigdy nie widzi
przyszłego odczytu), `git diff --check` czyste, skan sekretów czysty
(kosmetyczny diff odrzucony jak zawsze), bez zmian Compose.

**Nie zrobione w tym cyklu:** żadna strategia nie konsumuje jeszcze tych
cech (jak w Cyklach 26-28). `options.py` (316 linii, znacznie większy i
bardziej złożony niż pozostałe — `OptionSurfaceSnapshot`/
`build_option_surface_snapshot`) świadomie odłożony na własny, dedykowany
cykl zamiast pospiesznego wpięcia. `price_cvd_divergence_frame`
(Cykl 28's uwaga) nadal nie wpięty. Pozostałe osierocone moduły:
`cross_market.py`, `cross_venue.py`, `interaction.py`, `options.py`
wciąż nieosiągalne z `pipeline.py`.

## 4dd. Cykl 30 — `cross_market.py` (siła względna BTC/ETH/SOL, lead-lag) wpięty do `build_feature_matrix`

Po zielonym CI dla `8272bbc` (Cykl 29). Kontynuacja tej samej listy —
`cross_market_context_frame()` (kontekst siły względnej/basis/lead-lag
między BTC/ETH/SOL). Powrót do wzorca Cyklu 26/29 (pre-computed frame),
z JEDNĄ realną różnicą architektoniczną wymagającą świadomej decyzji
projektowej: wyjście `cross_market_context_frame()` jest w formacie
DŁUGIM (LONG) — jeden wiersz per (timestamp, asset), wiele assetów na
timestamp — nie bezpośrednio joinowalne, bo `build_feature_matrix` nie
ma (i celowo nie dostaje) parametru `symbol` mówiącego, który asset
reprezentuje `df`.

Rozwiązanie: udokumentowano jawnie, że WYWOŁUJĄCY musi PRZEFILTROWAĆ
ramkę do jednego assetu (`context[context["asset"] == symbol]`) PRZED
przekazaniem do `build_feature_matrix` — ta funkcja nigdy nie zgaduje,
który wiersz jest właściwy, zamiast cicho brać "cokolwiek posortuje się
pierwsze" dla danego timestampu (dokładnie ten rodzaj niejednoznaczności,
którego ta funkcja unika wszędzie indziej). Pominięto `spot_return`/
`benchmark_return` jako nadmiarowe względem `return_1` (liczone z `df`
bezpośrednio, już w `FEATURE_COLUMNS`).

Walidacja: Ruff pass, Mypy pass dla 246 plików źródłowych, `1359 passed`
w Pytest (1355 + 4 nowe testy w `test_cross_market_pipeline_features.py`:
pominięcie zostawia wyjście bez zmian, wpięcie przefiltrowanej-do-jednego-
assetu ramki dodaje właściwe kolumny (surowe `spot_return`/
`benchmark_return` jawnie sprawdzone jako nieobecne), korelacja NaN przed
dojrzeniem rollingu (poprawiono własny off-by-one w teście —
korelacja potrzebuje `rolling_window` okresów ZWROTÓW, a zwroty same
potrzebują jednego dodatkowego wcześniejszego bara przez `pct_change`),
as-of join nigdy nie widzi przyszłego odczytu), `git diff --check`
czyste, skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez
zmian Compose.

**Nie zrobione w tym cyklu:** żadna strategia nie konsumuje jeszcze tych
cech (jak w Cyklach 26-29). `options.py` nadal odłożony na dedykowany
cykl. Pozostałe osierocone moduły: `cross_venue.py`, `interaction.py`,
`options.py`, `price_cvd_divergence_frame` (z `divergence.py`) wciąż
nieosiągalne z `pipeline.py`.

## 4ee. Cykl 31 — `interaction.py` (cancel/replenish/sweep/absorption/exhaustion) wpięty do `build_feature_matrix`

Po zielonym CI dla `ee0f9eb` (Cykl 30). Zbadano `cross_venue.py` (94
linie, najmniejszy pozostały moduł) jako pierwszego kandydata, ale jego
`cross_venue_snapshot()` ma FUNDAMENTALNIE inny kształt niż wszystko
dotąd wpięte — to funkcja PUNKTOWA (jedno wywołanie = jeden `as_of`
timestamp = jeden wiersz per venue), nie generator gotowej serii
czasowej; wpięcie wymagałoby pętli per-bar wywołującej ją wielokrotnie
nad pełną, wielogiełdową ramką `quotes` — inny, większy projekt integracji
niż as-of-join. Świadomie odłożone, przechodząc zamiast tego do
`interaction.py` (207 linii), które PASUJE dokładnie do wzorca Cyklu 26
(`book_liquidity_change_frame`/`trade_interaction_frame` budowane z
`list[NormalizedMarketEvent]`, dokładnie jak `trade_flow_frame`/
`l2_imbalance_frame`).

`src/features/pipeline.py`: dwa nowe, niezależne parametry
`book_liquidity_change`/`trade_interaction` (pre-computed frames,
wzorzec Cyklu 26), dołączone WPROST (surowe wolumeny/flagi/scory, bez
dalszej transformacji — spójne z tym, jak `cvd`/`book_imbalance` były
dołączone w Cyklu 26). Nowe stałe
`BOOK_LIQUIDITY_CHANGE_FEATURE_COLUMNS` (6 kolumn: dodane/anulowane/
uzupełnione per strona) i `TRADE_INTERACTION_FEATURE_COLUMNS` (11 kolumn:
sweep/absorption/exhaustion flagi i scory + progress w tickach).

**Napotkany i naprawiony błąd we własnym teście, nie w kodzie
produkcyjnym:** oryginalny fixture testowy wysyłał wszystkie transakcje
`trade_interaction_frame` w JEDNEJ syntetycznej wiadomości WS — obie
emitowane bucketowe wartości `timestamp` kolapsowały do IDENTYCZNEGO
znacznika czasu (bo `max_receive` per bucket brał `receive_ts_ns` całej
wiadomości, ta sama dla obu bucketów), czyniąc as-of-join niejednoznacznym.
Naprawiono przez podział fixture'a na dwie osobne wiadomości WS z różnymi
`receive_ts_ns` — wierniej odzwierciedla rzeczywistość (transakcje
przychodzą w czasie, nie wszystkie naraz) i czyni test faktycznie
znaczącym.

Walidacja: Ruff pass, Mypy pass dla 246 plików źródłowych, `1363 passed`
w Pytest (1359 + 4 nowe testy w `test_interaction_pipeline_features.py`:
pominięcie zostawia wyjście bez zmian, oba extra niezależne (jeden bez
drugiego), book-liquidity NaN gdy wszystkie bary poprzedzają pierwszy
odczyt (timestampy pochodne z fixture'a, nie zgadywane ręcznie —
lekcja z pierwszej nieudanej wersji tego testu), trade-interaction
poprawnie as-of joinowane po naprawie fixture'a), `git diff --check`
czyste, skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez
zmian Compose.

**Nie zrobione w tym cyklu:** żadna strategia nie konsumuje jeszcze tych
cech (jak w Cyklach 26-30). `cross_venue.py` (inny kształt integracji,
patrz wyżej), `options.py` (własny dedykowany cykl),
`price_cvd_divergence_frame` (z `divergence.py`) nadal nieosiągalne z
`pipeline.py`.

## 4ff. Cykl 32 — OKX klines + rozszerzenie multi-exchange backtest engine (Cykl 25) o OKX

Po zielonym CI dla `29966b4` (Cykl 31). Zamiast kolejnego elementu
`build_feature_matrix` (żadna strategia i tak jeszcze nie konsumuje
istniejących extra), wybrano dokończenie wątku z priorytetu 6 użytkownika:
ten sam wzorzec co Cykl 25 (Binance), teraz dla OKX — w pełni izolowane
źródło klines REST (`src/data/okx_klines_client.py`,
`ingest_okx_klines.py`, `okx_klines_storage.py`,
`scripts/download_okx_klines.py`, `configs/instruments_okx.yaml`) plus
wpięcie do `src/backtesting/instruments.py`
(`DEFAULT_INSTRUMENTS_CONFIG_PATHS`/`_VENUES`) i `engine.py`
(`_KLINE_READERS`).

**Odkrycie na żywo, zweryfikowane realnym `GET /api/v5/public/instruments`
i `/market/history-candles`:** OKX SWAP paginuje BACKWARD (`after`
cursor, najnowsze-pierwsze — jak Bybit, przeciwnie do Binance), a
`MAX_LIMIT` faktycznie wynosi 300 (nie 100, jak sugerowały niektóre
źródła dokumentacji) — obie rzeczy zweryfikowane bezpośrednim
wywołaniem, nie założone. Ważniejsze odkrycie: instrumenty SWAP na OKX są
CONTRACT-denominated (`ctVal`/`lotSz`), nie base-currency-denominated jak
Bybit/Binance — `BTC-USDT-SWAP` ma `ctVal=0.01` BTC/kontrakt,
`ETH-USDT-SWAP` `ctVal=0.1`, `SOL-USDT-SWAP` `ctVal=1` — realny efektywny
minimalny rozmiar rozpięty na dwa rzędy wielkości między symbolami.
Rozwiązane tak samo jak Binance (Cykl 25): jeden `size_increment: 0.0001`
w `instruments_okx.yaml`, drobniejszy niż każdy realny wymóg — nigdy nie
pozwala na grubsze wypełnienie niż rzeczywistość, udokumentowane wprost
w komentarzu configu.

**Naprawiony, świadomie znaleziony problem:** dodanie realnego wpisu
`"okx"` do `venue_for_exchange`/`DEFAULT_INSTRUMENTS_CONFIG_PATHS`
unieważniło dwa testy z Cykl 25
(`tests/integration/test_backtest_engine_multi_exchange.py`), które
celowo używały `"okx"` jako przykładu JESZCZE nieobsługiwanej giełdy
(`test_venue_for_exchange_distinguishes_bybit_and_binance`,
`test_engine_rejects_an_unknown_exchange`). Zmienione na `"coinbase"`
(nadal bez `configs/instruments_coinbase.yaml`/wpisu w `_VENUES`) —
przywraca faktyczny cel testów (odrzucenie naprawdę nieobsługiwanej
giełdy), zamiast przypadkowo zależeć od tego, że OKX zostanie
nieobsługiwane na zawsze. Dodano też trzy nowe testy analogiczne do
Cyklu 25 (`test_okx_instrument_specs_load_from_the_okx_config`,
`test_engine_runs_end_to_end_against_real_okx_klines_storage` — realny
przebieg silnika NautilusTrader z venue OKX,
`test_engine_exchange_default_still_reads_bybit_storage_not_okx` —
potwierdza izolację storage'u).

Walidacja: Ruff pass, Mypy pass dla 250 plików źródłowych (`src`+
`scripts`, do góry z 246), `1366 passed` w Pytest (1363 + 3 nowe testy w
`test_backtest_engine_multi_exchange.py`), `git diff --check` czyste,
skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian
Compose.

**Nie zrobione w tym cyklu:** realna weryfikacja end-to-end z faktycznie
pobranymi świecami OKX przez `scripts/download_okx_klines.py` (jak przy
Binance w Cyklu 25) — testy jednostkowe/integracyjne używają syntetycznych
danych zapisanych bezpośrednio przez `write_okx_klines`; ręczne pobranie
i przebieg z prawdziwym REST-em jeszcze nie wykonane. Coinbase/Deribit
nadal nie mają odpowiednika klines/backtest-engine (naturalne,
dobrze zdefiniowane rozszerzenie tego samego wzorca — Coinbase to
produkty spot więc sensowność klines jest inna niż dla perpów; Deribit
ma już dated-futures/opcje przez REST market-summary, klines dla samych
futures nadal nieobsłużone).

## 4gg. Cykl 33 — naprawa: WAF OKX blokuje domyślny User-Agent `urllib` na WSZYSTKICH endpointach REST

Po zielonym CI dla `2ea77b1` (Cykl 32, 8/8 checks). Kontynuacja
weryfikacji na żywo odłożonej w Cyklu 32 ("Nie zrobione w tym cyklu:
realna weryfikacja end-to-end..."): próba realnego pobrania świec OKX
przez `scripts/download_okx_klines.py` zakończyła się `HTTPError: 403
Forbidden`.

**Zdiagnozowane i zweryfikowane na żywo:** WAF OKX odrzuca (403,
powtarzalnie, 3/3 prób) KAŻDE żądanie do `www.okx.com/api/v5/*` z
domyślnym `User-Agent` biblioteki `urllib.request`
(`Python-urllib/3.11`) — potwierdzone bezpośrednim `curl` (200 OK, ten
sam endpoint) i bezpośrednim porównaniem: identyczny goły `urlopen()` bez
nagłówków działa bez problemu dla Binance i Deribit (oba 200 OK), więc to
NIE jest problem sieciowy/sandboxa, tylko blokada specyficzna dla WAF
OKX. Nagłówek `User-Agent` niepodszywający się pod przeglądarkę, tylko
jawnie inny niż domyślny (`Mozilla/5.0 (compatible;
GreenfieldMarketData/1.0)`), w pełni wystarcza — zweryfikowane na żywo.

**Konsekwencja odkryta przy okazji:** ten sam goły wzorzec
`urllib.request.urlopen(url)` bez nagłówków istnieje też w
`src/data/okx_derivatives_client.py` (Cykl 18, poller OI/long-short OKX,
udokumentowany w sekcji 5/7 jako "GOTOWE") — czyli TA implementacja też
zawsze dostawałaby 403 na żywym ruchu, mimo że przechodzi własne testy
(które wstrzykują fake fetcher i nigdy nie wywołują `default_okx_fetcher`
na prawdziwej sieci). Naprawiono oba moduły identycznie: `OKX_USER_AGENT`
+ `urllib.request.Request(url, headers={"User-Agent": OKX_USER_AGENT})`
zamiast gołego `urlopen(url)`.

Po naprawie: pełny live end-to-end przebieg wykonany i potwierdzony —
realne pobranie 49 świec `BTC-USDT-SWAP` 1h (1-3 czerwca 2024) przez
`scripts/download_okx_klines.py`, zapisane przez `write_okx_klines`,
odczytane przez `read_okx_klines`, i faktyczny przebieg silnika
NautilusTrader (`run_backtest` z `exchange="okx"`) — `run_finished` i
poprawny account report na venue OKX. Domyka to zastrzeżenie z Cyklu 32
("realna weryfikacja end-to-end... jeszcze nie wykonane").

Walidacja: Ruff pass, Mypy pass dla 250 plików, `1366 passed` w Pytest
(bez zmian liczby testów — to naprawa działania na żywo, nie nowej
logiki/gałęzi kodu pokrywanej przez istniejące testy z fake fetcherem),
`git diff --check` czyste, skan sekretów czysty (kosmetyczny diff
odrzucony jak zawsze), bez zmian Compose.

**Nie zrobione w tym cyklu:** analogiczna weryfikacja na żywo dla
`scripts/collect_okx_open_interest.py`/`collect_okx_long_short_ratio.py`
(sam fetcher naprawiony i pokrywa oba, ale osobnego end-to-end przebiegu
tych dwóch skryptów na żywo nie wykonano — poza zakresem tego cyklu,
skupionego na kline'ach). Warto rozważyć w przyszłym cyklu podobną
weryfikację na żywo (nie tylko testy z fake fetcherem) dla innych,
jeszcze nie uruchomionych na żywo REST-owych klientów w projekcie, na
wypadek analogicznych blokad WAF u innych giełd.

## 4hh. Cykl 34 — `divergence.py::price_cvd_divergence_frame` wpięty do `build_feature_matrix`

Po zielonym CI dla `2db22ba` (Cykl 33, 8/8 checks). Powrót do wątku
Cykli 26-31 (wpięcie osieroconych `src/features/` modułów) — ostatni
łatwo pasujący kandydat: `price_cvd_divergence_frame` (z `divergence.py`)
liczy się BEZPOŚREDNIO z tej samej surowej ramki `trade_flow`, którą
`build_feature_matrix` już przyjmuje jako parametr (Cykl 26) — potrzebuje
tylko jej własnych kolumn `trade_vwap`/`cvd`, więc nie wymaga nowej
funkcji źródłowej ani nowego kształtu integracji.

Nowy parametr `cvd_divergence: bool = False` (jak `momentum_flow` —
bool, nie gotowa ramka) — ale w odróżnieniu od `momentum_flow` (liczony
z samego `df`), ten wymaga `trade_flow` jako WEJŚCIA: przekazanie
`cvd_divergence=True` bez `trade_flow` rzuca `ValueError` zamiast cicho
nic nie robić — świadomy wybór, bo funkcja strukturalnie nie może
policzyć niczego bez tej ramki. Nowa stała
`CVD_DIVERGENCE_FEATURE_COLUMNS` (7 kolumn: regular/hidden bullish/
bearish divergence flagi, confirmed pivot low/high flagi, pivot_age_bars),
nowe pola konfiguracyjne `cvd_divergence_left_bars`/
`cvd_divergence_right_bars` w `FeatureConfig` (domyślnie 2/2, zgodnie z
domyślnymi `price_cvd_divergence_frame`).

**Test zweryfikowany na realnej, ręcznie skonstruowanej serii z faktyczną
dywergencją** (nie tylko obecność kolumn): seria cen/CVD z dwoma pivotami
niskimi, gdzie drugi ma niższą cenę ale wyższe CVD niż pierwszy — zgodnie
z logiką `confirmed_divergence_frame`, potwierdzone dokładnie w wierszu 10
jako `regular_bullish_divergence=1`. Napotkany i naprawiony błąd we
własnym teście (nie w kodzie produkcyjnym): pierwsza wersja zakładała, że
flaga dywergencji "trzyma się" (as-of forward-fill) na kolejnych barach
jak `cvd`/`trade_delta` — ale `confirmed_divergence_frame` emituje JEDEN
WIERSZ NA KAŻDY indeks potwierdzenia (nie tylko na faktyczne zdarzenia),
więc as-of join trafia we własny wiersz każdego bara, nie w poprzedni
"sticky" — naprawiono zamieniając test na sprawdzenie braku wycieku z
przyszłości (obcięta `trade_flow` bez wystarczających danych do
potwierdzenia drugiego pivota nigdy nie pokazuje przyszłej wartości 1 na
barach 10-11).

Walidacja: Ruff pass, Mypy pass dla 250 plików źródłowych, `1370 passed`
w Pytest (1366 + 4 nowe testy w
`test_cvd_divergence_pipeline_features.py`), `git diff --check` czyste,
skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian
Compose.

**Nie zrobione w tym cyklu:** żadna strategia nie konsumuje jeszcze tych
cech (jak w Cyklach 26-31). `cross_venue.py` (inny kształt integracji,
patrz 4ee) i `options.py` (własny dedykowany cykl) pozostają jedynymi
osieroconymi modułami `src/features/` — po tym cyklu praktycznie
wszystkie inne moduły tego katalogu mają już ścieżkę do
`build_feature_matrix`.

## 4ii. Cykl 35 — `cross_venue.py`: nowy `cross_venue_series_frame` (walk-forward) + wpięcie do `build_feature_matrix`

Po zielonym CI dla `1effe05` (Cykl 34). Powrót do `cross_venue.py`,
świadomie odłożonego w Cyklu 31 (patrz 4ee) — `cross_venue_snapshot()`
jest funkcją PUNKTOWĄ (jedno wywołanie = jeden `as_of` = jeden wiersz
per venue), niekompatybilną z bezpośrednim as-of joinem. Zamiast dalej
odkładać, zbudowano most: nowa funkcja `cross_venue_series_frame()` w
`cross_venue.py` — dokładnie ten sam wzorzec co Cykl 27
(`rolling_volume_profile_frame` przed wpięciem `volume_profile`) — chodzi
po `as_of_timestamps`, wywołuje `cross_venue_snapshot()` dla każdego,
redukuje wielogiełdowy wynik do JEDNEGO wiersza podsumowania per bar
(`cross_venue_count`, `cross_venue_max_abs_deviation_bps`,
`cross_venue_outlier_count`, `cross_venue_median_price`).

`src/features/pipeline.py`: nowy parametr `cross_venue_context:
pd.DataFrame | None = None` (ramka pre-budowana przez wywołującego, jak
`derivatives_context`/`interaction` — wymaga
`canonical_instrument_id`, którego `build_feature_matrix` nie zgaduje,
tak samo jak przy `cross_market_context`). `cross_venue_median_price`
(surowa cena) skonwertowana do `cross_venue_median_distance`
(close-relative), reszta kolumn dołączona wprost (już
scale-invariant liczniki/bps). Nowa stała
`CROSS_VENUE_CONTEXT_FEATURE_COLUMNS` (4 kolumny).

Walidacja: Ruff pass, Mypy pass dla 250 plików źródłowych, `1375 passed`
w Pytest (1370 + 2 nowe testy `cross_venue_series_frame` w
`test_cross_venue.py` + 3 nowe testy pipeline'u w
`test_cross_venue_pipeline_features.py`), `git diff --check` czyste,
skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian
Compose.

**Nie zrobione w tym cyklu:** żadna strategia nie konsumuje jeszcze tych
cech (jak w Cyklach 26-31/34). `options.py` (316 linii,
`OptionSurfaceSnapshot`/`build_option_surface_snapshot`) pozostaje
JEDYNYM osieroconym modułem `src/features/` — ma identyczny problem
kształtu (funkcja punktowa `as_of_utc` → jeden snapshot), ale jest
istotnie większy i bardziej złożony (wielopoziomowa struktura wygasania/
strike'ów, bramki jakości danych) niż `cross_venue.py` był — nadal
zasługuje na własny, dedykowany cykl, jak zaznaczono wcześniej, zamiast
pośpiesznego wciśnięcia przy okazji tego.

## 4jj. Cykl 36 — near-ATM Deribit option-ticker poller + `OptionQuote` bridge (dedykowany cykl dla `options.py`)

Po zielonym CI dla `b705dbd` (Cykl 35). Dedykowany cykl dla ostatniego
osieroconego modułu `src/features/options.py`, zapowiedziany w kilku
poprzednich cyklach jako zbyt duży, by wcisnąć przy okazji.

**Kluczowe odkrycie zweryfikowane na żywo:** bulk endpoint Deribit
(`get_book_summary_by_currency`, Cykl 24) zwraca `mark_iv`, ale NIGDY
`bid_iv`/`ask_iv`/`delta` — te trzy pola istnieją WYŁĄCZNIE na
per-instrumentowym endpoincie `/public/ticker` (potwierdzone bezpośrednim
porównaniem obu realnych odpowiedzi). `build_option_surface_snapshot`
TWARDO wymaga `bid_iv`/`ask_iv` (odrzuca "missing_two_sided_iv" inaczej)
i potrzebuje `delta` do wyboru kwotowań 25-delta — więc żadna realna
powierzchnia nie da się zbudować z samych danych bulk summary. Wywołanie
`/public/ticker` dla wszystkich ~2000 aktywnych instrumentów opcji
byłoby tak samo niepraktyczne jak pełne booki L2 (ten sam argument co w
Cyklu 24) — rozwiązane przez nowy, ograniczony wybór "near-ATM": z już
pobranej odpowiedzi bulk (za darmo, w tym samym wywołaniu, ma
strike/expiry/underlying_price dla każdego instrumentu) wybieramy N
najbliższych terminów wygaśnięcia i K strike'ów najbliżej underlying na
każdej stronie (domyślnie 2×5×2=20 instrumentów), i TYLKO dla nich
wołamy `/public/ticker`.

Nowe pliki: `src/data/deribit_option_instrument.py` (parser nazwy
instrumentu Deribit `{BASE}-{DDMMMYY}-{STRIKE}-{C|P}` +
`select_near_atm_option_instruments`), `deribit_option_ticker_client.py`
(cienki klient `/public/ticker`), `schema_deribit_option_ticker.py`,
`deribit_option_ticker_storage.py`, `deribit_option_ticker_collector.py`
(łączy bulk summary + per-instrument ticker, współdzieli
`rest_poller.py`), `scripts/collect_deribit_option_ticker.py`,
`src/data/deribit_option_quotes.py` (most: konwertuje zapisane wiersze
tickera na `list[OptionQuote]`, warstwa danych, nie feature — ten sam
podział co `order_flow.py`'s `list[NormalizedMarketEvent]`). Docker
Compose: nowy `x-deribit-option-ticker-common` (na górze pliku, PRZED
`services:` — nauczka z pomyłki Cyklu 24) + 2 serwisy (BTC/ETH), profil
`deribit-option-ticker`, disabled by default.

**Naprawiony błąd znaleziony przez własny test przed commitem:** parser
nazwy instrumentu zakładał dzień zawsze 2-cyfrowy (7-znakowy token dat)
— realne dane na żywo pokazały Deribit NIE dopełnia zerem
jednocyfrowych dni (`ETH-4SEP26-...`, 6-znakowy token), co pierwotny
parser odrzucał całkowicie. Naprawione przed napisaniem błędnego kodu do
produkcji dzięki testowi `test_parses_a_single_digit_day`, napisanym
właśnie dlatego że dane referencyjne z prawdziwego API to pokazały —
bez tej naprawy poller cicho gubiłby ~1/30 terminów wygaśnięcia
(każdy przypadający na dzień 1-9).

**Pełna weryfikacja end-to-end na żywo, cały łańcuch:** realny
`DeribitOptionTickerCollector.poll_once()` (BTC, 1 termin × 3 strike'i)
→ 6 zapisanych wierszy z faktycznymi `bid_iv`/`ask_iv`/`delta` → odczyt →
`option_quotes_from_ticker_rows()` → `build_option_surface_snapshot()` →
realny `OptionSurfaceSnapshot` z `near_atm_iv=61.5`, `atm_strike=78000`,
prawdziwym `put_call_oi_ratio` i odrzuceniami `wide_iv_spread` dla 2 z 6
kwotowań (bramki jakości faktycznie coś odrzuciły, nie przepuściły
wszystkiego bezkrytycznie).

Walidacja: Ruff pass, Mypy pass dla 257 plików źródłowych (z 250),
`1401 passed` w Pytest (1375 + 26 nowych: parser/selekcja 12,
ticker-storage 5, ticker-collector 4, ticker-client 1, quotes-bridge 4),
`git diff --check` czyste, skan sekretów czysty (kosmetyczny diff
odrzucony jak zawsze), `docker compose config --quiet` czyste (anchor
poprawnie na górze pliku od razu, bez powtórki błędu z Cyklu 24).

**Nie zrobione w tym cyklu:** wpięcie do `build_feature_matrix` — jak
`cross_venue_snapshot` przed Cyklem 35, `build_option_surface_snapshot`
jest funkcją PUNKTOWĄ, ale ze znacznie bogatszą, zagnieżdżoną strukturą
wyjścia (per-expiry cechy, nie proste skalary) niż cross-venue — decyzja,
KTÓRE skalarne cechy per-bar wyciągnąć z tej struktury (i jak
zagregować po wielu terminach wygaśnięcia) zasługuje na własną,
przemyślaną analizę zamiast pospiesznego wyboru przy okazji. Żadna
strategia i tak jeszcze nie konsumuje żadnych cech z Cykli 26-35. Po tym
cyklu WSZYSTKIE moduły `src/features/` mają już realną, żywą ścieżkę
danych (nawet jeśli nie wszystkie mają jeszcze wpięcie do
`build_feature_matrix`).

## 4kk. Cykl 37 — `multidomain_bridge.py`: wpięcie `classify_multidomain_regimes` (osierocone poza `src/features/`)

Po zielonym CI dla `a28728f` (Cykl 36). Skoro po Cyklu 36 każdy moduł
`src/features/` ma już realną ścieżkę danych, wysłano forka do zbadania
`src/regimes/`, `src/engines/`, `src/risk/` pod kątem tej samej klasy
problemu (kod w pełni zbudowany i przetestowany, ale bez żadnego
wywołującego). Wynik: `src/risk/` w pełni wpięte (bez akcji);
`src/engines/` (contracts/directional/neutral/meta, 1090 linii) w pełni
osierocone, ale wymaga NAJPIERW brakującej całej warstwy
`FamilyEvidence`/`ConfirmationFamily` (nic w repo jej nie produkuje) —
poprawnie odłożone jako osobny, wieloetapowy projekt, nie coś do
wciśnięcia teraz; `src/regimes/multidomain.py`
(`classify_multidomain_regimes`/`stabilize_regime_labels`, 315 linii, w
pełni przetestowane) wskazane jako najmniejszy, najczystszy cel — zero
wywołujących nigdzie w repo.

Zbadano wymagany schemat wejścia (`spread_bps`, `depth_notional`,
`signed_delta`, `open_interest`, `liquidation_total`,
`market_breadth_positive_fraction`, `cross_asset_return_dispersion`,
`benchmark_return`, `realized_volatility` + OHLC) i potwierdzono: KAŻDA
z tych wartości da się wyprowadzić z już zbudowanych, już wpiętych
(Cykle 26-35) funkcji cech — `spread_bps`/`depth_notional` z
`l2_imbalance_frame`'s `spread`/`mid_price`/`bid_depth`/`ask_depth`,
`signed_delta` to dokładnie `trade_flow_frame`'s `trade_delta` pod inną
nazwą, `liquidation_total`/`market_breadth_positive_fraction`/
`cross_asset_return_dispersion`/`benchmark_return` to bezpośrednie,
niezmienione kolumny z wyjścia `derivatives_context_frame`/
`cross_market_context_frame`, `realized_volatility` liczone lokalnie tą
samą funkcją co `pipeline.py`'s `out["realized_vol"]`. Żadna nowa logika
obliczeniowa nie była potrzebna — tylko most składający.

Nowy plik: `src/regimes/multidomain_bridge.py` —
`assemble_multidomain_regime_frame()` (as-of joinuje wszystkie źródła w
wymagany schemat) + `classify_multidomain_regimes_from_sources()`
(assembly + klasyfikacja w jednym wywołaniu).

**Ważne odkrycie udokumentowane wprost w docstringu:**
`classify_multidomain_regimes` odrzuca (fail-closed) WSZYSTKIE wiersze
naraz, jeśli KTÓRYKOLWIEK wiersz ma niefinitywną wartość w wymaganej
kolumnie — w przeciwieństwie do `build_feature_matrix`'s "NaN aż do
dojrzenia okna, wybierz sam co zrobić z NaN" filozofii. Oznacza to, że
`classify_multidomain_regimes_from_sources` NIE przycina wiodących
wierszy NaN sama (odróżnienie mechanicznego rozgrzewania okna od
prawdziwej luki w danych wymagałoby zgadywania) — to odpowiedzialność
wywołującego, jawnie udokumentowana, ze świadomym testem
udowadniającym zarówno ścieżkę odrzucenia, jak i sukcesu po ręcznym
przycięciu.

Walidacja: podczas pisania testu end-to-end napotkano i naprawiono
realną właściwość numeryczną (nie błąd produkcyjny) — stała (bez
wariancji) seria wejściowa daje `_rolling_zscore` = NaN (std=0), więc
fixture testowy musiał mieć faktyczną zmienność w spread/depth/OI/
wolumenach likwidacji, nie stałe wartości — poprawne zachowanie
`_rolling_zscore` (NaN = brak informacji do policzenia zscore, uczciwa
odpowiedź), nie coś do obejścia. Ruff pass, Mypy pass dla 258 plików
źródłowych, `1406 passed` w Pytest (1401 + 5 nowych), `git diff --check`
czyste, skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze),
bez zmian Compose.

**Nie zrobione w tym cyklu:** żadna strategia/skrypt jeszcze nie
konsumuje `classify_multidomain_regimes_from_sources` (jak
`scripts/analyze_regimes.py` robi dla jednodomenowego
`classify_regimes`) — naturalne rozszerzenie, ale osobna decyzja co do
kształtu raportu. `src/regimes/analogs.py` (`find_historical_analogs`,
399 linii, w pełni przetestowane, zero wywołujących) pozostaje
następnym wskazanym przez forka celem. `src/engines/` (Setup/
Directional/Neutral/Meta) świadomie odłożone jako własny, wieloetapowy
projekt wymagający najpierw brakującej warstwy evidence.

## 4ll. Cykl 38 — `analogs_bridge.py`: wpięcie `find_historical_analogs`

Po zielonym CI dla `d36cda5` (Cykl 37; z powodu wyczerpania niezalogowanego
limitu GitHub API — 60 req/h — podczas intensywnego pollingu w tym
i poprzednich cyklach, status CI Cyklu 35/37 nie zawsze dało się
natychmiast potwierdzić przez API; walidacja lokalna — ruff/mypy/pytest —
była czysta dla obu przed commitem, jak zawsze, więc kontynuowano bez
czekania na reset limitu). Drugi cel wskazany przez tego samego forka co
Cykl 37: `src/regimes/analogs.py`'s `find_historical_analogs` (399 linii,
w pełni przetestowane, zero wywołujących).

W przeciwieństwie do `multidomain_bridge.py` (Cykl 37), ten most
ŚWIADOMIE NIE wybiera źródła reżimu za wywołującego — projekt ma teraz
DWA prawdziwie różne, oba poprawne sposoby na policzenie `regime`
(jednodomenowy `classify_regimes`'s `trend_regime`, albo bogatszy
per-domenowy wynik Cyklu 37) — wymuszenie jednego byłoby dokładnie tym
rodzajem niewyjaśnionego wyboru, którego ten projekt unika. Podobnie
`data_quality_score` — nie istnieje żaden ogólnoprojektowy per-barowy
wskaźnik jakości (`src/data/data_quality.py`'s `QualityCheck`/
`PartitionQualityReport` to audyty per-partycja Silver, nie per-bar
score [0,1]) — jedyna uczciwa, nie zmyślona definicja bez wymyślania
nowego modelu jakości: binarna, 1.0 gdy wszystkie kolumny `features` są
finite dla danego wiersza, 0.0 inaczej.

Nowy plik: `src/regimes/analogs_bridge.py` —
`assemble_analog_search_frame(df, features, regime)` przyjmuje
`features`/`regime` jako already-aligned serie/ramki (indeks zgodny z
`df`, jak wyjście `build_feature_matrix`/`classify_regimes`), rzuca
`ValueError` przy niezgodnym indeksie zamiast cichego złego
wyrównania.

**Ważne odkrycie zweryfikowane realnym wywołaniem:**
`find_historical_analogs`'s `_validate_values` sprawdza finite dla
WSZYSTKICH wierszy całej ramki (nie tylko kandydatów) w kolumnach cech
użytych przez `AnalogSearchConfig` — dokładnie ten sam "fail-closed na
całej ramce" kontrakt co `classify_multidomain_regimes` z Cyklu 37, a
NIE bramkowany przez `data_quality_score` (który tylko filtruje
kandydatów PO przejściu walidacji). Oznacza to, że `data_quality_score`
mojego mostu jest głównie deskryptywny/pomocniczy — realny wymóg to
przycięcie ramki do zakresu, gdzie wybrane kolumny cech są już
w pełni dojrzałe, udokumentowane wprost w docstringu, ten sam wzorzec
co Cykl 37.

Test end-to-end użył PRAWDZIWEGO `build_feature_matrix`/
`classify_regimes` (nie ręcznie spreparowanych wartości cech, w
przeciwieństwie do istniejącego `test_historical_analogs.py`, który
celowo testuje samą logikę `find_historical_analogs` na w pełni
kontrolowanych danych) — zweryfikowano bezpośrednio, że wynik to
faktycznie `is_meaningful=True` z 5 sąsiadami i realnymi rozkładami
zwrotu, nie tylko ścieżka fallback.

Walidacja: Ruff pass, Mypy pass dla 259 plików źródłowych, `1410 passed`
w Pytest (1406 + 4 nowe), `git diff --check` czyste, skan sekretów
czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian Compose.

**Nie zrobione w tym cyklu:** żadna strategia/skrypt jeszcze nie
konsumuje `assemble_analog_search_frame`/`find_historical_analogs` na
żywo (jak `scripts/analyze_regimes.py` robi dla `classify_regimes`) —
naturalne rozszerzenie, osobna decyzja co do kształtu raportu/CLI.
`src/engines/` (Setup/Directional/Neutral/Meta) pozostaje jedynym
odłożonym celem ze zwiadu forka — świadomie, wymaga najpierw
brakującej warstwy `FamilyEvidence`/`ConfirmationFamily`.

## 4mm. Cykl 39 — `scripts/find_historical_analogs.py`: pierwszy realny konsument mostów Cykli 37-38

Po zielonym CI dla `d26ef8e` (Cykl 38, potwierdzone opóźnione — patrz
notatka w 4ll o wyczerpaniu niezalogowanego limitu GitHub API; po
resecie limitu Cykle 36 i 37 potwierdzone 8/8 zielone). Domyka "Nie
zrobione w tym cyklu" z Cyklu 38 ("no strategy/script consumes this
yet").

**Świadomie NIE zaatakowano `src/engines/` w tym cyklu**, mimo że to
jedyny pozostały cel ze zwiadu forka sprzed Cyklu 37. Zbadano kształt
`FamilyEvidence`/`ConfirmationFamily` (`src/engines/contracts.py`) —
wymaga `score` (-1..1), `confidence` (0..1), `quality` (0..1) per jedna
z 6 rodzin (`price_auction`, `order_flow`, `derivatives`,
`volatility_options`, `cross_market`, `regime_analog`). W przeciwieństwie
do Cykli 26-38 (mechaniczne przepięcie już istniejących, jednoznacznie
zdefiniowanych wielkości — zmiana nazwy, konwersja jednostek, as-of
join), wymyślenie WZORU na `score`/`confidence` dla realnej rodziny
(np. czy wysoki `derivatives_crowding_score` to sygnał byczy czy
kontrariański — to pytanie wymagające badawczej walidacji, nie
mechanicznego mapowania) byłoby dokładnie tym rodzajem niewyjaśnionego,
niezweryfikowanego wyboru, którego master plan's sekcje 13
(anti-overfitting) i 14 (promotion gates) istnieją, by uniemożliwić.
Świadomie odłożone jako wymagające prawdziwej pracy badawczej/
walidacyjnej, nie coś do zgadnięcia w autonomicznym cyklu.

Zamiast tego: przegląd `src/analytics/`/`src/research/` (katalogi
pominięte przez zwiad forka) metodą liczenia importerów — jedyny
sierota, `src/research/degradation.py`, to ZNANY już wcześniej
(Cykl 4!) i udokumentowany w sekcji 5 punkt 4 tego dokumentu gap,
zablokowany na tej samej przyczynie od tamtego czasu (brak operacyjnego
źródła baseline i scheduled evaluation loop — infrastruktura
wdrożeniowa, poza zakresem repo-only). Nic nowego do zrobienia tam bez
decyzji operacyjnej.

Zamiast tego wybrano bezpieczny, mechaniczny cel: CLI dla
`find_historical_analogs`/`analogs_bridge.py` (Cykl 38), używający
WYŁĄCZNIE danych klines (żadnych L2/derivatives/cross-market, w
przeciwieństwie do `multidomain_bridge.py` z Cyklu 37) — `build_feature_
matrix` + `classify_regimes`'s `trend_regime` jako jedyna, domyślna
rodzina cech. Nowy plik: `scripts/find_historical_analogs.py`.

**Pełna weryfikacja end-to-end na żywo:** pobrano realne świece Bybit
BTCUSDT 1h (styczeń-czerwiec 2024, `scripts/download_data.py` — publiczny
REST, zero interakcji z żywym collectorem) i uruchomiono CLI —
`is_meaningful=True`, `eligible_candidate_count=1702`,
`neighbor_count=20`, realne rozkłady zwrotu na 3 horyzontach.
Zweryfikowano też `--query-timestamp`/`--feature-columns`/
`--no-require-same-regime` oraz ścieżkę błędu (brak danych → exit code 1,
czytelny komunikat).

Walidacja: Ruff pass, Mypy pass dla 260 plików źródłowych, `1414 passed`
w Pytest (1410 + 4 nowe w `test_find_historical_analogs_script.py` —
walidacja argumentów i ścieżka braku danych; realna ścieżka sukcesu
zweryfikowana ręcznie na żywo, nie w automatycznym teście — brak
lokalnych danych klines w repo-only środowisku do uruchomienia jej jako
części CI), `git diff --check` czyste, skan sekretów czysty (kosmetyczny
diff odrzucony jak zawsze), bez zmian Compose.

**Stan po Cyklu 39 — szczera ocena:** cała bezpieczna, mechaniczna praca
fundamentu danych i cech (Cykle 21-39: replay dla wszystkich 5 giełd,
multi-exchange klines/backtest engine, wszystkie moduły `src/features/`
i `src/regimes/` osiągalne z realnymi danymi) jest wyczerpana. Trzy
kategorie pozostałej pracy z master planu: (a) wymaga jawnej zgody
użytkownika — włączenie PAPER/LIVE, wdrożenie VPS, nowy soak marker dla
produkcyjnych collectorów Binance/OKX/Coinbase/Deribit, polityka
retencji danych; (b) wymaga prawdziwej pracy badawczej/walidacyjnej, nie
mechanicznego przepięcia — `src/engines/`'s warstwa `FamilyEvidence`
(patrz wyżej); (c) drobne, nieblokujące rozszerzenia — inne rodziny cech
dla `find_historical_analogs` (auction/order-flow zamiast samego OHLCV),
CLI dla `classify_multidomain_regimes_from_sources` (wymagałby realnych
danych L2/derivatives/cross-market jednocześnie, których repo-only
środowisko nie ma).

## 4nn. Cykl 41 — usunięcie martwego `src/strategies/sizing.py` (fałszywy docstring)

Po zielonym CI dla `37bcb58` (Cykl 40, docs-only). Użytkownik napisał
"kontynuuj" — po własnej ocenie z Cyklu 39/40 ("bezpieczna, mechaniczna
praca wyczerpana"), wysłano forka do jeszcze jednego, szerszego
przeglądu (`src/backtesting/`, `src/strategies/`, `src/analytics/`,
`src/research/` — katalogi nie objęte wcześniejszymi zwiadami) zamiast
od razu zakładać, że nic nie zostało.

Znaleziono i zweryfikowano bezpośrednio (nie tylko zaufano forkowi):
`src/strategies/sizing.py`'s `position_size()` to martwy kod z fałszywym
docstringiem ("Every benchmark strategy in this package uses this same
sizing rule") — realne sizing we wszystkich strategiach
(`base.py:234`, potwierdzone bezpośrednim odczytem) idzie przez
`src.risk.engine.RiskEngine.evaluate()`, który liczy swój WŁASNY
`notional = equity * risk_fraction; quantity = instrument.make_qty(...)`
niezależnie, bez importu z `sizing.py`. Grep po całym repo:
`position_size(` ma zero wywołań poza własnym plikiem testowym.
`docs/PHASE_0_ARCHITECTURE_RESEARCH.md` (dokument, na który wskazuje
docstring) potwierdza architekturę: "risk/ # risk engine (position
sizing, limity, drawdown)" — `sizing.py` to pozostałość sprzed
konsolidacji do `RiskEngine`, nigdy nie usunięta.

Usunięto `src/strategies/sizing.py` i `tests/unit/test_sizing.py` w
całości (zgodnie z konwencją projektu: pewność co do martwego kodu →
usunięcie, nie zostawianie fasady).

Walidacja: Ruff pass, Mypy pass dla 259 plików źródłowych (spadek z 260
— jeden plik usunięty), `1410 passed` w Pytest (1414 - 4 usunięte testy
`sizing.py`), `git diff --check` czyste, skan sekretów czysty
(kosmetyczny diff odrzucony jak zawsze), bez zmian Compose.

**Wynik pełnego zwiadu forka:** poza tym jednym znaleziskiem — potwierdzono
brak TODO/FIXME/XXX gdziekolwiek w `src/`/`scripts/`; `src/backtesting/`
i pozostałe 15 modułów `src/strategies/` w pełni wpięte (żadnych innych
sierot); żadna strategia poza `ml_filtered.py` nie wywołuje
`build_feature_matrix` w ogóle, więc dodanie Cykli 26-38 extras do
istniejących strategii wymagałoby wymyślenia nowej logiki sygnałowej —
poprawnie poza zakresem, tak samo jak `src/engines/`. Fork potwierdza
wcześniejszą ocenę: poza tym drobnym sprzątaniem, bezpieczna mechaniczna
praca repo-only jest wyczerpana.

## 4oo. Cykl 42 — pierwszy producent `FamilyEvidence`: `derivatives_evidence.py` (research-stage v1)

Po zielonym CI dla `0f1428e` (Cykl 41). Użytkownik napisał wprost:
"kontynuuj zgodnie z planem, nie pytaj mnie więcej o nic" — jednoznaczne
polecenie kontynuowania bez zatrzymywania się na kolejne potwierdzenia.
Ponowna ocena wcześniejszej decyzji o nietykaniu `src/engines/`
(Cykle 37-41): sekcja 10.2 master planu mówi "confirmation thresholds
and weights are fit without access to holdout data" — a nie "nie pisz
tego kodu, dopóki nie przeprowadzisz osobnych badań empirycznych".
Sekwencja promocji projektu (Research → OOS candidate → Shadow → Paper
→ LIVE_SMALL → LIVE, sekcja 14) to WŁAŚNIE mechanizm, przez który
tego typu reguła ma przejść, zanim będzie zaufana — napisanie PIERWSZEJ,
jawnie oznaczonej jako "research-stage v1" reguły scoringu i przetestowanie
jej end-to-end przez already-built `evaluate_directional_setup` jest
kontynuacją planu, nie skrótem go omijającym, dopóki nic z tego nie
dotyka kapitału/PAPER/LIVE/VPS (nadal absolutnie nietykalne).

**Zakres świadomie wąski:** jeden producent evidence (rodzina
DERIVATIVES), nie sześć naraz. Reguła oparta na JEDNYM, dobrze
ugruntowanym pomyśle technicznym — kierunek z `mark_return`
(z-score'owany, tanh-bounded), PRZEKONANIE (conviction) z tego, czy
`oi_price_confirmation` (już policzone przez `derivatives_context_frame`,
Cykl 29) potwierdza ruch (realne nowe pozycjonowanie) czy mu przeczy
(short-covering/long-liquidation — ruch bez realnego przekonania, score
w pełni wyzerowany, nie tylko przytłumiony). Świadomie NIE włączono do
score: `funding_zscore`/`basis_zscore`/`derivatives_crowding_score`/
`liquidation_imbalance` — każdy mógłby wzmocnić lub zaprzeczyć sygnałowi,
ale spiętrzenie kilku, słabiej ugruntowanych pomysłów w jeden nieprzejrzysty
score w jednym autonomicznym cyklu straciłoby dokładnie tę
audytowalność, na której nalegały wszystkie poprzednie cykle. Nowy plik:
`src/engines/derivatives_evidence.py`, funkcja `derivatives_family_evidence()`
zwraca `FamilyEvidence | None` (nie syntetyczny wpis quality=0, który
zatruwałby całą decyzję przez `evaluate_directional_setup`'s "ANY evidence
poniżej progu → WAIT" — `None` = ten głos po prostu pomijany przez
wywołującego).

**Pełna weryfikacja end-to-end, prawdziwym łańcuchem:** realny
`derivatives_context_frame()` → `derivatives_family_evidence()` →
prawdziwe `DirectionalSetupRequest`/`evaluate_directional_setup()`
(z `minimum_confirming_families=1`, bo to jedyna wpięta na razie rodzina)
→ faktyczna decyzja `LONG` z realnym `SetupLeg`. Pierwszy raz w historii
tego repo, gdy `src/engines/` faktycznie coś zdecydował na podstawie
prawdziwych (nie ręcznie wpisanych w teście) danych.

Walidacja: Ruff pass, Mypy pass dla 260 plików źródłowych, `1417 passed`
w Pytest (1410 + 7 nowych, w tym pełny test end-to-end), `git diff
--check` czyste, skan sekretów czysty (kosmetyczny diff odrzucony jak
zawsze), bez zmian Compose.

**Uczciwie: co to NIE jest.** To NIE jest empirycznie zwalidowana reguła
— nie przeszła przez OOS/Monte Carlo/promotion gates, nie ma dowodu
realnej krawędzi (edge) na rzeczywistych danych. To research-stage v1:
kod istnieje, jest testowalny, jest audytowalny, i JEST gotowy do
poddania go tej samej infrastrukturze walidacyjnej (Monte Carlo, Cykl 16;
walk-forward/promotion, istniejące), którą projekt już ma. Pozostałych 5
rodzin (`price_auction`, `order_flow`, `volatility_options`,
`cross_market`, `regime_analog`) NIE zrobiono w tym cyklu — każda
zasługuje na tę samą, jedną-na-raz dyscyplinę, nie pospieszne
uzupełnienie wszystkich sześciu naraz. `neutral.py`/`meta.py` też
jeszcze nieużywane na żywo.

## 4pp. Cykl 43 — drugi producent `FamilyEvidence`: `order_flow_evidence.py` + pierwsza realna zgoda/konflikt dwóch rodzin

Po zielonym CI dla `edfa118` (Cykl 42, 8/8). Kontynuacja "jedna rodzina
na raz" zapowiedziana w Cyklu 42 — druga rodzina, ORDER_FLOW, celowo
zbudowana STRUKTURALNIE RÓWNOLEGLE do `derivatives_evidence.py`: kierunek
z powrotu `trade_vwap` (z-score, tanh-bounded — `trade_vwap` to już
istniejący w projekcie proxy ceny dla tej rodziny, Cykl 34's
`price_cvd_divergence_frame` używa go tak samo), przekonanie z tego, czy
`trade_delta` (agresywny wolumen kupna-sprzedaży per bucket, Cykl 26)
potwierdza kierunek ceny czy mu przeczy (ruch bez realnej agresywnej
strony = w pełni wyzerowany score, ten sam wzorzec "smart money
confirmation" co przy OI). Świadomie NIE włączono `cvd` (wielkość o
dłuższym horyzoncie niż jeden bucket) ani `book_imbalance`/`spread` z
`l2_imbalance_frame` (osobny strumień Silver, wymagałby własnego
as-of alignmentu) — ta sama dyscyplina "jeden ugruntowany pomysł, nie
stos kilku" co w Cyklu 42.

**Pierwsza prawdziwa wielorodzinna zgoda/konflikt w historii repo:**
nowy `tests/unit/test_evidence_integration.py` łączy OBA producenty
(derivatives + order-flow) w jedno wywołanie `evaluate_directional_setup`
— gdy się zgadzają (obie byczo potwierdzone), silnik faktycznie zwraca
`LONG` z prawdziwym `SetupLeg`; gdy się NIE zgadzają (jedna byczo, druga
niedźwiedzio, obie potwierdzone we własnych rodzinach), silnik faktycznie
zwraca `WAIT` z `CONFLICTING_INDEPENDENT_FAMILIES` — dokładnie reguła z
sekcji 10.2 master planu ("Conflicting high-quality families normally
produce WAIT"), zweryfikowana działającym kodem, nie tylko
zacytowana.

**Naprawiony błąd we własnym teście integracyjnym (nie w kodzie
produkcyjnym), znaleziony przez faktyczne uruchomienie:** pierwsza
wersja fixture'a dla konfliktu wymusiła `trade_delta` zawsze dodatnie
niezależnie od kierunku ceny — dla przypadku niedźwiedziego (`final_return
< 0`) dawało to SPRZECZNY (nie potwierdzony) sygnał order-flow (score=0),
więc drugi test dostawał `LONG` zamiast oczekiwanego `WAIT` (tylko jedna
rodzina faktycznie głosowała). Naprawiono przez warunkowe ustawienie
znaku `delta[-1]` zgodnie z kierunkiem `final_return`, tak żeby fixture
faktycznie reprezentował "obie rodziny potwierdzone we własnym kierunku,
ale przeciwstawne kierunki" — dokładnie to, co test miał testować. Drugi
napotkany i naprawiony problem: pierwsza wersja fixture'ów użyła
niezależnych zakresów dat dla obu rodzin (godzinowe świece derivatives
vs. minutowe trade_flow, każde zaczynające się od tej samej daty startowej
ale kończące się w zupełnie różnych momentach) — powodowało to fałszywe
`STALE_OR_LOW_QUALITY_EVIDENCE` (jedna rodzina "z przyszłości" względem
drugiej, poza `maximum_data_age_seconds`). Naprawiono kotwicząc oba
fixture'y do tego samego `_AS_OF` timestampu.

Walidacja: Ruff pass, Mypy pass dla 261 plików źródłowych, `1426 passed`
w Pytest (1417 + 7 nowych w `test_order_flow_evidence.py` + 2 nowe w
`test_evidence_integration.py`), `git diff --check` czyste, skan
sekretów czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian
Compose.

**Uczciwie, jak w Cyklu 42:** nadal research-stage v1, bez dowodu realnej
krawędzi na danych historycznych — to co dodano to WIĘCEJ przetestowanej,
audytowalnej infrastruktury silnika decyzyjnego, nie zwalidowana
strategia. Pozostałe 4 rodziny (`price_auction`, `volatility_options`,
`cross_market`, `regime_analog`) i `neutral.py`/`meta.py` nadal
nietknięte, każda zasługuje na tę samą dyscyplinę.

## 4qq. Cykl 44 — trzeci producent `FamilyEvidence`: `cross_market_evidence.py`

Po zielonym CI dla `a661f79` (Cykl 43, 8/8). Trzecia rodzina,
CROSS_MARKET, oparta na innym, ale równie ugruntowanym pomyśle niż
poprzednie dwie (świadomie NIE ta sama "kierunek + potwierdzenie"
struktura, bo cross-sectional rank ma inną, naturalnie już ograniczoną
[0,1] naturę) — cross-sectional rank trading: kierunek/wielkość wprost z
`cross_sectional_return_rank` (już policzone przez
`cross_market_context_frame`, Cykl 30, już ograniczone [0,1], liniowo
przemapowane na [-1,1] — najsilniejszy w danym momencie ranking = score
bliski +1, najsłabszy bliski -1), przekonanie z tego, czy
`cross_asset_return_dispersion` (też już policzone) jest aktualnie
WYSOKIE względem własnej historii (z-score lokalnie liczony,
sigmoid — dokładnie ta sama funkcja `_sigmoid` co `multidomain.py`'s
`liquidity_stress_score`, Cykl 37, nie nowy wymyślony kształt) — sygnał
rankingu jest bardziej znaczący, gdy rynek faktycznie się różnicuje, a
mniej znaczący, gdy wszystko porusza się w lockstep. Świadomie NIE
włączono `benchmark_rolling_correlation`/`benchmark_lead_correlation`/
`spot_perpetual_basis_bps` — ta sama dyscyplina co Cykle 42-43.

Testy użyły PRAWDZIWEGO `cross_market_context_frame()` (3-aktywowy panel,
nie ręcznie spreparowana ramka) — w tym dedykowany test dowodzący, że
ten sam ranking przy NISKIEJ dyspersji (wszystkie aktywa poruszają się
razem) daje faktycznie MNIEJSZY |score| niż przy WYSOKIEJ dyspersji
(jedno aktywo wyraźnie odrywa się od reszty) — mechanizm przekonania
faktycznie coś robi, nie tylko istnieje w kodzie. Wszystkie 6 testów
przeszło za pierwszym razem (bez napraw fixture'a, w przeciwieństwie do
Cyklu 43) — staranniejszy dobór danych testowych od początku.

Walidacja: Ruff pass, Mypy pass dla 262 plików źródłowych, `1432 passed`
w Pytest (1426 + 6 nowych), `git diff --check` czyste, skan sekretów
czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian Compose.

**Uczciwie, jak w Cyklach 42-43:** nadal research-stage v1, bez dowodu
realnej krawędzi na danych historycznych. Trzy z sześciu rodzin gotowe
(DERIVATIVES, ORDER_FLOW, CROSS_MARKET); pozostają `price_auction`,
`volatility_options`, `regime_analog`, oraz `neutral.py`/`meta.py`
nadal nietknięte.

## 4rr. Cykl 45 — czwarty producent `FamilyEvidence`: `price_auction_evidence.py`

Po zielonym CI dla `bc282d7` (Cykl 44, 8/8). Czwarta rodzina,
PRICE_AUCTION — dosłowne znaczenie nazwy z sekcji 10.2 master planu
("price structure and auction"): klasyczna teoria auction market
(Market Profile, Steidlmayer) — zamknięcie POWYŻEJ value area (VAH) =
akceptacja wyższych cen, sygnał byczy; PONIŻEJ (VAL) = niedźwiedzi;
WEWNĄTRZ value area = rynek nadal w równowadze, score dokładnie 0 (nie
mała niezerowa liczba udająca kierunek). W przeciwieństwie do Cykli
42-43 (osobna seria kierunku + osobna seria potwierdzenia), teoria
auction daje OBA z JEDNEJ wielkości (odległość `close` od VAH/VAL jako
ułamek szerokości value area, tanh-bounded — ta sama normalizacja co
`poc_distance`/`value_area_width` w `build_feature_matrix`, Cykl 27) —
nie ma tu drugiej, niezależnej serii do bramkowania.

`rolling_volume_profile_frame`'s (Cykl 27) własne wyjście NIE ma `close`
ani `max_source_timestamp` — funkcja przyjmuje więc ramkę PRZYGOTOWANĄ
przez wywołującego (`timestamp`/`poc`/`vah`/`val`/`close`, as-of
połączone z własnym OHLCV), ten sam "wywołujący buduje dokładny wymagany
kształt" wzorzec co każdy inny most od Cyklu 26. `timestamp` samo
traktowane jako `max_source_timestamp_utc` (ta sama zasada "klines SĄ
źródłem" co przy `momentum_flow`, Cykl 28), bo `rolling_volume_profile_
frame`'s własny `timestamp` już koduje prawdziwe źródło danych z
przetworzonych transakcji.

Walidacja: Ruff pass, Mypy pass dla 263 plików źródłowych, `1440 passed`
w Pytest (1432 + 8 nowych, w tym dedykowany test na degenerate value
area — `vah<=val` — zwracający `None` zamiast dzielenia przez zero/
ujemną szerokość), `git diff --check` czyste, skan sekretów czysty
(kosmetyczny diff odrzucony jak zawsze), bez zmian Compose.

**Uczciwie, jak w Cyklach 42-44:** nadal research-stage v1. Cztery z
sześciu rodzin gotowe (DERIVATIVES, ORDER_FLOW, CROSS_MARKET,
PRICE_AUCTION); pozostają `volatility_options`, `regime_analog`, oraz
`neutral.py`/`meta.py` nadal nietknięte.

## 4ss. Cykl 46 — piąty producent `FamilyEvidence`: `regime_analog_evidence.py`

Po zielonym CI dla `0dc3967` (Cykl 45, 8/8). Piąta rodzina,
REGIME_ANALOG, oparta na Cyklu 38's `find_historical_analogs` —
w przeciwieństwie do poprzednich czterech, ta rodzina ma już WŁASNĄ,
dedykowaną maszynerię jakości/przyczynowości (`minimum_neighbors`,
`maximum_distance`, `minimum_quality_score`, nienakładające się na
siebie sąsiedztwa, werdykt `is_meaningful`/`warning`) — najbardziej
obronny wybór v1 to bezpośrednie ponowne użycie TEGO werdyktu, zamiast
wymyślania równoległego: `is_meaningful=False` → `None` (zaufanie
własnemu osądowi `find_historical_analogs`, nie podważanie go). Kierunek/
wielkość wprost z `AnalogDistribution.positive_probability` (już
ograniczone [0,1] — dosłowny empiryczny win-rate wśród wybranych
historycznych analogów) przemapowane liniowo na [-1,1]. `confidence`
skaluje się z `sample_size` względem `confidence_full_sample_size`
(domyślnie 20) — więcej precedensów historycznych = większa pewność
statystyczna, mechaniczna, nie-tradingowa miara.

Testy PONOWNIE UŻYŁY dokładnie tego samego rzeczywistego potoku
(`build_feature_matrix` + `classify_regimes` + `find_historical_analogs`),
który `test_analogs_bridge.py` (Cykl 38) już udowodnił dający
`is_meaningful=True` — zamiast ręcznie preparować `HistoricalAnalogResult`,
test faktycznie przechodzi przez całą realną maszynerię przyczynowości
tej rodziny. Wszystkie 6 testów przeszło za pierwszym razem.

Walidacja: Ruff pass, Mypy pass dla 264 plików źródłowych, `1446 passed`
w Pytest (1440 + 6 nowych), `git diff --check` czyste, skan sekretów
czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian Compose.

**Uczciwie, jak w Cyklach 42-45:** nadal research-stage v1. Pięć z sześciu
rodzin gotowe (DERIVATIVES, ORDER_FLOW, CROSS_MARKET, PRICE_AUCTION,
REGIME_ANALOG); pozostaje tylko `volatility_options` (Cykl 36's
`options.py`, wymaga jeszcze mniej mechanicznego mapowania niż inne —
bogata, zagnieżdżona struktura `OptionSurfaceSnapshot`/
`OptionExpiryFeatures`, wymaga decyzji które pola per-expiry
zagregować) oraz `neutral.py`/`meta.py` nadal nietknięte.

## 4tt. Cykl 47 — szósty i ostatni producent `FamilyEvidence`: `volatility_options_evidence.py` + kapsztonowy test 6 rodzin naraz

Po zielonym CI dla `8094a28` (Cykl 46, 8/8). Szósta i ostatnia rodzina,
VOLATILITY_OPTIONS, oparta na Cyklu 36's `build_option_surface_snapshot`
— 25-delta risk reversal (`call_25d_iv - put_25d_iv`, już policzone przez
`options.py`), STANDARDOWY, podręcznikowy kierunkowy odczyt skew na
biurkach FX/vol: dodatni risk reversal = calle droższe niż puty = rynek
płaci za ekspozycję na górę = byczy skew; ujemny = niedźwiedzi.
Znormalizowane przez `atm_iv` tej samej ekspiracji (żeby dana liczba
punktów zmienności znaczyła to samo niezależnie od tego, czy otoczenie
ma IV=20 czy IV=80), tanh-bounded. Użyta TYLKO najbliższa ekspiracja
(`snapshot.expiries[0]`) — tam koncentruje się krótkoterminowy sygnał
kierunkowy z rynku opcji, ta sama dyscyplina "jeden pomysł" co poprzednie
pięć. `confidence` = `accepted_quote_count / (accepted+rejected)` —
własny wskaźnik przejścia bramek jakości powierzchni, mechaniczny, nie
wymyślony. Zwraca `None`, gdy `risk_reversal_25d is None` (za mało
pokrycia 25-delta call/put — na żywo w Cyklu 36 zdarzało się to często
przy wąskim near-ATM wyborze instrumentów).

Testy ponownie użyły dokładnie tego samego fixture'a `OptionQuote`/
`build_option_surface_snapshot`, co istniejący
`tests/unit/test_options_features.py` — nie wymyślono nowego.

**Kapsztonowy test, `test_full_evidence_integration.py`:** wszystkie
SZEŚĆ rodzin, każda zbudowana z WŁASNEJ prawdziwej funkcji źródłowej
(nie ręcznie sklejonych `FamilyEvidence`), połączone w JEDNO wywołanie
`evaluate_directional_setup` z PRAWDZIWYMI domyślnymi progami silnika
(`DirectionalEngineConfig()` — `minimum_confirming_families=3`,
`family_vote_threshold=0.25`, bez sztucznego obniżania) po raz pierwszy —
faktyczna decyzja `LONG` z realnym `SetupLeg`, `len(decision.evidence)
== 6`. Jedyny poluzowany parametr configu: `maximum_data_age_seconds`
(rozszerzony), bo sześć syntetycznych fixture'ów ma naturalnie różną
granularność czasową (godzinowe świece derivatives, minutowe bucket'y
trade-flow, kwotowania opcji, zapytania historical-analog) — realny
system produkcyjny zbierałby to niemal jednocześnie, test celowo
izoluje TO co faktycznie sprawdza (czy sześć niezależnie zbudowanych
dowodów łączy się poprawnie pod realnymi progami głosowania), a nie
sztuczną niezgodność czasową fixture'ów. Przeszedł za pierwszym razem.

Walidacja: Ruff pass, Mypy pass dla 265 plików źródłowych, `1451 passed`
w Pytest (1446 + 5 nowych), `git diff --check` czyste, skan sekretów
czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian Compose.

**Uczciwie: co to WSZYSTKO (Cykle 42-47) NIE jest.** Żadna z sześciu reguł
scoringu nie przeszła przez OOS/Monte Carlo/promotion gates — zero dowodu
realnej krawędzi (edge) na danych historycznych. To co powstało: w pełni
audytowalna, w pełni przetestowana (włącznie z prawdziwym
sześcio-rodzinnym end-to-end) infrastruktura silnika decyzyjnego, która
BYŁA CAŁKOWICIE NIEOSIĄGALNA przed Cyklem 42 (zero linii kodu w repo
kiedykolwiek produkowało `FamilyEvidence`). `neutral.py`/`meta.py` nadal
nietknięte — `evaluate_neutral_opportunity` potrzebowałby innego kształtu
evidence (funding/basis capture, nie kierunkowy score), `meta.py`
konsumuje już gotowe `SetupDecision`, nie surowe evidence, więc mogłoby
być następnym naturalnym krokiem, gdyby ktoś zdecydował się kontynuować
tę linię pracy. Prawdziwa empiryczna walidacja dowolnej z sześciu reguł
(backtest na rzeczywistych danych historycznych przez istniejącą
infrastrukturę Monte Carlo/walk-forward) pozostaje właściwym następnym
krokiem badawczym, nie czymś do zrobienia autonomicznie bez dostępu do
prawdziwego, długiego datasetu i decyzji strategicznych, które to
wymaga.

## 4uu. Cykl 48 — uczciwa empiryczna weryfikacja sygnałowa: DERIVATIVES i CROSS_MARKET pokazują BRAK/MIESZANĄ krawędź na realnych danych

Po zielonym CI dla `a92d15e` (Cykl 47; status CI tego konkretnego
commitu nie zawsze dało się natychmiast potwierdzić przez API z powodu
wyczerpania niezalogowanego limitu 60 req/h — jak wcześniej w Cyklu
33/37, walidacja lokalna ruff/mypy/pytest była czysta przed commitem,
więc kontynuowano bez czekania na reset). Sekcja 4tt/Cykl 47 zakończyła
się notatką: "prawdziwa empiryczna walidacja... pozostaje właściwym
następnym krokiem badawczym". Zamiast dalej to odkładać, wykonano
pierwszy realny test — pobrano prawdziwe dane Bybit (`scripts/
download_data.py` dla BTC/ETH/SOL klines 1h, `scripts/
download_funding_oi.py` dla funding+OI, styczeń-czerwiec 2024, publiczny
REST, zero interakcji z żywym collectorem) i policzono Information
Coefficient (korelacja Spearmana score vs. zwrot naprzód) oraz hit-rate
dla dwóch reguł: DERIVATIVES (Cykl 42) i CROSS_MARKET (Cykl 44).

**Wynik, w pełni uczciwie zaraportowany (żadnego dostrajania po
zobaczeniu wyników — sekcja 11.3 master planu: "publish negative results
... prevent repeated mining of rejected variants"):**

DERIVATIVES (BTCUSDT, n≈3600 barów 1h): IC UJEMNE na krótkich
horyzontach — horizon=1: IC=-0.0417, horizon=4: IC=-0.0328, horizon=24:
IC=-0.0140. Hit-rate wśród "potwierdzonych" barów (|score|>0.1):
46.4% / 47.2% / 50.5% — GORZEJ niż rzut monetą na najkrótszym
horyzoncie. Oznacza to, że hipoteza "OI potwierdza ruch → kontynuacja"
NIE działa tak jak zakładano na tej próbce — jeśli cokolwiek, występuje
SŁABY efekt mean-reversion na 1-4 godziny, przeciwny do zakładanego
kierunku.

CROSS_MARKET (BTC wśród BTC/ETH/SOL, n≈3600): IC SŁABE i niespójne
— horizon=1: IC=+0.0218, horizon=4: IC=-0.0062, horizon=24: IC=+0.0224
(bez bramki dyspersji: +0.0331). Wartości |IC|<0.03 są w praktyce
nieodróżnialne od szumu na próbce tej wielkości — brak jasnego,
solidnego sygnału w żadną stronę.

**Ważne zastrzeżenia metodologiczne, jawnie udokumentowane w skryptach:**
brak prawdziwej historii `mark_price`/`index_price` Bybit pobranej w tym
projekcie — użyto `close` ze świec jako proxy dla obu (uzasadnione dla
płynnego BTCUSDT, ale nie identyczne z prawdziwym mark price); jedna
próbka ~5-miesięczna (styczeń-czerwiec 2024, w większości hossa) — nie
uogólnia się automatycznie na inne reżimy/okresy; brak kosztów
transakcyjnych/poślizgu w tym sprawdzeniu (to sam sygnał, nie backtest
strategii); brak formalnej rejestracji hipotezy/OOS split przez
`src/research/` (Experiment Factory) — to lekki, nieformalny sanity
check, nie formalna ścieżka promocji.

Nowe, PRZYDATNE NA PRZYSZŁOŚĆ narzędzia badawcze (nie jednorazowy
skrypt-śmieć): `scripts/evaluate_derivatives_evidence_signal.py`,
`scripts/evaluate_cross_market_evidence_signal.py` — sparametryzowane
(symbol/uniwersum, zakres dat, okna), z jasno udokumentowanymi
ograniczeniami we własnych docstringach, gotowe do ponownego uruchomienia
na innych okresach/symbolach przez kogokolwiek kto kontynuuje tę linię
pracy.

Walidacja: Ruff pass, Mypy pass dla 267 plików źródłowych, `1456 passed`
w Pytest (1451 + 5 nowych — walidacja argumentów obu nowych skryptów;
sam sygnałowy check uruchomiony ręcznie na żywo, nie w automatycznym
teście, bo wymaga pobranych danych rynkowych), `git diff --check`
czyste, skan sekretów czysty (kosmetyczny diff odrzucony jak zawsze),
bez zmian Compose.

**Co to oznacza dla dalszej pracy:** DERIVATIVES i CROSS_MARKET (Cykle
42, 44) w obecnej postaci v1 NIE mają zweryfikowanej dodatniej krawędzi
na tej próbce — jeśli ktoś kontynuuje tę linię pracy, następny krok to
NIE dostrajanie formuł do tej jednej próbki (dokładnie to, przed czym
ostrzega sekcja 13 master planu — "confirmation thresholds and weights
are fit without access to holdout data"), tylko albo (a) formalna
rejestracja i test na szerszym, wielookresowym datasecie przez
`src/research/`, albo (b) świadome przeformułowanie hipotezy (np.
DERIVATIVES jako sygnał mean-reversion zamiast confirmation — realna,
przeciwna hipoteza, którą te same dane by testowały) jako NOWY,
zarejestrowany eksperyment, nie edycja tego samego kodu aż wyniki się
poprawią. Pozostałe cztery reguły (ORDER_FLOW, PRICE_AUCTION,
REGIME_ANALOG, VOLATILITY_OPTIONS) nie zostały jeszcze sprawdzone
empirycznie — wymagałyby danych, których to repo-only środowisko nie ma
pobranych (realne L2/trade/opcje historyczne).

## 4vv. Cykl 49 — trzeci uczciwy sygnałowy sanity-check: REGIME_ANALOG, niespójny/szumowy na tej próbce

Po zielonym CI dla `9a2eff5` (Cykl 48; GitHub API rate limit ponownie
wyczerpany podczas próby potwierdzenia — użytkownik zapytał wprost, co
z tym zrobić; wyjaśniono, że to nie blokuje żadnej realnej pracy
(commit/push idą przez `git`, nie REST API), zaproponowano opcjonalny
token, użytkownik odpowiedział "ok kontynuuuj" bez podawania tokena —
kontynuowano z domyślnym podejściem: walidacja lokalna jako realna
brama, sprawdzanie CI oportunistycznie, nie po każdym pushu).

Trzecia (z sześciu) reguła sprawdzona empirycznie na tych samych realnych
danych Bybit (styczeń-czerwiec 2024): REGIME_ANALOG (Cykl 46). W
przeciwieństwie do DERIVATIVES/CROSS_MARKET (Cykl 48), `find_historical_
analogs` to funkcja PUNKTOWA (jedno wywołanie = jedno zapytanie,
ponownie skanujące wszystkich dotychczasowych kandydatów) — sprawdzenie
KAŻDEGO bara byłoby zbyt kosztowne obliczeniowo, więc nowy `scripts/
evaluate_regime_analog_evidence_signal.py` chodzi po historii co
`--stride` barów (domyślnie 24 = raz dziennie na świecach 1h),
jawnie udokumentowany kompromis między czasem wykonania a mocą
statystyczną (mniejsza próbka niż wektoryzowane sprawdzenia z Cyklu 48).

**Wynik, ponownie w pełni uczciwie zaraportowany, bez dostrajania:**
horizon=1: IC=+0.0587 (hit-rate 55.9%, n=148); horizon=4: IC=-0.1025
(hit-rate 43.8%, n=147); horizon=24: IC=+0.1346 (hit-rate 50.5%, n=134).
Znak IC ODWRACA SIĘ między horyzontami, a wielkości próbek (n≈130-150,
rząd wielkości mniejszy niż wektoryzowane sprawdzenia DERIVATIVES/
CROSS_MARKET z n≈3600) są zbyt małe, by odróżnić te odczyty od szumu —
niespójny wzorzec między horyzontami przy tak małej próbce jest
klasycznym sygnałem "brak solidnego, wiarygodnego efektu", nie odkryciem
czegokolwiek użytecznego. Ta sama uczciwa, nie-dostrajająca postawa co
Cykl 48: zaraportowano dokładnie to, co wyszło, bez prób "poprawienia"
wyniku.

Walidacja: Ruff pass, Mypy pass dla 268 plików źródłowych, `1459 passed`
w Pytest (1456 + 3 nowe — walidacja argumentów skryptu), `git diff
--check` czyste, skan sekretów czysty (kosmetyczny diff odrzucony jak
zawsze), bez zmian Compose.

**Podsumowanie stanu empirycznej weryfikacji po Cyklu 49 (3 z 6 reguł
sprawdzone):** DERIVATIVES — ujemne IC na krótkich horyzontach, słaby
mean-reversion zamiast zakładanej kontynuacji. CROSS_MARKET — słabe,
niespójne IC, nieodróżnialne od szumu. REGIME_ANALOG — niespójne,
zmieniające znak IC przy małej próbce, także nieodróżnialne od szumu.
**Żadna z trzech sprawdzonych reguł nie pokazuje solidnej, wiarygodnej
dodatniej krawędzi na tej jednej ~5-miesięcznej próbce BTCUSDT/ETH/SOL z
2024.** ORDER_FLOW, PRICE_AUCTION, VOLATILITY_OPTIONS pozostają
empirycznie niesprawdzone — każda wymaga realnych danych L2/trade/opcji
historycznych, których to repo-only środowisko nie ma pobranych (Bybit/
Deribit REST nie oferuje głębokiej historii L2/trade tape, tylko obecny
stan/ostatnie transakcje — potrzebny byłby żywy collector działający
przez dłuższy czas, poza zakresem repo-only pracy).

## 4ww. Cykl 50 — `neutral.py` osiągalny: `evaluate_neutral_opportunity` z prawdziwym DERIVATIVES + CROSS_MARKET evidence

Po zielonym CI dla `4c3df8a` (Cykl 49-docs). Użytkownik zapytał wprost:
"a co według planu powinieneś teraz robić?" — sprawdzono checkpoint
Phase 7 master planu (`docs/GREENFIELD_V2_MASTER_PLAN.md`), który jawnie
stwierdza: "live portfolio wiring and Neutral/Arbitrage engine remain
TARGET STATE" — jedyny konkretnie nazwany, jeszcze nieukończony element
tej fazy. Sprawdzenie `src/engines/neutral.py`'s `evaluate_neutral_
opportunity`'s `_rejection_reason` ujawniło coś ważnego: `required_
families = {ConfirmationFamily.DERIVATIVES, ConfirmationFamily.
CROSS_MARKET}` — DOKŁADNIE te dwie rodziny, dla których producenci
evidence już istnieją (Cykle 42, 44). W przeciwieństwie do Directional
Engine (Cykle 42-47, sześć NOWYCH reguł scoringu), wpięcie Neutral
Engine jest CZYSTO MECHANICZNE — zero nowej logiki scoringu, tylko
złożenie już istniejących, już zwalidowanych producentów evidence w
`NeutralOpportunityRequest`.

Nowy plik: `tests/unit/test_neutral_evidence_integration.py` — realny
`derivatives_family_evidence()` + `cross_market_family_evidence()`
(te same funkcje z Cykli 42/44, real dane syntetyczne jak w Cyklu 43)
podane do prawdziwego `evaluate_neutral_opportunity()` — daje faktyczną
decyzję `ARBITRAGE` z dwiema nogami (`SetupLeg` BUY na bybit, SELL na
okx) i `reason_codes=("BOUNDED_CROSS_EXCHANGE_FUNDING_APPROVED",)`.
Pozostałe pola (`NeutralCostBreakdown`/`NeutralInventoryState`/
`NeutralStressBounds`/`LegExecutionPolicy`) to operacyjny stan
(zdrowie venue, margines, dostępność pożyczki) — nie coś wywodzone z
danych rynkowych, więc test używa realistycznych wartości placeholder,
ta sama konwencja co istniejący `tests/unit/test_neutral_engine.py`.

**Naprawiony błąd znaleziony przez faktyczne uruchomienie (nie w kodzie
produkcyjnym):** `FamilyEvidence.max_source_timestamp_utc` to zwykły
`datetime.datetime`, nie `pd.Timestamp` — `latest_source +
pd.Timedelta(seconds=1)` daje już `datetime.datetime` (pandas
poprawnie dodaje Timedelta do datetime), więc `.to_pydatetime()` na tym
wyniku rzucał `AttributeError`. Naprawione przez `datetime.timedelta`
zamiast `pd.Timedelta` i usunięcie zbędnego `.to_pydatetime()`.

Walidacja: Ruff pass, Mypy pass dla 268 plików źródłowych, `1460 passed`
w Pytest (1459 + 1 nowy), `git diff --check` czyste, skan sekretów
czysty (kosmetyczny diff odrzucony jak zawsze), bez zmian Compose.

**Uczciwie:** to POTWIERDZA, że architektura jest osiągalna i spójna
(Neutral Engine naprawdę współdzieli evidence z Directional, jak
projekt to przewidywał), NIE że sama okazja arbitrażowa jest empirycznie
zwalidowana — `expected_gross_edge_bps`/koszty/stresy w tym teście to
nadal placeholder, nie realne dane z dwóch giełd jednocześnie. `meta.py`
(konsumuje już gotowe `SetupDecision`, nie surowe evidence) pozostaje
jedynym nietkniętym elementem `src/engines/`.

## 4xx. Cykl 51 — stabilizacja CI i przenośności testów

- Asercja błędu CLI dla assetu spoza `--universe` normalizuje teraz ANSI i
  whitespace. Zachowuje kontrolę niezerowego kodu wyjścia i znaczenia błędu,
  ale nie zależy od szerokości terminala ani zawijania Rich/Typer na runnerze
  GitHub Actions.
- Test uprawnień `ShadowWorkStore` zachowuje ścisłe wymaganie `0440` na
  Linux/VPS, a na Windows sprawdza reprezentowalny przez ten system tryb
  read-only `0444`.
- Walidacja lokalna: Ruff pass, Mypy pass (206 plików), pełny Pytest
  `1457 passed, 3 skipped`, `git diff --check` pass.
- Brak zmian w workflow, runtime, collectorach, VPS, PAPER/SHADOW/LIVE.

## 4yy. Cykl 52 — spójny timing i symetryczna selekcja opcji Deribit

- Jeden kontrakt timingowy współdzielony przez collector i feature pipeline:
  domyślny polling 300 s, 60 s jawnego marginesu na batch/opóźnienie oraz
  maksymalny wiek quote 360 s. Krótsze okno wymaga jawnego research override.
- `select_near_atm_option_instruments` wybiera teraz osobno N najbliższych
  strike'ów poniżej i N powyżej underlying, z jednym dokładnym ATM na każde
  option right. Wynik jest deterministyczny i deduplikowany.
- Komentarz Compose podaje rzeczywiste maksimum 44 ticker calls przy
  domyślnej konfiguracji. Profil nadal jest wyłączony i nic nie zostało
  wdrożone na VPS.
- Dodane testy granicy świeżości, jawnego override, asymetrycznej siatki,
  dokładnego ATM, deduplikacji i niepoprawnego interwału pollera.

## 4zz. Cykl 53 — empiryczny gate zależności confirmation families

- Nowy point-in-time audit mierzy bezwzględną korelację Spearmana dla każdej
  pary rodzin: pełna próbka, rolling windows oraz osobne reżimy. Silna
  korelacja odwrotna także oznacza zależność, nie niezależne potwierdzenie.
- Wynik jest wersjonowanym JSON artifactem o statusie `PASS`, `FAIL` albo
  `INSUFFICIENT_DATA`. Dane przyszłe są odrzucane, a mała próbka blokuje
  promocję zamiast domyślnie przechodzić.
- Progi znajdują się w `configs/confirmation_independence.yaml`; opisują
  wykrywanie duplikacji informacji, nie dowód trading edge.
- `PromotionRegistry.promote_multi_family_to_challenger` wymaga raportu
  `PASS` obejmującego wszystkie deklarowane rodziny. Zwykłe, jednorodzinne
  strategie zachowują dotychczasową ścieżkę promocji.
- Testy obejmują niezależne szeregi, silną zależność dodatnią i odwrotną,
  małą próbkę, zależność tylko w jednym reżimie, future-data guard oraz
  fail-closed promotion path.

## 4aaa. Cykl 54 — point-in-time market adapter dla Neutral Engine

- Usunięto z integracji Neutral Engine sztuczne okno świeżości
  `10_000_000` sekund. Evidence ma wspólny cutoff i przechodzi prawdziwy
  domyślny limit 30 s.
- `neutral_market.py` wylicza gross cross-exchange funding edge z
  jednoczesnych executable bid/ask, różnicy funding oraz jawnej niepewności
  modelu. Capacity jest minimum dostępnej pojemności obu nóg.
- Future/stale quotes, różne symbole, ta sama giełda i niepoprawna
  konfiguracja są odrzucane. Fees, exit spread, slippage, borrow i orphan-leg
  risk pozostają jawnie w `NeutralCostBreakdown`, poza gross edge.
- To nadal research adapter, nie live portfolio wiring i nie zgoda na
  ARBITRAGE/PAPER/LIVE. Brak kwotowań ma kończyć się WAIT u przyszłego
  runtime callera.

## 4bbb. Cykl 55 — crash-safe mutable Parquet partitions

- Wspólny `merge_atomic_parquet` zabezpiecza mutable REST datasets Binance,
  OKX i Deribit: cross-platform exclusive lock, deterministyczny merge/
  dedup, plik tymczasowy w tym samym filesystemie, fsync oraz atomic replace.
- Awaria przed replace pozostawia poprzedni poprawny Parquet i usuwa plik
  tymczasowy. Współbieżne writery nie tracą wzajemnie rekordów.
- Podłączone magazyny: Binance/OKX klines, Binance/OKX derivatives, Deribit
  market summary i Deribit option ticker. Immutable Bronze raw store nie był
  zmieniany.
- Testy obejmują symulowaną awarię zapisu, 20 współbieżnych writerów,
  deterministyczny replay oraz wszystkie istniejące round-trip storage tests.

## 4ccc. Cykl 56 — per-symbol instrument realism BTC/ETH/SOL

- Zastąpiono wspólne, zbyt drobne gridy osobnymi snapshotami instrumentów
  Bybit, Binance i OKX dla BTC/ETH/SOL. Każdy symbol ma własny tick size,
  quantity step, precision i jawny contract multiplier.
- Snapshot zawiera publiczny endpoint źródłowy i datę pobrania 2026-08-24.
  Parametry zweryfikowano przez publiczne instrument-info/exchangeInfo;
  fee tier nadal jest udokumentowanym non-VIP defaultem.
- OKX zachowuje zarówno `ctVal`, jak i efektywny base quantity increment
  (`lotSz * ctVal`) wymagany przez model `CryptoPerpetual`.
- `validate_order_grid` odrzuca ceny i ilości, których dana giełda nie
  przyjęłaby. Testy obejmują różnice BTC/SOL oraz end-to-end Bybit/Binance/OKX.

## 4ccd. Cykl 57 — Linux CI portability atomic Parquet lock

- CI dla Cyklu 55 ujawniło błąd typowania niewidoczny na Windows: Mypy na
  Linux analizował odwołania do Windowsowego `msvcrt` w lokalnym closure.
- Locking rozdzielono na platformowe implementacje wybierane przez
  `sys.platform`, bez ignorowania błędów typów. Jawnie zweryfikowano oba cele
  przez `mypy --platform win32` i `mypy --platform linux` oraz testy atomiczne.

## 4cce. Cykl 58 — lineage-aware point-in-time joins

- Wspólny kontrakt as-of dla feature i regime pipeline uwzględnia teraz nie
  tylko czas zdarzenia, lecz również `max_source_timestamp`, czyli moment
  faktycznej dostępności całej informacji źródłowej.
- Opóźniony stary event nie może cofnąć już obserwowalnego nowszego stanu;
  niejednoznaczne duplikaty i nieważne timestampy failują zamiast zgadywać.
- Testy pokrywają delayed arrival, late-old event, future invariance,
  stabilność przy podziale decyzji na chunki, legacy source oraz faktyczne
  użycie kontraktu przez `build_feature_matrix`.

## 4ccf. Cykl 59 — trwały producent MetaDecision → SHADOW

- `ShadowDecisionProducer` uruchamia Meta Engine nad research-approved
  kandydatami, mapuje wybrany setup jeden-do-jednego na propozycje Portfolio
  Risk i zapisuje immutable `ShadowWork` przed idempotentnym enqueue.
- Globalny kill switch i wszystkie WAIT-y pozostają trwałymi decyzjami bez
  propozycji. Brak pełnej korelacji dla wielu symboli zmienia wynik na WAIT.
- Producent nie importuje execution adaptera. Testy obejmują pełne
  producer→store→queue→event-loop przekazanie, restart/redelivery, konflikt
  idempotency, global risk gate oraz zbalansowane wielonożne ARBITRAGE.

## 4ccg. Cykl 60 — Directional evidence → Meta → trwały SHADOW i kontrakt UI

- `DirectionalShadowSnapshot` jest wersjonowanym, immutable wejściem z
  identyfikatorami obserwacji/kandydata, pełnym `ShadowSessionContext`,
  point-in-time `DirectionalSetupRequest`, stanem portfela, zgodą research,
  equity i czasem produkcji.
- `DirectionalShadowOrchestrator` łączy sześć niezależnych rodzin evidence z
  Directional Engine, Meta Engine i istniejącym trwałym producentem SHADOW.
  Nie ma adaptera wykonawczego. Niezgodny kontekst, future evidence,
  nieobsługiwana wersja, błędny zegar lub produkcja po limicie świeżości
  failują przed enqueue; gate promocji i brak zgody research dają `WAIT`.
- Test integracyjny dowodzi pionowej ścieżki sześć rodzin → `LONG` → Meta →
  immutable store → durable queue oraz zachowania WAIT/fail-closed.
- `docs/OPERATOR_UI_SPEC.md` ustala kontrakt przyszłego read-only API i panelu
  operatorskiego: status collectorów i data quality, ATAS/MC, derivatives,
  options, regimes/analogs, decyzje, research, SHADOW/PAPER, risk i audit.
  Nie zawiera endpointów wykonawczych ani LIVE i nie zastępuje Grafany.

## 4cch. Cykl 61 — ścisły Bybit Demo gateway i trwały place/cancel PAPER smoke

- Dodano bezpośredni gateway pybit, którego host jest niekonfigurowalnie
  przypięty do `api-demo.bybit.com`. Nie czyta kluczy mainnet i odrzuca klienta
  wskazującego inny endpoint.
- Read-only preflight sprawdza API key, portfel, pozycje i otwarte zlecenia,
  ale dodatkowo wymusza write-capable Contract Order/Position, brak uprawnień
  innych niż obowiązkowe, dokładnie zdefiniowane bundle Unified Trading
  (`Spot`/`Derivatives`/`Options`) oraz nazwaną whitelistę IP. Uprawnienia
  asset/wallet/transfer nadal failują; raport jest sanitizowany.
- `DemoPaperCoordinator` mapuje wyłącznie risk-approved Bybit BTC/ETH/SOL
  proposal na mały Limit/PostOnly w Demo. Przed siecią zapisuje trwałe
  `SUBMITTED`; restart/niejednoznaczny timeout nigdy nie wysyła drugi raz tego
  samego zlecenia. Execution IDs, partial fills, fees, adverse slippage oraz
  potwierdzone cancel/reject są rekonsyliowane do SQLite WAL.
- Operator ma osobny read-only `scripts/bybit_demo_preflight.py` oraz jawnie
  uzbrajany `scripts/bybit_demo_smoke_order.py`; ten drugi wymaga dokładnego
  `GREENFIELD_DEMO_ORDER_CONFIRMATION=BYBIT_DEMO_ONLY`, stabilnego request ID,
  maksymalnie 250 wirtualnych USDT i pasywnej ceny. Szczegóły w
  `docs/BYBIT_DEMO_RUNBOOK.md`.
- Nie uruchomiono żadnego zlecenia podczas implementacji. To tor Demo/PAPER,
  nie LIVE, nie obejmuje kapitału i nie stanowi promocji żadnej strategii.

## 4cci. Cykl 62 — recovery-safe BTC Demo 100 USDT / 100x round-trip

- Dodano osobny, operator-only koordynator i CLI dla jednorazowego testu
  infrastruktury na wirtualnych środkach Bybit Demo: około 100 USDT notional
  BTCUSDT przy ustawionym 100x, Market BUY, następnie Market SELL dokładnie
  faktycznej pozycji z bezwzględnym `reduceOnly=true`.
- Tor wymaga dwóch niezależnych, dokładnych potwierdzeń, endpointu wykonawczego
  `api-demo.bybit.com`, publicznych metadanych tylko z `api.bybit.com`, zerowej
  pozycji i zerowej liczby otwartych zleceń BTC przed wejściem. Rozmiar musi
  znaleźć się w przedziale 75–125 USDT; inaczej nic nie jest wysyłane.
- Obie nogi są zapisywane przed siecią w SQLite i mają deterministyczne
  `orderLinkId`. Niejednoznaczny timeout pozostaje `SUBMITTED`; ponowne
  uruchomienie z tym samym request ID wyłącznie rekonsyliuje, bez duplikacji.
  Zamknięcie może być ponowione tylko po autorytatywnym cancel/reject i zawsze
  jest reduce-only. `COMPLETE` wymaga pozycji zero na giełdzie i w PAPER ledger.
- Testy obejmują pełny BUY/close, właściwą flagę reduce-only, leverage 100,
  crash/restart bez ponownej wysyłki, oba confirmation gates, istniejącą
  ekspozycję/open orders, niemożliwy minimalny notional, hedge mode i short.
- Sam commit nie wykonuje zlecenia. Faktyczny operator-run pozostaje Demo/PAPER
  i nie stanowi promocji strategii ani zgody na LIVE.
- Pierwszy operator-run ujawnił realną eventual consistency Bybit Demo: order
  history raportował cumulative fill wcześniej niż endpoint executions. Tor
  rozpoznaje teraz ten stan osobnym `DemoExecutionLagError`, nigdy nie ponawia
  BUY i natychmiast trwałym `reduceOnly` spłaszcza autorytatywną pozycję; pełne
  `COMPLETE` nadal czeka na fills potrzebne do uzgodnienia PAPER ledger.
- Operator ponowił ten sam `btc-demo-20260824-001` po wdrożeniu poprawki.
  Wynik `COMPLETE`: BUY `0.001 BTC @ 78,893.2`, jeden SELL reduce-only
  `0.001 BTC @ 78,865.3`, 100x, około `0.08677 USDT` łącznych opłat, exchange
  position `0` i PAPER position `0`. Rzeczywisty notional około `78.9 USDT`
  wynikał z kroku `0.001 BTC` i mieścił się w ustalonej bramce 75–125 USDT.
  Jest to dowód infrastruktury Demo, nie edge i nie promocja do LIVE.

## 5. Następna zalecana kolejność prac

1. ~~Dodać immutable, checksummed `ShadowWork` store oraz loader~~ — GOTOWE
   (Cykl 1).
2. ~~Dodać proces usługi SHADOW z kontrolowanym SIGTERM, heartbeat i
   preflightem zgodności dataset/code/config fingerprint~~ — GOTOWE (Cykl 2).
   Producent MetaDecision→trwała kolejka jest GOTOWY w Cyklu 59; pozostaje
   operacyjne składanie realnych feature/evidence wejść dla tego producenta.
3. ~~Zbudować trwałą rekonsyliację PAPER order/position/fill~~ — GOTOWE
   (Cykl 3). Ścisły bezpośredni Bybit Demo place/cancel bridge GOTOWY w
   Cyklu 61; automatyczny promoted-setup→PAPER observation loop pozostaje.
4. ~~Dodać champion/challenger dashboard oraz automatyczne degradation/
   retirement gates~~ — GOTOWE (Cykl 4, silnik i dashboard gotowe; brakuje
   operacyjnego źródła baseline i scheduled evaluation loop).
5. Uruchomić failure injection i wielodniowy SHADOW/PAPER observation period.
6. Równolegle, ale bez naruszania Bybit soak, dodać osobne produkcyjne
   collectory Binance, OKX, Coinbase i Deribit. **WSZYSTKIE CZTERY GOTOWE
   do wdrożenia** (repo-only: silnik + working continuity gate + pełny
   script/config/compose wiring, Cykle 5–11 — patrz 4g/4i/4j/4k). Każdemu
   brakuje tylko tego samego operacyjnego kroku: nowego soak markera
   autoryzującego jego `collector_id` (poza zakresem repo-only pracy, wymaga
   decyzji/wdrożenia poza tym repo). Znane luki resztkowe (WS raw
   collector L2, punkt 7 niżej opisuje osobny REST-poller dla Deribit
   opcji/dated futures, GOTOWE Cykl 24): Binance `forceOrder`→Silver i
   REST-pollery OI/long-short (Cykl 10, GOTOWE — patrz punkt 7); SOL na
   Deribit świadomie wykluczony z WS L2 collectora (brak instrumentów,
   zweryfikowane na żywo).
7. Ten sam kontrakt jakości danych co Bybit dla pozostałych giełd
   (priorytet 4 master planu). **Normalizacja multi-exchange i wspólny
   canonical schema (priorytet 5) już gotowe** — `normalize_raw_lake()`
   obsługiwał wszystkie 5 giełd od przed serii cykli; `data_quality.py`
   już exchange-agnostyczny. `dataset_catalog.py` (point-in-time snapshoty)
   był Bybit-only aż do Cyklu 12 — teraz generyczny (patrz 4l). Kontrola
   miejsca na dysku (priorytet 6) — raport zajętości Bronze per giełda/
   kanał/data + wiek partycji GOTOWY (Cykl 13, patrz 4m, tylko odczyt).
   Binance `forceOrder`→Silver GOTOWE (Cykl 14, patrz 4n). Binance REST
   pollery OI/long-short GOTOWE (Cykl 17, patrz 4q — osobne moduły/
   katalogi, zero zmian w istniejącym Bybit storage.py). OKX REST pollery
   OI/long-short GOTOWE (Cykl 18, patrz 4r — ten sam wzorzec, wspólny
   `rest_poller.py`; naprawiony w Cyklu 33/4gg — goły `urllib.request`
   dostawał 403 od WAF OKX na żywym ruchu, mimo przechodzących testów z
   fake fetcherem). Coinbase świadomie pominięty dla tego wzorca
   (produkty spot, OI/long-short nie ma zastosowania). Deribit datowane
   futures/opcje/IV/skew/term-structure GOTOWE (Cykl 24, patrz 4x) — REST
   market-summary poller zamiast per-instrument WS L2 (998 BTC / 886 ETH
   aktywnych opcji na żywo zweryfikowane — pełne booki L2 byłyby
   niepraktyczne przy tej skali). Post-hoc wykrywanie luk (poza sequence
   gate'ami collectorów, które działają tylko na żywo) — `src/data/
   bybit_replay.py` (pre-istniejący), `binance_replay.py` (Cykl 20),
   `okx_replay.py` (Cykl 21), `coinbase_replay.py` (Cykl 22),
   `deribit_replay.py` (Cykl 23) — **KOMPLETNE dla wszystkich 5 giełd**,
   każdy dostępny przez `scripts/replay_raw_<exchange>.py`. Pozostaje do
   zrobienia: faktyczna retencja/archiwizacja danych — świadomie NIE
   zaimplementowana (Cykl 13), wymaga osobnej decyzji o polityce od
   użytkownika przed jakąkolwiek automatyzacją usuwania.
8. Domknąć walk-forward/OOS/Monte Carlo/bootstrap, multiple-testing controls i
   parameter-stability reports na własnym zgromadzonym datasecie. Koszty
   scenariuszowe (`adverse`/`severe`) GOTOWE (Cykl 15, patrz 4o) — `adverse`
   pozostaje jedyną bramką promocji (świadomy wybór zakresu), `severe`
   liczony jako dodatkowy, niebramkujący stress-test dla kandydatów PASSED.
   Monte Carlo moving-block bootstrap GOTOWE (Cykl 16, patrz 4p) —
   `run_monte_carlo` wspiera teraz block bootstrap obok IID, wpięty do
   cyklu workera jako dodatkowy, niebramkujący stress-test dla kandydatów
   PASSED, z poprawną (Wilson CI) reprezentacją `risk_of_ruin` przy zero
   zaobserwowanych zdarzeń. `BYBIT_VENUE` hardkodowanie GOTOWE (Cykl 25,
   patrz 4y) — `src/backtesting/instruments.py`/`engine.py`
   sparametryzowane przez `exchange` (domyślnie "bybit", zero zmian w
   zachowaniu istniejących wywołań), plus nowe, w pełni izolowane źródło
   klines dla Binance (`src/data/binance_klines_client.py`/
   `ingest_binance_klines.py`/`binance_klines_storage.py`,
   `scripts/download_binance_klines.py`) — zweryfikowane end-to-end na
   żywo (realne pobrane świece BTCUSDT + faktyczny przebieg silnika
   NautilusTrader z venue BINANCE), nie tylko testami syntetycznymi. OKX
   GOTOWE (Cykl 32, patrz 4ff) — ten sam wzorzec
   (`src/data/okx_klines_client.py`/`ingest_okx_klines.py`/
   `okx_klines_storage.py`, `scripts/download_okx_klines.py`,
   `configs/instruments_okx.yaml`), zweryfikowany testami end-to-end na
   syntetycznych danych ORAZ (Cykl 33, patrz 4gg) realnym pobraniem na
   żywo (49 świec `BTC-USDT-SWAP` 1h + faktyczny przebieg silnika
   NautilusTrader z venue OKX) — po naprawie blokady WAF OKX na domyślny
   `User-Agent` biblioteki `urllib`, która inaczej uniemożliwiłaby
   działanie tego klienta (i pollera OI/long-short z Cyklu 18) na żywym
   ruchu. Coinbase/Deribit nadal nie mają
   odpowiednika — naturalne, dobrze zdefiniowane rozszerzenie tego samego
   wzorca, nie nowy projekt (Coinbase to produkty spot, więc sensowność
   klines/perpetual-backtest jest inna niż dla Bybit/Binance/OKX).
9. Wpięcie osieroconych modułów `src/features/`/`src/regimes/` do ich
   jedynych punktów wejścia (`build_feature_matrix`,
   `find_historical_analogs`) — **GOTOWE dla wszystkiego poza
   `cross_venue.py`/`options.py`/`src/engines/`, a i te trzy mają już
   most/kolektor GOTOWY, tylko nie w pełni domknięty**. Cykle 26-31:
   order-flow/L2-imbalance (4z), volume-profile/VWAP (4aa),
   momentum-flow (4bb), derivatives-context (4cc), cross-market (4dd),
   liquidity-interaction (4ee) — wszystkie wpięte do `build_feature_
   matrix`. Cykl 34: price/CVD divergence (4hh). Cykl 35: `cross_venue.py`
   (funkcja punktowa, rozwiązana nowym walk-forward wrapperem
   `cross_venue_series_frame`, ten sam wzorzec co volume-profile).
   Cykl 36: `options.py` (dedykowany cykl — near-ATM Deribit
   option-ticker poller + `OptionQuote` bridge, bo `build_option_surface_
   snapshot` wymaga `bid_iv`/`ask_iv`/`delta`, dostępnych TYLKO z
   per-instrumentowego `/public/ticker`, nie z bulk summary Cyklu 24;
   wpięcie do `build_feature_matrix` NIE zrobione — bogatsza, zagnieżdżona
   struktura wyjścia niż cross-venue, wymaga osobnej decyzji o tym, które
   cechy skalarne wyciągnąć). Cykl 37: `classify_multidomain_regimes`
   wpięty przez nowy `multidomain_bridge.py` (wszystkie wymagane kolumny
   już dostępne z istniejących cech, zero nowej logiki obliczeniowej).
   Cykl 38: `find_historical_analogs` wpięty przez `analogs_bridge.py`
   (caller wybiera źródło regime/features, most nie narzuca). Cykl 39:
   pierwszy realny konsument — `scripts/find_historical_analogs.py`,
   zweryfikowany na żywo na realnych świecach Bybit BTCUSDT. Żadna
   strategia jeszcze nie konsumuje żadnej z tych cech w produkcji
   (świadomie odłożone — wymagałoby decyzji strategii/badawczej, nie
   mechanicznego przepięcia).
10. `src/engines/` (Setup/Directional/Neutral/Meta, warstwa decyzyjna
    nad `FamilyEvidence`/`ConfirmationFamily`) — **WSZYSTKICH SZEŚĆ
    PRODUCENTÓW EVIDENCE GOTOWYCH (Cykle 42-47, patrz 4oo-4tt)**,
    research-stage v1. Po użytkowniku wprost poleceniu "kontynuuj
    zgodnie z planem, nie pytaj mnie więcej o nic" (2026-08-24),
    ponownie oceniono wcześniejszą decyzję o nietykaniu tej warstwy —
    sekwencja promocji master planu (Research → OOS → Shadow → Paper →
    LIVE_SMALL → LIVE, sekcja 14) to WŁAŚNIE mechanizm, przez który taka
    reguła ma przejść, zanim będzie zaufana; napisanie pierwszych,
    jawnie oznaczonych "research-stage v1" reguł i przetestowanie ich
    end-to-end jest kontynuacją planu, nie skrótem go omijającym — nic z
    tego nie dotyka kapitału/PAPER/LIVE/VPS (nadal absolutnie
    nietykalne). Każda rodzina zbudowana JEDNA NA RAZ, oparta na
    dokładnie JEDNYM ugruntowanym, podręcznikowym pomyśle (OI-price
    confirmation, aggressor-flow confirmation, cross-sectional rank,
    value-area breakout, empiryczny win-rate historycznych analogów,
    25-delta risk reversal) — nigdy stos kilku interakcyjnych, słabiej
    ugruntowanych heurystyk naraz. `tests/unit/test_full_evidence_
    integration.py` (Cykl 47) dowodzi, że wszystkie sześć razem
    faktycznie działa pod PRAWDZIWYMI domyślnymi progami silnika
    (`DirectionalEngineConfig()`), nie tylko osobno.

    **Aktualizacja po Cyklach 48-49: empiryczna weryfikacja WYKONANA dla
    3 z 6 reguł, na realnych danych Bybit (BTC/ETH/SOL, styczeń-czerwiec
    2024), metodą Information Coefficient (korelacja Spearmana score vs.
    zwrot naprzód) — patrz 4uu/4vv.** DERIVATIVES: IC UJEMNE na krótkich
    horyzontach (-0.042 przy 1h), hipoteza "OI potwierdza → kontynuacja"
    NIE działa na tej próbce (słaby mean-reversion zamiast tego).
    CROSS_MARKET: IC słabe i niespójne, nieodróżnialne od szumu.
    REGIME_ANALOG: IC zmienia znak między horyzontami na małej próbce
    (n≈150), też szum. **Żadna z trzech sprawdzonych reguł nie pokazuje
    solidnej dodatniej krawędzi na tej jednej próbce.** Zgodnie z
    zasadą "nie dostrajaj do tej samej próbki" (sekcja 13 master planu),
    formuł NIE poprawiano po zobaczeniu wyników — wynik zaraportowano
    dokładnie taki, jaki wyszedł (sekcja 11.3: "publish negative
    results"). Trzy narzędzia badawcze pozostają do ponownego użycia:
    `scripts/evaluate_{derivatives,cross_market,regime_analog}_evidence_
    signal.py`. ORDER_FLOW, PRICE_AUCTION, VOLATILITY_OPTIONS pozostają
    empirycznie NIESPRAWDZONE — wymagają realnych danych L2/trade/opcji
    historycznych, których żaden publiczny REST Bybit/Deribit nie
    udostępnia masowo (tylko bieżący stan/ostatnie transakcje) —
    wymagałoby żywego collectora działającego przez dłuższy czas, poza
    zakresem repo-only pracy.

    Prawdziwy następny krok, jeśli ktoś kontynuuje tę linię: NIE
    dostrajanie tych samych formuł do tej samej próbki, tylko albo (a)
    formalna rejestracja i test na szerszym, wielookresowym/wielo-
    reżimowym datasecie przez `src/research/` (Experiment Factory), albo
    (b) świadome przeformułowanie hipotezy jako NOWY, osobno
    zarejestrowany eksperyment (np. DERIVATIVES jako mean-reversion
    zamiast confirmation — realna, przeciwna hipoteza, którą te same
    dane by przetestowały), albo (c) pobranie realnych danych L2/trade/
    opcji (wymaga decyzji o żywym collectorze/retencji, poza repo-only).
    `neutral.py`/`meta.py` nadal nietknięte — `evaluate_neutral_
    opportunity` potrzebowałby innego kształtu evidence (funding/basis
    capture, nie kierunkowy score), `meta.py` konsumuje już gotowe
    `SetupDecision`, nie surowe evidence.

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

### 4mm. Cykl 63 — realny skaner okazji Bybit dla przyszłego Demo PAPER

- Dodano `src/execution/bybit_demo_opportunity_feed.py`: publiczne, ściśle
  przypięte do `https://api.bybit.com` świece 5m, ostatnie transakcje, mark/index
  klines, OI, funding i tick size; malformed/stale/future/wrong-host fail-closed.
- Dodano `src/execution/demo_opportunity_scanner.py`: trzy niezależne rodziny
  (auction/order-flow/derivatives) trafiają do istniejącego Directional Engine.
  Oryginalny MC-like momentum/money-flow jest wyłącznie veto, nigdy dodatkowym
  głosem. Brak kompletnej rodziny, stale dane, kill switch, brak promocji lub
  brak dodatniego edge po kosztach kończy się `WAIT`.
- Dodano bezpieczny, read-only `scripts/scan_bybit_demo_opportunities.py`.
  CLI nie pozwala podać fikcyjnego statusu promocji ani oczekiwanego zysku:
  pozostaje `RESEARCH_CANDIDATE`/zero-edge i dlatego nie może złożyć zlecenia.
- Realny publiczny skan BTCUSDT wykonany 2026-08-24: wszystkie trzy rodziny
  zbudowane, wynik `WAIT`; żadnego endpointu tradingowego nie wywołano.
- Użytkownik wybrał dla docelowego Demo-only automatu `100x` i margin równy
  maksymalnie 1% aktualnego kapitału na trade. Następny cykl musi dodać trwały
  executor z jedną pozycją, reduce-only exit, dziennymi limitami i restartową
  rekonsyliacją, ale nadal nie może ominąć `PAPER_CHALLENGER`/edge artifact.

## 7. Szybkie odtworzenie i walidacja

### 4mm. Cykl 64 — deterministyczny sizing i exit envelope Demo

- `demo_autonomous_risk.py` koduje dokładnie decyzję operatora: 100x i 1%
  deployowalnego kapitału jako margin. Kapitał do sizingu jest mniejszą z
  wartości `totalEquity` i `totalAvailableBalance`; dzięki temu wykryta na Demo
  rozbieżność equity/available nie zwiększa zlecenia.
- Ilość jest zawsze zaokrąglana w dół do kroku giełdy. Domyślne zabezpieczenia
  to jedna pozycja, stop 20 bps, take profit 30 bps, maksymalnie 30 minut,
  sześć wejść na dzień UTC, cooldown 15 minut i dzienny limit straty 1%.
- Moduł nie wysyła zleceń i nie omija bramki promocji. Jest deterministycznym
  kontraktem ryzyka dla następnego trwałego executor loop.

### 4mm. Cykl 65 — tierowany wieloletni backfill BTC/ETH/SOL

- `historical_backfill.yaml` definiuje jeden jawny, ograniczony plan danych
  Bybit/Binance/OKX: 1m=180 dni, 5m=2 lata, 15m=3 lata,
  1h/4h/1d=około 5 lat oraz Bybit funding/OI zgodnie z retencją dostawcy.
- `backfill_historical_research.py` domyślnie tylko pokazuje wszystkie zadania;
  `--execute` uruchamia istniejące, walidujące i idempotentne downloadery.
  Filtry i `--max-jobs` umożliwiają etapowe wykonanie na VPS bez cichego
  rozszerzania zużycia dysku.
- REST backfill nie udaje tick/L2/liquidation/options historii. Te rodziny
  wykorzystują wyłącznie własny Bronze od startu collectorów (obecnie około
  trzech dni) i pozostają niepromowalne, dopóki nie uzbierają wymaganej próby.

### 4mm. Cykl 66 — hybrydowy input historia + Bronze + live

- `HybridBybitOpportunityFeed` łączy lokalne 5m Parquet z live REST i używa
  sprawdzonych checksumami Bronze `publicTrade` zamiast krótkiej próbki REST.
- Wymaga co najmniej trzech dat UTC, 300 transakcji i świeżości do 6 minut;
  brak historii, uszkodzony manifest/part albo stary collector kończy się
  błędem fail-closed, nie fallbackiem do słabszych danych.
- Skaner otrzymał opcjonalne `--data-dir`; nadal nie ma ścieżki składania
  zleceń ani możliwości wymuszenia promocji. L2/liquidations pozostają w
  Bronze do osobnej empirycznej walidacji ATAS-like.

### 4mm. Cykl 67 — trwały lifecycle i dzienny risk ledger Demo

- `AutonomousDemoStateStore` zapisuje observation→entry submitted→open→exit
  submitted→closed oraz `SAFETY_HOLD` w SQLite WAL z `synchronous=FULL`.
- `observation_id` daje deterministyczny `trade_id`; replay identycznego stanu
  jest bezpieczny, konflikt failuje, a druga aktywna pozycja BTC/ETH/SOL jest
  blokowana również po restarcie.
- Osobny dzienny rekord UTC utrwala startowy deployowalny kapitał, liczbę
  wejść, realized PnL, cooldown i kill switch. Limit transakcji i dzienny
  limit straty są ponownie sprawdzane atomowo podczas zapisu wejścia.
- To nadal state/risk layer bez połączenia z endpointem order submission;
  następny cykl łączy go z `DemoOrderReconciler` i zawsze reduce-only exit.

### 4mm. Cykl 68-71 — Demo ATAS/MC executor, obserwowalność i test VPS

- `DemoScalpExecutor` połączył eksperymentalny skaner ATAS-like/MC-like z
  trwałym PAPER ledgerem i wyłącznie endpointem Bybit Demo. Wejście używa
  100x oraz maksymalnie 1% deployowalnego kapitału jako margin; wyjście jest
  zawsze `reduce-only`. Obowiązują jedna pozycja, limit dzienny, cooldown,
  stop, target i 10-minutowy time exit.
- Dodano trwały, jednorazowy operator probe, atomowy `health.json`, healthcheck
  Docker/Prometheus oraz bezpieczne wznowienie po restarcie. Kod `110043`
  (dźwignia już ustawiona) jest traktowany jako idempotentny sukces; pozostałe
  błędy Bybit nadal failują.
- Walidacja przed wdrożeniem poprawki `16514a3`: Ruff i Mypy czyste, pełny
  pytest: `1569 passed, 3 skipped`; repo nie zawiera pliku z kluczami Demo.
- Commit `16514a3` jest wypchnięty na
  `origin/codex/kontynuacja-claude-code`. Feature branch i draft PR pozostają
  niescalone; `main` nie został nadpisany.

Stan operacyjny VPS na zakończenie 2026-08-24 (UTC):

- preflight Bybit Demo potwierdził właściwy endpoint i IP allowlist;
- pierwsza pełna próba BUY→SELL została zakończona `reduce-only`, a konto
  zweryfikowano jako płaskie;
- druga, jawnie wymuszona próba infrastrukturalna otworzyła LONG BTCUSDT
  `1.265 BTC` przy `100x`; brak otwartych zleceń, a
  `bybit-demo-scalper` raportował `healthy` i cykle `OPEN`;
- zapisano marker jednorazowego probe, więc po zamknięciu tej pozycji restart
  nie może ponownie wymusić wejścia;
- historyczny backfill pozostaje uruchomiony w odłączonej sesji tmux
  `greenfield-claude`; nie należy jej przerywać ani usuwać
  `historical-backfill.log` podczas pracy procesu.

Znane, jawne ograniczenia do naprawy w pierwszym następnym cyklu:

1. chwilowy lag Bybit między order history i execution feed powoduje obecnie
   restart procesu; recovery ostatecznie uzgadnia zlecenie, ale lag powinien
   zwracać trwałe `ENTRY_SUBMITTED`/`EXIT_SUBMITTED` bez tracebacku;
2. dzienny risk ledger porównuje bieżący kapitał ze startowym zbyt ściśle;
   koszty poprawnie zmieniają saldo, więc baseline powinien pozostać
   niezmiennym punktem odniesienia, a nie warunkiem równości;
3. po zamknięciu aktywnego trade brak trzech kwalifikujących się dat Bronze
   może zatrzymać skan przez `BybitOpportunityFeedError`; brak danych musi być
   publikowany jako zdrowe, fail-closed `WAIT/INSUFFICIENT_DATA`, bez pętli
   restartów. Nie wolno obniżać progu ani udawać kompletności datasetu.

Do czasu naprawienia punktów 1-3 ten deployment jest testem infrastruktury
Demo, a nie dowodem gotowości strategii ani promocją do LIVE. Realny LIVE i
realny kapitał pozostają zabronione bez nowej, osobnej autoryzacji.

### 4nn. Cykl 72 — pełna remediacja audytu bezpieczeństwa i wykonania

- Dzienne ledgery `RiskEngine` i `PortfolioRiskEngine` przesuwają dzień tylko
  do przodu. Zdarzenie z opóźnionym timestampem nie może wyzerować bieżącej
  straty; stare żądanie wejścia kończy się fail-closed.
- Kandydat badawczy utrwala teraz rodziny potwierdzeń przy rejestracji.
  Wielorodzinny kandydat nie może wejść do `PAPER_CHALLENGER` starą ścieżką bez
  raportu niezależności, a stała/nieokreślona korelacja (`NaN`) jest `FAIL`.
- Demo scalper obsługuje lag order-history/execution-feed bez restartu. Po
  częściowym i anulowanym wyjściu składa unikalne, trwałe `reduce-only` na
  resztę (maksymalnie pięć prób), sumuje wszystkie fill/cost records i przed
  zamknięciem wymaga zgodności ilości. Niezgodność kończy się `SAFETY_HOLD`.
- Preflight uprawnień jest odświeżany co 15 minut zamiast w każdym 30-sekundowym
  cyklu. Startowy kapitał dnia pozostaje immutable baseline, ale normalna
  zmiana bieżącego salda po fee/PnL nie blokuje kolejnego wejścia.
- Brak kwalifikującej historii/Bronze jest zdrowym `WAIT` z kodem
  `INSUFFICIENT_DATA`; progi kompletności nie zostały obniżone.
- `SessionRecorder` zachowuje wszystkie partial fills i odrzuca identyczny
  replay. Odrzucone wejście zwalnia slot `RiskEngine`, także gdy sam submit
  rzuci wyjątek.
- Auction tick-binning używa `Decimal` + `ROUND_HALF_UP`; compactor izoluje
  uszkodzony katalog i kontynuuje pozostałe bez kasowania źródeł; zapis
  eksperymentu utrwala faktyczny fee/slippage multiplier, effective
  probability, seed i entry delay.
- Walidacja lokalna: Ruff clean, Mypy clean (226 modułów), pełny pytest
  `1582 passed, 3 skipped`, `git diff --check` clean i skan sekretów clean.

Znane granice: podany audyt mówił o 22 znaleziskach, ale przekazana lista
zawierała tylko dziewięć opisanych pozycji oraz trzy obserwowane problemy VPS.
Wszystkie przekazane, odtwarzalne problemy zostały objęte poprawką i testami;
nie wolno twierdzić, że nieudostępnione 12 pozycji zostało zweryfikowane.

### 4oo. Cykl 73 — wydajny Bronze reader i bezpieczny restart Demo

- Historia 5m/funding/OI z repo została skopiowana do dedykowanego wolumenu
  `/opt/greenfield-v2/data` przez `rsync --ignore-existing`; nie usunięto ani
  nie nadpisano danych raw. Aktywne collectory Bybit BTC/ETH/SOL pozostały
  nietknięte.
- `discover_manifests` zawęża teraz wyszukiwanie po fizycznych partycjach
  exchange/market/channel/symbol. Dodatkowy bounded reader czyta wyłącznie
  najnowsze manifesty potrzebne do limitu transakcji, ale nadal sprawdza co
  najmniej jeden kwalifikujący manifest dla każdej wymaganej daty UTC.
- Regresje obejmują pomijanie niepowiązanej uszkodzonej partycji, odrzucanie
  niebezpiecznych komponentów ścieżki i zatrzymanie odczytu po osiągnięciu
  limitu wierszy. Pełna walidacja: Ruff clean, Mypy clean (226 modułów),
  `1585 passed, 3 skipped`, `git diff --check` clean.
- Commity `fa47c4b` i `8afeb6f` są wypchnięte na
  `origin/codex/kontynuacja-claude-code`. Na VPS zbudowano dokładnie aktualny
  obraz i zwalidowano profil Compose `demo-scalp`.
- Skan hybrydowy BTC na realnym jeziorze zakończył się w około 17 sekund i
  zwrócił audytowalne `WAIT`. Następnie uruchomiono
  `bybit-demo-scalper` jako `restart: unless-stopped`; kolejne cykle raportują
  `healthy`, `WAIT`, brak wymuszenia operatora, brak pozycji i brak otwartych
  zleceń. Jednorazowy marker probe pozostaje zużyty.
- Nie przeprowadzano sztucznego partial fill ani execution-lag na giełdzie.
  Te ścieżki mają deterministyczne testy regresji; operacyjny fault-injection
  pozostaje wymaganym dowodem przed formalnym PAPER, bez wymuszania ryzyka na
  działającym koncie Demo.
- CI ujawnił wcześniejszą niejednoznaczność nazw modułów `scripts`. Commit
  `f2e59d2` utworzył jawny pakiet i rozdzielił typy downloaderów; dokładne
  `mypy src scripts` oraz oba przebiegi GitHub Actions (push i draft PR) są
  zielone po cztery zadania każdy.

### 4pp. Cykl 74 — formalny restart siedmiodniowego Phase 1 soak

- Historyczny marker `phase1-20260822t183659z` został zbadany, a nie
  retroaktywnie zaliczony: źródłowy commit jest przestarzały, okno ma około
  70 godzin, a heartbeat gaps przekraczają 510 sekund. Dane pozostają cenne,
  ale raport jest jednoznacznie `qualified=false`.
- Utworzono czysty, detached checkout
  `/home/ubuntu/greenfield-phase1-soak-20260825` przypięty do commita
  `2a7588f61049c327c2fb7822ed55a2bf0e22ff8c`. Fresh preflight jest zielony,
  a capacity forecast (4x burst + 5 GiB reserve) mieści się na dedykowanym
  wolumenie z niewielkim, monitorowanym zapasem; żadnych danych nie usunięto.
- Pierwszy marker `phase1-20260825t164500z` zachowano jako niekwalifikujący:
  kontenery starego projektu z `restart: unless-stopped` uruchomiły się po
  sygnale do PID i wprowadziły `stopped`/overlap w granicy sesji. To nie była
  utrata danych. Stare trzy usługi zatrzymano następnie przez Docker; finalne
  snapshoty mają `connected=false`, `queue_depth=0` i `events_received ==
  events_written` dla BTC, ETH i SOL.
- Właściwa immutable session to `phase1-20260825t164933z`. Trzy izolowane
  kontenery projektu `greenfield-phase1-20260825` są zdrowe i związane z tym
  markerem oraz dokładnym commitem. Wczesny audyt: po cztery próbki na symbol,
  maksymalny gap 5.01-5.03 s, zero drops/reconnects/sequence uncertainties;
  jedyny błąd to oczekiwany brak pełnych 604,800 sekund.
- Monitoring i Bybit Demo scalper pozostają osobnymi, zdrowymi workloadami.
  Formalnego soaku nie restartować ani nie aktualizować. Najpierw utrwalić
  siedmiodniowy raport, dopiero później wykonać graceful restart/reboot/backlog/
  restore drills i zbudować końcowy evidence bundle.

### 4qq. Cykl 75 — powtarzalny Demo fault-injection evidence gate

- `capture_demo_fault_drill.py` wykonuje wyłącznie kontrolowane scenariusze w
  izolowanych temporary stores: lag order-history/execution-feed, restart i
  częściowo wykonane anulowane wyjście z trwałym reduce-only na resztę.
- Przed i po scenariuszach odczytuje prawdziwe konto Bybit Demo i wymaga braku
  pozycji oraz otwartych zleceń. Sam drill nie wysyła żadnego zlecenia.
- Raport zapisuje pełny source commit, SHA-256 outputu, dokładne test targets,
  rezultat i obie granice flat-account. Jest immutable (`link`, bez
  overwrite), a dirty checkout, błąd testu lub ekspozycja failują zamknięte.
- Testy kontraktu obejmują kwalifikację, niepłaską granicę, błąd scenariusza i
  odmowę nadpisania wcześniejszego raportu. Operacyjny raport należy utworzyć
  dopiero z czystego wypchniętego commita na VPS.

### 4rr. Cykl 76 — historyczny backfill pod nadzorem i coverage contract

- Przerwany bez tracebacku proces (ostatni zapis: 27/60) wznowiono od początku
  jako transient systemd unit `greenfield-historical-backfill`, z
  `Restart=on-failure`. Istniejące partycje są merge/deduplicate, więc restart
  nie tworzy duplikatów; odłączenie SSH nie zatrzymuje usługi.
- `historical_coverage.py` audytuje wszystkie 60 planowanych kombinacji
  Bybit/Binance/OKX × BTC/ETH/SOL × timeframe oraz Bybit funding/OI. Raportuje
  granice, liczbę partycji/wierszy, duplikaty, gaps, maximum gap i przybliżone
  coverage bez syntetyzowania braków.
- `FULL`, `PARTIAL` i `MISSING` są jawne. Provider-bounded `PARTIAL` nie jest
  ukrywany, ale brak całego joba, zły symbol/timeframe, duplikat lub
  nieczytelny Parquet powoduje fail-closed. Raport jest immutable.
- Coverage report uruchomić dopiero po `systemctl` success dla skończonego
  backfillu i przypiąć ten sam `--as-of`, który widnieje w logu planu.

### 4ss. Cykl 77 — trwały dziennik empiryczny ATAS/MC Demo

- Scalper zapisuje teraz każdy cykl do append-only SQLite WAL obok trwałego
  lifecycle store. Rekord zawiera trzy niezależne rodziny dowodów, ich score,
  confidence, quality, komponenty i source timestamps oraz osobny veto
  Market-Cipher-like, cenę obserwacji i wynik wykonania.
- `observation_id` jest kluczem idempotencji: identyczny replay jest no-op,
  natomiast inna treść pod tym samym identyfikatorem failuje zamknięte.
- Jest to surowy materiał do przyszłego raportu kalibracji i outcome labeling;
  sam zapis nie promuje kandydata ani nie zmienia limitów ryzyka.
- `validate_demo_signals.py` etykietuje wyłącznie dojrzałe przyszłe obserwacje
  1/5/10 minut bez lookahead, wyklucza wymuszone probe i tworzy immutable
  raport. Brak 1,000 obserwacji lub naturalnych LONG/SHORT pozostaje jawnym
  `qualified=false`, a nie powodem do obniżenia progu.

### 4tt. Cykl 78 — ukończony historyczny backfill i operacyjne uruchomienie dziennika

- Transient unit `greenfield-historical-backfill.service` zakończył wszystkie
  60 zadań z `Result=success` i kodem wyjścia 0. Pierwszy immutable raport
  uczciwie wykazał trzy brakujące dzienne serie SOL, ponieważ wspólna granica
  50% traktowała rzeczywisty krach i odbicie SOL z listopada 2022 jako
  anomalię.
- Granicę zmieniono wyłącznie dla świec `1d` z 50% na 75%; intraday pozostał
  przy 50%, a niepoprawne OHLC nadal failują zamknięte. Po ponownym pobraniu
  tylko Bybit/Binance/OKX SOL `1d` raport
  `reports/historical-coverage-20260825-rerun1.json` ma `qualified=true`:
  60 zadań, 57 `FULL`, 3 `PARTIAL`, 0 `MISSING`, bez luk, duplikatów i błędów.
  Trzy `PARTIAL` to Bybit SOL `1h`/`4h`/`1d`, gdzie dostawca rozpoczyna dane
  2021-10-15, później niż żądany 2021-09-01; nie syntetyzowano historii.
- Zachowano oba raporty. SHA-256 raportu pierwszego to
  `070a9a8161415dbe977b609466bc9b504f02ca3a6bcb2949ee25385cb0c0b595`, a
  kwalifikującego rerun to
  `4807ddd2398136b539a0b14497ae206f675f430f25a03d2ee5abafc280816a73`.
- Demo scalper wdrożono ponownie wyłącznie z aktualnym obrazem, bez dotykania
  formalnego soaku. Dziennik powstał pod
  `/opt/greenfield-v2/data/state/demo-scalp/signals.sqlite3`; pierwszy raport
  walidacyjny zawiera dwie pełne obserwacje trzech rodzin, oba naturalne
  `WAIT`, i poprawnie pozostaje `qualified=false` z powodów
  `INSUFFICIENT_OBSERVATIONS`, `INSUFFICIENT_MATURED_OUTCOMES` oraz
  `NO_ACTIONABLE_SIGNALS`. Jego SHA-256 to
  `2d5d3af8fb02e6bdc9f715e5b662ade67431ae04967ba53a1f7ada5a8819d341`.
- Po wdrożeniu Demo konto pozostawało płaskie: zero pozycji i zero otwartych
  zleceń. Scalper oraz trzy formalne collectory Bybit BTC/ETH/SOL były
  `healthy`; formalna sesja `phase1-20260825t164933z` nie została
  zrestartowana ani zmodyfikowana.

### 4uu. Cykl 79 — produkcyjny, wersjonowany Silver→Gold dla mikrostruktury

- `materialize_daily_trade_microstructure` wybiera dokładnie jeden zamknięty
  dzień/exchange/market/symbol z Silver `trades`, weryfikuje każdą immutable
  partycję i jej causal lineage, odrzuca duplikaty oraz dopiero wtedy buduje
  Gold. Otwarty dzień, brak danych lub quarantined/corrupt Silver failują
  zamknięte.
- Dataset version wiąże dokładne content hashes partycji oraz hash wszystkich
  kwalifikujących `normalized_id`; code version pozostaje osobnym wymiarem.
  Ponowny build tego samego inputu jest idempotentny także przy późniejszym
  `as_of`.
- Powstają dwa checksummed feature sets: trade-flow (buy/sell volume, delta,
  CVD, count, VWAP) oraz footprint-auction (delta/volume, diagonal i stacked
  imbalance, POC, VAH/VAL). Każdy wiersz zachowuje
  `max_source_timestamp <= timestamp` przez kontrakt `FeatureStore`.
- CLI `scripts/materialize_microstructure_gold.py` zapisuje immutable raport
  wskazujący wszystkie Gold manifests. Job nie promuje strategii, nie składa
  zleceń i nie udaje, że dzienne CVD jest ciągłym wielodniowym CVD.

### 4vv. Cykl 80 — bounded daily Bronze→Silver selection

- `discover_manifests`, `normalize_raw_lake` i kompatybilny CLI obsługują
  teraz dokładny `utc_date`. Filtr jest częścią fizycznego globu partycji,
  więc jeden dzienny job nie skanuje ani nie odczytuje całej wielodniowej
  historii raw.
- Filtr pozostaje opcjonalny i nie zmienia zachowania istniejących callerów.
  Test integracyjny zapisuje dwa dni Bronze i dowodzi, że tylko wskazany dzień
  trafia do raportu i Silver.
- Umożliwia to operacyjny proof Bronze→Silver→Gold na osobnym katalogu dysku
  systemowego, bez zapisywania dodatkowych gigabajtów na wolumenie formalnego
  soaku.

### 4ww. Cykl 81 — row-streamed daily Gold po realnym capacity probe

- Pierwszy VPS proof ujawnił przed wejściem w Gold, że implementacja Cyklu 79
  budowała listę całego dnia trade objects oraz pełny footprint DataFrame.
  Przy około 425 MB skompresowanego BTC Bronze i VPS 8 GB byłoby to ryzyko dla
  działających collectorów, więc jednostkę zatrzymano na odseparowanym Silver
  stagingu; collectory i Demo pozostały zdrowe.
- Materializer wykonuje teraz quality/ID pass i feature pass partycja po
  partycji. Trade accumulator zachowuje stan CVD między częściami, footprint
  przechowuje wyłącznie bieżący bucket, a finalne DataFrame mają najwyżej
  dzienną liczbę bucketów. Set ID pozostaje celowo dla wykrywania duplikatów
  między częściami, ale pełne event objects nie są kumulowane.
- Regresja dzieli syntetyczny dzień między trzy Silver parts, w tym dwa eventy
  tego samego bucketa, i dowodzi identycznego, idempotentnego Gold outputu.

### 4xx. Cykl 82 — operacyjny BTC Bronze→Silver→Gold evidence proof

- Proof uruchomiono jako odseparowaną jednostkę systemd, z wejściem tylko do
  odczytu z dedykowanego jeziora i wyjściem
  `/home/ubuntu/greenfield-feature-evidence` na dysku systemowym. Nie
  restartowano ani nie aktualizowano formalnej sesji
  `phase1-20260825t164933z`; trzy collectory oraz Demo pozostały zdrowe.
- Dzień `2026-08-24`, Bybit linear `BTCUSDT`: zweryfikowano 1,051,280 Bronze
  events, zapisano 3,581,730 Silver rows w 16,872 częściach i zakwalifikowano
  3,581,729 trade rows. Jeden wiersz na granicy daty został poprawnie
  wykluczony przez causal UTC-date filter, a nie zgubiony po cichu.
- Gold zawiera dokładnie 2,880 wierszy: po 1,440 minut dla `trade-flow-60000ms-v1`
  i `footprint-auction-60000ms-v1`. Ostatni bucket jest zgodnie z kontraktem
  dostępny o północy następnego dnia, dlatego cztery manifesty obejmują dwie
  partycje availability-date na feature set. Wszystkie cztery przeszły
  niezależne `verify_feature_part`.
- `dataset_version` to
  `0bd755a855ab390c5c40c015cb57d9e6e67c8b5ff93d858e2e76316f5754c601`;
  SHA-256 raportu normalizacji to
  `2f46a5322863ab2495c99cef59714514a908350334c1a1114a65f8562b1c4748`,
  a raportu Gold
  `42e9bd84ab05a5ef5551f781f0fac66fa8f256041cfb46ae68fb51ba10f2cce1`.
  Jednostka zakończyła się `success` po około 14m44s czasu ściennego, z peak
  memory 1.7 GB i bez swapu. Po zakończeniu duplicate-ID set jest jawnie
  zwalniany przed drugim, strumieniowym przebiegiem feature build.
- W trakcie niezależnie działający eksperymentalny scalper znalazł naturalny
  LONG (nie probe operatora) i otworzył jedną pozycję Bybit Demo. Po 10
  minutach wysłał reduce-only exit; pierwsza próba odczytu execution feed
  zgłosiła kontrolowany lag, następny cykl poprawnie zrekoncyliował zamknięcie
  z `realized_pnl_usd=-283.0044721700245`. Konto wróciło do zera pozycji i
  zera otwartych zleceń. To jest telemetryczny test execution path oznaczony
  `experimental_not_promoted`, nie dowód edge ani promocja PAPER.

### 4yy. Cykl 83 — produkcyjny historical-bars→MC-like Gold

- Dodano zamknięty dzienny job dla oryginalnej, niewłasnościowej rodziny
  momentum wave/signal/histogram, money flow, RSI i potwierdzonych causal
  divergences. Rodzina pozostaje veto/filtrem i nie może być liczona jako
  kolejne niezależne potwierdzenie skorelowanych cech ceny.
- Job czyta wyłącznie miesiąc docelowy oraz minimalną liczbę poprzednich
  partycji potrzebną do stałego warmupu. Pełny dzień, pełny warmup, UTC,
  symbol/timeframe, ciągłość, unikalność timestampów i OHLC muszą przejść;
  timestamp Gold jest czasem zamknięcia świecy, nie jej otwarcia.
- Dataset version wiąże dokładne kwalifikujące wiersze, a aktualne hashe
  source Parquet pozostają osobnym dowodem. Dzięki temu dopisanie przyszłego
  dnia do partycji miesięcznej nie zmienia identity ani istniejącego Gold dla
  przeszłości. Output i raport są immutable/checksummed.
- Operacyjny proof na odseparowanej kopii Bybit `BTCUSDT 1m` z dnia
  `2026-08-24` zakwalifikował 1,696 wierszy (256 warmup + pełne 1,440 minut) i
  zapisał 1,440 Gold rows. Dwa manifesty wynikają z availability timestamp
  ostatniej świecy o północy kolejnego dnia; oba przeszły
  `verify_feature_part`, a identyczny rerun zwrócił te same ścieżki i dataset
  version `9b6181d33c3b53ee50eab14d056d97f50f2313fbfc349d78002607119a4794c8`.
  SHA-256 raportu to
  `dc32edfac702428635addccbd60f76d98c01a971884a0ab8f92e873946e83e34`.
  Formalne collectory i Demo pozostały zdrowe; source volume nie był
  modyfikowany, a proof pisał na dysku systemowym.

### 4zz. Cykl 84 — chunk-stable ATAS interaction Gold

- Produkcyjny closed-day microstructure job zapisuje trzeci, osobny feature
  set `trade-interaction-*-v1`: sweeps, absorption, exhaustion, ich score i
  price progress. Nie miesza tych pól z footprintem ani CVD i nie tworzy z
  nich sztucznie wielu niezależnych confirmation votes.
- `TradeInteractionAccumulator` zachowuje poprzedni bucket oraz bieżące trade
  rows między partycjami Silver. Sweep/absorption nie tracą części bucketa, a
  exhaustion nie resetuje się na fizycznej granicy pliku. Waliduje jeden
  symbol, kompletne trade fields i ściśle rosnącą kolejność, failując zamknięte.
- Test chunk-stability dzieli dokładnie ten sam tape na kilka aktualizacji i
  porównuje cały wynik z buildem jednoczęściowym; realny proof należy powtórzyć
  po wypchnięciu commita, bez zapisu na wolumen formalnego soaku.
- Realny, odseparowany rebuild tego samego dnia Bybit BTC zakończył się
  sukcesem po około 9 minutach, z obserwowanym peak memory około 728 MiB.
  Zweryfikował 3,581,729 source rows i zapisał 4,320 Gold rows: po 1,440 dla
  trade-flow, footprint-auction i trade-interaction. Wszystkie sześć
  availability-date manifests przeszło `verify_feature_part`; SHA-256 raportu
  to `098d586f27dd65a781c6fe1c46ff7a9d38fdec55a325836cdca187e0016162f4`.
  Formalny wolumen soaku pozostał wyłącznie do odczytu.

### 4aaa. Cykl 85 — immutable empirical Gold distribution evidence

- `audit_feature_distribution` wybiera dokładnie jeden
  `feature_set/symbol/dataset_version/code_version`, sprawdza lokalizację i
  identity każdego manifestu oraz ponownie weryfikuje checksumy Parquet przed
  odczytem. Brak danych, mieszany schema, duplikaty timestampów, wartości
  niefinitywne lub uszkodzony part kończą job błędem.
- Raport zapisuje dokładny hash zbioru manifestów, zakres czasu, liczbę wierszy
  oraz dla każdej cechy min/kwantyle/medianę/max/średnią/std/zero fraction i
  cardinality. Stała cecha jest jawnym warningiem, nie jest automatycznie
  usuwana ani strojona na tym samym materiale.
- Raport jest immutable i idempotentny. To opisowy dowód QA wejścia do badań,
  a nie test edge, promocja strategii ani multiple-testing control.
- Na realnym dniu BTC wszystkie cztery zbiory przeszły audit: trade-flow
  (1,440 rows/7 metrics/0 warnings), footprint-auction (1,440/10/1),
  trade-interaction (1,440/11/0) oraz MC-like momentum-money-flow
  (1,440/12/1). Dwa warningi dotyczą jawnych parametrów konfiguracyjnych
  stałych z definicji (`value_area_fraction=0.7`, `pivot_age_bars=2`), a nie
  martwych sygnałów. Hashe raportów to odpowiednio
  `8e33b6d7eb69580187e15c11225b61142ff723c16541f41dcb4a44308fc8716d`,
  `3df6ac71b7818ccdd810f730408403af1d447f890fa2b1f07fdfd2b832afd800`,
  `b6afb097614788d8c7412c882228800917315162642f9153e628190f9df4312f`
  i `e3521233bc712f2a16707f093f7257573f10f39fe421e6e0ac75e70155008121`.

### 4aab. Cykl 86 — production connection-safe L2 Gold

- `materialize_daily_l2_microstructure` odtwarza Silver order book od
  ostatniego snapshotu dostępnego przed początkiem docelowego dnia. Brak tego
  snapshotu, przerwa/regresja update ID, delta po zmianie connection ID,
  corrupt/niekwalifikowana partycja lub duplikat normalized ID failują
  zamknięte; reconnect wymaga nowego snapshotu.
- Chunk-stable `BookLiquidityAccumulator` zachowuje książkę, redukcje i okno
  replenishment także wtedy, gdy raw event lub sekwencja partycji przecina
  granicę wywołania. Działa równolegle z niezależnym odtwarzaniem top-depth;
  różna liczba albo lineage update'ów jest błędem, nie silent joinem.
- Minutowy, receive-time causal Gold zawiera rozkłady spreadu, ostatni mid i
  microprice, offset microprice, średnią/minimum depth, średnie/std/ostatnie
  imbalance oraz sumy additions, cancellations i replenishment z ich
  proporcjami. Dataset identity obejmuje dokładne Silver parts/IDs i wszystkie
  parametry. CLI oraz immutable report są gotowe; realny pełnodniowy proof może
  ruszyć dopiero po zamknięciu pierwszego pełnego dnia aktualnego soaku.

### Następna sesja — empiryczny ATAS historical-data export probe

- Zweryfikowano w oficjalnej dokumentacji ATAS, że API wskaźników obsługuje
  historyczne cumulative-trade requests (pojedynczy zakres maksymalnie 7 dni),
  zgłaszaną przez provider maksymalną głębokość historii oraz historyczne
  market-depth snapshot requests. Pełna historia DOM jest opcjonalną
  capability konkretnego connectora, więc nie wolno zakładać jej dostępności
  ani braku bez testu na Bybit.
- Jutro przygotować minimalny custom indicator/exporter C# dla Windows ATAS.
  Najpierw BTCUSDT: odczytać limity, pobrać jeden stary dzień wszystkich
  transakcji i prawdziwego DOM, zapisać metadane oraz porównać dzień wspólny z
  natywnym Greenfield Bronze. Dopiero po udanym proof rozszerzać na ETH/SOL i
  iterację dzień po dniu.
- Dane ATAS zachować jako oddzielne immutable `source=atas` z checksumami,
  manifestami, connector identity i point-in-time lineage. Nie mieszać ich z
  capture giełdowym i nie uznawać wygenerowanego/ograniczonego DOM za pełne L2.
- Przed masowym eksportem sprawdzić warunki licencji ATAS i dostawcy danych.
  Eksporter działa na Windows; Ubuntu VPS pozostaje hostem przechowywania,
  walidacji i badań. Nie zatrzymywać ani nie modyfikować formalnego soaku.

### Bieżący checkpoint — v2 net-cost gate i ATAS bridge boundary

- Najnowszym, nadrzędnym branchem jest `druga-proba-scalpingu` (zawiera cały
  wcześniejszy `codex/kontynuacja-claude-code`). Pełna walidacja punktu
  `6aa23c7` przeszła: Ruff, Mypy 321 plików, 1,640 testów + 3 skip.
- V2 liquidation-fade nie ma potwierdzonego edge. Pięciodniowy wynik po
  kosztach: 27 trades, 44.44% win rate wobec 55% breakeven i średnio
  `-0.1939 bps`. Profile v1/v2 na VPS pozostają zatrzymane.
- Dodano fail-closed `demo_v2_evidence_gate`: v2 nie uruchomi się bez
  SHA-pinned reportu dokładnie tego kandydata, jawnych fees, minimum 100 trades,
  dodatniej średniej netto i przewagi nad net breakeven. To nie jest promocja;
  OOS/walk-forward/DSR/PBO/stability i human gate pozostają osobno.
- Dodano pierwszy Windows C# ATAS cumulative-trade exporter source oraz
  testowany importer `source=atas` z checksumą, manifestem i odrębnym
  content-addressed Bronze landing. Importer umie walidować także przyszłe
  snapshoty DOM, ale exporter nie udaje tej capability bez realnego testu
  connectora.
- Na tym workstation jest `%APPDATA%\\ATAS`, lecz brak wykrywalnej instalacji
  programu/bibliotek i brak .NET SDK; nie można jeszcze uczciwie skompilować ani
  uruchomić DLL. Nie wolno parsować własnościowego cache `.dat`.
- Kolejny krok operacyjny: zainstalować/odnaleźć ATAS i zgodny SDK na Windows,
  zbudować DLL, pobrać jeden stary dzień BTC cumulative trades, zaimportować go
  z SHA i porównać wspólny dzień z native Bronze. Następnie dopiero proof DOM,
  ETH/SOL i review licencji. Formalnych collectorów/soaku nie dotykać.

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

### Bieżący checkpoint — v1/v2 wycofane, Bybit Demo zachowany jako szkielet

- Decyzją operatora oba eksperymenty zostały całkowicie usunięte z wykonywalnej
  części repo: ATAS/MC v1 oraz liquidation-fade v2. Usunięto ich skanery,
  feedy, journal/validation, wrapper backtestu, force-once, runnery i profile
  Compose. Powyższe wpisy pozostają wyłącznie historycznym ledgerem.
- Nie ma obecnie autonomicznej strategii Demo ani procesu, który można
  uruchomić w tle. Nie wolno przywracać v1/v2 tylko po to, aby bot handlował.
- Zachowano zweryfikowany szkielet Bybit Demo: preflight, balance/exposure,
  gateway, deterministyczną tożsamość zleceń, order/fill reconciliation,
  partial-fill/restart recovery, durable lifecycle i risk state, reduce-only
  exits, health publisher, fault drill oraz jawnie potwierdzany bounded BTC
  round-trip. `DemoStrategyExecutor` jest biblioteką bez źródła sygnału,
  runnera i domyślnej konfiguracji ryzyka.
- Następny priorytet to dane: domknięcie i audyt soaku, jakość Bronze/Silver/
  Gold, wdrażanie kolektorów OKX/Binance/Coinbase/Deribit po jednej giełdzie,
  realny historyczny eksport ATAS BTC z porównaniem overlap oraz dopiero potem
  badanie kandydatów przez OOS/walk-forward/adverse-cost/DSR/PBO/stability.
  Do Bybit Demo podłącza się wyłącznie kandydata, który przejdzie te bramki.

### Bieżący checkpoint — Phase 3 public-transport preflight

- Po audycie aktywnego soaku potwierdzono trzy zdrowe, odizolowane collectory
  Bybit BTC/ETH/SOL na commicie `2a7588f`: około 11.1 mln zapisanych eventów,
  15 GiB raw, zero dropów/reconnectów/sequence uncertainty, puste kolejki i
  około 78 GiB wolnego miejsca. Sesja ma dopiero około 23 godzin; nie jest
  siedmiodniowym acceptance evidence i nie została zrestartowana.
- Dodano `raw_venue_preflight.py` oraz CLI `preflight_raw_venues.py`. Dla
  Binance, OKX, Coinbase i Deribit otwierają wyłącznie publiczny WebSocket,
  wysyłają dokładną reprezentatywną subskrypcję i wymagają venue-specific ACK.
  DNS/TLS handshake bez poprawnej subskrypcji nie wystarcza.
- Raport jest immutable, bez sekretów i kwalifikuje się tylko przy czystym,
  dokładnym commicie oraz sukcesie wszystkich wybranych giełd. To dopiero
  preflight łączności: nie uruchamia profilu Compose, nie tworzy soak markera,
  nie dotyka Bybit Phase 1 i nie dowodzi kompletności danych ani edge.
- Następny krok po zielonym CI: wykonać raport na osobnym czystym checkoutcie
  VPS, następnie przygotować osobny start/soak contract najpierw dla OKX.
- Target-host proof wykonano na odizolowanym checkoutcie
  `/home/ubuntu/greenfield-phase3-preflight-20260826`, commit `5d713e4`. Pierwszy
  immutable raport poprawnie zakończył się FAIL, ponieważ środowisko miało
  tylko extra `dev` i nie zawierało runtime `websocket-client`. Po wykonaniu
  wymaganego `uv sync --extra data --locked` drugi, nowy raport osiągnął
  `qualified=true`: dokładny czysty commit oraz ACK dla Binance, OKX, Coinbase
  i Deribit. Żaden collector ani profil Compose nie został uruchomiony.

### Bieżący checkpoint — Phase 3 venue-bound soak contract

- Dodano kanoniczny kontrakt wdrożeniowy dla OKX, Binance, Coinbase i Deribit:
  profil Compose, market type, dokładne collector IDs, service names oraz
  odizolowany health namespace są jednym typowanym mappingiem, a nie luźnymi
  argumentami operatora.
- `RawSoakSession` schema v3 wymaga zgodności całej tej tożsamości oraz świeżego
  immutable public-transport preflightu dla wybranej giełdy. Marker wiąże jego
  SHA-256 i odrzuca capacity forecast bez dokładnego `venue` oraz
  `health_namespace`, więc raport Bybit nie może autoryzować OKX.
- `scripts/start_raw_venue_soak.py` sprawdza czysty dokładny commit i trzy świeże
  klasy evidence, tworzy marker atomowo/bez nadpisania i tylko drukuje komendę
  startu do osobnego review. Sam nie uruchamia collectorów.
- `audit_raw_soak.py` odczytuje namespace z markera. Wynik Phase 3 ma schema v3
  i zachowuje venue oraz hash transport preflightu; historia innej giełdy nie
  może przejść audytu przez zbieżny collector ID.
- Następny krok: przygotować ograniczony smoke/capacity proof OKX na osobnym
  checkoutcie i wolumenie, wygenerować świeże evidence dla jednego commita,
  następnie dopiero utworzyć formalny marker i uruchomić wyłącznie profil OKX.
  Aktywnego soaku Bybit nie restartować ani nie modyfikować.

### Bieżący checkpoint — bounded OKX smoke i venue capacity proof

- Dodano `run_raw_okx_smoke.py`: korzysta z tego samego silnika
  `RawOkxCollector`, lecz jest osobnym public-only pre-soak narzędziem. Wymaga
  czystego dokładnego commita i świeżego OKX transport preflightu, odmawia
  istniejącego sample directory i ma twardy timer 30-900 s (domyślnie 120 s).
  Nie tworzy soak markera i nie uruchamia Compose.
- Dodano rozdzielenie `request_stop()` od finalnego `stop()` w OKX collectorze,
  aby timer tylko wybudzał foreground WebSocket, a jedyne finalne flush/join
  wykonywał istniejący `run_forever` cleanup. Zachowanie jest testowane.
- Immutable smoke report kwalifikuje wyłącznie kompletny BTC/ETH/SOL
  orderbook/trades/ticker sample: raw niepusty, receive=write, queue=0,
  finalized/disconnected, zero drops i sequence uncertainty, bez runtime error.
  Wiąże commit, venue namespace i hash transport preflightu.
- `forecast_raw_venue_capacity.py` przelicza zakwalifikowaną próbkę na siedem
  dni z 4x burst i 5 GiB reserve, wiążąc cały smoke-report SHA-256. Phase 3 marker
  wymaga capacity schema v2 z właściwą venue/namespace/tożsamością; starego
  raportu Bybit nie da się użyć.
- Kod i testy nie są target-host proof. Kolejny ruch operacyjny po zielonym CI:
  świeży OKX preflight na dokładnym nowym commicie, 120 s bounded smoke na
  osobnym katalogu VPS, forecast na właściwy DATA_DIR, dopiero potem formalny
  marker i ręcznie zatwierdzony start samego profilu OKX. Bybit pozostaje bez
  zmian.

### Bieżący checkpoint — deterministyczny dzienny quality/catalog job

- Dodano `run_daily_data_maintenance.py`, który dla poprzedniego zamkniętego
  dnia UTC wykonuje istniejący fail-closed audyt Silver, a po jego sukcesie
  buduje point-in-time catalog snapshot dla każdej obecnej pary
  exchange/market_type, ograniczony dokładnie do tej samej partycji UTC.
- Cutoff jest zawsze równy północy po audytowanym dniu, więc retry tego samego
  dnia na tym samym commicie daje identyczne raporty. Jeden immutable report
  wiąże hash jakości oraz hashe i wersje wszystkich snapshotów z dokładnym,
  czystym Git HEAD.
- Job nie modyfikuje Bronze/Silver i nie przenosi wadliwych partycji;
  quarantine pozostaje overlay. Brak danych albo błąd jakości kończy się
  niezakwalifikowanym dowodem i bez tworzenia catalog snapshotów.
- `build_dataset_snapshot(..., utc_date=...)` jest opcjonalnym, addytywnym
  filtrem. Zwykli callerzy bez tego parametru zachowują dotychczasowy katalog
  kumulacyjny; daily job nie może już objąć starszej, nieaudytowanej w tym
  przebiegu partycji.
- `docs/DAILY_DATA_MAINTENANCE_RUNBOOK.md` opisuje manualny proof i kontrakt
  harmonogramu. Instalacja timera na VPS i zaobserwowany automatyczny przebieg
  nadal są wymaganym operational evidence; nie zostały zasymulowane lokalnie.

### Bieżący checkpoint — obiektywny storage restore proof

- Istniejący recovery drill `storage_restore` nie ufa już dwóm ręcznie
  wpisanym, równym hashom. `verify_storage_restore.py` sam strumieniowo hashuje
  wszystkie regularne pliki źródła backupu i osobnego katalogu restore,
  uwzględniając ścieżkę względną, rozmiar i SHA-256 każdego pliku.
- Źródło i restore muszą być różnymi, nienakładającymi się drzewami; symlinki,
  pliki specjalne i puste źródło są odrzucane. Raport jest immutable.
- `capture_phase1_recovery_drill.py` dla typu `storage_restore` wymaga tego
  zakwalifikowanego raportu, pobiera z niego oba tree hashe i wiąże SHA-256
  samego raportu z końcowym drill evidence. Ręczne wartości nie wystarczają.
- To domyka lukę kodową w dowodzie restore, ale nie jest dowodem wykonania na
  VPS. Należy nadal odtworzyć prawdziwy backup do osobnego katalogu, wykonać
  strict replay oraz zebrać before/after health w wymaganym oknie soaku.

### Bieżący checkpoint — BTC/ETH/SOL backtest data-readiness audit (2026-08-26)

Point-in-time audit while real Bronze-to-Silver production ran in the
background (BTC/ETH, 2026-08-25, bybit linear). No new heavy Bronze scan; this
reuses catalogs/reports already on disk plus lightweight manifest counts.

- **Real historical (REST backfill), catalogued, OOS-ready today**: Bybit/
  Binance/OKX klines (six intervals) plus Bybit funding and 5-min OI for BTC/
  ETH/SOL. `reports/historical-coverage-20260825-rerun1.json` is qualified:
  57/60 jobs FULL, 3 PARTIAL (Bybit SOL 1h/4h/1d, ~97.6% coverage — provider-
  bounded by SOL's later listing date, not a defect). This is genuine
  exchange data, distinct from the empty-page false negative in the earlier
  run, and does not require reading live raw Bronze at all.
- **Real live capture (Bronze), immutable, root-owned, growing**: Bybit
  linear trades/orderbook/ticker/liquidations/control for BTC/ETH/SOL,
  2026-08-22 (partial) through 2026-08-26 (open). ~16 GiB, 0 drops, 0
  reconnects, sequence continuity verified throughout this session.
- **Real Silver (normalized), in production for the first time**: this
  session's `normalize_raw_bybit.py` run for BTCUSDT/ETHUSDT 2026-08-25 into
  `/opt/greenfield-v2/data/silver` (previously did not exist in production).
  Not yet quality-audited or catalogued; SOL and the two older closed days
  (2026-08-23/24) are not started. Not OOS-ready until `audit_silver_quality`
  and the daily maintenance job qualify it.
- **Gold**: none in the production data root yet. Prior Gold proofs (BTC
  microstructure/L2/MC-like) were deliberately isolated, non-production runs
  under `/home/ubuntu/greenfield-feature-evidence`, already documented
  elsewhere in this file — real evidence, but not part of the catalogued
  production dataset.
- **Synthetic/test data**: none found mixed into the production data root.
  `data/calibration/2026-08-21-lossless-smoke` is a labeled smoke-test
  artifact, clearly separate from `data/raw`/`data/silver`/`data/klines`; test
  fixtures live only under `tests/`. No synthetic series is at risk of being
  mistaken for real market data in this dataset.
- **Existing "first baseline" evidence already exists and predates this
  session**: `reports/research_cycles/CYCLE-20260826T134213Z` (2026-08-26
  13:42–14:33 UTC), run against real klines/funding via `DATA_DIR`, covers
  price-structure (momentum, trend-following, price-action-confluence),
  cross-asset, and funding/OI hypothesis families separately for BTC/ETH/SOL
  (`configs/research_protocol.yaml`: 90/21/21-day train/validation/test
  split, purge_bars=20, embargo_bars=10, adverse-cost gate, DSR>=0.95,
  PBO<=0.2, min 30 OOS trades, min 60% positive folds, parameter-stability and
  perturbation checks). Result: 31/31 hypotheses `FAILED_GATE`, status
  `NO_CANDIDATE` — an honest negative result, not a run that needs redoing.
  This already satisfies the price-structure and funding/OI parts of a first
  baseline on real data with proper OOS/walk-forward/anti-overfitting
  controls and no promotion.
- **Not yet run**: a dedicated Market-Cipher-like momentum/money-flow
  *research hypothesis family*. The MC-like Gold feature module
  (`src/features/momentum_flow.py`) exists and is tested, but no strategy
  class or `configs/research_protocol.yaml` family wraps it into an OOS
  backtest yet — that is new (small) code, not a data problem.
- **Correctly blocked, not attempted**: an ATAS-like microstructure baseline.
  It requires real trades/L2 Silver, which is mid-production in this same
  session; running it now would both compete for I/O with the live
  normalization and use unaudited Silver. Per the standing instruction this
  auto-starts (deterministic replay + one bounded ATAS-like baseline on the
  common BTC/ETH/SOL Silver period) once BTC/ETH/SOL Silver for the target
  date is produced and quality-audited — not before.
- No new backtest, research cycle, or Demo action was started in this audit;
  CPU load was already near the 4-core ceiling from the two Silver jobs.

Gap matrix (what would need to happen before a MC-like or ATAS-like baseline
is real, in order): finish BTC/ETH Silver → SOL Silver → daily Silver
quality audit qualifies 2026-08-25 → (optional) build the MC-like hypothesis
family → run bounded ATAS-like/MC-like baselines on that one audited day,
explicitly labeled EXPLORATORY ONLY given the short microstructure history.

### Bieżący checkpoint — first production BTC Silver, SOL started (2026-08-26)

- First production `normalize_raw_bybit.py` run completed for BTCUSDT/
  2026-08-25 against `/opt/greenfield-v2/data`: exit 0, 51,316 source Bronze
  parts / 4,978,270 raw events verified, all 4 real channels present
  (orderbook 3,324,048; trades 950,556; ticker 702,724; liquidations 942, sum
  matches exactly), 40,091,897 Silver rows written, 51,316/51,316 unique part
  identities (no duplicates), 0 quarantined files. A bounded 40-part random
  sample (not an exhaustive scan, to avoid contending with the still-running
  ETH/SOL jobs) found 0 checksum mismatches and event timestamps spanning
  00:03–23:44 UTC, all inside 2026-08-25 — no future/wrong-day leakage in the
  sample. Collector health stayed green throughout (0 drops, 0 reconnects,
  sequence continuity verified) for BTC/ETH/SOL.
- SOL normalize for the same date started immediately after, keeping exactly
  two heavy jobs running (ETH + SOL) with BTC's slot freed, per the
  resource-bounded state machine. Bybit collectors were not touched.
- No Gold materialization has run against real production Silver yet — the
  production `/opt/greenfield-v2/data` root has no `gold/` directory. Prior
  Gold proofs (microstructure, L2, MC-like momentum/money-flow) are real but
  isolated, non-production runs under `/home/ubuntu/greenfield-feature-
  evidence`, already documented earlier in this file.
- ATAS-like feature inventory (code status only — none has run against real
  production Silver/Gold yet, so none is PRODUCTION DATA GENERATED): CVD/
  delta, footprint, stacked/diagonal imbalance, absorption, exhaustion,
  sweeps (`src/features/interaction.py`), Volume Profile/POC/VAH/VAL, VWAP/
  AVWAP, L2 best-bid/ask/spread/microprice/depth-band are IMPLEMENTED and
  TESTED. Liquidity heatmap is NOT IMPLEMENTED (no matching module anywhere
  in `src/`).
- MC-like feature inventory: momentum, the wave/oscillator component
  (`momentum_wave` in `src/features/momentum_flow.py`), money-flow, Wilder
  RSI, volatility context (`src/features/volatility.py`), and regular/hidden
  divergence (`src/features/divergence.py`) are IMPLEMENTED and TESTED.
  Multi-timeframe agreement remains NOT IMPLEMENTED (confirmed again, matches
  the earlier gap-audit commit). No dedicated MC-like hypothesis family
  exists in `configs/research_protocol.yaml`; the existing
  `CYCLE-20260826T134213Z` baseline is price-structure/funding-OI only and
  must not be read as an MC-like baseline.
- No ATAS-like or MC-like baseline has been attempted this cycle — correctly
  blocked on BTC/ETH/SOL Silver for 2026-08-25 existing and passing the daily
  quality audit first, and on not competing for I/O with the still-running
  ETH/SOL normalize jobs.

### Bieżący checkpoint — ETH Silver verified, OKX blocked on real disk headroom (2026-08-26)

- ETH `normalize_raw_bybit.py` for 2026-08-25 completed: exit 0, 51,026
  Bronze parts / 4,538,177 raw events verified across all 4 channels
  (orderbook 3,100,679; trades 777,591; ticker 659,403; liquidations 504, sum
  matches exactly), 33,988,202 Silver rows, 51,026/51,026 unique part
  identities, 0 quarantined files. Bounded 40-part random sample: 0 checksum
  mismatches, timestamps 00:56–23:57 UTC, 0 outside 2026-08-25. Same method as
  the BTC verification recorded above. SOL alone remains running (started
  after BTC's verification passed); collector health stayed green throughout.
- With only one heavy normalize job running, used the freed capacity for the
  independent OKX track (network/metadata-bound, does not compete with SOL's
  Parquet I/O) from the isolated `/home/ubuntu/greenfield-okx-soak-20260826`
  checkout at the current clean commit: fresh OKX public-transport preflight
  qualified; fresh target-host preflight qualified only after rerunning under
  `sudo` (the atomic-storage probe needs to write to the same root-owned
  `/opt/greenfield-v2/data` the real collector would use — the correct
  behavior, not a bug); a 120.5s bounded OKX smoke run qualified with 0 drops,
  0 sequence uncertainty, complete BTC/ETH/SOL baseline coverage (7,990
  events, 438 raw files, 3.64 MB).
- The venue capacity forecast **did not qualify**:
  `stressed_projection_fits_with_reserve=false`, projected headroom
  **-1.71 GiB** (required ≈78.44 GB — a 7-day, 4x-burst OKX projection plus
  the standard 5 GiB reserve — against ≈71.46 GB free at preflight time,
  which itself already reflects this session's new Silver production on top
  of the ongoing Bybit soak's growth). This is the fail-closed capacity gate
  working as designed, not a defect: the real disk headroom on
  `/opt/greenfield-v2/data` genuinely does not support adding OKX right now
  at the tool's conservative default burst/reserve assumptions.
  I did not weaken `--burst-multiplier`/`--runtime-reserve-gib` to force a
  pass, and did not create the soak marker or start any OKX collector.
- OKX bring-up (marker creation, isolated `docker compose --profile okx up`)
  stays blocked until real headroom exists — either the Bybit soak's data
  growth is offset by retention/compaction after a completed backup+restore
  cycle, or the data volume is resized. Resizing is infrastructure expansion
  and needs operator awareness even though it may not require payment on
  this provider; not attempted here. This does not block Binance/Coinbase/
  Deribit later — each gets its own capacity forecast against real disk state
  at that time.

### Bieżący checkpoint — market_cipher_like research hypothesis family added (2026-08-26)

- Closed the confirmed gap (no MC-like OOS hypothesis family existed):
  `docs/PREREGISTRATION_market_cipher_like.md` freezes the exact rule before
  any run — EMA-normalized momentum-wave/signal-line crossover
  (`src.features.momentum_flow.momentum_money_flow_frame`) confirmed by
  rolling money-flow direction from the *same* frame (one confirmation
  family, not two independent votes). RSI and divergence are computed but
  deliberately not gated on in v1; multi-timeframe agreement stays a
  separate future extension (§8.3 gap, unchanged).
- New `src/strategies/market_cipher_like.py`: reads the strategy's own
  klines once at construction, shifts timestamps to true close-time
  availability (identical to
  `src.features.bar_materialization.materialize_daily_momentum_flow`), and
  looks up the precomputed feature frame via `AsOfSeries` — the same
  as-of pattern already tested by `FundingContrarian`. `data_dir` is
  auto-injected by `run_backtest_window`'s existing generic
  `__struct_fields__` check; no special-casing needed there.
- Wired into `configs/research_protocol.yaml` (family H, 3 frozen variants,
  `max_new_hypotheses_per_cycle` 31→37) and `src/research/queue.py`
  (mirrors the `funding_oi` block; `timeframe` merged per-variant since it
  must match whichever timeframe a given hypothesis trades).
  `build_hypothesis_queue` verified to emit exactly 6 new hypotheses
  (3 symbols × 2 timeframes) alongside the existing 31, all others
  unchanged.
- Tests added: config validation (missing/invalid fields, missing/
  insufficient klines on disk), and a truncated-series no-lookahead proof
  through the real NautilusTrader engine (same structural test as
  `FundingAwareMultiHorizonTrend`'s) plus a determinism proof. First fixture
  attempt (smooth sinusoid price) produced momentum-histogram crossovers
  whose money-flow reading at that exact bar structurally never agreed in
  sign across 20 random seeds — money-flow genuinely lags a leading-
  indicator turning point, not a lookahead bug — so the fixture was
  replaced with a noisier regime-switching random walk (closer to real
  return microstructure), which produces plenty of genuine confirmations
  on both sides of the cutoff. 39 targeted tests pass; `ruff`/`mypy` clean
  on every changed file.
- **Not yet done**: a real backtest run against production BTC/ETH/SOL
  klines through the actual research orchestrator (walk-forward/DSR/PBO),
  and the full local `pytest -q` suite — both deliberately deferred while
  SOL normalize and the storage-restore backup copy are the two active
  heavy I/O jobs; CI on the push below runs the full suite regardless.

### Bieżący checkpoint — SOL Silver verified; qualified local-same-volume storage-restore rehearsal (2026-08-26)

- SOL `normalize_raw_bybit.py` for 2026-08-25 completed: exit 0, 51,001
  Bronze parts / 3,919,207 raw events verified across all 4 channels with
  matching sums, 24,847,729 Silver rows, no duplicate part identities,
  empty quarantine. Same bounded 40-part sample method as BTC/ETH: 0
  checksum mismatches, timestamps 00:24–23:37 UTC, all in range. **BTC,
  ETH, and SOL Silver for 2026-08-25 are now all independently verified.**
- **Storage-restore drill — LOCAL SAME-VOLUME RESTORE REHEARSAL, not
  off-host backup or disaster-recovery acceptance** (the backup and
  restore trees both live on `/opt/greenfield-v2/data`, the same physical
  volume as the source — this proves the backup/restore/verify mechanism
  end-to-end, not resilience to losing that volume):
  - Backup: `cp -a` of the closed 2026-08-23 raw partition (all 3 symbols,
    all channels, 3.8 GB / 332,402 files) to
    `/opt/greenfield-v2/data/_storage_drill_backup_20260826`.
  - Restore: separate `cp -a` from that backup to
    `/opt/greenfield-v2/data/_storage_drill_restore_20260826` — a
    distinct, non-overlapping tree, never sourced from live `raw/`.
  - `verify_storage_restore.py` (source vs. restored):
    `qualified=true`, `tree_sha256_equal=true`,
    `file_count_equal`/`byte_count_equal=true` — identical
    `db205554d2ba52261cd518b2634f3cd2daf17182a1627389a773a8fa296cf218` on
    both sides.
  - `capture_phase1_recovery_drill.py --drill-type storage_restore`:
    **`qualified=true`**, every check passed (timeline, named operator,
    before/after health sets, healthy-before, healthy-recovery,
    storage-bundle identity bound to the verification report, and the
    strict-replay check below). Drill window
    `2026-08-26T18:29:08Z`–`2026-08-26T22:45:10Z`; Bybit collectors were
    never stopped or restarted, `dropped_event_count=0` throughout.
  - Neither drill directory is deleted yet — kept as evidence pending a
    deliberate cleanup decision (size confirmed, not the only copy of
    anything: both are additional copies of already-immutable, already-
    replicated closed-day Bronze). Neither path is under the production
    catalog/capacity-scan surface (outside `raw/`, `silver/`, etc.).
  - **Genuine finding, not a defect, and not bypassed**: a full-history
    `replay_raw_bybit.py --data-dir /opt/greenfield-v2/data` (no date
    filter) fails closed with `RawStoreError: raw event order regressed
    or duplicated in stream ('bybit','linear','orderbook','BTCUSDT')`.
    Root cause: three raw soak sessions have accumulated on this VPS since
    2026-08-22 (`phase1-20260822t183659z`,
    `phase1-20260825t164500z`, `phase1-20260825t164933z`), each a fresh
    connection with its own independent `receive_sequence` counter: parts
    from adjacent sessions can have overlapping `receive_ts_ns` ranges
    that the current sort-by-`min_receive_ts_ns` ordering cannot fully
    separate. `iter_raw_events`'s per-stream monotonic check is correct
    and must not be weakened — the tool's implicit assumption (one
    continuous connection per stream) does not hold across a soak
    restart. Full-history-spanning-multiple-sessions replay remains
    **unproven and is a real, disclosed limitation**, separate from
    per-day/per-session replay (which already has production evidence
    elsewhere in this file).
  - Worked around **for this drill only** by scoping to the *current*
    continuous session (`receive_ts_ns >= 1787676585147065258`, its exact
    `start_ts_ns`), spanning its data across 2026-08-25/2026-08-26: 200,305
    manifests, 14,264,669 events, zero pre-session events touched. Result
    qualifies `_valid_replay`: all three `EXPECTED_SYMBOLS` present, 50
    bid/50 ask levels each, valid book and ticker checksums,
    `replay_checksum=a1170bd79f82e78300cd4dc349744cfc9c39425c41e2e7160f12f4ec058421af`.
    This is a real, disclosed workaround (documented here and in the
    script itself), not silent scope-narrowing.
  - Follow-up (not done here): either make `iter_raw_events` connection-
    aware (partition the monotonic check by `connection_id`, not just
    stream) or provide a supported bounded-replay CLI option — a genuine
    code gap, filed here rather than patched under time pressure without
    review.
  - `run_daily_data_maintenance.py` for 2026-08-25 (the real Silver
    quality audit + dataset catalog across all three symbols) ran for
    over two hours of CPU time before this entry was written — still
    progressing when documented, not yet a completed operational proof.
    Its actual qualification, runtime, and whether that duration is
    viable as a nightly cron are recorded in the next checkpoint once it
    finishes; flagging the duration itself as worth investigating
    regardless of outcome.

### Bieżący checkpoint — first real daily maintenance run qualifies (2026-08-26)

- `run_daily_data_maintenance.py` for `utc_date=2026-08-25` against real
  production `/opt/greenfield-v2/data` (BTC+ETH+SOL Silver together, first
  time this has run against genuine production data) **qualified=true**:
  quality audit `qualified=true`, 153,343/153,343 Silver partitions
  qualified, **0 quarantined**, 98,927,828 total rows, one dataset-catalog
  snapshot for `bybit/linear` covering all three symbols.
  `maintenance_id=629614bf3d4519bbac642be2ff4123b45a098145e55a7ef1dab6e133419f697a`.
  Collectors stayed healthy throughout (0 drops, 0 reconnects).
- **Operational finding**: this run took roughly 3h36m wall clock (19:24
  UTC start to ~23:00 finish; ~140+ min of that in CPU time alone). The
  per-partition quality report itself is 163.9 MB (every one of the
  153,343 partitions carries its own full check list). This is real,
  measured behavior against the actual production dataset size, not
  inefficiency introduced by a small fixture — but it means an `OnCalendar
  = 00:20:00 UTC` daily timer needs roughly a 4-hour completion budget
  before anything downstream (Gold materialization, research cycles) can
  assume yesterday's catalog exists. Worth profiling later (see MASTER
  PLAN's read-only-profiling guidance) but not blocking the timer install
  itself — this is a single nightly batch job, not a latency-sensitive one.
- An idempotency rerun (same exact command, same `utc_date`) is running now
  to prove the runbook's required same-`maintenance_id` guarantee before
  the systemd timer is installed — result recorded in the next checkpoint.

### Bieżący checkpoint — daily maintenance systemd timer installed and proven (2026-08-26/27)

- Idempotency confirmed: rerunning the exact same command/date returned the
  **identical** `maintenance_id=629614bf3d4519bbac642be2ff4123b45a098145e55a7ef1dab6e133419f697a`
  byte-for-byte, satisfying the runbook's precondition for enabling a timer.
- Installed `greenfield-daily-maintenance.service` (`Type=oneshot`,
  `User=root`, pinned to the `/home/ubuntu/greenfield-maintenance-20260826`
  checkout at commit `fc9d112`) and `greenfield-daily-maintenance.timer`
  (`OnCalendar=*-*-* 00:20:00 UTC`, `Persistent=true`,
  `RandomizedDelaySec=120`) into `/etc/systemd/system/`, `daemon-reload`,
  `enable --now`. `list-timers` confirms it correctly scheduled for the
  next occurrence.
- **Real deployment bug found and fixed while proving the manual trigger**:
  the service's first real run failed with "daily maintenance requires a
  clean checkout at the exact code version" even though the checkout was
  genuinely clean at the exact pinned commit. Root cause: `git` under
  `User=root` with a minimal systemd environment hit "detected dubious
  ownership" against the `ubuntu`-owned checkout — my own interactive
  `sudo` sessions had inherited a different, already-trusted context, which
  masked this. Confirmed by reproducing with `sudo env -i HOME=/root git
  ...`. Fixed with `sudo env -i HOME=/root git config --global --add
  safe.directory /home/ubuntu/greenfield-maintenance-20260826` (root's own
  `/root/.gitconfig`, not a repo-tracked file, no secret involved). This is
  a real, generally-applicable gotcha for any `User=root` systemd unit
  that runs `git` against a non-root-owned checkout — worth remembering
  for future service installs on this host.
- **Second gotcha, tooling not data**: `systemctl is-active --quiet` returns
  non-zero for the transient `activating` state, not just after real
  failure/inactivity — a wait-loop keyed on it alone gets a false-positive
  "finished" the instant a oneshot unit starts. Switched to polling the
  actual PID's existence instead.
- **Real observed automatic execution**: `systemctl start
  greenfield-daily-maintenance.service` (simulating what the timer will do
  at 00:20 UTC) ran for real, through the actual service/journal path, for
  `utc_date=2026-08-26` (today's not-yet-normalized day — SOL/BTC/ETH
  Silver only exists for 2026-08-25 so far). Result: `partition_count=0`,
  `qualified=false`, exit 1 — exactly the runbook's documented "valid
  fail-closed evidence (empty or unqualified day)", not a defect. systemd
  still reports the unit as `Failed` for a non-zero exit, which is
  semantically correct here but means an ops setup would need to inspect
  the report's `qualified` field (or distinguish an eventual richer exit
  code) rather than alert on every `systemctl status` failure — noted as a
  future refinement, not fixed now.
  - **Real, measured performance finding**: this "empty day" run still took
    **~10 minutes wall clock** (01:51:28→02:01:47 UTC), almost entirely
    I/O wait (`D` state, only ~30s actual CPU) rather than the seconds one
    might expect for zero matching partitions. This means daily-maintenance
    runtime scales with the *total* accumulated Silver history the
    discovery step walks, not just the target day's size — a real
    operational characteristic to watch as more days of Silver accumulate,
    not a bug in this run.
- Collectors were never stopped or restarted through the entire sequence
  (idempotency rerun, service install, two manual triggers including one
  failed one); `dropped_event_count=0`/`reconnect_count=0` confirmed
  immediately after.
- **Priority 2 (daily maintenance + systemd timer) is now complete** with
  real operational evidence, not just code.

### Bieżący checkpoint — first production Gold attempt hits the same cross-session boundary (2026-08-26/27)

- First real `materialize_microstructure_gold.py` run against production
  Silver (`BTCUSDT`, `utc_date=2026-08-25`, price-tick `0.1`) failed
  closed: `OrderFlowError: trade stream is not strictly ordered`, no
  partial Gold output written (no `gold/` directory exists at all — the
  fail-closed contract held). No code was weakened to force a pass.
- **Same root cause as the storage-restore drill's full-history replay
  finding, not a new defect**: 2026-08-25's Silver was normalized from
  the *entire* day's Bronze, which itself spans the
  `phase1-20260825t164500z` → `phase1-20260825t164933z` session restart
  around 16:45–16:49 UTC. The per-partition quality checks the daily
  maintenance audit ran are correctly scoped *within* each Silver part
  (and all 153,343 passed); the Gold trade accumulator enforces strict
  ordering *across* the whole day's parts as one continuous timeline,
  which is exactly where a cross-session gap surfaces. The check is
  correct and was not bypassed.
- Recovery plan chosen: `2026-08-23` and `2026-08-24` sit entirely inside
  the single continuous session that ran from `phase1-20260822t183659z`
  until the `2026-08-25T16:45` restart — neither day crosses a session
  boundary, so they should Gold-materialize cleanly. Started Silver
  normalize for `BTCUSDT/2026-08-24` (one symbol, one day — a bounded,
  representative partition per the standing "if full Gold is too heavy,
  do a bounded representative partition first" instruction) to get a
  genuinely clean first production Gold proof; result recorded next.
- This is now the second independent piece of evidence (replay + Gold)
  that the multi-session-spanning-day gap is real and affects more than
  one downstream consumer — raises the priority of the already-filed
  connection-aware-ordering follow-up, though still not attempted here
  under time pressure without review.

### Bieżący checkpoint — first real production Gold data (2026-08-27)

- **Hypothesis confirmed**: `materialize_microstructure_gold.py` for
  `BTCUSDT/2026-08-24` (clean single-session day, no restart inside it)
  **qualified=true**: 3,581,729 source Silver rows, 4,320 Gold rows
  (1,440 minutes × 3 feature sets: trade-flow, footprint-auction, trade-
  interaction), `dataset_version=0bd755a855ab390c5c40c015cb57d9e6e67c8b5ff93d858e2e76316f5754c601`.
  `/opt/greenfield-v2/data/gold/` did not exist before this — this is the
  first real production Gold data this project has ever produced (all
  prior Gold evidence was isolated, non-production proof runs).
  Availability-date splitting correctly produced both a `date=2026-08-24`
  and a small `date=2026-08-25` manifest per feature set (last minute's
  candle becomes available after midnight) — expected, not evidence of
  contamination from the earlier failed 2026-08-25 attempt (confirmed no
  `gold/` directory existed before this run at all).
- **Self-caught error**: typed an incorrect `--code-version` hash for the
  first attempt at this command (a fabricated-looking value, not the real
  `git rev-parse HEAD`). Caught it before the job produced any output,
  killed the process cleanly, verified the real HEAD, and reran — no
  mislabeled provenance was written. Recorded here as a reminder to always
  read a commit hash from a tool result rather than retyping it from
  memory.
- Started Silver normalize for `ETHUSDT`/`SOLUSDT`/`2026-08-24` (two heavy
  jobs in parallel, within the two-heavy-job limit) to extend Gold
  materialization to all three symbols on the same clean day — needed for
  the standing "compare BTC/ETH/SOL on the common period" requirement,
  which one symbol alone cannot satisfy. Results recorded next.

### Bieżący checkpoint — repo-wide ordering audit finds and fixes L2 Gold's missed connection-aware merge, BTCUSDT/2026-08-25 now qualifies (2026-08-27)

- A second real production run of `materialize_daily_trade_microstructure`
  for `BTCUSDT/2026-08-25` (code-version `e6a9c3a`, the connection-aware
  merge from the prior checkpoint) hit a **third** bug in the same merge,
  11 minutes and ~950k rows into the day: `row_index` was checked as a
  connection-global monotonic field, but it is scoped to one raw message
  only (resets to 0 on every new message a connection produces — one
  `publicTrade` message can fan out several trades). Fixed in `024d462`:
  `merge_rows_by_connection` gained a `connection_tie_break_key`, checked
  only within an exact `connection_sequence_key` tie. Fail-closed held
  again — no bad Gold output written.
- Following that third fix, did a repo-wide audit of every ordering/
  monotonicity/scope assumption touching `row_index`, `receive_sequence`,
  `receive_ts_ns`, `event_ts_ms`, `connection_id`, `update_id`, and
  manifest/bucket ordering (`src/`, `scripts/`), classifying each site as
  a real bug, safe by construction, a test gap, or needing production
  evidence:
  - **Real bug found**: `src/features/l2_materialization.py`
    (`materialize_daily_l2_microstructure`) was never migrated to
    `src.data.ordered_merge` when the trades builder and
    `raw_store.iter_raw_events` were — it still concatenated Silver L2
    manifests in naive `(min_receive_ts_ns, part_path)` order. At a
    reconnect this can hand `L2ImbalanceAccumulator`/
    `BookLiquidityAccumulator` a row chronologically earlier than one
    already consumed, tripping their own "L2 stream is not strictly
    ordered" / "L2 update gap or regression" checks as a false positive —
    the same failure class as the trades bug above, just never hit in
    production yet because no cross-session L2 Gold build had been
    attempted. Fixed in `e1bac50` (mirrors the trades builder exactly,
    including the `row_index` tie-break scoped to
    `connection_sequence_key`); reverting the fix and rerunning the new
    regression test reproduces `OrderFlowError: L2 stream is not strictly
    ordered` end to end, confirming the test actually catches the bug.
  - Everything else audited (the accumulators' own lexicographic ordering
    checks in `order_flow.py`/`interaction.py`, `raw_compactor.py`,
    `microstructure_compactor.py`'s full re-sorts, `normalization_pipeline.py`'s
    1:1 raw-to-Silver part mapping, `dataset_catalog.py`, `daily_data_maintenance.py`)
    is safe by construction — no cross-part chronological accumulation, or
    a genuine full re-sort rather than an assumption of pre-sorted
    concatenation.
  - **Documentation inaccuracy, not a functional bug**: `ordered_merge.py`'s
    module docstring and this file's earlier checkpoints claim a fresh
    `connection_id` "resets that connection's process-local
    `receive_sequence` counter to zero." Checked all five raw collectors
    (`bybit`/`binance`/`okx`/`coinbase`/`deribit`) — `_receive_sequence` is
    initialized once in `__init__` and never reset in `_prepare_connection`
    (called on every reconnect); it is actually monotonic for the
    collector's whole process lifetime. This is a *stronger* guarantee
    than the connection-scoped checks require (a subsequence of a globally
    increasing counter is still increasing), so it causes no correctness
    issue — flagged here so the docstring doesn't mislead a future change,
    not fixed under time pressure mid-audit.
  - 1691 tests pass (was 1690), mypy clean on 322 files.
- Updated the pinned maintenance checkout
  (`/home/ubuntu/greenfield-maintenance-20260826`, detached HEAD) to
  `e1bac50` and reran `materialize_microstructure_gold.py` for
  `BTCUSDT/2026-08-25` against real production
  `/opt/greenfield-v2/data` — **qualified=true**: 3,320,623 source Silver
  rows, 4,299 Gold rows across trade-flow/footprint-auction/trade-
  interaction, 16,920 source parts, no duplicate/order errors,
  `dataset_version=6486af67270899cf8643518ad9856e019170cf78c9c68e06368b21942ae62c95`.
  Peak RSS 739,080 KB (~722 MB) for the full day, confirming the
  bounded-memory streaming design holds at real production scale; wall
  clock 29m06s (first run, cold) then 10m41s (idempotent rerun, warm page
  cache).
  - **Idempotency confirmed**: rerunning the exact same command byte-for-
    byte reproduced the identical `dataset_version`, identical row counts,
    and the identical (already-written) report path — no immutable-report
    collision, satisfying the same determinism guarantee proven for daily
    maintenance in the prior checkpoint.
  - This is the third independent piece of production evidence (replay,
    then trade Gold, now trade Gold again post-row_index-fix) that
    connection-aware ordering via `src.data.ordered_merge` holds across a
    real soak-session restart. The L2 Gold fix above is proven only by
    the new unit regression test (including confirming it fails against
    the pre-fix code) — `materialize_l2_gold.py` has not yet been run
    against real production `/opt/greenfield-v2/data` for a day crossing
    a session boundary; that remains open production evidence to collect,
    not claimed here.

### Bieżący checkpoint — GREENFIELD PROFITABILITY PIVOT begun: BTC/ETH/SOL common Gold, TCA markouts, funding data inventory, Hyperliquid adapter, real coarse screen (2026-08-27)

Pivot from infrastructure to net-edge search, per the standing plan. P0
(cross-session ordering/replay/Gold validation, all checkpoints above) is
closed and not reopened without new failure evidence.

- **Common BTC/ETH/SOL production Gold (2026-08-24)**: materialized
  `ETHUSDT`/`SOLUSDT` trade-microstructure Gold against real
  `/opt/greenfield-v2/data` (BTC already existed). ETH qualified=true,
  3,788,832 → 4,320 Gold rows. SOL qualified=true, 1,050,259 → 4,320 Gold
  rows. All three symbols now have a comparable clean day.
- **market_cipher_like OOS**: launched `run_research_cycle.py` for real
  against production data, frozen protocol untouched
  (`docs/PREREGISTRATION_market_cipher_like.md`). This runs the entire
  37-hypothesis queue (every implemented family), not just this one -
  that is the only entry point the preregistration allows. Still running
  as of this entry (13/37, all PASSED so far — a gate-clearance status,
  not a profitability verdict). No retuning after partial results, per
  standing instruction; NO_CANDIDATE is an accepted outcome. Result
  recorded in the next checkpoint once it finishes.
- **Execution calibration/TCA extended, not replaced**:
  `src/execution/calibration.py` gained `compute_markout_calibration`
  (empirical post-fill markouts/adverse selection at +100/250/500ms and
  +1/2/5/10/30/60s) and `compare_predicted_to_realized` (predicted vs
  realized spread/slippage/fill-probability). No real PAPER execution
  data exists anywhere yet (checked this repo and production) to run
  either against — dormant library code, proven only by 5 new unit tests,
  ready for when SHADOW/PAPER exists.
- **Cross-exchange funding data inventory** (Bybit/Binance/OKX,
  BTC/ETH/SOL): only **Bybit** has funding-rate history, open interest,
  and tick-level L2 (collectors actually running in production).
  **Binance and OKX have klines only** — no funding-rate client exists in
  code for either venue at all (`binance_derivatives_client.py`/
  `okx_derivatives_client.py` only have open-interest/long-short-ratio);
  their OI/raw-L2 collector code exists but is undeployed (no data on
  disk, no process running). A genuine cross-exchange funding
  differential needs funding+BBO on ≥2 venues, so only Bybit alone
  qualifies from this trio today.
- **Bounded read-only Hyperliquid research adapter** (per the plan's
  explicit fallback for missing data, rather than building Binance/OKX
  funding collectors): `src/data/hyperliquid_client.py` (thin wrapper
  over Hyperliquid's single `POST /info` endpoint),
  `schema_hyperliquid.py`/`hyperliquid_storage.py` (asset-context
  snapshots, funding history, cross-venue predicted funding, BBO — top
  level of `l2Book` only, never full depth),
  `hyperliquid_collector.py` (live poller), `hyperliquid_funding_history.py`
  (paginated backfill — live-verified a single `fundingHistory` call
  caps at 500 rows and does not return the full requested range). No
  order placement anywhere. Every response shape was live-verified
  against `https://api.hyperliquid.xyz/info` in this session (docs only
  vaguely covered `predictedFundings`/`fundingHistory` and did not
  document `l2Book` at all). **Real evidence, not just tests**: ran a
  real 30-day funding-history backfill (720 hourly rows each for
  BTC/ETH/SOL) and a real live snapshot poll into production
  `/opt/greenfield-v2/data` — `hyperliquid_asset_ctx`/`hyperliquid_bbo`/
  `hyperliquid_predicted_funding`/`hyperliquid_funding_history` all now
  hold genuine data. Incidental finding: Hyperliquid's `predictedFundings`
  returns `BinPerp`/`HlPerp`/`BybitPerp` (not `OkxPerp`) predicted funding
  for BTC/ETH/SOL in one call — a possible future way to get Binance's
  predicted funding without its own client; not exploited here.
  21 new unit tests, all against fakes (no real network calls in CI).
- **Real-data coarse screen, Bybit vs Hyperliquid** (reused
  `src.engines.neutral_market.derive_cross_exchange_funding_edge`, no new
  carry engine): Bybit had no lightweight current-quote client either
  (only full L2 tick collection or historical klines), so added
  `src/data/bybit_ticker_client.py` (thin wrapper over public
  `GET /v5/market/tickers`, live-verified). `scripts/
  screen_cross_exchange_funding.py` normalizes each venue's own funding
  cadence (Bybit 8h, Hyperliquid ~1h, both read from the response, never
  assumed) to a common hourly rate before projecting the differential.
  **Real live run, 2026-08-27**: `funding_differential_bps == 0.0` for
  BTC/ETH/SOL in all six direction combinations (Bybit's and
  Hyperliquid's hourly-normalized funding rates coincide exactly right
  now); `entry_basis_bps` ranges -6.7..+4.8, inside the 5bps
  model-uncertainty band. **Genuine null result, not a bug or a
  misconfiguration**: no gross cross-exchange funding edge exists for
  these three majors between these two venues at this moment. This is
  only the coarse (gross-edge) pass — no fees/exit-cost/slippage/orphan-
  leg-risk modeling — so it does not by itself rule out a cost-adjusted
  edge existing later or on a different pair; it does mean there is
  nothing here worth preregistering and testing right now.
- **Not yet done** (next highest-value steps, in order): (1) let
  market_cipher_like OOS finish and record its frozen verdict: (2) if a
  cross-exchange carry candidate ever does show a real gross edge on a
  rerun of the screen, preregister it before building anything further —
  none exists yet, so nothing to preregister; (3) the 4H/1D strategy
  tournament (trend following / breakout / funding-aware multi-horizon
  trend / MC-like standalone / best+MC-filter / best+MC-veto) — not
  started, waiting on the research cycle to free its CPU budget; (4) Meta
  Engine ranking and champion/challenger selection to SHADOW/PAPER — not
  started, has no candidates yet to rank.

### Bieżący checkpoint — market_cipher_like full OOS evidence + 4H/1D tournament complete, verdict WAIT (2026-08-27)

- **market_cipher_like OOS finished**: `CYCLE-20260827T093155Z` (started
  09:31:55Z, finished 11:26:12Z, 1h54m32s wall clock, peak RSS 4.1GB) -
  **NO_CANDIDATE, 0/37 hypotheses passed, 68 global trials**. Full
  per-hypothesis evidence (trades, gross/fees/funding/net return,
  win rate, profit factor, expectancy, Sharpe/Sortino, max drawdown, DSR,
  PBO, all 6 symbol/timeframe combinations) re-derived read-only from the
  frozen protocol (same data, same params, same windows - no retuning)
  and shown in full to the user. All 6 failed: the 3 negative-return (4h)
  variants lost money outright; the 3 positive-return (1d) variants
  failed on sample size (24-27 OOS trades vs 30 required - exactly the
  preregistration's own predicted failure mode), PBO~1.0, DSR~0.000, and
  return concentration in 1-2 trades. Noted but not fixed: `EquityMetrics.
  sharpe`/`sortino` are numerically degenerate on sparse-trade 1d windows
  (equity-curve-stitching artifact, not a real signal - DSR is unaffected
  since it's computed differently).
- **4H/1D strategy tournament run** (BTC/ETH primary, SOL separate tier;
  1m/5m/15m untouched per standing instruction). All 6 items tested
  through the exact same walk-forward + `evaluate_candidate` promotion
  gate as market_cipher_like - reusing `src.research.orchestrator.
  _run_hypothesis`/`evaluate_candidate` directly, no new evaluator:
  1. **Trend Following** (already in the cycle above, family
     `momentum_trend`/strategy `trend_following`): all 6 FAILED_GATE.
  2. **Breakout** (`src/strategies/breakout.py`, lookback_bars=20, its
     documented default - never run through this pipeline before,
     single fixed config = no grid = no p-hacking possible): all 6
     FAILED_GATE, but BTC/4h reached **DSR=0.820** (need ≥0.95) on 94
     OOS trades, 51.7% of folds positive (need ≥60%) - the closest
     anything in the tournament came to clearing the gate. `PBO=1.0` on
     every Breakout entry is NOT genuine overfitting evidence - PBO
     needs ≥2 param variants to compute at all and fails closed to 1.0
     with none; a real, disclosed asymmetry in the gate (a single-config
     strategy can never pass the PBO check as built), not fixed here.
  3. **Funding-Aware Multi-Horizon Trend** (already in the cycle above,
     3 hypotheses - fixed 4h/1d pair, one per symbol per protocol): all
     3 FAILED_GATE. ETH's +20.05% was the single best raw aggregate
     return of the entire tournament, still rejected (DSR=0.239, PBO=1.0,
     199.5% perturbation degradation, 55.2%<60% folds positive).
  4. **MC-like standalone** (market_cipher_like, see above): all 6
     FAILED_GATE.
  5/6. **Breakout + MC filter/veto**
     (`src/strategies/breakout_mc_confirmation.py`, new: composes
     Breakout's unchanged N-bar break with market_cipher_like's
     momentum_histogram read the same causal `AsOfSeries` way
     MarketCipherLike itself does, fixed to market_cipher_like's FIRST
     preregistered variant - decided before running, not selected for
     looking good). `mode="filter"` requires active histogram agreement;
     `mode="veto"` blocks only on active disagreement. Tested across the
     full BTC/ETH/SOL x 4h/1d universe, not narrowed to the best base
     alone. All 12 (6 filter + 6 veto) FAILED_GATE. **Filter and veto
     produced numerically identical trade counts/returns on every
     symbol** - the histogram is essentially always available by the
     time any walk-forward TEST window starts (warmup completes during
     TRAIN), so the "missing reading" case the two modes actually differ
     on almost never occurs in practice; a real, disclosed finding about
     this dataset, not a bug in the two modes' logic (unit tests confirm
     they differ correctly on a synthetic missing-reading case). More
     importantly: **the MC confirmation made every result worse than
     unconfirmed Breakout**, not better - DSR roughly halved on every
     symbol (BTC 0.820->0.40/0.46, ETH 0.693->0.29/0.33, SOL
     0.224->0.10/0.11) while trade count dropped too. The pre-stated
     economic hypothesis (momentum confirmation reduces breakout
     fakeouts) is **not supported by this data** - reported as a
     negative result, not hidden or retuned away.
- **Tournament verdict: WAIT.** 0/25 total hypotheses (37 in the full
  research cycle covering families A/B/C/F/G/H, minus H's 6 already
  counted once, plus 6 breakout + 12 breakout_mc = 25 tournament-scoped
  trials across items 1-6) cleared the promotion gate. Breakout/BTCUSDT/
  4h (unconfirmed) is the standout near-miss (DSR 0.820) but still fails
  on fold-breadth and perturbation sensitivity, not sample size - a
  genuinely different failure shape than everything else tested, worth
  remembering if this line of research continues, but not a candidate
  today.
- **Meta Engine (`src/engines/meta.py`) was not invoked**: it ranks
  live, timestamped `SetupDecision`s from `research_approved` engines
  against real-time portfolio state (correlation, exposure, kill-switch) -
  a live per-signal arbitration tool, not an offline backtest-comparison
  tool. Since nothing here cleared the promotion gate, nothing is
  `research_approved` yet, so there is nothing genuine to feed it. No
  champion, no challenger, no SHADOW/PAPER promotion - consistent with
  the standing decision framework's "żaden research gate nie przeszedł ->
  NO_CANDIDATE" / WAIT.
- All new code (breakout_mc_confirmation strategy + registry entry, 13
  unit tests) committed and pushed (`4d9ed72`). Tournament trial results
  were run via one-off scratchpad scripts (not committed - they just
  drive existing `_run_hypothesis`/`evaluate_candidate` machinery with
  manually-constructed `QueuedHypothesis`/`Hypothesis` objects) but wrote
  real entries to the production trial ledger
  (`reports/research/trial_ledger.jsonl`), so they count toward all
  future DSR deflation like any other trial.
- **Next highest-value step**: per the standing framework, WAIT is a
  terminal, valid outcome for this research cycle - there is no
  champion/challenger to move to SHADOW/PAPER right now. Options for a
  future cycle (not started, no action taken): widen the tournament
  universe (more symbols/timeframes), revisit execution/toxicity-filter
  framing for order flow (explicitly not attempted as a standalone
  scalper per standing instruction), or wait for real PAPER data to
  exist so the execution-calibration markout work (already built) has
  something to measure.

### Bieżący checkpoint — Hyperliquid<->Bybit cross-exchange funding coarse screen complete, verdict NO_CANDIDATE (2026-08-27)

Full real-data net-P&L coarse screen for BTC/ETH/SOL, both directions,
using only existing engines (`derive_cross_exchange_funding_edge`,
`evaluate_neutral_opportunity`/`NeutralCostBreakdown` - no new carry
engine). Driven by a one-off scratchpad script (not committed - pure
analysis, not infra), all findings from real, live-verified/downloaded
data.

- **Data gathered**: Hyperliquid funding history for BTC/ETH/SOL
  backfilled 2023-05-12..2026-08-27 (full available history, 28,302
  hourly rows/coin) into production `/opt/greenfield-v2/data/
  hyperliquid_funding_history/`. Bybit funding history already existed
  (2021-08..now). **Real limitation found**: Hyperliquid's
  `candleSnapshot` (needed for basis/price history) only retains a
  ROLLING ~209-day window (2026-01-31..2026-08-27 as of this run,
  live-verified, not assumed) - NOT full market history. Since "funding
  payments alone are not profit - basis change must be included" is a
  hard requirement, the full net-P&L simulation is bounded to that
  209-day common window; the longer funding-only history is reported
  separately as context only, never as a decision basis.
- **Fee schedules verified** (2026-08-27, base/non-VIP tier): Bybit
  maker 2.0bps/taker 5.5bps; Hyperliquid maker 1.5bps/taker 4.5bps, no
  maker rebate at base tier.
- **Pre-stated, fixed decisions** (made before running, never tuned
  after seeing results): 24h holding horizon; entry gated on
  taker/taker fees (never assumes a maker fill); entry threshold =
  conservative net edge LOW > 10bps (`NeutralEngineConfig.
  minimum_net_edge_lower_bps`); 3x assumed leverage for margin/
  liquidation stress bounds.
- **Result: 0 episodes entered, all three symbols, both directions,
  every hour of the 209-day window (~29,646 hourly evaluations)**.
  Conservative net edge (LOW bound, taker/taker) was negative in
  100.00% of hours for every symbol/direction. Even resimulated under
  the BEST-CASE maker/maker fee scenario (7bps vs taker/taker's 20bps),
  net edge still never cleared the 10bps buffer anywhere in a 6-hour-
  sampled pass across the same window (max maker/maker net_low found:
  +1.18bps, SOL).
- **Attribution** (exactly which cost eats the edge, per the standing
  decision framework): **FEES are the dominant killer**, not
  basis/slippage/margin/leg-risk/capacity. Round-trip taker/taker fees
  (20bps) alone typically exceed the entire gross edge; even best-case
  maker/maker fees (7bps) leave almost nothing after the required
  uncertainty band, spread, and slippage. The underlying gross edge
  itself (funding differential + basis) is real but small: median
  gross-base (no uncertainty band) was actually *positive* for BTC/ETH
  (+1.16/+1.61bps) 47-70% of hours, and its own p90 reached +5.4-5.9bps
  - the edge exists, it just isn't big enough to survive real
  transaction costs at this horizon between two both-efficient venues.
  Margin buffer/liquidation distance were never binding (3x assumed
  leverage leaves ~3300bps of buffer, far above the 500/1000bps
  minimums). Capacity was small for ETH ($25.9k) and SOL ($13.5k, live
  top-of-book, binding leg) but never the actual constraint since no
  trade ever qualified regardless of size.
- **Concrete illustration** (item 3's full per-trade field breakdown,
  using the single best real moment found across all ~29,646
  evaluations): SOL, long Hyperliquid/short Bybit, 2026-02-06 07:00
  UTC. Entry: HL ask 79.425 / Bybit bid 79.516, entry basis +11.51bps,
  funding differential (24h projected) +29.77bps, gross edge base
  +41.28bps (a genuine, real basis dislocation - the best one HL/Bybit
  produced for SOL in 209 days). Net edge by fee scenario: maker/maker
  +19.44bps (would have cleared) / maker/taker +12.94bps (would have
  cleared) / **taker/taker +6.44bps (falls short of the 10bps buffer)**
  / adverse -3.56bps. This is exactly why "never assume a maker fill"
  matters: the single best opportunity in the whole dataset only clears
  the bar under an optimistic fill assumption this project's own
  standing instruction says not to make.
- **Longer funding-only context** (2023-05-12..2026-08-27, ~28,848
  hours, NOT a decision basis): median |funding differential| 0.65-
  0.87bps/8h (0.08-0.11bps/hour), p90 2.76-4.02bps/8h, rare maxima
  60-105bps/8h. Naive annualized-equivalent of the median would be
  ~7.0-9.5%/yr - genuinely the kind of number that looks attractive
  isolated from costs, which is exactly why annualized funding is
  disclaimed as description-only, never a decision basis, per the
  standing instruction: this screen's actual, cost-inclusive result is
  0 viable trades in 209 days.
- **Stress scenarios**: not separately re-simulated with a P&L overlay,
  since the base case never produced a single entered episode to stress
  - every requested stress (funding flips after entry, adverse basis
  move, one-leg fill, taker on both legs, 2x slippage, venue outage,
  margin increase, delayed hedge) would only widen an already-negative
  conservative edge further, never rescue it. Recorded as a reasoned
  conclusion, not a fabricated stress-test output.
- **Verdict: NO_CANDIDATE.** No preregistration, no OOS/Shadow/Paper -
  correctly not proceeding on a candidate that doesn't exist, per the
  standing decision framework. Not retuned after seeing results (the
  24h horizon, 10bps buffer, and fee schedule were fixed before this
  run and never adjusted).
- **Next highest-value step**: per the standing instruction, no new
  infrastructure, other venues, or new strategies until Hyperliquid<->
  Bybit had a first concrete net-P&L verdict - it now has one
  (NO_CANDIDATE). Options for later, not started: widen to more
  symbols/venue pairs, revisit with a much longer basis history if
  Hyperliquid ever exposes one, or treat this as closed and move to a
  different pivot item.

### Bieżący checkpoint — CI red on HEAD `0728f30`, screen made reproducible, BASE/LOW terminology corrected (2026-08-27)

- **CI correction, retracting a wrong claim**: this session earlier told
  the user "the only ruff findings are pre-existing and unrelated to
  this work" about 7 findings in `src/data/ordered_merge.py`,
  `src/data/raw_store.py`, and three `tests/data_integrity/`/
  `tests/unit/` files. That characterization was **wrong** - CI workflow
  run 33081173906 failed its required `lint-type-test` job on exactly
  those 7 `ruff check .` findings (B905 missing `strict=` on `zip()` x2,
  I001 unsorted imports, E501 x3, UP037 quoted annotation), and HEAD
  `0728f30` was red because of them, not for any unrelated unmerged
  reason. Fixed all 7 exactly as specified, no `--unsafe-fix`, no
  behavior change verified per finding:
  - `ordered_merge.py`/`test_ordered_merge.py` (UP037): `strict=True`
    added to the ONE `zip()` comparing two `sequence_key()` outputs of
    the same schema (always equal length by construction - this is
    exactly the class of bug B905 exists to catch, not a behavior
    change in any valid input).
  - `test_cross_session_raw_replay.py`: `strict=False` added explicitly
    - `zip(first_run, first_run[1:])` is a deliberate consecutive-pair
    iteration with intentionally mismatched lengths; `strict=True` here
    would have broken the test by raising on the last pair.
  - `raw_store.py`: import block reordered (datetime before functools),
    no code touched.
  - `test_raw_replay_bounded_memory.py`: 3 lines wrapped under 100 cols,
    no logic changed.
  - Confirmed via `git stash`: the one test failure seen locally after
    these edits (`test_replay_memory_does_not_scale_linearly_with_event_count`,
    a memory-ratio benchmark) also failed transiently against the
    unmodified HEAD under the same system load and passed on rerun -
    flaky/environment-sensitive, not caused by this fix.
- **Screen made reproducible, per instruction**: the one-off scratchpad
  analysis is now `scripts/screen_hyperliquid_bybit_funding_carry.py`
  (versioned, committed), with `tests/unit/
  test_screen_hyperliquid_bybit_funding_carry.py` (13 tests: exact fee
  totals per scenario, funding_bps=0 double-count guard, basis sign
  convention, both direction sign conventions for realized basis P&L and
  realized funding P&L, cross-checked against an independent price-leg
  derivation). A small (~5KB) machine-readable manifest -
  `reports/hyperliquid-bybit-funding-carry/manifest.json`, explicitly
  un-ignored in `.gitignore` (the only exception to `reports/*`) -
  records parameters, live spread/capacity inputs, the basis-price and
  funding-only data windows, SHA-256 checksums of every input dataset
  read, observation counts, and the verdict. Raw hourly/episode data is
  never written to a committed location.
- **Parameters and verdict confirmed unchanged** by re-running the
  versioned script: `HORIZON_HOURS=24`, `SAFETY_BUFFER_BPS=10.0`,
  `ASSUMED_LEVERAGE=3.0`, same fee schedule, same entry-gate scenario
  (taker/taker) - untouched. Re-run against the same live-observed
  spread/capacity values already on record (re-fetching fresh live
  values was deliberately avoided here: Hyperliquid's own top-of-book
  size swung from 10.9 BTC to 0.0008 BTC between two fetches seconds
  apart during this session - reusing the already-documented snapshot
  reproduces the recorded finding instead of drifting it on noise).
  Result: 0 episodes, `NO_CANDIDATE`, unchanged.
- **BASE vs LOW corrected** (the terminology gap the user's instruction
  flagged): the script now computes and records, for every one of the 4
  fee scenarios, both BASE (point estimate) and LOW (conservative bound)
  across the FULL hourly grid (not a sample) - a `net_edge_for_scenario`
  helper factored out so this is the same arithmetic
  `evaluate_neutral_opportunity` uses internally, not a second
  implementation. Re-verified against the actual code (not assumed):
  the figures **+19.44 / +12.94 / +6.44 / -3.56 bps** reported earlier
  for maker/maker / maker/taker / taker/taker / adverse **were, and
  remain, LOW values** (`net_low` in the original computation) at SOL's
  single best moment (2026-02-06 07:00 UTC, long Hyperliquid/short
  Bybit) - not point estimates. The BASE (point estimate) figures at
  that exact same moment are **+29.89 / +23.39 / +16.89 / +11.89 bps**,
  materially higher, now recorded for the first time.
  - **A real error found and corrected while reconciling this**: the
    earlier "+1.18bps max maker/maker LOW across the window" was
    computed from a coarser 6-hour-sampled supplementary scan that
    *missed* SOL's actual best hour (07:00 UTC doesn't fall on a 6-hour
    grid boundary starting from the window's own start). Recomputed
    properly over the full, non-sampled grid, the true maximum
    maker/maker LOW anywhere in the dataset is **+19.44bps** (the same
    SOL moment above) - which does exceed the 10bps buffer under an
    optimistic maker/maker assumption. This does not change the
    official verdict: the entry gate uses taker/taker only ("never
    assume a maker fill"), and under taker/taker the true maximum LOW
    is +6.44bps, still short of 10bps, and only 2 of 29,646 full-grid
    observations had a positive taker/taker LOW at all (0.0067%) - none
    reaching the buffer. `NO_CANDIDATE` stands, now on a fully
    reconciled evidence base instead of a mix of full-grid and sampled
    figures.
  - Full breakdown (BASE / LOW, bps, across all 29,646 observations,
    maximum found and fraction of observations positive) is in the
    manifest's `best_net_edge_bps_by_scenario` and
    `positive_fraction_by_scenario` fields for all 4 scenarios, not
    just the two headline ones above.
- **Validated from a clean checkout**: `uv sync --all-extras --locked`,
  `uv run ruff check .`, `uv run mypy src scripts`, `uv run pytest -q`,
  `git diff --check`, a secret scan, and docker compose config
  validation all pass on the commit that includes these fixes (see the
  commit message for exact command output summary).
- One logical commit for all of the above (ruff fixes + versioned
  screen script + tests + manifest + this doc correction), pushed to
  `druga-proba-scalpingu`, CI re-checked green before considering this
  cycle closed.

### Bieżący checkpoint — soak reboot: root cause fixed, disqualification formalized, new soak BLOCKED on disk capacity (2026-08-27)

**SOAK OLD SESSION STATUS — `phase1-20260825t164933z`: `DISQUALIFIED_EARLY`,
final status `EARLY_TERMINATED_KNOWN_FAILURE`, reason
`MAX_HEARTBEAT_GAP_EXCEEDED`.**
- Evidence generated with the existing, unmodified tool
  (`scripts/audit_raw_soak.py`, no code changes), written to
  `/opt/greenfield-v2/data/reports/raw_collector_soak_phase1-20260825t164933z.json`:
  `qualified=false` for all three collectors, `required_duration_secs=604800`
  (7 days) vs. actual observed window `175295.0s` (~2.03 days) - i.e. this is
  **not** a completed 7-day PASS/FAIL, it is an early termination on a
  necessary-condition breach, exactly as instructed.
- Start: `2026-08-25T16:49:45.147065Z` (`start_ts_ns=1787676585147065258`).
  Report generated (session end of observation):
  `2026-08-27T17:31:20.151582Z`.
- Reboot window (from the BTCUSDT heartbeat history,
  `/opt/greenfield-v2/data/health/history/bybit-linear-btcusdt/2026-08-27.jsonl`):
  last heartbeat before the gap `2026-08-27T07:25:28.727831Z`
  (connection `2805da40...`, itself already `reconnect_count=1`), first
  heartbeat after recovery `2026-08-27T07:34:03.515639Z` (new connection
  `0bce9594...`, still the live connection today). Measured gap
  **514.788s** (BTC), 513.493s (ETH), 514.531s (SOL) - all far over the
  30.0s `maximum_heartbeat_gap_secs` acceptance threshold in
  `src/data/raw_soak.py` (unchanged).
- Zero dropped events on all three symbols throughout (34,553 / 33,9xx /
  33,9xx heartbeat samples), 1 reconnect each, max queue depth 749 (BTC) /
  648 (ETH) / 445 (SOL) - the gap is real downtime, not silent loss during
  the gap itself.
- Session marker, all raw data, and the JSON evidence report are
  untouched and not deleted, overwritten, or hidden. The prior session
  `phase1-20260822t183659z` marker is also untouched.

**REBOOT ROOT CAUSE.** `/opt/greenfield-v2/data`'s fstab entry uses
`nofail`, which lets the mount complete asynchronously without blocking
`local-fs.target`/`sysinit.target` - so `docker.service`'s implicit
ordering via those targets did not guarantee the mount was ready before
Docker started. Docker's `restart: unless-stopped` then retried the raw
collector containers immediately on boot, and each one hit its own
correct, fail-closed start gate (`src/data/raw_collector_start_gate.py`,
`Path(...).resolve(strict=True)` on the data dir) 5 times ("No such file
or directory: /app/data/health") before the mount became available -
adding restart-loop delay on top of the reboot's own unavoidable
downtime. This is the same failure class that disqualified the earlier
`phase1-20260822t183659z` attempt.

**RECOVERY FIX.** A systemd drop-in,
`/etc/systemd/system/docker.service.d/10-wait-for-greenfield-data-mount.conf`
(host-level config, not part of this git repo):
```ini
[Unit]
RequiresMountsFor=/opt/greenfield-v2/data
```
`RequiresMountsFor=` is systemd's purpose-built directive for this exact
case - it resolves to the correct mount unit and adds both `After=` and
`Requires=` automatically, including for `nofail` mounts. Applied via
`systemctl daemon-reload`. **Does not** make a reboot gap-free (the
collector is still down for the reboot's real duration regardless) -
only removes the extra failed-restart-loop delay/noise once the host is
back up. Deliberately verified **without** forcing a real reboot (per
standing instruction to ask before any full VPS reboot):
- `systemctl show docker.service --property=After,Requires` now lists
  `opt-greenfield\x2dv2-data.mount` in both.
- `systemd-analyze verify docker.service` exits 0 clean.
- `systemctl list-dependencies docker.service` shows the mount unit in
  the graph.
- These three checks are now a committed, reusable, no-reboot dry-run
  tool: `scripts/verify_docker_mount_ordering.py` (`uv run python
  scripts/verify_docker_mount_ordering.py`, exits 1 if any check fails),
  with its pure comparison logic (handling `systemctl show`'s C-style
  double-backslash quoting of escaped unit names) unit-tested in
  `tests/unit/test_verify_docker_mount_ordering.py` (4 tests, synthetic
  systemctl output including the real double-backslash-quoted case).
  Currently passes all 6 checks live against this host.

**NEW SOAK SESSION — `BLOCKED_INSUFFICIENT_DISK_CAPACITY`, not started.**
Attempted P3 exactly as specified: new dated checkout
(`/home/ubuntu/greenfield-phase1-soak-20260827`, `git worktree`, pinned
and clean at `fa7c69e533758f52ed1b3be8fcea997f41ea731b`), then
`scripts/preflight_phase1_vps.py` against `/opt/greenfield-v2/data`, then
a fresh, real, bounded (25.6s) live public Bybit BTC/ETH/SOL sample
(direct `RawBybitCollector` import bypassing the CLI start-gate for a
throwaway scratch directory - the same architectural pattern
`scripts/run_raw_okx_smoke.py` uses for OKX, since Bybit/Phase1 predates
and isn't covered by the venue-generic `raw_venue_smoke`/`raw_venue_soak`
framework), fed into `scripts/forecast_phase1_capacity.py`. Both fail on
real, current numbers, with **no thresholds changed**
(`burst_multiplier=4.0`, `runtime_reserve_gib=5.0`, `target_days=7.0`,
`minimum-free-gib=90.0` all defaults, untouched):
- `preflight_phase1_vps.py`: `data_disk_capacity` fails -
  `free_gib=50.53` vs. `required_gib=90.00`; `atomic_data_storage` also
  fails (write probe permission issue as `ubuntu`, not investigated
  further since capacity alone already disqualifies).
- `forecast_phase1_capacity.py` (measured rate **38.47 KB/s** from the
  live sample): `required_capacity_bytes=98,440,593,280`
  (91.68 GiB = stressed 4x projection 86.68 GiB + 5 GiB reserve) vs.
  `available_capacity_bytes=54,242,877,440` (50.51 GiB) →
  `projected_headroom_bytes=-44,197,715,840`, `qualified=false`.
  Reports: `reports/phase1_vps_preflight_20260827.json` and
  `reports/phase1_capacity_forecast_20260827.json` inside the new dated
  checkout (not committed to git, matching how the 2026-08-25 originals
  are also VPS-local operational evidence, not repo content).
- Volume total is only **97.87 GiB** (`/dev/sdb1`, 105,087,164,416 bytes);
  current used **42.37 GiB** (raw soak evidence 20G, Silver 15G, health
  262M, quality 241M, two storage-drill copies 3.8G+3.8G already flagged
  in the 2026-08-26 checkpoint as "kept pending a deliberate cleanup
  decision", klines/catalog/funding/etc. the remainder). The original
  2026-08-25 soak already qualified with only 3.79 GiB of headroom on a
  then-nearly-empty disk - this volume was marginal from day one and has
  no room left for a second full soak's stressed projection on top of
  everything else now living on it.
- **No destructive or capacity-freeing action taken**: raw soak evidence,
  Silver, catalog/quality, and the two storage-drill copies are all
  untouched, per explicit instruction. No acceptance gate
  (`maximum_heartbeat_gap_secs`, `minimum_duration_secs`,
  `burst_multiplier`, `runtime_reserve_gib`, `minimum-free-gib`) was
  changed to force a pass.
- **Capacity sizing for resuming P3 after a volume resize** (same
  measured rate, same unchanged gates, solving for a target total volume
  size `V` such that after the new soak's worst-case (4x-burst) 7-day
  write on top of everything already on the volume, `V` still has the
  requested persistent headroom left over):
  | Persistent headroom after soak | Minimum total volume `V` |
  |---|---|
  | 20% | **~161.3 GiB** |
  | 25% | **~172.1 GiB** |
  | 30% | **~184.4 GiB** |

  (`V = (current_used + new_soak_stressed_bytes) / (1 - headroom_fraction)`,
  with `current_used=42.37 GiB` and `new_soak_stressed_bytes=86.68 GiB`
  from the numbers above.) This does **not** model concurrent growth of
  other pipelines (Silver/curated/quality/future venues) during the 7
  days themselves, only the new soak's own footprint plus today's
  snapshot of everything else - a real provider resize should round up
  from these figures, not target them exactly. **Once the volume is
  resized, re-run P3 from this same checkpoint with the same, unchanged
  acceptance gates - do not shrink `burst_multiplier`/`reserve`/duration
  to fit a smaller resize instead.**
- Old (disqualified) soak containers (`greenfield-phase1-20260825-*`)
  deliberately left running and untouched - they are healthy, harmless
  to leave collecting (their data is retained as evidence regardless of
  qualification), and stopping them was only relevant as part of a P3
  handoff that is now blocked anyway.

**Next**: PROFITABILITY PIVOT continues on P5 (Hyperliquid↔Bybit
sensitivity/cost-attribution analysis) and other tracks that don't need
material extra storage, per explicit instruction; P3 resumes, unchanged,
once the volume is resized.

### Bieżący checkpoint — P5: Hyperliquid↔Bybit sensitivity/cost-attribution closes NO_CANDIDATE_CURRENT_MARKET_STRUCTURE (2026-08-27)

New versioned script, `scripts/analyze_hyperliquid_bybit_carry_sensitivity.py`
(+ `tests/unit/test_analyze_hyperliquid_bybit_carry_sensitivity.py`, 9
tests), reuses the parent screen's exact functions
(`simulate_episode`, `net_edge_for_scenario`, `cost_breakdown`,
`derive_cross_exchange_funding_edge`) - **no new engine, no retuning, the
parent screen's `NO_CANDIDATE` verdict and frozen parameters
(`HORIZON_HOURS=24`, `SAFETY_BUFFER_BPS=10.0`) are untouched.** Re-ran
against the same recorded live spread/capacity snapshot already on
record (same reasoning as before: HL top-of-book size is too noisy
second-to-second to re-fetch meaningfully). Report:
`reports/hyperliquid-bybit-funding-carry/sensitivity_manifest.json`
(committed, same `.gitignore` exception class as the parent's
`manifest.json` - no raw data, ~19KB).

- **A real methodology bug found and fixed before trusting any number**:
  the first run pooled BOTH directions (`long_bybit_short_hl` and
  `long_hl_short_bybit`) unconditionally per hour. `realized_basis_pnl_bps`
  and `realized_funding_pnl_bps` are each other's exact negation between
  the two directions by construction (see their docstrings in the parent
  script), so pooling both makes `mean_funding_differential_bps`,
  `mean_entry_basis_bps`-adjacent figures, and both realized-P&L means
  compute to **exactly 0.0** every time - a mirror-image cancellation
  artifact, not a real "funding/basis average to zero" finding. Fixed by
  selecting, once per hour, the direction a rational actor would actually
  pick (higher `expected_gross_edge_bps.base` - the same selection logic
  the parent screen's episode-entry loop already uses), and only
  recording that one direction's numbers. n dropped from 9,882 to 4,941
  observations per coin (2x → 1x, exactly as expected once mirrors are no
  longer double-counted).
- **Cost decomposition (pooled across BTC/ETH/SOL, corrected)**: average
  REALIZED gross edge (funding + basis P&L over the 24h horizon) is only
  **+1.55 bps** (funding +0.83bps, basis +0.71bps - entry basis averages
  +1.00bps but a large part reverts by exit, mean exit basis −0.86bps).
  Fees alone are **7.0 / 13.5 / 20.0 / 20.0 bps** (maker/maker,
  maker/taker, taker/taker, adverse) - fees exceed the entire average
  realized gross edge by 4.5x even in the cheapest (maker/maker) case.
  **Fees are the dominant cost category**, not basis, not slippage, not
  the LOW bound's uncertainty buffer - the edge is too small in the first
  place for any of those secondary costs to be the deciding factor.
- **Per-coin realized net-edge distributions** (median, all scenarios,
  all deeply negative): BTC maker/maker −5.6bps / taker/taker −18.6bps;
  ETH −5.4 / −18.4bps; SOL −5.6 / −18.6bps. Only maker/maker (and, for
  ETH/SOL, maker/taker and even taker/taker at their positive tail) ever
  shows a positive MAX across thousands of hourly observations - medians
  never approach the +10bps buffer under any real fee scenario.
- **Passive-entry / partial-maker-fill sensitivity sweep** (P5 point 4):
  swept assumed fill probability p ∈ {0, 0.25, 0.5, 0.75, 1.0}, blending
  REALIZED maker/maker and taker/taker outcomes and charging an
  adverse-selection penalty of `p × 10bps` (reusing the parent screen's
  own "adverse" scenario extra-slippage figure, not inventing a new
  number) - **no historical L2/tick book data exists for either venue to
  calibrate a real empirical fill probability**, so this is disclosed as
  a stated sensitivity sweep, not a forecast, and p=1.0 (guaranteed maker
  fill) is explicitly excluded from being the verdict basis. Even at
  p=1.0 - the most favorable point in the sweep, guaranteed maker fills
  on both legs, still net of the adverse-selection penalty - median net
  edge is **BTC −15.6bps, ETH −15.4bps, SOL −15.6bps**, roughly 25bps
  short of the +10bps buffer. This is not a close call at any point in
  the sweep.
- **Verdict: `NO_CANDIDATE_CURRENT_MARKET_STRUCTURE`** (P5 point 5,
  distinct from the parent screen's plain `NO_CANDIDATE` - this is the
  broader "not even a realistic maker/taker or passive-entry variant
  works" closure the instruction asked for). Robust check requires ALL of
  BTC/ETH/SOL to clear the buffer on a MEDIAN basis at some p < 1.0 -
  none do, not even close. **No promotion to SHADOW/PAPER/LIVE** - this
  remains backtest-only evidence.
- Validated: `ruff check .`, `mypy src scripts`, full `pytest -q`
  (1761+ tests), `git diff --check`, secret scan (baseline regenerated,
  timestamp-only diff), docker/monitoring compose config - all pass.
- **Next highest-value step**: per the standing instruction not to build
  new infrastructure without a direct P&L link, and with Hyperliquid↔Bybit
  now closed on both the coarse screen and this sensitivity follow-up,
  the next PROFITABILITY PIVOT priority is Track B (empirical
  order-flow-toxicity-veto research, preregistered hypothesis, BTC/ETH/SOL,
  no SHADOW/PAPER/orders) from the original multi-track instruction -
  still not started. Track A (OKX Phase 3) and Track C (ATAS bridge audit)
  remain available but lower-priority per that same instruction's
  "reuse/no-new-strategy-yet" framing until B has a first verdict. P3
  (new Bybit soak) stays `BLOCKED_INSUFFICIENT_DISK_CAPACITY` pending the
  user's volume-resize decision (sizing already delivered above).

### Odzyskany checkpoint — execution-quality probe + Track B prerejestracja (2026-08-28)

Przerwana praca Claude została odzyskana z VPS, przejrzana i domknięta na
osobnym branchu `codex/ml-model-tournament-v1`. Ten checkpoint jest wyłącznie
kodem i metodologią: **nie uruchomiono żadnego zlecenia Demo, nie wdrożono
probe i nie zatrzymano ani nie restartowano collectorów**.

- Dodano wyłączony domyślnie, jednorazowy Bybit Demo execution-quality probe
  dla BTC/ETH/SOL. Wymaga dwóch jawnych confirmation gates, jest przypięty do
  endpointu Demo, używa stałego 1x, ma twardy limit 100 USDT notional, osobny
  state store, dzienny limit/licznik/cooldown/kill-switch i natychmiastowy
  reduce-only flatten po dowolnym fillu. To generator dowodów TCA, nie
  strategia i nie sygnał.
- Dodano trwały SQLite journal obserwacji zleceń i top-of-book markoutów.
  Idempotentny replay identycznego rekordu jest dozwolony, ale konflikt pod
  tym samym `order_id` albo `(trade_id, horizon)` teraz kończy się fail-closed
  zamiast cichego `INSERT OR IGNORE`.
- Zamrożono prerejestrację Track B `order_flow_toxicity_veto` oraz skrypt
  wystarczalności danych. Próg 20 ciągłych dni Silver trades na każdy symbol
  jest niezmienny w CLI; brak którejkolwiek wymaganej cechy oznacza
  `INSUFFICIENT_FEATURES`/`WAIT`, a nie głos 0 dopuszczający wejście.
- Walidacja odzyskanego zakresu: targeted 24 tests, cały repo `ruff` i `mypy`
  czyste, `pytest -q` = 1779 passed / 6 skipped. Dwa testy peak-RSS są jawnie
  pomijane wyłącznie na Windows, ponieważ używają uniksowego modułu
  `resource`; pozostają aktywne na Linux CI/VPS. Skan sekretów i
  `git diff --check` czyste; złożony model Docker Compose zweryfikowany na
  VPS. Bybit BTC/ETH/SOL collectors pozostały healthy.

**Następny krok**: ML Model Tournament V1 według osobnej, zamrożonej
prerejestracji — wspólny setup/meta-label, prawdziwy expanding walk-forward z
purging/embargo, kalibracja i cost-aware gate dla Logistic/RF/ExtraTrees/
XGBoost/LightGBM. Żadnej promocji do SHADOW/PAPER/LIVE.

### Checkpoint — ML Model Tournament V1 zamknięty REJECT (2026-08-28)

- Feature branch: `codex/ml-model-tournament-v1`; implementacja i global-ledger
  binding znajdują się w commitach `dbcd11f` i `2b67727`. XGBoost/LightGBM
  korzystają z tego samego feature schema, setupów, expanding walk-forward,
  purging/embargo, calibration tail i cost-aware gate co Logistic/RF/
  ExtraTrees. Budżet pozostał zamrożony na 14 trialach.
- Definitywny real-data run: 3337 setupów BTC/ETH/SOL, 666-obserwacyjny holdout,
  `holdout_id=c58baab7671a373d5ebf`. Wszystkie próby zapisano w istniejącym
  append-only ledgerze jako `TRIAL-000101`–`TRIAL-000114`; globalne 114 prób
  uwzględniono w DSR. Ponowna próba użycia tego holdoutu kończy się fail-closed.
- `winner=null`, `verdict=REJECT`. ExtraTrees, Logistic i LightGBM wybrały WAIT
  dla całego holdoutu. RF uzyskał +0.019885 base tylko na 4 transakcjach i zero
  adverse. XGBoost stracił -0.115067 base na 19 transakcjach, mimo +0.016760
  adverse na 5; DSR odpowiednio 0.042420 i 0.000594. Żaden model nie spełnił
  bramki dodatniego base+adverse i minimum 30 transakcji w obu scenariuszach.
- Pełne wyniki i ograniczenia są w `docs/ML_MODEL_TOURNAMENT_V1.md`. Manifest
  VPS SHA-256 to
  `8f0b6e63fe570cc31af540e2c93efa42e687ee0e8a4a3b66e8481f73467c0054`;
  wygenerowany raport nie jest commitowany zgodnie z polityką repo.
- Podczas pierwszego definitywnego zapisu ujawniono operacyjny owner mismatch
  (`root:root`) globalnego ledgera. Nie było częściowego wpisu; zawężono zmianę
  do właściciela jednego pliku, powtórzono identyczny zamrożony przebieg i
  zapisano komplet 14 rekordów. Nie zmieniono feature'ów, etykiet, parametrów
  ani kosztów po zobaczeniu holdoutu.
- Bybit BTC/ETH/SOL collectors pozostały uruchomione i sequence-verified; nie
  wykonano żadnego zlecenia, SHADOW/PAPER/LIVE pozostają wyłączone.

**Następny prerejestrowany eksperyment**: Triple Barrier labels na nowym
chronologicznym holdoucie. Nie stroić ani nie otwierać ponownie Tournament V1.

### Checkpoint — Triple Barrier Labels V1 zamknięty REJECT (2026-08-28)

- Prerejestracja `c7d8dcb`, implementacja `9c80222`, branch
  `codex/triple-barrier-labels-v1`. Zamrożone bariery 2 ATR PT / 1 ATR SL /
  24h vertical; same-bar collision rozstrzygany konserwatywnie jako stop.
- Zużyty holdout ML Tournament V1 został całkowicie wykluczony. Screen użył
  2669 wcześniejszych, identycznych fixed/triple kandydatów i pięciu expanding
  folds. Wykonano 50 dopasowań model-fold oraz wszystkie scenariusze kosztów.
- Triple Barrier poprawił Brier każdej rodziny, ale nie stabilny net edge.
  Najlepszy ekonomicznie Triple RF: +0.007155 base (98 trades), +0.058593
  adverse (tylko 8 trades), DSR 0.005045. Triple XGBoost: -0.218680 base i
  -0.085697 adverse. Żadna rodzina nie spełniła bramki.
- Globalny ledger ma teraz 124 wpisy, z nowymi `TRIAL-000115`–`TRIAL-000124`.
  `winner` nie istnieje, werdykt `REJECT`, brak SHADOW/PAPER/LIVE.
- Manifest VPS SHA-256:
  `1ed33fc21bdc80d40d0553fc4232c43da4e516bc77ab501995472f70d3350333`.
  Bybit BTC/ETH/SOL collectors pozostały healthy i nie były restartowane.

**Wniosek**: nie stroić barier ani boosting models na tych danych. Kolejny
eksperyment powinien zmienić źródło informacji/sampling, nie tylko złożoność
klasyfikatora; Track B order-flow toxicity pozostaje prerejestrowany, ale jego
twardy próg 20 ciągłych dni Silver musi zostać zachowany.

### Checkpoint — Binance public archive Bronze + streaming trade Silver (2026-08-28)

- Branch `codex/binance-historical-market-backfill-v1`, pierwszy commit
  `8b16e68`. `configs/binance_public_archive.yaml` definiuje BTC/ETH/SOL spot
  i USD-M trades/aggTrades, funding, 1m mark/index/premium oraz daily metrics.
- `scripts/backfill_binance_public_archive.py` robi równoległy HEAD inventory,
  twardy budget/reserve gate, oficjalny checksum download i atomowe manifesty.
  Probe lipca 2026: 24/24 miesięcznych archiwów dostępne, 5,184,285,056 bytes
  compressed; pełna wieloletnia kopia nie mieści się przy 47 GB free.
- `scripts/normalize_binance_trade_archives.py` oraz
  `src/data/binance_trade_archive.py` strumieniowo materializują trades i
  aggTrades do Silver Parquet bez ładowania miesiąca do RAM. Milisekundy i
  spotowe mikrosekundy są normalizowane do UTC; buyer-maker daje poprawny znak
  delty. Ścisły `(timestamp, trade_id)` order i checksums są fail-closed.
- Pełny test repo po pierwszym commitcie: ruff clean, mypy 347 source files,
  pytest 1803 passed / 6 skipped. Pierwszy pełny Binance funding archive run
  wystartował jako `greenfield-binance-funding-backfill.service` w izolowanym
  worktree; Bybit collectors pozostały sequence-verified i bez dropów.

**Następna kolejność bez strojenia strategii**: zamknąć real funding run,
uruchomić mark/index/premium + metrics, wykonać mały real trade ZIP→Silver
proof, dopiero potem pobrać ograniczony najnowszy miesiąc BTC/ETH/SOL spot i
perp oraz zbudować wspólny clock/CVD/footprint baseline.

### Checkpoint — Binance common clock + ATAS/MC-like feature bridge (2026-08-28)

- Funding backfill zakończył się sukcesem: 229 realnie dostępnych miesięcznych
  archiwów, wszystkie z oficjalnym `.CHECKSUM`; brakujące miesiące pozostały
  jawnie niedostępne. Nie utworzono sztucznych plików.
- Pierwszy historyczny proof (`BTCUSDT` spot trades 2017-08) wykrył stary
  beznagłówkowy wariant Binance CSV. Commit `ae1915a` dodał jawne schematy
  legacy; ponowny run zapisał 69,180 wierszy Silver z manifestem.
- `src/features/binance_archive_flow.py` dodaje przyczynowe trade bars,
  historyczne delta/CVD/VWAP, dokładny wspólny zegar spot-perp i basis oraz
  wektorowy footprint/imbalance i POC/VAH/VAL. Istniejąca clean-room rodzina
  MC-like jest podłączona do tych samych OHLCV, bez kodu własnościowego.
- Na VPS działa ograniczony backfill i streamingowa normalizacja lipca 2026
  dla sześciu strumieni `trades`. Osobna niskopriorytetowa kolejka derivatives
  jest ustawiona po nim; oba tory zachowują 20 GiB hard reserve i nie dotykają
  collectorów Bybit.

**Następny krok**: zapisać Gold partycje i lineage dla ukończonego okresu,
znormalizować funding/metrics/reference prices, policzyć coverage i dopiero na
wspólnym OOS uruchomić prerejestrowane baselines. `aggTrades` rozszerzać po
pomiarze rzeczywistego ZIP→Silver ratio, aby nie zdublować danych kosztem
bezpieczeństwa wolumenu.

### Checkpoint — Binance funding Bronze→Silver (2026-08-28)

- Dodano ścisły normalizer miesięcznych `fundingRate`: oczekiwany provider
  schema, UTC, dodatni interval, skończony rate, monotoniczny unikalny czas,
  atomowy Parquet i source/output SHA-256 lineage.
- CLI odkrywa wyłącznie realnie pobrane archiwa i zachowuje hard reserve;
  idempotentny replay wymaga zgodności obu checksumów.
- Targeted walidacja: ruff/mypy clean i 2 testy parsera/idempotencji. Realny
  run 229 archiwów jest następną odłączoną operacją po zakończeniu ciężkiej
  normalizacji trade tape.

### Checkpoint — Binance historical Gold materializer (2026-08-28)

- Dodano zamknięto-okresowy Silver→Gold job dla BTC/ETH/SOL. Dla każdego
  symbolu zapisuje osobno spot/perp bars, footprint, Volume Profile i MC-like
  oraz dokładnie zsynchronizowany `spot_perp_flow`.
- Manifest wiąże SHA-256 obu wejść Silver, parametry tick/frequency, wszystkie
  output checksums i row counts. Ponowne wykonanie jest idempotentne tylko przy
  pełnej zgodności dowodu; puste wyjście i naruszenie rezerwy dysku failują.
- CVD ma na tym etapie jawny `cvd_scope=period`; nie jest przedstawiany jako
  wieloletni ciągły CVD. Cross-period offset pozostaje osobnym wymaganiem przed
  masowym walk-forward.

### Checkpoint — historical L2 provider gate (2026-08-28)

- Oficjalny Bybit REST daje aktualny snapshot, nie replay 30–90 dni. Tardis
  dokumentuje prawdziwe Bybit incremental L2 oraz darmowy pierwszy dzień
  miesiąca; exact sample URL i kryteria przyjęcia zapisano w
  `docs/HISTORICAL_L2_ACQUISITION.md`.
- GET/Range z Windows i VPS zwrócił Cloudflare 403, a zwykła sesja browserowa
  została zablokowana przez klienta. Nie przyjęto danych, nie policzono coverage
  i niczego nie kupiono. Następny krok wymaga provider-supported sample path;
  zakup wymaga osobnej zgody na konkretną cenę.

### Checkpoint — Binance retained-coverage evidence (2026-08-28)

- Dodano `scripts/audit_binance_archive_coverage.py` i ścisły moduł audytu,
  który osobno raportuje faktycznie zachowane okresy Bronze, znormalizowane
  okresy i liczbę wierszy Silver oraz materializacje Gold.
- Wspólny okres `trades` albo `aggTrades` jest deklarowany dopiero, gdy istnieje
  we wszystkich sześciu strumieniach: spot i USD-M perp dla BTC/ETH/SOL.
  Analogicznie okres Gold jest kompletny dopiero przy wszystkich trzech
  symbolach. Braki nie są forward-fillowane ani syntetyzowane.
- Raport nie nadaje automatycznie statusu OOS-ready: wymagane pozostają osobne
  bramki jakości, lineage i zamkniętego okresu. Job produkcyjny zostanie
  uruchomiony dopiero po zakończeniu bieżących kolejek trades, funding,
  derivatives i Gold.

### Checkpoint — Binance derivatives Bronze→Silver (2026-08-28)

- Na podstawie realnych oficjalnych plików (nie założonego schematu) dodano
  normalizację miesięcznych 1m `markPriceKlines`, `indexPriceKlines` i
  `premiumIndexKlines` oraz dziennych 5m `metrics`.
- Silver zachowuje mark/index/premium OHLC i czasy otwarcia/zamknięcia, a
  metrics zachowuje OI, OI value, top-trader/account long-short oraz taker
  long-short ratio dla BTC/ETH/SOL. Schemat, symbol, czas, monotoniczność,
  duplikaty i wartości skończone są sprawdzane fail-closed.
- Każda partycja ma source/output SHA-256 lineage, atomowy zapis, idempotencję
  i 20 GiB produkcyjnej rezerwy. To wypełnia tor OI/reference-price; pełna
  historyczna taśma likwidacji nadal wymaga osobnego, udowodnionego źródła.

### Checkpoint — bounded aggTrades continuation (2026-08-28)

- Gold CLI obsługuje teraz jawny wybór `trades` albo `aggTrades`; manifest i
  katalog wyjściowy już rozdzielają te rodziny, więc nie ma nadpisywania.
- Po zakończeniu aktualnej kolejki zaplanowany jest wyłącznie zamknięty lipiec
  2026 dla sześciu strumieni aggTrades, z osobnym download budget i twardą
  rezerwą 20 GiB. Dopiero pomiar jego ZIP→Silver→Gold określi bezpieczny zakres
  dalszej historii; nie uruchamia się pełnego wieloletniego mirrora w ciemno.

### Checkpoint — continuous historical CVD (2026-08-28)

- Dodano deterministyczny stitcher zamkniętych partycji. Weryfikuje pojedynczą
  tożsamość strumienia, brak nakładania czasu, duplikatów i zgodność lokalnego
  CVD z `trade_delta`, po czym przyczynowo przelicza jeden ciągły CVD.
- Wynik ma jawne `source_period` i `cvd_scope=continuous`. Uszkodzony albo
  mieszany strumień failuje zamiast tworzyć pozorną wielomiesięczną historię.

### Checkpoint — produkcyjna naprawa Binance Silver/Gold (2026-08-29)

- Audyt faktycznych jednostek systemd wykazał cztery niezależne przyczyny
  zatrzymania kolejki: provider replay w spot ETH, chwilowy DNS w downloaderze,
  brak katalogu roboczego w późniejszych jednostkach oraz OOM miesięcznego
  Gold. Zdrowych collectorów Bybit nie zatrzymano ani nie restartowano.
- Spot ETH został naprawiony bez wyłączenia walidacji. Provider powtórzył
  dokładnie 259,000 rekordów; bounded recent-replay dedupe zaakceptował tylko
  byte-equivalent normalized rows. Wynik: 70,199,896 rekordów, zakres całego
  2026-07 i atomowy SHA-256 manifest. Spot SOL zapisał 18,385,315 rekordów bez
  deduplikacji.
- Downloader reference prices został ponowiony z poprawnym working directory;
  derivatives normalizer zapisał 131 realnych partycji. Jedyny nowy wyjątek,
  dzienny metrics ETH 2026-07-17, miał 288 unikalnych lecz przetasowanych
  snapshotów. Metrics są teraz stabilnie sortowane po czasie i nadal odrzucają
  duplikaty.
- Gold ma bounded-memory opcję `--day YYYY-MM-DD`, partycję `date=...`, jawny
  `cvd_scope=day` i ścisłą kompletność miesiąca w coverage. Realny proof BTC
  2026-07-01 zapisał komplet dziewięciu wyjść (m.in. 1,440 barów i 554,315
  poziomów footprint spot) z memory peak 117.5 MB. Wspólna siatka BTC 0.01
  zachowuje legalne ceny spot i jest nadzbiorem kroku futures 0.1.
- Odłączona kolejka VPS: `greenfield-binance-gold-july-daily.service`, potem
  `greenfield-binance-aggtrades-july.service`, a na końcu
  `greenfield-binance-coverage-final.service`. Wszystkie używają checkoutu
  `/home/ubuntu/greenfield-binance-backfill`, niskiego priorytetu I/O i rezerwy
  20 GiB. Coverage nie nadaje automatycznie statusu OOS-ready.
- Dodano osobny finalizer kompletnego okresu. Nie skleja wielkich trade tape:
  waliduje wszystkie dzienne manifesty i checksums, następnie łączy małe bary,
  przelicza CVD bez resetów dziennych, ponownie liczy MC-like z jedną ciągłą
  rozgrzewką i odtwarza exact-clock spot/perp. Brak choć jednego dnia failuje;
  wynik ma jawne zakresy `continuous_period`.

### Checkpoint — lipiec Binance OOS-ready, baseline REJECT (2026-08-30)

- Commit `9e14089` zastąpił zbyt sztywną tolerancję CVD ograniczeniem zależnym
  od skumulowanej skali flow. Produkcyjny continuous Gold przeszedł dla
  BTC/ETH/SOL bez akceptowania materialnej rozbieżności.
- Commit `dbc56dd` dodał archiwalną bramkę quality/lineage. Pełny VPS audit
  przeskanował 438,788,719 rekordów `trades`; 6/6 Silver i 3/3 continuous Gold
  przeszły checksum, schema, identity, closed-period, ordering, duplicate i
  daily-lineage checks. Raport:
  `/opt/greenfield-v2/data/reports/binance-public-archive/quality-trades-2026-07-final-v1.json`.
- Coverage potwierdza wspólny lipiec dla `trades` i `aggTrades` we wszystkich
  sześciu spot/perp × BTC/ETH/SOL strumieniach. Na wolumenie zostało około
  31 GiB, twarda rezerwa nadal wynosi 20 GiB.
- Commit `3677f93` zamroził protokół przed pierwszym uruchomieniem: druga połowa
  lipca OOS, wejście minutę po sygnale, brak overlap, horyzonty 5/15/60 min i
  12 bps kosztu round-trip. Raport `reports/binance-public-archive/
  baselines-2026-07-v1.json` zawiera 18 wyników oraz input/preregistration
  checksums.
- Wszystkie wyniki netto są ujemne. Najmniej ujemny: ATAS-like ETH 60 min,
  średnio +4.795 bps brutto / -7.205 bps netto, 220 zdarzeń. MC-like również
  nie pokonał kosztów na żadnym symbolu ani horyzoncie.
- Werdykt `NO EDGE / EXPLORATORY ONLY`; `promotion_allowed=false`. Nie włączać
  SHADOW/PAPER i nie stroić parametrów na lipcu. Następna kolejność: bezpieczny
  backup/prune Bronze+Silver lipca, czerwiec → Silver/Gold → ten sam audit i
  dokładnie ten sam frozen baseline; dopiero kilka niezależnych okresów daje
  materiał do walk-forward.
- CI HEAD `9da43d9` jest zielone. Collectory Bybit BTC/ETH/SOL pozostały healthy
  i nie były restartowane.

### Checkpoint — zweryfikowana rotacja lipca i rolling preregistration (2026-08-30)

- Commit `5e2f6f8` dostarczył fail-closed rotację kompletnego miesiąca. Lipiec
  `trades/aggTrades` miał dokładnie 48 wymaganych plików Bronze/Silver i
  11,159,153,155 bajtów. Każdy plik skopiowano i sprawdzono SHA-256 przed
  usunięciem źródła.
- Kopia znajduje się w `/home/ubuntu/greenfield-monthly-backups/2026-07` na
  `/dev/sda1`, podczas gdy lake działa na `/dev/sdb1`. To chroni przed awarią
  wolumenu danych, ale nadal jest kopią na tym samym VPS, a nie off-host DR.
  `rotation-manifest.json` ma `qualified=true`, a `prune-evidence.json` ma
  `source_pruned=true`. Niezależny restore proof odtworzył spot SOL trades ZIP
  na wolumen lake, potwierdził byte-identical copy oraz zgodny SHA-256,
  po czym usunął wyłącznie plik tymczasowy. Gold oraz raporty
  jakości/baseline pozostały online.
- Wolne miejsce lake wzrosło z około 31 do 41 GiB. Collectory Bybit pozostały
  `running/connected`, kolejki 0, dropy 0, continuity verified.
- Commit `0bda886` zamroził przed pierwszym pozalipcowym wynikiem rolling
  protocol v1: pierwsza dokładna połowa każdego zamkniętego miesiąca jest
  warm-up, druga połowa OOS; pozostałe hipotezy, koszty i horyzonty są
  bit-identyczne z lipcem. Czerwiec został rozpoczęty z rezerwą 20 GiB.
  Na wyraźną decyzję operatora kolejne etapy i miesiące mają hard floor 5 GiB;
  bieżąca normalizacja zachowuje swój już uruchomiony próg 20 GiB.
- Zamrożony extended tournament uruchomiono na gotowym lipcu: 36 kombinacji
  czterech dodatkowych rodzin × BTC/ETH/SOL × 5/15/60 min. Wszystkie są ujemne
  netto po 12 bps. Najlepszy `price_mean_reversion_v1`, ETH 60 min: 152
  zdarzenia, +7.41 bps średnio brutto i -4.59 bps netto. Werdykt pozostaje
  `EXPLORATORY ONLY / NO PROMOTION`; parametry nie zostały zmienione.

### Checkpoint — wrażliwość maker/taker (2026-08-30)

- Baseline raportuje teraz, obok zachowanego konserwatywnego kosztu 12 bps,
  trzy jawne scenariusze all-in: maker/maker 6 bps (4 bps fee + 2 bps bufor),
  maker/taker 9 bps (7.5 + 1.5) i taker/taker 13 bps (11 + 2).
- Pełne uruchomienie na danych źródłowych policzy osobno mean/median, win rate
  i compound return każdego scenariusza. Raport jawnie zapisuje
  `maker_fill_probability_modeled=false`; samo PostOnly nie gwarantuje fillu.
- Wrażliwość istniejących 36 zagregowanych wyników lipca: tylko ETH 60 min
  `price_mean_reversion_v1` pozostaje dodatni przy maker/maker (+1.41 bps
  średnio). Przy maker/taker (-1.59 bps) i taker/taker (-5.59 bps) jest ujemny;
  wszystkie pozostałe kombinacje są ujemne nawet przy maker/maker. Werdykt
  nadal `EXPLORATORY ONLY / NO PROMOTION`.

### Checkpoint — PostOnly sensitivity i Selective Gate v0 (2026-08-30)

- Kosztowy baseline raportuje teraz trzy jawnie niekalibrowane warianty
  PostOnly: pełny fill, partial fill, miss po timeout i adverse selection.
  Każdy wynik jest liczony per opportunity po oczekiwanej części wykonanego
  nominału. Nie ma założenia gwarantowanego fillu.
- Dodano fail-closed `SELECTIVE_GATE_V0`. Wymaga co najmniej dwóch unikalnych
  okresów, pełnego wsparcia zdarzeń oraz dodatniego mean/median po
  konserwatywnym scenariuszu kosztów w każdym okresie. Risk veto zawsze daje
  `WAIT`; nawet PASS oznacza wyłącznie `RESEARCH_CANDIDATE`.
- Próba na jedynym dostępnym raporcie extended z lipca poprawnie zwróciła
  `WAIT` dla wszystkich 36 kombinacji z powodem
  `INSUFFICIENT_INDEPENDENT_PERIODS`. Czerwiec pozostaje blockerem danych,
  a nie powodem do obniżenia bramki.
- Izolowany VPS replay na realnym lipcowym continuous Gold utworzył raporty
  `baselines-2026-07-v2.json` (SHA-256 `d736edd4591363cda976db09bc850fa03773e4fef9c006533970fff9d7bba609`)
  i `extended-baselines-2026-07-v2.json` (SHA-256
  `34d19f1b2620b4badcb18fe87cfc0a9061c378fc30e48887dbd4bfec6e17b0ab`).
  Najlepszy extended ETH 60 min: gross +7.412 bps, maker/maker +1.412,
  maker/taker -1.588, taker/taker -5.588 oraz bazowy PostOnly/taker-exit
  expected -1.884 bps per opportunity. Parametry sygnału pozostały zamrożone.

### Checkpoint — prerejestracja quarter-hour order-flow v0 (2026-08-30)

- Przed obejrzeniem wyniku zamrożono clean-room replikację hipotezy
  quarter-hour opening order flow z publicznej pracy Kim/Hansen (2026).
- Test używa wyłącznie BTC/ETH/SOL Binance perpetual Gold 1 min. Imbalance z
  pierwszego pełnego baru rozpoczynającego minuty 00/15/30/45 wyznacza kierunek;
  próg 80. percentyla jest liczony tylko z wcześniejszej połowy miesiąca.
- Wejście jest opóźnione o pełną minutę, horyzonty 4/8/12 h, zdarzenia nie mogą
  się nakładać. Raport zachowuje maker/maker, maker/taker, taker/taker oraz
  niekalibrowaną wrażliwość PostOnly.
- Czerwiec i lipiec są wyłącznie dwiema replikacjami historycznymi. Wymagany
  pozostaje późniejszy forward-OOS; dodatni maker-only wynik nie zezwala na
  SHADOW/PAPER/LIVE.
- Pierwszy zamrożony replay lipca dał 1/9 wynik wyraźnie dodatni po pełnym
  taker/taker: ETH 12 h, 28 niepokrywających się zdarzeń, +34.359 bps gross,
  +21.359 bps mean net i +27.506 bps median net. Bazowa wrażliwość
  PostOnly/taker-exit wynosi +12.264 bps per opportunity. BTC 8 h ma dodatnią
  średnią +1.688 bps,
  ale ujemną medianę -13.578 bps; pozostałe 7/9 są ujemne.
- To jest pojedynczy, mały miesiąc. Parametrów nie zmieniono; wynik pozostaje
  hipotezą do odrzucenia lub potwierdzenia na czerwcu i późniejszym forward-OOS.
- Empiryczny execution probe został uruchomiony na Bybit Demo po potwierdzeniu
  zerowej ekspozycji. Pierwszy ETH maker probe (30 USDT, 1x) został wypełniony,
  natychmiast reduce-only spłaszczony i zamknięty z PnL -0.01839428 USDT.
  Dane fill/fee/latency/markout są w osobnym probe journal i nie są sygnałem.
- Naprawiono blokujący błąd CLI (Typer nie obsługiwał opcji `Decimal`). Dodano
  bezpieczny wrapper i systemd timer co dwie godziny, rotujący BTC/ETH/SOL z
  trwałym request ID, 12 prób/dobę i osobnym ledgerem. Kalibracja pozostaje
  nieważna do osiągnięcia minimalnej liczby próbek i walidacji train/test.
- Selective Gate pozostaje `WAIT`: ETH 12 h ma tylko 28 zdarzeń, poniżej
  niezmienionego minimum 30. Zamrożono pełny wrzesień jako forward-OOS; próg
  80. percentyla zostanie wcześniej ustalony z kompletnych czerwca+lipca.
  Sierpień jest pominięty, ponieważ prerejestracja powstała pod koniec miesiąca.
- Operacyjny runner Selective Gate v0 nie przyjmuje już nadpisywalnych progów
  ani scenariusza kosztowego: używa zamrożonego `taker_taker`, 3 bps bufora i
  domyślnego risk veto. Raport jest atomowy, immutable i zawiera SHA-256 obu
  wejściowych raportów miesięcznych, więc czerwiec/lipiec można audytowalnie
  odtworzyć bez dostrajania po wyniku.
- Bramka scala wiele prerejestrowanych rodzin z tego samego miesiąca przed
  porównaniem okresów i fail-closed odrzuca powtórzoną tożsamość
  `family/symbol/horizon`. Pozwala to ocenić razem ATAS-like, MC-like,
  extended oraz quarter-hour bez udawania, że są osobnymi miesiącami.
- Przed wynikiem czerwca zapisano przyszły kierunek „black horse” w
  `PREREGISTRATION_GLOBAL_ORDER_FLOW_SELECTIVE_V0.md`: common order flow
  BTC/ETH/SOL, osobne modele fillu i wyniku po fillu, cost-aware lower bound
  oraz ranking top 1%/5%. Kod modelu nie powstaje jeszcze — twarde minimum to
  12 zamkniętych miesięcy i 100 empirycznych prób per symbol/mode.
- Skorygowano optymistyczne założenie wyjścia PostOnly: raport zachowuje
  osobno maker exit i taker exit, ale primary jest teraz taker exit. Ponowny
  replay lipca nie zmienił gross ani standardowych maker/taker/taker wyników;
  zmienił tylko primary PostOnly expected. Immutable raporty: base v4
  `4b39ab1d...77bd`, extended v4 `6b5bef21...b600`, quarter-hour v3
  `280f6971...6ca4`.
