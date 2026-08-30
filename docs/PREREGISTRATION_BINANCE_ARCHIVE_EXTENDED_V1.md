# Prerejestracja Binance archive extended baseline v1

Status: **ZAMROŻONE przed pierwszym uruchomieniem**. Wyniki są wyłącznie
`EXPLORATORY ONLY`; nie mogą promować strategii do SHADOW/PAPER/LIVE.

Wspólne zasady są identyczne z rolling baseline v1: audited closed month,
pierwsza połowa warm-up, druga połowa OOS, sygnał z `t`, wejście `t+1m`,
wyjście 5/15/60 minut, brak overlap i stały koszt round-trip 12 bps. Dane to
continuous futures Gold `trades` 1 min dla BTCUSDT, ETHUSDT i SOLUSDT.

Okno wszystkich rodzin wynosi 240 poprzednich barów, próg z-score wynosi 2.0:

- `trend_breakout_v1`: long po wybiciu ponad maksimum poprzednich 240 close,
  short po wybiciu poniżej minimum;
- `price_mean_reversion_v1`: fade odchylenia log-price od rozkładu poprzednich
  240 wartości;
- `order_flow_impulse_v1`: kierunkowo za z-score `trade_delta/volume`;
- `vwap_reversion_v1`: fade z-score bieżącego `close/trade_vwap-1`.

Bieżący bar jest zawsze wyłączony z estymacji okna. Nie ma siatki parametrów,
strojenia między miesiącami, dźwigni ani sizingu. Raport ma checksums quality,
prerejestracji i Gold manifestów. Interpretacja wymaga kilku niezależnych
miesięcy; dodatni pojedynczy wynik nie jest kandydatem do promocji.
