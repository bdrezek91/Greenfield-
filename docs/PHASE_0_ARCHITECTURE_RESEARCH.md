# PHASE 0 — Research technologiczny i wybór architektury

Status: **UKOŃCZONE**
Data: 2026-08-14
Zakres: wyłącznie research i decyzja architektoniczna. Brak kodu strategii, brak kluczy API, brak trybu LIVE.

---

## 1. Cel fazy

Ocenić dostępne w 2026 roku narzędzia do budowy platformy badawczej dla tradingu
algorytmicznego (Bybit USDT Perpetual Futures) i wybrać architekturę, która najlepiej
spełnia wymagania projektu: modularność, realistyczny backtest (futures/short/leverage/
funding/fees/slippage), walk-forward, integracja ML, reprodukowalność, deployment na VPS
przez Docker Compose.

Freqtrade **nie** jest traktowany jako założenie — jest jednym z ocenianych kandydatów.

---

## 2. Ocenione narzędzia

### 2.1 Freqtrade

| Kryterium | Ocena |
|---|---|
| Jakość backtestingu | Świece (OHLCV) w silniku eventowym, brak natywnego order-booka/tick data. Zakłada wykonanie w obrębie świecy z konfigurowalnym slippage/spread. |
| Futures | Tak — `trading_mode: futures`, isolated margin na Bybit. |
| Short | Tak, wymaga strategii przygotowanej pod hedging/futures. |
| Leverage | Tak, konfigurowalny per-pair. |
| Funding | Częściowe — Bybit nie udostępnia pełnej historii funding rate, więc backtest funding jest przybliżany (dry-run calc), nie realną historią. To istotne ograniczenie dla realizmu backtestu. |
| Fees / slippage | Wbudowane, konfigurowalne. |
| Multi-timeframe | Tak (informative pairs). |
| Tick / order book | Brak. |
| ML integration | FreqAI wbudowane, ale mocno związane z własnym pipeline'em Freqtrade (trudniej o niezależną warstwę ML). Projekt świadomie NIE chce zaczynać od FreqAI. |
| Walk-forward | Brak natywnego, w pełni zautomatyzowanego walk-forward frameworku (jest hyperopt + ręczne okna). |
| Live trading | Dojrzałe, szeroko używane na Bybit/Binance itd. |
| VPS deployment | Bardzo dojrzałe — Docker, REST API, Telegram, FreqUI. |
| Maintenance | Aktywnie rozwijany, duża społeczność. |
| Performance | Wystarczająca do pojedynczych par; nie jest zoptymalizowany pod wektorowe testowanie tysięcy kombinacji parametrów. |
| Reprodukowalność | Dobra (config JSON + strategy versioning), ale eksperyment-tracking trzeba dobudować samodzielnie. |

**Wniosek:** świetny jako silnik **execution/live/paper** na późniejszym etapie, słaby jako
fundament pod niezależną, modularną warstwę research/ML/statystyki, której chcemy w Fazach 2-13.

### 2.2 NautilusTrader

| Kryterium | Ocena |
|---|---|
| Jakość backtestingu | Bardzo wysoka — silnik eventowy z modelem order-booka, realistyczna symulacja wykonania. |
| Futures | Tak, konta typu margin/futures wspierane natywnie. |
| Short | Tak. |
| Leverage | Tak. |
| Funding | Obsługiwane jako część modelu instrumentu (perpetual funding), ale zależne od dostępności danych z giełdy — tak samo jak w innych frameworkach ograniczone jakością danych historycznych Bybit. |
| Fees / slippage | Konfigurowalne modele fill/slippage/fees, bardziej granularne niż Freqtrade. |
| Multi-timeframe | Tak, natywne. |
| Tick / order book | Tak — to główna przewaga: L1/L2 order book, trades, bary dowolnej granulacji. |
| ML integration | Neutralne wobec ML — dane wyjściowe (Arrow/Parquet, DataFrames) łatwo podłączyć do dowolnego frameworku ML; brak narzuconego "AI layer". |
| Walk-forward | Trzeba zbudować samodzielnie na bazie API silnika (ale API dobrze się do tego nadaje — deterministyczne, powtarzalne runy). |
| Live trading | Tak, ten sam kod strategii dla backtestu i live (parytet architektoniczny). |
| VPS deployment | Wspierane, ale mniej "gotowego" tooling'u konsumenckiego niż Freqtrade (brak UI typu FreqUI, mniejsza społeczność non-dev). |
| Maintenance | Aktywnie rozwijany (Rust core + Python API), rosnąca popularność w 2026. |
| Performance | Bardzo dobra (rdzeń w Rust), dobrze skaluje się do dużych datasetów i wielu instrumentów. |
| Reprodukowalność | Wysoka — deterministyczny silnik eventowy, jasny podział danych/strategii/execution. |

