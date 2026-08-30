# Prerejestracja quarter-hour order-flow v0

Status: **ZAMROŻONE przed pierwszym uruchomieniem**. Jest to clean-room,
ograniczona replikacja hipotezy opisanej przez Kim i Hansen (2026), a nie kopia
ich kodu ani pełnego modelu. Wyniki są `EXPLORATORY ONLY`; nie mogą uruchomić
SHADOW, PAPER ani LIVE.

## Hipoteza

Agresywny order flow w pierwszym pełnym barze minutowym rozpoczynającym każdy
kwadrans UTC (minuty 00, 15, 30, 45) ma ten sam znak co późniejszy zwrot
BTCUSDT, ETHUSDT albo SOLUSDT na Binance USDT-M perpetual. Badane są wyłącznie
horyzonty 4, 8 i 12 godzin.

## Dane i przyczynowość

- Gold `trades`, Binance futures-um, 1 min; BTCUSDT, ETHUSDT, SOLUSDT.
- Bar oznaczony czasem `T` obejmuje `[T-1m,T)`. Bar otwarcia kwadransa spełnia
  `(T-1m).minute % 15 == 0`.
- Imbalance: `(buy_volume-sell_volume)/(buy_volume+sell_volume)`.
- Pierwsza połowa zamkniętego miesiąca jest wyłącznie warm-up/trainingiem.
  Dla każdego symbolu próg to 80. percentyl bezwzględnego imbalance z barów
  kwadransowych tej części. Próg nie może korzystać z OOS.
- W OOS sygnał występuje tylko, gdy `abs(imbalance) >= próg`; kierunek to znak
  imbalance. Bar sygnałowy musi być zamknięty.
- Wejście jest opóźnione o pełną minutę: close w `T+1m`. Wyjście następuje po
  dokładnie 4, 8 albo 12 godzinach. Brak dokładnej ceny oznacza brak transakcji.
- Transakcje danego symbolu i horyzontu nie mogą się nakładać.

## Koszty i decyzja

- Raportowane oddzielnie: maker/maker 6 bps, maker/taker 9 bps oraz
  taker/taker 13 bps round-trip, zgodnie z zamrożonym modelem Greenfield.
- Raportowana jest też istniejąca analiza wrażliwości Post-Only; nie jest ona
  empirycznie skalibrowanym modelem fillu.
- Czerwiec i lipiec 2026 są dwiema niezależnymi replikacjami wstecznymi, nie
  pełnym walk-forward. Po obejrzeniu któregokolwiek wyniku nie wolno zmieniać
  progu, horyzontów, kierunku ani kosztów.
- Nawet dodatni wynik nie jest kandydatem do wykonania. Wymagany jest późniejszy,
  nienaruszony okres forward-OOS, stabilność między aktywami i przejście
  Selective Gate/risk veto.

## Zamrożony forward-OOS

- Czerwiec i lipiec służą wyłącznie jako replikacje oraz do ustalenia jednego
  progu per symbol: 80. percentyl `abs(imbalance)` z połączonych, kompletnych
  danych obu miesięcy. Po jego zapisaniu nie wolno go aktualizować we wrześniu.
- `2026-09-01T00:00Z`–`2026-10-01T00:00Z` jest pierwszym prawdziwym pełnym
  forward-OOS. Sierpień jest pomijany, ponieważ prerejestracja powstała dopiero
  pod jego koniec.
- Wrzesień zachowuje dokładnie ten sam kierunek, opóźnienie, horyzonty,
  brak overlap i koszty. Pełny miesiąc jest konieczny także dlatego, że
  12-godzinny test na połowie miesiąca ma mniej niż 30 zdarzeń po selekcji i
  nie może przejść istniejącego Selective Gate bez nieuczciwego obniżania progu.

## Kryterium falsyfikacji

Hipoteza odpada, jeżeli po kosztach taker/taker nie ma dodatniej mediany i
średniej netto w obu miesiącach dla tego samego symbolu i horyzontu. Wynik
maker-only nie wystarcza bez empirycznego modelu fillu oraz adverse selection.
