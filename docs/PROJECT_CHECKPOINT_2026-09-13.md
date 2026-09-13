# Greenfield — wykonanie, obecny stan i dalszy plan

Data: 2026-09-13. Dokument uzupełnia nadrzędny MASTER PLAN.
Jedyny branch lokalny i zdalny: `main` (potwierdzone `git ls-remote --heads`).
Nie było dodatkowych branchy do scalenia ani usunięcia w tym cyklu.

## Docelowe zadanie programu

Pomagać traderowi oceniać okazje na BTC, ETH i SOL: zbierać wiadomości i dane
rynkowe, identyfikować podobne sytuacje historyczne, policzyć rozkład późniejszych
wyników po kosztach i pokazać warunki wejścia oraz unieważnienia scenariusza.
Brak dostatecznych dowodów oznacza WAIT. Sam podobny wykres lub news nie jest
potwierdzoną przewagą. Dotychczasowe silniki backtestu, ryzyka i Demo zostają.

## Co wykonano dotychczas

| Obszar | Wykonana praca i dowody | Granice wnioskowania |
| --- | --- | --- |
| Dane | Bronze/Silver/Gold, Parquet, manifesty, checksumy, normalizacja, lineage i quality gates | Kod pipeline'u nie dowodzi kompletności każdej doby |
| Zbieranie | Bybit BTC/ETH/SOL trades, L2, ticker i likwidacje; adaptery innych giełd w repo | Obecnie potwierdzono trzy zdrowe collectory Bybit; pozostałe wdrożenia wymagają osobnej inwentaryzacji |
| Historia | Czerwiec i lipiec 2026 Binance trades/aggTrades spot/perp przeszły pipeline i audyt; raporty w `reports/binance-public-archive` | OOS-ready oznacza dopuszczenie danych do testu; miesiące zostały już obejrzane |
| Cechy | CVD/delta, footprint, profile wolumenu, VWAP, cechy order flow oraz niezależne MC-like | To nie jest dokładna kopia ATAS/Market Cipher ani dowód dostępu do ich płatnej historii |
| Research | Backtesty, koszty maker/maker, maker/taker, taker/taker, PostOnly sensitivity, walk-forward, analogi i risk gates | Fill probability/adverse selection wymagają kalibracji empirycznej |
| Wyniki | Selective Gate czerwca/lipca: 63 WAIT, 0 kandydatów; carry Hyperliquid–Bybit: NO_CANDIDATE | Nie ma potwierdzonej, stabilnie zarabiającej strategii |
| Demo | Zweryfikowane API, zakup/zamknięcie BTC, rekonsyliacja i szkielet execution/probes | Stare scalpery v1/v2 wycofano; wynik Demo nie jest dowodem rentowności LIVE |
| Operacje | Docker/monitoring/CI, testy i historia na main; 13.09 uruchomiono zewnętrzny inode guard | Nadal potrzebna trwała retencja i off-host recovery |

Szczegółową chronologię cykli i ich ograniczenia zachowano w
`CLAUDE_CODE_CONTINUATION.md` oraz `MAIN_CONSOLIDATION_REPORT_2026-08-30.md`.

## Faktycznie sprawdzony VPS

- Host: `57.128.220.89`, `vps-c7a8bf17`; dawny `77.55.209.155` jest wycofany.
- `/dev/sdb1` jest zamontowany pod `/opt/greenfield-v2/data`; na początku cyklu
  około 9,8 GiB wolnego i 151 192 wolne inode'y. `/` ma około 6,4 GiB wolnego.
- Trzy collectory Bybit są healthy. Kolejka catch-up od 06.09 ma stan
  `STOPPED_REQUIRES_REVIEW` podczas SOL trades 30.08, po 28 udanych krokach:
  trades→Gold BTC/ETH/SOL 26–29.08 oraz BTC/ETH 30.08.
- Nie zakończono audytu kompletności tego batcha. Błąd SOL i późniejszy incydent
  inode'ów wymagają jawnego oznaczenia luk. Ciągłość po restarcie nie naprawia luk.
- 13.09 inode'y osiągnęły zero pomimo wolnych bajtów. Awaryjne archiwa pięciu
  partycji Silver zachowały dane i odblokowały collectory. Kontrolowano liczby
  plików i hash archiwum; nie przedstawiać tego jako pełnego porównania każdej
  pary źródło–odtworzony plik. Nowy automat wykonuje mocniejszą weryfikację.
