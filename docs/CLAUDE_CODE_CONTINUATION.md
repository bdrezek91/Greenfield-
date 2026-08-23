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
   `rest_poller.py`). Coinbase świadomie pominięty dla tego wzorca
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
   NautilusTrader z venue BINANCE), nie tylko testami syntetycznymi.
   OKX/Coinbase/Deribit nadal nie mają odpowiednika — naturalne,
   dobrze zdefiniowane rozszerzenie tego samego wzorca, nie nowy projekt.

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
