# Prerejestracja: `market_cipher_like`

Status: **ZAMROŻONE** przed pierwszym uruchomieniem OOS. Hipoteza, reguły wejścia/wyjścia,
sizing, siatka parametrów i kryteria odrzucenia poniżej nie zmieniają się w tym cyklu
badawczym. Jakakolwiek zmiana wymaga nowego cyklu i nowej prerejestracji.

## Metadane zamrożenia

- Branch: `druga-proba-scalpingu`
- Commit bazowy (przed implementacją strategii): `d2370533d2ee280c8878064b2b35e97ea8233510`
- Wersja protokołu: `1` (`configs/research_protocol.yaml`)
- Holdout: `2026H1-v1`, 60 dni, nienaruszony, nieużyty dotąd przez tę rodzinę
- Fingerprint danych: do uzupełnienia w `reports/research/` przy faktycznym
  uruchomieniu przez `run_research_cycle.py` (VPS ma realne dane, to środowisko
  developerskie może nie mieć pełnej historii)

## Mechanizm ekonomiczny

Niezależna, oryginalna implementacja rodziny "Market-Cipher-like" —
znormalizowana EMA-owa fala momentum (`src.features.momentum_flow.
momentum_money_flow_frame`) plus rolling money-flow. Hipoteza ekonomiczna: zmiana
znaku momentum (przecięcie fali własnej linii sygnałowej) oznacza świeżą zmianę
kierunku krótkoterminowego popytu/podaży; potwierdzenie kierunku przepływu
pieniądza (`money_flow`, oparty o typical-price-weighted volume, analog Money
Flow Index) odróżnia prawdziwą zmianę reżimu od szumu wokół zera. To NIE jest
duplikat rodziny `momentum_trend` (surowy zwrot ceny nad oknem) — inna matematyka,
inna ścieżka danych (EMA-znormalizowany kanał + wolumen), inny sygnał wejścia
(przecięcie, nie próg zwrotu).

RSI, wave/signal histogram i regular/hidden divergence z tej samej ramy są
obliczane i dostępne, ale **nie wchodzą w regułę wejścia v1** — patrz "Znane
ograniczenia" niżej. Multi-timeframe agreement jest osobnym, jeszcze
niezaimplementowanym elementem (master plan §8.3), nieużytym tu.

## Dokładne reguły

### Uniwersum i dane
- Symbole: `BTCUSDT`, `ETHUSDT`, `SOLUSDT` — jeden wspólny zestaw reguł/parametrów.
- Timeframe: `4h` i `1d` (`timeframes_primary`), każdy osobną hipotezą — tak jak
  `momentum_trend`, żadnego mieszania timeframe'ów w jednej regule.
- Wejście do `momentum_money_flow_frame`: klines tego samego symbolu/timeframe'u co
  strategia handluje, przesunięte na czas dostępności zamknięcia (`timestamp +
  interwał`, dokładnie ten sam mechanizm co `src.features.bar_materialization.
  materialize_daily_momentum_flow`), więc funkcja nigdy nie widzi świecy zanim się
  faktycznie zamknie.

### Sygnał wejścia (obie strony, long i short)
- `momentum_histogram = momentum_wave - momentum_signal` (już liczone przez
  `momentum_money_flow_frame`).
- Przecięcie w górę: poprzednia wartość histogramu ≤ 0, bieżąca > 0 → kandydat long.
- Przecięcie w dół: poprzednia wartość histogramu ≥ 0, bieżąca < 0 → kandydat short.
- Brak przecięcia (ten sam znak co poprzednio) lub niewystarczająca historia (warmup
  `momentum_span` + `signal_window` barów jeszcze nie miniony) → brak sygnału, pozycja
  płaska (fail-closed, ten sam wzorzec co `CrossAssetMomentum`/`FundingAwareMultiHorizonTrend`).

### Filtr money-flow (potwierdzenie, nie osobny głos)
- Long wymaga `money_flow > 0` w chwili przecięcia w górę.
- Short wymaga `money_flow < 0` w chwili przecięcia w dół.
- To JEDNA rodzina potwierdzeń (Market-Cipher-like), nie dwie niezależne — money_flow
  liczony z tej samej `momentum_money_flow_frame`, skorelowany z wejściem z
  definicji, celowo nie liczony jako druga niezależna confirmation family.