**Wniosek:** najlepszy fundament pod **modularną platformę badawczą** zgodną z wymaganą
architekturą warstwową (DATA → FEATURES → STRATEGY → BACKTEST → RISK → PORTFOLIO →
EXECUTION → ANALYTICS → ML). Krzywa uczenia wyższa niż Freqtrade, mniej "batteries included"
dla operatora nietechnicznego — ale to nie jest priorytetem tego projektu.

### 2.3 VectorBT / VectorBT Pro

| Kryterium | Ocena |
|---|---|
| Jakość backtestingu | Wektorowy (numpy/numba) — świetny do masowego testowania hipotez i parametrów, słabszy do modelowania mikrostruktury wykonania (brak natywnego order-booka, uproszczony model fill). |
| Futures / short / leverage | Wspierane na poziomie pozycji/portfela, ale mniej "giełdowo realistyczne" niż Nautilus (brak natywnego modelu liquidation/margin call per-exchange). |
| Funding | Można doliczyć jako koszt syntetyczny, brak natywnego modelu funding jak w Nautilus. |
| Fees / slippage | Konfigurowalne, proste modele. |
| Multi-timeframe | Tak, przez resampling. |
| Tick / order book | Brak (dane barowe). |
| ML integration | Bardzo dobra — natywnie działa na numpy/pandas, łatwo łączyć z sklearn/LightGBM itd. |
| Walk-forward | Ma wbudowane narzędzia do splitów i optymalizacji na tysiącach kombinacji jednocześnie — najlepsze narzędzie w tej kategorii spośród ocenianych. |
| Live trading | Brak natywnego silnika live/execution — to czysto biblioteka do analizy/backtestingu. |
| VPS deployment | N/A (biblioteka, nie framework operacyjny). |
| Maintenance | Aktywnie rozwijany, VectorBT Pro płatny z dodatkowymi funkcjami. |
| Performance | Najwyższa spośród ocenianych do masowej analizy (tysiące wariantów w czasie pojedynczego backtestu innych silników). |
| Reprodukowalność | Dobra, zależna od dyscypliny w kodzie badawczym. |

**Wniosek:** doskonałe narzędzie **wewnątrz** warstwy ANALYTICS/BACKTEST do szybkiej
eksploracji (parameter robustness, Monte Carlo, walk-forward na dużą skalę), ale nie
zastępuje silnika execution/live. Kandydat do użycia **jako dodatkowy komponent**, nie jako
całość architektury.

### 2.4 Backtrader

| Kryterium | Ocena |
|---|---|
| Status projektu | Praktycznie nieutrzymywany od kilku lat (brak aktywnego rozwoju), mimo popularności historycznej. |
| Backtesting | Eventowy, realistyczny model zleceń, ale bez natywnego wsparcia futures/perpetual/funding dla giełd krypto — trzeba domodelować ręcznie. |
| Performance | Wolniejszy niż VectorBT przy dużej liczbie kombinacji parametrów. |
| ML / walk-forward | Brak wbudowanego wsparcia, wszystko trzeba dobudować. |

**Wniosek:** odrzucony — brak aktywnego maintenance i brak natywnego wsparcia dla
perpetual futures czynią go gorszym wyborem niż Nautilus/VectorBT w 2026 roku.

### 2.5 Własny silnik Python (pełny custom)

