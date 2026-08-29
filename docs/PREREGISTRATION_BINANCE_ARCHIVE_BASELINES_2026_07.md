# Prerejestracja Binance archive baseline — 2026-07

Status: **ZAMROŻONE przed pierwszym uruchomieniem**. Wyniki są `EXPLORATORY ONLY` i
nie mogą promować strategii do SHADOW/PAPER.

## Dane i podział

- BTCUSDT, ETHUSDT, SOLUSDT; Binance spot i USDT-M perpetual; `trades`; Gold 1 min.
- Okres: pełny zamknięty lipiec 2026, dopiero po pozytywnym quality/lineage audit.
- `2026-07-01T00:00Z`–`2026-07-16T12:00Z`: wyłącznie warm-up.
- `2026-07-16T12:00Z`–`2026-08-01T00:00Z`: jedyny raportowany OOS.
- Sygnał z baru zamkniętego w chwili `t`; wejście po cenie close dokładnie w `t+1m`;
  wyjście dokładnie po 5, 15 albo 60 minutach. Brak dokładnego baru = brak transakcji.
- Transakcje w obrębie jednej rodziny/symbolu/horyzontu nie mogą się nakładać.
- Stały konserwatywny koszt round-trip: 12 bps. Brak dźwigni i sizingu.

## ATAS-like order-flow v1

Clean-room, bez kodu własnościowego. Causal rolling z-score 240 poprzednich wartości
`spot_perp_delta_divergence`; bieżący bar jest wyłączony ze średniej i odchylenia.
`z >= 2` daje long, `z <= -2` daje short. Nie ma siatki parametrów ani dodatkowych
filtrów dobieranych po wyniku.

## MC-like v1

Zamrożone domyślne Gold: `channel_span=10`, `momentum_span=21`,
`signal_window=4`, `money_flow_window=14`. Long: histogram przechodzi z `<=0` do
`>0` i `money_flow>0`. Short: przejście z `>=0` do `<0` i `money_flow<0`.

## Raport i interpretacja

Dla każdej rodziny, pary i horyzontu: liczba zdarzeń, średnia/mediana gross i net
bps, win-rate po kosztach oraz skumulowany net return przy sekwencyjnym założeniu.
Brak sygnałów i wynik ujemny są prawidłowymi rezultatami. Jeden miesiąc nie jest
dowodem trwałej przewagi; wymagane są kolejne niezależne miesiące walk-forward.
