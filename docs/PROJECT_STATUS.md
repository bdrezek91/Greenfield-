# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 3)

---

## CURRENT PHASE

**PHASE 3 — Backtesting engine** — UKOŃCZONA.

Silnik backtestu (`src/backtesting`) jest zaimplementowany i przetestowany:
integracja z NautilusTrader (instrumenty, dane, koszty, venue), pierwszy
pełny, uruchamialny przebieg backtestu na realistycznych danych —
**bez żadnej strategii** (świadomie, zgodnie z zakresem fazy). Żadna kolejna
warstwa (strategie, risk, portfolio, ML) nie istnieje.

---

## DONE

- `configs/instruments.yaml` — specyfikacja instrumentów (fee schedule,
  precyzja ceny/ilości, domyślny leverage) — jawnie oznaczona jako
  przybliżenie (patrz KNOWN ISSUES).
- `src/backtesting/instruments.py` — budowa instrumentów NautilusTrader
  `CryptoPerpetual` dla Bybit linear perpetuals (`<SYMBOL>-PERP.BYBIT`).
- `src/backtesting/data_adapter.py` — konwersja kanonicznych klines
  (`src/data/schema.py`) na obiekty `Bar` Nautilusa (`BarDataWrangler`).
- `src/backtesting/costs.py` — `ExecutionAssumptions`: model opłat
  maker/taker oparty o instrument (`MakerTakerFeeModel`) i model
  wykonania/poślizgu z konfigurowalnym, powtarzalnym (seed) prawdopodobieństwem
  poślizgu o jeden tick (`FillModel`).
- `src/backtesting/funding.py` — przybliżenie kosztu funding jako korekta
  post-hoc (Nautilus w zainstalowanej wersji nie ma wbudowanego modułu
  symulacji funding dla perpetuals) — liczy, przez ile standardowych
  rozliczeń Bybit (00:00/08:00/16:00 UTC) pozycja była utrzymywana, i mnoży
  przez konfigurowalną stawkę.
- `src/backtesting/engine.py` — `build_engine`/`run_backtest`: składa
  `BacktestEngine` z venue Bybit (konto margin, konfigurowalny domyślny
  leverage), instrumentami, danymi z `src/data/storage` i modelami kosztów.
  **Uruchamiany z zerem strategii** — dowodzi poprawności całego pipeline'u
  dane → instrument → venue → koszty bez żadnej rodziny strategii (Faza 5+).
- `scripts/run_backtest.py` — CLI uruchamiające powyższe na lokalnie
  przechowywanych danych Parquet; zweryfikowane realnym uruchomieniem
  (patrz TESTY / WALIDACJA).
- Aktywowano grupę zależności `backtest` (`nautilus_trader`) w
  `pyproject.toml`, `docker/Dockerfile` i CI. `vectorbt` świadomie NIE
  zainstalowany jeszcze — dołączy w Fazie 5 wraz z pierwszymi rodzinami
  strategii (eksploracyjne sweepy parametrów), zgodnie z zasadą
  nieinstalowania nieużywanych zależności.
- Testy: `tests/unit/test_instruments.py`, `test_data_adapter.py`,
  `test_costs.py`, `test_funding.py` (konwencje znaku long/short, liczba
  rozliczeń funding, sumowanie po pozycjach) oraz
  `tests/integration/test_backtest_engine.py` — pełny przebieg silnika na
  syntetycznych danych zapisanych przez `src.data.storage`, weryfikujący że
  konto startuje z konfigurowanego salda i pozostaje płaskie (zero
  strategii = zero transakcji), dla jednego i wielu symboli, oraz
  obsługę symbolu bez danych na dysku.
- `docs/BACKTESTING.md` zaktualizowany o sekcję implementacyjną, przybliżenie
  funding i znane ograniczenie specyfikacji instrumentów.

---

## TESTY / WALIDACJA WYKONANA W TEJ FAZIE

- `python3 -m ruff check .` — OK.
- `python3 -m mypy src` — OK (22 pliki źródłowe, bez błędów).
- `python3 -m pytest -q` — **49/49 testów przechodzi** (27 z Faz 1-2 + 22
  nowych z Fazy 3).
- `detect-secrets scan` — brak nowych sekretów, `.secrets.baseline`
  zregenerowany.
- **Realne uruchomienie end-to-end silnika i CLI** (nie tylko testy
  jednostkowe): `python scripts/run_backtest.py` na syntetycznych danych
  zapisanych przez warstwę danych z Fazy 2 — silnik poprawnie zbudował
  venue/instrument/dane/koszty, backtest zakończył się z saldem końcowym
  równym początkowemu (100 000 USDT) i zero pozycji, zgodnie z oczekiwaniem
  dla przebiegu bez strategii. To odróżnia tę fazę od Fazy 1/2, gdzie
  odpowiednio Docker i live-fetch danych nie mogły zostać zweryfikowane
  end-to-end z powodu ograniczeń środowiska — tutaj pełny przebieg *był*
  możliwy do uruchomienia i uruchomiony, bo nie wymaga sieci ani Dockera.