**Zalety:** pełna kontrola, brak zależności od cudzych decyzji projektowych, dokładnie taki
model funding/liquidation/margin, jaki chcemy.
**Wady:** ogromny koszt utrzymania, ryzyko subtelnych błędów w silniku wykonania (dokładnie
tego typu błędów, przed którymi projekt ma się chronić — lookahead, błędny model fill).
Trzeba by odtworzyć to, co NautilusTrader już ma przetestowane przez społeczność.

**Wniosek:** nieuzasadnione budowanie backtestera/execution silnika od zera. Warstwy
STRATEGY, FEATURES, RISK, PORTFOLIO, ANALYTICS, ML — owszem, budujemy własne (bo to jest
istota projektu badawczego). Silnik zdarzeń/backtestu — nie ma sensu duplikować Nautilusa.

### 2.6 CCXT / CCXT Pro

Ocenione jako warstwa **DATA** (pobieranie OHLCV, order book, trades) — dojrzałe,
wieloogiełdowe, dobrze wspiera Bybit (spot + linear perpetual). CCXT Pro dodaje WebSocket
(live order book, trades) przydatny później do mikrostruktury i do warstwy execution/paper.
Rekomendacja: używać CCXT do REST/historycznych danych OHLCV oraz jako fallback/uniwersalna
warstwa abstrakcji giełdowej; dla natywnych strumieni WS Bybit rozważyć bezpośrednio
`pybit` (oficjalny SDK) w warstwie EXECUTION, gdy przyjdzie na to czas (Faza 10+).

### 2.7 Oficjalne API Bybit (REST + WebSocket, `pybit`)

Najbardziej wiarygodne źródło danych dla: klines, funding rate history, open interest,
mark/index price, liquidation feed, order book. Rekomendacja: warstwa DATA korzysta
docelowo z oficjalnego API Bybit jako źródła prawdy, z CCXT jako warstwą pośrednią/
ujednolicającą tam, gdzie ułatwia to kod (np. jednolity interfejs do wielu giełd w
przyszłości).

### 2.8 Frameworki ML do time-series trading

| Framework | Rola w projekcie |
|---|---|
| scikit-learn (Logistic Regression, Random Forest, Extra Trees) | Baseline — obowiązkowy punkt odniesienia zanim użyjemy czegokolwiek droższego obliczeniowo. |
| LightGBM / XGBoost / CatBoost | Główne modele tabularyczne do setup scoring, regime classification, expected return/R — dobry stosunek jakości do kosztu, natywne wsparcie sample weights (przydatne do purgingu/embargo). |
| statsmodels / arch | Do modeli statystycznych regime/volatility (GARCH itp.) jako nie-ML baseline. |
| PyTorch (później, opcjonalnie) | Dopiero gdy proste modele wyczerpią przewagę i będzie konkretna hipoteza uzasadniająca sieć neuronową (np. sekwencyjne cechy mikrostruktury). Nie na start. |
| mlflow / własny rejestr eksperymentów | Do trackingu eksperymentów ML — spójne z ogólnym `experiment_id` z sekcji 10 wymagań. |

Deep learning / LSTM / RL — świadomie odłożone; zgodnie z zasadą projektu prosty model
musi najpierw pokonać benchmark, zanim uzasadnimy złożoność.

---

## 3. Trzy rozważane architektury

### Architektura A — "Freqtrade-centric"
Freqtrade jako rdzeń całego systemu (dane, backtest, live), FreqAI jako warstwa ML,
własny kod tylko jako dodatkowe strategie/hyperopt loss functions.

- **Zalety:** najszybszy start, dojrzały live trading, gotowy deployment.
- **Wady:** narusza wymaganą modularność (dane/strategia/backtest są wewnętrznie sprzężone
  z Freqtrade), słabe wsparcie funding history, FreqAI narzuca własny paradygmat ML,
  trudno o niezależną warstwę ANALYTICS/eksperyment-tracking, trudno o iteracyjny
  research (Freqtrade jest zoptymalizowany pod pojedyncze strategie, nie pod masowe
  testowanie hipotez i Monte Carlo).
