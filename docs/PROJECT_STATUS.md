# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 2)

---

## CURRENT PHASE

**PHASE 2 — Data engine** — UKOŃCZONA.

Warstwa danych (`src/data`) jest zaimplementowana i przetestowana: pobieranie
klines z Bybit (mockowane w testach — patrz "KNOWN ISSUES"), walidacja
integralności, zapis/odczyt Parquet partycjonowany symbol/timeframe/rok-miesiąc.
Żadna kolejna warstwa (features, strategie, backtest, risk, ML) nie istnieje.

---

## DONE

- `configs/symbols.yaml` — uniwersum startowe: 11 symboli Bybit USDT
  Perpetual (BTC, ETH, SOL, XRP, BNB, DOGE, ADA, LINK, AVAX, BCH, LTC) i 6
  timeframe'ów (1m, 5m, 15m, 1h, 4h, 1d).
- `src/data/config.py` — loader konfiguracji symboli/timeframe'ów.
- `src/data/schema.py` — kanoniczny schemat OHLCV (typy, wymagane kolumny,
  wymóg tz-aware UTC).
- `src/data/bybit_client.py` — cienki, wstrzykiwalny wrapper na publiczny
  endpoint klines Bybit v5 (przez `pybit`), bez wymogu kluczy API.
- `src/data/ingest.py` — paginacja wstecz po historii Bybit dla zadanego
  zakresu dat, złożenie danych do kanonicznego schematu, deduplikacja.
- `src/data/validate.py` — komplet kontroli integralności z sekcji 8
  wymagań projektu: missing candles, duplicates, timestamp continuity,
  zero volume, anomalous prices, UTC, incomplete trailing candle.
  `ValidationReport.is_valid` traktuje luki/duplikaty/anomalie cenowe/non-UTC
  jako błędy krytyczne; zero volume i niedomkniętą świecę końcową jako
  nie-krytyczne (oczekiwane).
- `src/data/storage.py` — zapis/odczyt Parquet, partycjonowanie
  `symbol/timeframe/rok-miesiąc.parquet`, inkrementalny zapis scala i
  deduplikuje z istniejącymi partycjami.
- `scripts/download_data.py` — CLI (`typer`) spinające fetch → validate →
  store; zbiór danych, który nie przechodzi walidacji, nie jest zapisywany.
- Dodano `pyyaml`, `tzdata` do zależności core; grupa `data` (`pybit`,
  `ccxt`) aktywowana w `docker/Dockerfile` (`pip install -e ".[dev,data]"`).
- Testy: `tests/data_integrity/test_validate.py` (13 przypadków — każdy typ
  problemu z osobna + dataset czysty/niekrytyczny/krytyczny),
  `tests/unit/test_ingest.py` (paginacja jedno- i wielostronicowa, zakresy
  dat, pusty wynik, walidacja start<=end), `tests/unit/test_bybit_client.py`
  (rozpakowanie odpowiedzi, propagacja błędu API), `tests/unit/test_storage.py`
  (round-trip, podział na miesiące, scalanie inkrementalne, slicing dat),
  `tests/unit/test_config.py` (poprawność wczytania uniwersum symboli).
- `docs/DATA.md` zaktualizowany o sekcję implementacyjną i znane ograniczenie.

---

## TESTY / WALIDACJA WYKONANA W TEJ FAZIE

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (17 plików źródłowych, bez błędów).
- `python3 -m pytest -q` — **27/27 testów przechodzi** (wcześniejszy 1 +
  26 nowych z Fazy 2).
- `detect-secrets scan` — brak nowych sekretów, `.secrets.baseline`
  zregenerowany po dodaniu nowych plików.
- Uwaga narzędziowa: w tym środowisku binarki `pytest`/`ruff`/`mypy` z PATH
  wskazywały na osobną, izolowaną instalację (uv tool) bez zależności
  projektu — walidacja wykonywana przez `python3 -m {pytest,ruff,mypy}`,
  które używają środowiska z zainstalowanym `pip install -e ".[dev,data]"`.
  Ten sam problem nie dotyczy obrazu Docker (tam `pytest`/`ruff`/`mypy` są
  jedynymi zainstalowanymi instancjami).

---

## KNOWN ISSUES

