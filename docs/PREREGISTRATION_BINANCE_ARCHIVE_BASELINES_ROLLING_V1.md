# Prerejestracja Binance archive rolling baseline v1

Status: **ZAMROŻONE przed pierwszym uruchomieniem na miesiącu innym niż
2026-07**. Wyniki są `EXPLORATORY ONLY` i nie mogą promować strategii do
SHADOW/PAPER.

## Dane i podział

- Każdy test obejmuje jeden pełny, zamknięty miesiąc BTCUSDT, ETHUSDT i
  SOLUSDT; Binance spot i USDT-M perpetual; `trades`; continuous Gold 1 min.
- Miesiąc musi wcześniej przejść niezależny quality/lineage audit z wynikiem
  `oos_ready=true`.
- Pierwsza dokładna połowa czasu miesiąca służy wyłącznie jako warm-up. Druga
  połowa jest jedynym raportowanym OOS. Dla miesiąca o nieparzystej liczbie dni
  granica wypada o 12:00 UTC.
- Sygnał z zamkniętego baru `t`; wejście po close dokładnie w `t+1m`; wyjście
  dokładnie po 5, 15 albo 60 minutach. Brak dokładnego baru oznacza brak trade'u.
- Zdarzenia jednej rodziny/symbolu/horyzontu nie nakładają się. Stały koszt
  round-trip wynosi 12 bps. Brak dźwigni i sizingu.

## Zamrożone hipotezy

- `atas_like_order_flow_v1`: causal z-score z 240 poprzednich wartości
  `spot_perp_delta_divergence`; long przy `z>=2`, short przy `z<=-2`.
- `mc_like_v1`: domyślne Gold `channel_span=10`, `momentum_span=21`,
  `signal_window=4`, `money_flow_window=14`; crossover histogramu przez zero
  musi zgadzać się ze znakiem money flow.

Nie wolno stroić progów, okien, kosztów ani horyzontów między miesiącami.
Raport zawiera checksum quality reportu, tej prerejestracji i wejściowych Gold
manifestów. Dopiero kilka niezależnych miesięcy może zasilić formalny
walk-forward; pojedynczy dodatni miesiąc nie wystarcza do promocji.