- **Werdykt:** odrzucona jako architektura całościowa — sprzeczna z zasadą "najpierw
  research platform, potem strategia" i z wymogiem modularności z sekcji 4.

### Architektura B — "Nautilus-centric" (silnik jednolity dla backtest + live)
NautilusTrader jako wspólny silnik backtest/live, własne moduły research (features,
regimes, risk, portfolio, ML) budowane jako niezależne biblioteki Python komunikujące się
przez jasno zdefiniowane interfejsy (DataFrame/Arrow), VectorBT używany punktowo do
masowej eksploracji parametrów przed przejściem do pełnego backtestu w Nautilusie.

- **Zalety:** naturalnie modularna (Nautilus sam wymusza rozdzielenie danych/strategii/
  execution), jeden model wykonania dla backtestu i live (mniejsze ryzyko rozjazdu
  backtest-vs-live), wysoka wydajność, dobra reprodukowalność, łatwe dojście do paper/live
  bez przepisywania strategii (sekcja 31 wymagań).
- **Wady:** wyższy próg wejścia, więcej kodu do napisania na start (Faza 1-3 zajmą więcej
  czasu niż przy Freqtrade), mniej gotowego UI operatorskiego (trzeba będzie zbudować
  własny monitoring — co i tak jest wymagane w sekcji 33).
- **Werdykt:** **rekomendowana**.

### Architektura C — "Hybrid research-first"
Całkowicie własna, lekka warstwa DATA/FEATURES/BACKTEST oparta o pandas/VectorBT dla
szybkiego prototypowania statystycznego, z Freqtrade dołączanym **dopiero w Fazie 10+**
wyłącznie jako silnik execution/paper/live (strategia eksportowana jako gotowe sygnały,
Freqtrade jako "wykonawca" a nie "mózg").

- **Zalety:** bardzo szybki start warstwy badawczej (VectorBT jest szybszy do pisania niż
  Nautilus), dobra wydajność do Monte Carlo/walk-forward na dużą skalę.
- **Wady:** dwa różne silniki wykonania (własny/VectorBT do researchu, Freqtrade do
  live) — realne ryzyko rozjazdu między tym, co backtest "obiecuje", a tym, co live
  faktycznie robi (dokładnie problem, przed którym ostrzega sekcja 32: expected vs actual
  fills). Podwójne utrzymanie modelu fees/funding/slippage w dwóch miejscach.
- **Werdykt:** odrzucona jako architektura docelowa, ale **VectorBT pozostaje elementem
  Architektury B** jako narzędzie eksploracyjne wewnątrz warstwy ANALYTICS/BACKTEST —
  różnica jest taka, że nie zastępuje głównego silnika wykonania, tylko go przyspiesza na
  etapie generowania hipotez.

---

## 4. Rekomendowana architektura (Architektura B)

**Rdzeń wykonania (backtest + paper + docelowo live): NautilusTrader.**
**Eksploracja masowa / robustness / Monte Carlo: VectorBT (open-source; VectorBT Pro do
rozważenia później, jeśli limity open-source będą realnym problemem).**
**Warstwa danych: oficjalne API Bybit (`pybit`) jako źródło prawdy + CCXT jako
uniwersalna warstwa abstrakcji tam, gdzie ułatwia wielogiełdowość w przyszłości.**
**Wszystkie warstwy powyżej silnika (features, regimes, risk, portfolio, ML, analytics)
— własny kod Python, niezależny od Nautilusa, komunikujący się przez Parquet/DataFrame,
żeby dało się je testować i podmieniać osobno.**

Uzasadnienie zgodności z wymaganiami projektu:
- **Modularność (sekcja 4):** Nautilus sam narzuca rozdzielenie strategii od execution;
  własne moduły features/risk/portfolio/ml/analytics żyją poza silnikiem i komunikują się
  danymi, nie importami wzajemnymi.
- **Realizm backtestu (sekcja 14):** Nautilus ma model fill/slippage/fees/leverage/margin
  bliższy rzeczywistości giełdowej niż wektorowe silniki.
