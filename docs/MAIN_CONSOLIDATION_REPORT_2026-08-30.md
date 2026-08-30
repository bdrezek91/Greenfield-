# Greenfield — raport konsolidacji do `main`

Data: 2026-08-30

## 1. Cel i źródło konsolidacji

Źródłem jest commit `b0f8ae4` z brancha
`codex/binance-historical-market-backfill-v1`. Jest on liniowym następcą
dotychczasowego `main` i zawiera 351 commitów rozwoju projektu. Konsolidacja
nie włącza automatycznie rozbieżnych eksperymentów tylko dlatego, że istniały
na osobnym branchu.

## 2. Co zbudowano

### Rdzeń badawczy i bezpieczeństwo

- odtwarzalne środowisko Python/uv, obrazy Docker, CI, typowanie i rozbudowany
  zestaw testów;
- Experiment Factory z prerejestracją, globalnym ledgerem prób, OOS,
  walk-forward, PBO/Monte Carlo i bramkami promocji;
- backtesting z prowizjami, spreadem, slippage, fundingiem, partial fillami,
  mark-to-market i kontrolami look-ahead;
- risk engine, kill-switch, limity portfela, trwała rekonsyliacja oraz zasada
  fail-closed. LIVE pozostaje osobno autoryzowany i wyłączony.

### Dane Bronze, Silver i Gold

- collectory i kontrakty replay dla Bybit oraz fundamenty Binance, OKX,
  Coinbase i Deribit;
- immutable raw envelopes, manifests/checksumy, quarantine, quality/lineage,
  katalog danych, capacity forecast, backup/restore proof i bezpieczna rotacja;
- normalizacja Silver i Gold dla trade flow, L2, footprintu, CVD, Volume
  Profile, VWAP/AVWAP, interakcji płynności oraz historycznych barów;
- historyczny backfill Binance spot/perpetual BTC, ETH i SOL oraz wspólny zegar
  spot-perp.

### Cechy i decyzje

- ATAS-like: delta/CVD, footprint, imbalance, sweep, absorption/exhaustion,
  POC/VAH/VAL i profile wolumenu;
- MC-like: momentum/money-flow, RSI i dywergencje bez kopiowania kodu ani
  prywatnych formuł;
- funding, OI, basis, crowding, likwidacje, opcje, cross-market, regimes i
  embargoed historical analogs;
- sześć niezależnych rodzin evidence, Meta Engine oraz kontrakty
  `LONG/SHORT/WAIT/ARBITRAGE`;
- SHADOW/PAPER/Bybit Demo skeleton z idempotencją, recovery, reduce-only,
  monitoringiem i trwałym audytem. Dwie eksperymentalne wersje scalpera
  wycofano; zachowano bezpieczną infrastrukturę egzekucji.

## 3. Wyniki empiryczne do chwili konsolidacji

- lipiec 2026 przeszedł pipeline i prerejestrowane baseline'y, lecz wszystkie
  podstawowe ATAS-like/MC-like wyniki były ujemne netto;
- czerwiec 2026 przeszedł pełny Bronze→Silver→Gold→quality/lineage i otrzymał
  `oos_ready=true`;
- wspólny Selective Gate dla czerwca i lipca ocenił 63 tożsamości strategii:
  **63 `WAIT`, 0 `RESEARCH_CANDIDATE`**;
- pojedyncze dodatnie średnie nie były stabilne pomiędzy miesiącami albo nie
  miały minimalnego wsparcia zdarzeń;
- Hyperliquid↔Bybit carry zakończył się `NO_CANDIDATE`; model tournament i
  triple-barrier screen również nie dały kandydata;
- model kosztów rozdziela maker/maker, maker/taker i taker/taker. Post-Only
  uwzględnia full/partial/miss, timeout i adverse selection zamiast zakładać
  gwarantowany fill;