- Minutowy `greenfield-inode-guard.timer` zatrzymuje trzy collectory przy
  <=100 000 inode'ów. Guard sam nie odzyskuje miejsca i nie restartuje usług.
- Produkcyjny collector zachowuje swój pinned checkout. Brudny checkout
  `/home/ubuntu/greenfield-claude` zawiera cudzą pracę i nie był czyszczony.

## Kolejność dalszych prac i kryteria odbioru

1. **Retencja — bieżący cykl.** Automat pakuje wyłącznie zamknięte Silver trades
   z zakończonym normalize+Gold w zapisie kolejki. Pełne hashe, odtworzenie każdego
   pliku, kontrola niezmienności przed prune, wznowienie po przerwaniu, timer i
   obserwacja prawdziwego wykonania. Cel operacyjny: 400 tys. wolnych inode'ów,
   o ile istnieją kwalifikujące się partycje. To skończona pula; jej wyczerpanie
   musi być raportowane. Same-volume tar nie jest kopią odporną na awarię dysku.
2. **Dane.** Zintegrować lokalizacje archiwów z katalogiem/restore workflow;
   zweryfikować coverage, luki, duplikaty, timestampy i lineage BTC/ETH/SOL.
   Wznawiać materializację seryjnie przy zachowaniu rezerwy. Żaden czytnik nie
   może uznać zarchiwizowanej, niezamontowanej partycji za kompletny pusty dzień.
3. **News/Event v0.** Najpierw mały zbiór źródeł: oficjalne publikacje makro,
   komunikaty giełd/projektów, dostawca historycznych newsów po weryfikacji API,
   licencji i dostępności. Zachować URL, publikację, first-seen, pobranie,
   wersję, deduplikację i jakość czasu. Oddzielić rewizje i plotki od faktów.
4. **Point-in-time + analogi.** Synchronizować UTC i dostępność informacji;
   import dzisiaj nie dowodzi, że informację znaliśmy wtedy. Zamrozić typ
   wydarzenia, okno, parametry i koszty przed wynikiem. Uwzględnić podobne
   porażki, embargo, brak overlap i liczbę prób. Porównać z baseline bez newsów.
5. **Pierwszy panel.** Read-only karta: wydarzenie/źródło, kontekst rynku,
   analogi i ich liczba, rozkład wyniku netto/obsunięcia, niepewność, scenariusz
   i invalidation. Odbiór: jeden odtwarzalny przepływ od źródła do karty dla
   BTC/ETH/SOL; niewystarczający zbiór daje WAIT.
6. **Dalsza walidacja.** Kolejne niezależne okresy oraz forward obserwacja.
   Dopiero potem kwalifikacja do kontrolowanego Demo i ocena egzekucji.
   LIVE, płatne dane i nowe wydatki wymagają osobnej decyzji użytkownika.

## Co jeszcze nie jest gotowe

News pipeline, historyczny dataset wydarzeń, point-in-time news/market join,
panel tradera, długoterminowa retencja całego Bronze, off-host backup i
potwierdzona rentowność. Stare procenty ukończenia dotyczą poprzedniego zakresu;
nowy kierunek mierzymy powyższymi odbiorami, bez przenoszenia starego 72%.

## Praca z archiwami

Nowe archiwa: `_archives/bybit-silver-trades/SYMBOL-DATE/partition.tar` oraz
`manifest.json` (mapa nazwa→rozmiar/SHA-256 i hash tar). Przed materializacją lub
odtwarzaniem zatrzymać timer i zaczekać na zakończenie aktywnej archiwizacji.
Nie rozpakowywać bez sprawdzenia hashów, nazw członków, braku dowiązań i rezerwy
inode'ów/bajtów. CLI domyślnie tylko pokazuje plan; `--execute --prune` uruchamia
archiwizację. Przerwany `.partial` lub tar bez manifestu wymaga przeglądu;
źródła nie są wtedy usuwane. Timer używa wyłącznie zakończonych kroków wskazanego
batcha, nie usuwa Bronze, Gold, konfiguracji ani repozytoriów.