- **Brak rozjazdu backtest/live (sekcja 32):** ten sam silnik i ten sam kod strategii dla
  backtest, paper i (docelowo) live — eliminuje klasę błędów, którą Freqtrade+custom albo
  VectorBT+Freqtrade by wprowadziły.
- **Walk-forward i Monte Carlo (sekcje 17, 19):** VectorBT jako narzędzie wewnątrz warstwy
  ANALYTICS do szybkiej masowej walidacji parametrów, finalne okna TEST i decyzje o
  wdrożeniu strategii do paper — zawsze przez pełny silnik Nautilus.
- **ML (sekcje 22-27):** brak narzuconego paradygmatu ML — własna warstwa `ml/` konsumuje
  cechy z `features/` i produkuje sygnały/scoring, niezależnie od silnika backtestu.

**Freqtrade nie jest częścią rekomendowanej architektury na start.** Może zostać ponownie
oceniony w późniejszej fazie wyłącznie jako alternatywny silnik execution/live, jeśli
pojawi się konkretny powód (np. potrzeba gotowego UI operatorskiego dla nietechnicznego
operatora) — ale nie jako fundament projektu.

---

## 5. Struktura systemu (repozytorium)

Nazwa robocza repozytorium: **`ai-trading-lab`** (nazwa zaakceptowana, brak lepszej
propozycji na tym etapie — nazwa jest neutralna i opisowa, więc nie ma powodu jej zmieniać).

```
ai-trading-lab/
  src/
    data/            # pobieranie, walidacja, przechowywanie danych (Bybit REST/WS, Parquet)
    features/        # feature engineering (bez lookahead) - price/volatility/volume/structure
    strategies/       # definicje sygnałów (rodziny strategii, nie pojedyncze indykatory)
    regimes/          # klasyfikacja reżimów rynkowych (trend/vol/range)
    backtesting/       # integracja z NautilusTrader + wrappery VectorBT do eksploracji
    risk/             # risk engine (position sizing, limity, drawdown)
    portfolio/         # agregacja wielu instrumentów, korelacje, ekspozycja
    execution/         # order intent -> exchange adapter (backtest/paper/live)
    ml/               # baseline models, regime classifiers, calibration, explainability
    analytics/         # metryki, Monte Carlo, robustness, deflated Sharpe, raporty
  configs/            # konfiguracje eksperymentów, symboli, timeframe'ów, ryzyka
  scripts/            # CLI do pobierania danych, uruchamiania backtestów, raportów
  tests/
    unit/
    integration/
    data_integrity/
    lookahead/
    strategy/
  research/           # notebooki/skrypty eksploracyjne, nieprodukcyjne
  reports/            # wygenerowane raporty eksperymentów (bez dużych danych)
  docker/             # Dockerfile per usługa
  docs/
  README.md
  .env.example
  .gitignore
  docker-compose.yml
```

Zasada graniczna: `src/backtesting` i `src/execution` są jedynymi miejscami, które znają
NautilusTrader; reszta modułów (`features`, `strategies`, `risk`, `ml`, `analytics`)
operuje na zwykłych DataFrame'ach/Parquet i nie importuje Nautilusa bezpośrednio — to
zapewnia, że silnik backtestu/execution można w teorii wymienić bez przepisywania warstw
badawczych.

---

## 6. Przepływ danych (wysoki poziom)

```
Bybit (REST/WS: klines, funding, OI, mark/index, liquidations, trades, order book)
   ↓
DATA layer (pobieranie + walidacja integralności: missing candles, duplicates,
            timestamp continuity, zero volume, anomalie cen, UTC) 
   ↓
Parquet (partycjonowane: symbol/timeframe/rok-miesiąc), przechowywane na VPS,
         NIE w repozytorium
   ↓
FEATURES layer (cechy liczone wyłącznie z danych dostępnych do t; wersjonowane)
   ↓
REGIMES layer (klasyfikacja reżimu w oparciu o trend/ATR/ADX/realized vol)
   ↓
STRATEGY / SIGNAL layer (sygnały per rodzina strategii, testowane per reżim)
   ↓
BACKTEST ENGINE (NautilusTrader dla pełnego, realistycznego backtestu;
                  VectorBT dla masowej eksploracji parametrów przed pełnym testem)
   ↓
RISK ENGINE (position sizing, limity ryzyka, decyzja czy/jak duża pozycja)
   ↓
PORTFOLIO ENGINE (agregacja wielu instrumentów, korelacje, ekspozycja portfela)
   ↓
EXECUTION (order intent -> adapter: backtest fill / paper fill / (docelowo) Bybit live)
   ↓
ANALYTICS (metryki, Monte Carlo, robustness, deflated Sharpe, raporty per experiment_id)
   ↓
ML / AI (setup scoring, regime classification, expected R, position sizing hints —
          konsumuje output z FEATURES i ANALYTICS, nie podejmuje decyzji przez prompt LLM)
```

