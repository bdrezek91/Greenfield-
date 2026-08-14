# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 0)

---

## CURRENT PHASE

**PHASE 0 — Research technologiczny i wybór architektury** — UKOŃCZONA.

Projekt jest w punkcie zerowym: wybrano architekturę, nie napisano jeszcze kodu
produkcyjnego, nie skonfigurowano żadnych kluczy API, tryb LIVE nie istnieje.

---

## DONE

- Ocena narzędzi: Freqtrade, NautilusTrader, VectorBT/VectorBT Pro, Backtrader, własny
  silnik, CCXT/CCXT Pro, oficjalne API Bybit, frameworki ML — patrz
  `docs/PHASE_0_ARCHITECTURE_RESEARCH.md`.
- Porównanie 3 architektur (Freqtrade-centric / Nautilus-centric / Hybrid research-first).
- Wybór architektury rekomendowanej: **Nautilus-centric** (NautilusTrader jako silnik
  backtest/paper/docelowo live, VectorBT jako narzędzie eksploracyjne wewnątrz warstwy
  analytics, oficjalne API Bybit + CCXT w warstwie danych).
- Zaprojektowana struktura repozytorium (`ai-trading-lab`) zgodna z podziałem
  DATA → FEATURES → STRATEGY → BACKTEST → RISK → PORTFOLIO → EXECUTION → ANALYTICS → ML.
- Zaprojektowany przepływ danych end-to-end.
- Zaprojektowane podejście do backtestingu (realizm wykonania, ochrona przed lookahead,
  benchmarki, walk-forward, multiple testing/overfitting).
- Zaprojektowane podejście do ML (baseline-first, purged/walk-forward split, kalibracja,
  explainability, brak decyzji tradingowych przez prompt LLM).
- Zaprojektowany deployment na VPS (Docker Compose, logiczny podział usług, tryby
  RESEARCH/BACKTEST/PAPER z LIVE domyślnie zablokowanym, obsługa sekretów przez `.env`).
- Utworzono `docs/PHASE_0_ARCHITECTURE_RESEARCH.md` i `docs/PROJECT_STATUS.md`.

---

## IN PROGRESS

Brak — Faza 0 zamknięta, Faza 1 nie rozpoczęta.

---

## NEXT

**PHASE 1 — Repo + Docker + podstawowa infrastruktura**, do rozpoczęcia dopiero po
kolejnym wyraźnym poleceniu (zgodnie z zasadą "nie przechodź do kolejnej fazy bez
polecenia"). W jej zakresie docelowo:

- Utworzenie pełnej struktury katalogów `src/*`, `configs/`, `scripts/`, `tests/`,
  `research/`, `reports/`, `docker/`.
- `docker-compose.yml` z logicznie rozdzielonymi usługami.
- `.env.example` (bez sekretów) i `.gitignore` (w tym `.env`, dane, duże modele).
- Szkielet CI (GitHub Actions): lint, testy, type-checking, secret-scan.
- Szkielet dokumentacji: `docs/ARCHITECTURE.md`, `docs/RESEARCH_METHODOLOGY.md`,
  `docs/DATA.md`, `docs/BACKTESTING.md`, `docs/ML.md`, `docs/VPS_DEPLOYMENT.md`.

---

## KNOWN ISSUES

- Brak natywnej pełnej historii funding rate z Bybit — sposób modelowania funding w
  backteście wymaga decyzji w Fazie 2/3 (patrz pytania badawcze poniżej).
- NautilusTrader ma wyższy próg wejścia niż Freqtrade i mniej gotowego tooling'u
  operatorskiego (UI) — świadomie zaakceptowane jako koszt modularności i realizmu.

---

## RESEARCH QUESTIONS

1. Czy VectorBT open-source wystarczy na etapie walk-forward na dużą skalę (Faza 7), czy
   będzie potrzebny VectorBT Pro?
2. Jaki model przybliżenia funding rate przyjąć dla Bybit w backteście, biorąc pod uwagę
   ograniczoną dostępność historii?
3. Kiedy (jeśli w ogóle na wczesnym etapie) potrzebne będą dane tick-level/order-book, a
   kiedy dane barowe (1m-1d) wystarczą do wartościowego researchu?
4. Jaki mechanizm eksperyment-trackingu (własny rejestr / mlflow / lekka baza) najlepiej
   spełni wymagania reprodukowalności z sekcji 10 wymagań projektu bez nadmiernej
   złożoności — decyzja w Fazie 4.

---

## Decyzje projektowe podjęte w Fazie 0

- Nazwa repozytorium: `ai-trading-lab`.
- Silnik backtest/execution: NautilusTrader (nie Freqtrade, nie Backtrader, nie custom).
- Narzędzie eksploracyjne do masowej analizy parametrów/Monte Carlo: VectorBT.
- Warstwa danych: oficjalne API Bybit (`pybit`) jako źródło prawdy + CCXT jako opcjonalna
  warstwa abstrakcji na przyszłość.
- Format danych: Parquet, przechowywany na VPS, nigdy w repozytorium GitHub.
- Freqtrade pozostaje możliwym kandydatem wyłącznie jako alternatywny silnik
  execution/live w dalekiej przyszłości — nie jest częścią obecnego planu.