### Wyjście
Reużyty istniejący mechanizm, żaden nowy wskaźnik: `HoldForBarsStrategy`
`holding_period_bars` (twardy limit) plus opcjonalny `use_atr_exit`
(`atr_period=14`, `atr_exit_multiple=2.0` — wartości domyślne używane gdzie indziej
w repo, nie strojone pod tę hipotezę).
- `holding_period_bars`: `60` dla `4h` (10 dni), `20` dla `1d` (20 dni) — analogiczne
  proporcje do istniejących rodzin.

### Sizing
Volatility-scaled, reużyty istniejący mechanizm `RiskEngine`
(`volatility_target`/`vol_lookback_bars`) — jeden wspólny model ryzyka.

## Siatka parametrów

Ustalone na sztywno, nie strojone pod hipotezę: `money_flow_window=14`,
`rsi_window=14`, `pivot_left=2`, `pivot_right=2` (niewykorzystywane przez regułę v1,
ale obliczane deterministycznie), `holding_period_bars` jak wyżej.

Warianty (3, jeden parametr wariantowany — `channel_span`/`momentum_span`, ten sam
duch co `momentum_trend`'s `lookback_bars`):

| `channel_span` | `momentum_span` | `signal_window` |
|---|---|---|
| 9 | 13 | 4 |
| 10 | 21 | 4 |
| 10 | 21 | 8 |

## Selekcja wariantu

Wyłącznie na VALIDATION (`src.backtesting.walk_forward._select_params`,
niemodyfikowany), metryka `sharpe`. TEST i holdout nigdy nie wpływają na wybór.

## Przyczynowość (brak look-ahead)

`momentum_money_flow_frame` liczona jest na całej dostępnej historii klines
przesuniętej na czas zamknięcia świecy przed jakimkolwiek wywołaniem — identycznie
jak produkcyjny Gold job (`materialize_daily_momentum_flow`). Odczyt w strategii
przez `AsOfSeries.window_ending_at(bar.ts_event, n)` może zwrócić wyłącznie wartości
z `timestamp <= bar.ts_event`, nigdy przyszłe. Test obcięty (truncated-series) w
`tests/data_integrity/` potwierdza to bezpośrednio dla całej ramy klines
zasilającej tę strategię.

## Znane ograniczenia (jawne, nie ukryte)

- RSI i regular/hidden divergence są liczone, ale nie wchodzą w regułę wejścia v1 —
  dodanie ich zwiększyłoby powierzchnię parametrów bez uprzedniego dowodu, że sam
  crossover+money-flow nie wystarcza (brief: "nie dodawaj wskaźników tylko po to, by
  poprawić backtest").
- Multi-timeframe agreement (master plan §8.3, potwierdzony brak implementacji) nie
  jest częścią tej reguły — osobna, przyszła rozbudowa tej samej strategii, tym samym
  wzorcem co `higher_bar_type` w `FundingAwareMultiHorizonTrend`.

## Oczekiwane failure modes

- Przecięcia histogramu przy `momentum_span` rzędu 21 barów są rzadkie na 4h/1d →
  `min_oos_trades` (30) może nie być spełnione, szczególnie 1d/SOLUSDT.
- Filtr money-flow może odrzucać większość przecięć w trendach o słabym wolumenie →
  niska rotacja, uczciwy `NO_CANDIDATE`.
- DSR≥0.95 przy rosnącym globalnym liczniku prób pozostaje bardzo wysokim progiem —
  oczekiwany wynik to `NO_CANDIDATE`/`REJECTED`, nie sukces z góry zakładany.

## Kryteria odrzucenia

Dokładnie te z `configs/research_protocol.yaml` `promotion_gate` — żadne złagodzone,
żadne pominięte. `NO_CANDIDATE`/`REJECTED` jest tak samo poprawnym wynikiem badawczym
jak `RESEARCH_CANDIDATE` — nie jest porażką implementacji.