Każdy eksperyment (backtest, walk-forward run, model ML) zapisuje metadane zgodnie z
sekcją 10 wymagań (`experiment_id`, `git_commit`, `dataset_version`, zakres dat, symbole,
timeframe'y, wersja strategii, parametry, fees/slippage/funding, metryki, timestamp) —
mechanizm eksperyment-trackingu zostanie zaprojektowany szczegółowo w Fazie 4.

---

## 7. Projekt podejścia do backtestingu

- Silnik: NautilusTrader (event-driven, bar + docelowo order-book granularity).
- Realizm wykonania: modele fill/slippage/spread/fees/funding/leverage/liquidation
  konfigurowane per eksperyment i **zapisywane jako część metadanych eksperymentu** — nigdy
  ukryte założenie "wykonanie po cenie close".
- Ochrona przed lookahead/leakage: cechy liczone wyłącznie na danych `<= t`; testy
  `tests/lookahead/` mają automatycznie wykrywać przypadki, gdy feature "widzi przyszłość"
  (np. przez porównanie wartości cechy przy obcięciu datasetu w różnych punktach).
  Świadomie odrzucamy naiwny `random train_test_split` — patrz sekcja 25 wymagań.
- Benchmarki obowiązkowe przed jakąkolwiek strategią: Buy & Hold, Random Entry, Simple
  Trend Following, Simple Mean Reversion — zaprojektowane w tym samym pipeline co
  właściwe strategie, żeby porównanie było uczciwe (te same koszty, ten sam risk engine).
- Walk-forward: automatyczny framework przesuwanego okna (np. TRAIN 12mc / VALIDATION 3mc
  / TEST 3mc), finalny equity curve składany z kolejnych okresów TEST — zaprojektowany
  szczegółowo w Fazie 7, zaimplementowany na bazie powtarzalnych runów silnika Nautilus.
- Multiple testing / overfitting: roadmapa docelowo obejmuje Deflated Sharpe Ratio,
  Probability of Backtest Overfitting, bootstrap, White's Reality Check — pierwsza wersja
  (Faza 4) skupi się na bootstrap + deflated Sharpe jako najniższy koszt wdrożenia przy
  realnej wartości ochrony przed selection bias.

---

## 8. Projekt podejścia do ML (docelowo, nie w tej fazie)

- Dane wejściowe do ML: wyłącznie output warstwy `features/` (bez dostępu do surowych
  danych z przyszłości względem punktu predykcji).
- Split: time-series split / purged split / walk-forward, z purging i embargo tam, gdzie
  etykiety mogą się nakładać w czasie (np. etykieta "R po N świecach").
- Baseline obowiązkowy przed czymkolwiek droższym: Logistic Regression, Random Forest,
  Extra Trees — dopiero potem LightGBM/XGBoost/CatBoost, i dopiero jeśli te przebiją
  baseline out-of-sample, rozważenie czegoś droższego.
- Zastosowania pierwszej generacji: setup scoring, regime classification, expected
  return/R, volatility prediction, trade filtering, position sizing — nigdy predykcja ceny
  następnej świecy.
- Kalibracja (Brier Score, calibration curve) i explainability (feature importance,
  permutation importance, SHAP) jako standardowy element raportu modelu, nie opcja.
- LLM (w tym Claude) używane wyłącznie do researchu/raportów/hipotez/debugowania — nigdy
  jako podejmujący decyzję BUY/SELL przez prompt. Finalna decyzja tradingowa musi być
  deterministyczna i audytowalna (kod, nie tekst).

---

## 9. Projekt deploymentu na VPS

- Docker Compose jako punkt wejścia (`docker compose up -d`), usługi logicznie
  rozdzielone (np. `data-collector`, `research`/`backtest` runner, `execution` (docelowo),
  `monitoring`), a nie jeden monolityczny kontener.
- Dane (Parquet, modele ML) żyją w wolumenach na VPS, nigdy w repozytorium GitHub.
- Sekrety (API keys Bybit) wyłącznie przez `.env` (w `.gitignore`), z `.env.example` bez
  wartości — zgodnie z sekcją 6 wymagań; klucze API nie są jeszcze potrzebne w Fazie 0/1.
- Tryby pracy systemu: `RESEARCH`, `BACKTEST`, `SHADOW`, `PAPER`; `LIVE`
  domyślnie zablokowany na poziomie konfiguracji/kodu (explicit opt-in wymagany w
  przyszłej fazie, nie coś co włącza się przypadkiem).
- Monitoring (Faza 9+ operacyjnie, ale zaprojektowany strukturalnie już teraz): health
  usług, świeżość danych, łączność z giełdą, ostatnia świeca/transakcja, błędy, zasoby
  systemowe (CPU/RAM/dysk), licznik restartów.
- CI (GitHub Actions): lint, testy, type-checking, podstawowy secret-scan — bez
  uruchamiania dużych backtestów w CI (te uruchamiane lokalnie/na VPS na żądanie).

---

## 10. Otwarte pytania badawcze (do dalszych faz)

1. Czy VectorBT (open-source) wystarczy, czy w Fazie 7 (walk-forward na dużą skalę)
   pojawi się realna potrzeba VectorBT Pro (płatny)?
2. Jak dokładnie modelować funding rate w backteście Bybit, skoro pełna historia funding
   nie jest łatwo dostępna retroaktywnie — jaki jest akceptowalny przybliżony model
   (Faza 2/3 decyzja, wymaga sprawdzenia dostępnych źródeł danych funding rate)?
3. Czy do mikrostruktury (order book, CVD) będziemy potrzebować danych tick-level od
   początku, czy to zostaje odłożone do momentu, gdy strategie regime/trend/momentum na
   danych barowych wyczerpią swoją wartość badawczą (zgodnie z sekcją 7 wymagań — nie
   musimy pobierać wszystkiego od pierwszego dnia)?
4. Jaki dokładnie mechanizm eksperyment-trackingu (własny rejestr vs mlflow vs lekki
   plik/DB) najlepiej spełni wymagania reprodukowalności bez nadmiernej złożoności —
   decyzja w Fazie 4.

---

## 11. Decyzja końcowa Fazy 0

- **Architektura:** B — Nautilus-centric, z VectorBT jako narzędziem eksploracyjnym
  wewnątrz warstwy analytics/backtest.
- **Nazwa repozytorium:** `ai-trading-lab`.
- **Freqtrade:** odrzucony jako fundament; pozostaje możliwym kandydatem na alternatywny
  silnik execution w dalekiej przyszłości, nie jest częścią obecnego planu.
- **Backtrader:** odrzucony (brak aktywnego maintenance, brak natywnego wsparcia
  perpetual futures).
- **Custom pełny silnik backtestu:** odrzucony (nieuzasadniony koszt utrzymania i ryzyko
  błędów wykonania, które Nautilus już rozwiązuje).
- **Dane:** oficjalne API Bybit (`pybit`) jako źródło prawdy, CCXT jako opcjonalna warstwa
  abstrakcji na przyszłość (wielogiełdowość).
- **ML:** brak decyzji o konkretnych modelach na tym etapie — tylko architektura (warstwa
  `ml/` niezależna od silnika backtestu, baseline-first, time-series split, kalibracja,
  explainability jako standard).

Faza 1 (repo + Docker + podstawowa infrastruktura) rozpocznie się dopiero po kolejnym
poleceniu.