- dostępne probe'y Bybit Demo potwierdziły przykładowo około 2.0 bps maker i
  5.5 bps taker, ale próbka jest zbyt mała do kalibracji.

Wniosek jest celowo konserwatywny: infrastruktura badawcza działa, ale nie ma
jeszcze dowodu stabilnej przewagi pozwalającej na SHADOW/PAPER/LIVE.

## 4. Walidacja kandydata na `main`

Na czystym checkoutcie Windows wykonano:

- `uv sync --all-extras` — sukces;
- `uv run ruff check .` — sukces;
- `uv run mypy src scripts` — sukces, 375 plików źródłowych;
- `uv run pytest -q` — 1868 passed, 6 skipped;
- `git diff --check` — sukces;
- skan sekretów względem `.secrets.baseline` — bez nowego wyniku.

Jedyny komunikat to `FutureWarning` Pandas w konstrukcji danych jednego testu;
nie jest to awaria ani błąd ścieżki produkcyjnej. Lokalny host nie ma Dockera,
dlatego budowę obrazów, Compose i monitoring weryfikuje GitHub Actions.

## 5. Decyzje dotyczące rozbieżnych branchy

Poniższe tipy nie wchodzą do finalnego `main`:

- `2252062` — stary dokumentacyjny checkpoint Phase 1 VPS;
- `32b4745` — osobny Financial Decision Cockpit, który usuwa większość
  Greenfield i nie jest kontynuacją obecnej architektury;
- `4a3714e` wraz z siedmioma poprzedzającymi commitami `gpt-branch` — stary
  eksperymentalny protokół, między innymi obniżający próg Deflated Sharpe.

Pozostałe branche są przodkami finalnego tipa albo starymi aliasami. Usunięcie
branchy nie oznacza scalania wymienionych eksperymentów.

## 6. Dane i ograniczenia operacyjne

- czerwcowe i lipcowe raw trades/aggTrades przeszły checksumowany backup,
  restore proof i rotację; Gold oraz kompaktowe raporty pozostają online;
- według ostatniego checkpointu lake miał około 40 GiB wolnego, ale lokalny
  wolumen backupu tylko około 13 GiB;
- kolejny pełny miesiąc raw wymaga off-host object storage albo dodatkowego
  wolumenu. Niezabezpieczonych raw danych nie wolno usuwać;
- collectory BTC/ETH/SOL były healthy, lecz ich bieżący stan należy zawsze
  potwierdzić read-only na VPS przed decyzją operacyjną.

## 7. Rekomendowany dalszy kierunek

1. Zapewnić off-host storage i automatyczny, okresowo odtwarzany backup.
2. Zebrać co najmniej 12 niezależnych zamkniętych miesięcy oraz minimum 30 dni
   kompletnego L2/trades dla BTC, ETH i SOL.
3. Zebrać co najmniej 100 probe'ów na każdy bucket symbol × maker/taker i
   skalibrować fill probability, timeout oraz adverse selection na danych
   train/test.
4. Zrealizować zamrożony `PASSIVE_TOXICITY_GATE_V0`, którego domyślna decyzja
   pozostaje `SKIP`; oddzielić model prawdopodobieństwa fillu od modelu wyniku
   po fillu.
5. Przeprowadzać tylko prerejestrowane miesięczne replaye i pełny forward-OOS
   bez dostrajania po obejrzeniu wyniku.
6. Dopiero po stabilnym wyniku netto w wielu okresach rozważyć SHADOW, potem
   PAPER. LIVE_SMALL wymaga osobnej zgody i spełnienia wszystkich bramek.

Najbardziej wiarygodny „czarny koń” nie jest nowym wskaźnikiem kierunkowym,
lecz selekcją jakości egzekucji: odrzucaniem toksycznych filli i wyborem
`SKIP/POST_ONLY/TAKER` tylko wtedy, gdy dolna granica EV pokrywa realne koszty
oraz bufor bezpieczeństwa.