---

## KNOWN ISSUES

- **`configs/instruments.yaml` zawiera przybliżone, jednolite specyfikacje
  instrumentów** (price/size precision i increment), a nie realne wartości
  per-symbol pobrane z endpointu instrument-info Bybit — ten sam powód co w
  Fazie 2 (blokada `api.bybit.com` w tej sesji). Fee schedule (maker
  0.02%/taker 0.055%) to powszechnie dokumentowana domyślna stawka Bybit i
  powinna być bliska rzeczywistości; tick/lot size już nie — np. realny tick
  BTCUSDT jest inny niż jednolite 0.01 użyte tutaj. **Rekomendacja:** przed
  Fazą 5 (pierwsze strategie) zsynchronizować `configs/instruments.yaml` z
  realnym instrument-info Bybit na maszynie z dostępem do sieci.
- **Funding jest przybliżeniem post-hoc, nie częścią symulacji w silniku.**
  Zainstalowana wersja NautilusTrader nie ma wbudowanego modułu funding dla
  perpetuals; `src/backtesting/funding.py` liczy koszt jako korektę po
  zakończeniu backtestu na podstawie historii ekspozycji pozycji, nie jako
  dynamiczny wpływ na margin/likwidację w trakcie symulacji. Udokumentowane
  w `docs/BACKTESTING.md`.
- Docker nadal niezweryfikowany end-to-end w tej sesji (patrz Faza 1) —
  `docker/Dockerfile` zaktualizowany o grupę `backtest`, ale build obrazu
  wymaga maszyny z działającym demonem Dockera.

---

## NEXT

**PHASE 4 — Analytics + experiment tracking**, do rozpoczęcia dopiero po
kolejnym wyraźnym poleceniu. W jej zakresie docelowo:

- Mechanizm eksperyment-trackingu (`experiment_id`, `git_commit`,
  `dataset_version`, zakres dat, symbole, timeframe'y, wersja strategii,
  parametry, fees/slippage/funding, metryki, timestamp) — decyzja
  implementacyjna (własny rejestr / lekka baza / mlflow).
- Zestaw metryk z sekcji 18 wymagań (Sharpe, Sortino, Calmar, Max Drawdown,
  Profit Factor, Expectancy, Ulcer Index, itd.) liczony z raportów silnika
  Nautilusa (`generate_positions_report`, `generate_account_report`).
- Pierwsza wersja diagnostyki przeciwko multiple testing (bootstrap,
  Deflated Sharpe Ratio).
- Raporty eksperymentów w `reports/` (nie w Git — dane generowane).

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę
   (Faza 7), czy będzie potrzebny VectorBT Pro? (bez zmian)
2. Jaki model przybliżenia funding rate przyjąć dla Bybit w backteście?
   **Częściowo zaadresowane w Fazie 3**: przyjęto model post-hoc oparty o
   liczbę standardowych rozliczeń (00:00/08:00/16:00 UTC) i konfigurowalną
   stawkę — patrz `docs/BACKTESTING.md`. Otwarte pozostaje: czy i kiedy
   przejść na w pełni dynamiczny model wpływający na margin w trakcie
   symulacji, oraz jaką rzeczywistą stawkę przyjąć (obecnie placeholder
   0.01%/interwał).
3. Kiedy (jeśli w ogóle na wczesnym etapie) potrzebne będą dane
   tick-level/order-book, a kiedy dane barowe (1m-1d) wystarczą? (bez zmian)
4. Jaki mechanizm eksperyment-trackingu najlepiej spełni wymagania
   reprodukowalności bez nadmiernej złożoności — decyzja w Fazie 4.

---

## Decyzje projektowe podjęte w Fazie 3

- Silnik uruchamiany **z zerem strategii** jako kryterium akceptacji Fazy 3
  — udowadnia poprawność pipeline'u dane/instrument/venue/koszty bez
  naruszania zasady "najpierw platforma badawcza, potem strategie" i bez
  wchodzenia w zakres Fazy 5.
- Funding jako jawna, udokumentowana korekta post-hoc zamiast prób
  odtworzenia niesprawdzonej mechaniki wewnątrz silnika — zgodnie z zasadą
  projektu, że backtest nie może cicho zakładać czegoś, czego nie da się
  zweryfikować.
- `vectorbt` celowo NIE zainstalowany w tej fazie — trafi do zależności
  `backtest` dopiero, gdy pojawi się kod, który go faktycznie używa (Faza 5),
  spójnie z decyzją z Fazy 1 o nieinstalowaniu nieużywanych zależności.
- Specyfikacje instrumentów w osobnym pliku konfiguracyjnym
  (`configs/instruments.yaml`), nie zahardkodowane — ułatwia to podmianę na
  realne wartości z instrument-info Bybit bez zmiany kodu.