- **Brak realnego, live testu pobierania danych z Bybit w tej sesji.**
  Polityka sieciowa środowiska blokuje `api.bybit.com` (potwierdzone przez
  status agent-proxy: `403` na CONNECT, klasyfikowane jako blokada
  organizacyjna, nie usterka przejściowa — zgodnie z zasadami środowiska nie
  próbowałem tego obejść). Pipeline `fetch → validate → store` jest w pełni
  przetestowany jednostkowo na zamockowanym transportcie odzwierciedlającym
  realny kształt odpowiedzi Bybit v5 (`retCode`/`result.list`, kolejność
  malejąca, paginacja `limit=1000`), ale nie był uruchomiony przeciwko
  prawdziwemu API. **Rekomendacja:** pierwsze prawdziwe uruchomienie
  `python scripts/download_data.py --start ... --end ...` powinno nastąpić
  na maszynie bez tego ograniczenia (docelowy VPS lub środowisko lokalne)
  jako pierwszy krok przed Fazą 3, żeby potwierdzić zgodność założeń co do
  kształtu odpowiedzi API z rzeczywistością.
- Build obrazu Dockera nadal nie zweryfikowany end-to-end w tej sesji (patrz
  KNOWN ISSUES z Fazy 1 — demon Dockera niedostępny w sandboxie). Aktualny
  Dockerfile instaluje teraz `.[dev,data]`; zależności `pybit`/`ccxt` zostały
  zweryfikowane jako instalowalne i importowalne lokalnie (poza obrazem).
- Model funding rate wciąż nierozwiązany (patrz pytania badawcze) — Faza 2
  celowo pobiera tylko klines (OHLCV), zgodnie z sekcją 7 wymagań
  ("nie zakładaj, że wszystko musimy pobierać od pierwszego dnia").

---

## NEXT

**PHASE 3 — Backtesting engine**, do rozpoczęcia dopiero po kolejnym
wyraźnym poleceniu. W jej zakresie docelowo:

- Integracja z NautilusTrader: adapter danych z Parquet (`src/data`) do
  formatu wymaganego przez silnik backtestu.
- Konfiguracja modeli fees/slippage/leverage/funding (przybliżenie) w
  `src/backtesting`.
- Pierwszy pełny, uruchamialny (choć jeszcze bez strategii) przebieg
  backtestu na realnych danych — wymaga uprzedniego pobrania danych na
  maszynie z dostępem do Bybit (patrz KNOWN ISSUES).
- Aktywacja grupy zależności `backtest` (`nautilus_trader`, `vectorbt`) w
  `pyproject.toml`/Dockerfile.

---

## RESEARCH QUESTIONS

(bez zmian od Fazy 0/1 — żadne z tych pytań nie wymagało jeszcze decyzji)

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę
   (Faza 7), czy będzie potrzebny VectorBT Pro?
2. Jaki model przybliżenia funding rate przyjąć dla Bybit w backteście,
   biorąc pod uwagę ograniczoną dostępność historii?
3. Kiedy (jeśli w ogóle na wczesnym etapie) potrzebne będą dane
   tick-level/order-book, a kiedy dane barowe (1m-1d) wystarczą?
4. Jaki mechanizm eksperyment-trackingu (własny rejestr / mlflow / lekka
   baza) najlepiej spełni wymagania reprodukowalności bez nadmiernej
   złożoności — decyzja w Fazie 4.

---

## Decyzje projektowe podjęte w Fazie 2

- Źródło danych: wyłącznie publiczny endpoint klines Bybit v5 przez `pybit`
  (bez kluczy API) — zgodnie z decyzją Fazy 0. CCXT pozostaje zainstalowane
  jako przyszła warstwa abstrakcji, ale nieużywane w kodzie tej fazy.
  Funding rate, open interest, liquidations, order book — świadomie odłożone
  (sekcja 7 wymagań pozwala na to wprost).
  Uniwersum symboli/timeframe'ów w `configs/symbols.yaml`, nie zahardkodowane
  w kodzie — łatwe do rozszerzenia bez zmiany logiki.
- `ValidationReport.is_valid` rozróżnia błędy krytyczne (luki, duplikaty,
  anomalie cenowe, non-UTC) od nie-krytycznych (zero volume, niedomknięta
  świeca) — CLI odmawia zapisu danych, które nie przechodzą walidacji
  krytycznej, ale nie blokuje się na warunkach oczekiwanych/normalnych.
- Inkrementalne zapisy Parquet scalają się z istniejącymi partycjami zamiast
  je nadpisywać — pozwala to na wielokrotne, częściowo nakładające się
  pobrania bez ryzyka utraty danych lub duplikatów.
