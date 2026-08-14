# PROJECT STATUS — ai-trading-lab

Ostatnia aktualizacja: 2026-08-14 (po zakończeniu Fazy 1)

---

## CURRENT PHASE

**PHASE 1 — Repo + Docker + podstawowa infrastruktura** — UKOŃCZONA.

Repozytorium ma teraz pełną strukturę katalogów, tooling (lint/type-check/testy),
Docker/Docker Compose, CI oraz komplet dokumentacji bazowej. Żadna warstwa
biznesowa (dane, features, strategie, backtest, risk, ML) nie jest jeszcze
zaimplementowana — tylko szkielet pakietów z opisem odpowiedzialności.

---

## DONE

- Pełna struktura katalogów zgodna z projektem z Fazy 0: `src/{data,features,
  strategies,regimes,backtesting,risk,portfolio,execution,ml,analytics}`,
  `configs/`, `scripts/`, `tests/{unit,integration,data_integrity,lookahead,
  strategy}`, `research/`, `reports/`, `docker/`.
- `pyproject.toml`: core dependencies (pandas, pyarrow, pydantic, python-dotenv,
  structlog, typer) + opcjonalne grupy `data`/`backtest`/`ml` (świadomie
  puste/nieinstalowane do czasu, aż odpowiednia warstwa powstanie — Fazy 2/3/11),
  `dev` (pytest, ruff, mypy, detect-secrets).
- `.gitignore` (sekrety, dane, modele, cache) i `.env.example` (bez sekretów,
  ze zmienną `TRADING_MODE` domyślnie `RESEARCH`).
- `docker/Dockerfile` + `docker-compose.yml` z dwiema usługami: `research`
  (interaktywny workspace) i `tests` (jednorazowy runner `pytest`) — usługi
  `data-collector`/`execution`/`monitoring` celowo NIE dodane teraz (brak
  jeszcze kodu, który by je uzasadniał — dodane w Fazach 2/10).
- CI (`.github/workflows/ci.yml`): lint (ruff), type-check (mypy), testy
  (pytest + coverage), secret-scan (detect-secrets + `.secrets.baseline`).
  Brak uruchamiania backtestów w CI — zgodnie z wymaganiem.
- Dokumentacja bazowa: `docs/ARCHITECTURE.md`, `docs/RESEARCH_METHODOLOGY.md`,
  `docs/DATA.md`, `docs/BACKTESTING.md`, `docs/ML.md`, `docs/VPS_DEPLOYMENT.md`
  (każdy dokument opisuje docelowe podejście i wskazuje fazę implementacji).
- Zaktualizowany `README.md` z instrukcją startu i mapą repozytorium.
- Smoke test (`tests/unit/test_project_setup.py`) potwierdzający, że pakiet
  `src` się importuje i pytest jest poprawnie skonfigurowany.

---

## TESTY / WALIDACJA WYKONANA W TEJ FAZIE

- `ruff check .` — OK, brak błędów.
- `mypy src` — OK, brak błędów (11 plików źródłowych).
- `pytest -q` — 1/1 testów przechodzi.
- `detect-secrets scan` — brak nowych sekretów względem `.secrets.baseline`.
- `docker compose config` — plik `docker-compose.yml` poprawny składniowo,
  wolumeny/usługi/env_file rozwiązują się prawidłowo.
- `git status` — potwierdzono brak `.env` i brak plików z sekretami w staging.

---

## KNOWN ISSUES

- **Pełny build obrazu Dockera (`docker compose build` / `up -d`) nie został
  wykonany end-to-end w tej sesji** — demon Dockera nie startuje w obecnym
  środowisku sandboxowym (brak uprawnień do `dockerd`, `ulimit: Operation not
  permitted`). Zweryfikowano za to: (a) poprawność `docker-compose.yml` przez
  `docker compose config`, (b) że zależności z `pyproject.toml` instalują się
  bezbłędnie (`pip install -e ".[dev]"` lokalnie — dokładnie to samo polecenie,
  którego używa `docker/Dockerfile`). Rekomendacja: pierwsze uruchomienie
  `docker compose build && docker compose up -d research` na docelowym
  VPS/lokalnej maszynie z działającym Dockerem powinno być pierwszym krokiem
  walidacji przed Fazą 2.
- Grupy zależności `data`/`backtest`/`ml` w `pyproject.toml` są zdefiniowane,
  ale nieinstalowane domyślnie w obrazie — to celowe (YAGNI), nie błąd.

---

## NEXT

**PHASE 2 — Data engine**, do rozpoczęcia dopiero po kolejnym wyraźnym
poleceniu. W jej zakresie docelowo:

- Implementacja `src/data`: pobieranie klines z oficjalnego API Bybit
  (`pybit`), zapisywanie do Parquet (partycjonowane symbol/timeframe/
  rok-miesiąc), walidacja integralności (`tests/data_integrity/`).
- Dodanie grupy zależności `data` do obrazu Docker.
- Skrypt CLI w `scripts/` do pobierania/aktualizowania danych.
- Decyzja o modelu przybliżenia funding rate (patrz pytania badawcze).

---

## RESEARCH QUESTIONS

(bez zmian od Fazy 0)

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

## Decyzje projektowe podjęte w Fazie 1

- `research` i `tests` jako jedyne usługi Docker Compose na tym etapie;
  kolejne usługi dopiero, gdy będzie za nimi realny kod.
- Ciężkie zależności (NautilusTrader, VectorBT, pybit, ccxt, scikit-learn/
  LightGBM) zadeklarowane jako opcjonalne extras, ale nieinstalowane, dopóki
  warstwa, która ich potrzebuje, nie zostanie zaimplementowana — utrzymuje to
  obraz bazowy lekki i szybki do zbudowania.
- `TRADING_MODE=RESEARCH` jako domyślna wartość w `.env.example`; `LIVE` bez
  mechanizmu odblokowania na tym etapie w ogóle nie istnieje w kodzie.
