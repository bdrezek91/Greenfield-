# Prerejestracja: `funding_aware_multi_horizon_trend`

Status: **ZAMROŻONE** przed pierwszym uruchomieniem OOS. Hipoteza, reguły wejścia/wyjścia,
sizing, siatka parametrów i kryteria odrzucenia poniżej nie zmieniają się w tym cyklu
badawczym. Jakakolwiek zmiana wymaga nowego cyklu i nowej prerejestracji.

## Metadane zamrożenia

- Gałąź robocza: `claude/funding-aware-multi-horizon-trend`
- Commit bazowy (naprawa modelu kosztów, przed implementacją strategii):
  `0248d2ee02e6691a60cd301b5b759b5dee26aaa4`
- Gałąź bazowa: `claude/ai-trading-experiment-factory-2lfl0x`
- Wersja protokołu: `1` (`configs/research_protocol.yaml`, niezmieniona)
- Holdout: `2026H1-v1`, 60 dni, nienaruszony, nieużyty dotąd przez tę rodzinę
- Fingerprint danych: **do uzupełnienia na VPS przed pierwszym uruchomieniem OOS** —
  to środowisko deweloperskie nie ma dostępu do `/data` z realnymi danymi
  BTCUSDT/ETHUSDT/SOLUSDT (tylko VPS je ma). Fingerprint per symbol/timeframe
  (`src.research.ledger.fingerprint_dataset_content`) zostanie zapisany w
  `reports/research/` przez `run_research_cycle.py` przy faktycznym uruchomieniu i
  wklejony tu jako aneks przed jakąkolwiek interpretacją wyników.

## Mechanizm ekonomiczny

Wolny trend na perpetual futures crypto może mieć dodatnią expectancy po realistycznych
kosztach, jeśli:
1. kierunek jest potwierdzony jednocześnie na dwóch horyzontach (4h i 1d) — pojedynczy
   krótkoterminowy sygnał 4h ma wysoki odsetek fałszywych sygnałów (szum), zgodność z
   wolniejszym 1d filtruje część tego szumu bez czekania na sam sygnał 1d (który
   generowałby zbyt mało transakcji przy niskiej rotacji);
2. rozmiar pozycji skaluje się odwrotnie do zmienności — ten sam nominalny sygnał
   trendu niesie inne ryzyko w różnych reżimach zmienności; stały % kapitału
   nadmiernie eksponuje portfel w reżimach wysokiej zmienności;
3. ekstremalny funding nie jest samodzielnym sygnałem, tylko filtrem kosztowym: wejście
   zgodne z kierunkiem, za który trzeba by ekstremalnie dużo płacić w funding (long przy
   bardzo dodatnim funding, short przy bardzo ujemnym) ma z góry gorszą expectancy po
   kosztach, niezależnie od tego czy sam trend jest prawdziwy.

To NIE jest rodzina zbadana w V15 (residual/relative-value mean reversion, jednoznacznie
ujemna expectancy) — to kierunkowy trend-following z filtrem kosztowym, ekonomicznie i
mechanicznie odrębny.

## Dokładne reguły

### Uniwersum i dane
- Symbole: `BTCUSDT`, `ETHUSDT`, `SOLUSDT` — jeden wspólny zestaw reguł i parametrów,
  bez filtrowania po symbolu na podstawie wyników.
- Timeframe podstawowy: `4h` (decyzje wejścia/wyjścia).
- Timeframe potwierdzający: `1d`, wyłącznie ZAMKNIĘTA świeca dostępna w chwili decyzji
  4h (patrz "Przyczynowość" niżej).
- `1h`: wyłącznie pomocniczy test odpornościowy poza głównym zestawem hipotez
  rejestrowanych w `queue.py` — nigdy jedyna podstawa promocji, wynik raportowany
  osobno, nieużywany do żadnej decyzji bramkowej.

### Sygnał kierunkowy (obie strony, long i short)
- Sygnał 4h: zwrot ceny zamknięcia nad `lookback_bars_4h` barami. Dodatni → kandydat
  long, ujemny → kandydat short, zero → brak sygnału.
- Sygnał 1d: identyczna reguła (zwrot nad `lookback_bars_1d` dniami), liczona wyłącznie
  na zamkniętych świecach 1d.
- Wejście wymaga **zgodności znaku** obu sygnałów. Brak wystarczającej historii 1d →
  pozostań płaski (fail-closed, ten sam wzorzec co `CrossAssetMomentum`).

### Filtr kosztowy funding (weto, nie sygnał)
- Z-score stawki funding nad `funding_zscore_lookback` historycznymi obserwacjami
  sprzed chwili decyzji (as-of join, `src.data.as_of_series.AsOfSeries`, ten sam
  mechanizm co `FundingContrarian`).
- Próg z-score = `2.0` (ekstremum, ustalone raz, nie strojone per symbol/wariant).
- Long zawetowany, jeśli z-score funding > +2.0 (ekstremalnie dodatni — long płaciłby
  najwięcej).
- Short zawetowany, jeśli z-score funding < -2.0 (ekstremalnie ujemny — short płaciłby
  najwięcej).
- Weto nigdy nie generuje transakcji samodzielnie — może tylko zablokować wejście,
  które i tak wynikało z sygnału 4h+1d.

### Wyjście
Zgodnie z brzmieniem brief - trzy dozwolone mechanizmy, żaden nowy wskaźnik: reużyty
istniejący mechanizm ATR-stop (`src.strategies.base.HoldForBarsStrategy`,
`use_atr_exit=True`, już zaimplementowany i przetestowany dla innych strategii w tym
repo) jako trailing/stop-i-target wyjście, plus `holding_period_bars` jako
prerejestrowany twardy limit czasu utrzymania (backstop, nie główny mechanizm wyjścia
przy niskiej rotacji).
- `atr_period = 14`, `atr_exit_multiple = 2.0` — wartości domyślne już używane gdzie
  indziej w repo, nie strojone pod tę hipotezę.
- `holding_period_bars = 60` (4h: 10 dni) — limit, nie cel; oczekiwany, że ATR-stop
  wyzwoli się wcześniej przy niskiej rotacji.

### Sizing
Volatility-scaled, reużyty istniejący mechanizm `RiskEngine`
(`volatility_target`/`vol_lookback_bars` w `BenchmarkStrategyConfig`) — jeden wspólny
model ryzyka dla wszystkich trzech symboli, żadnych osobnych progów per symbol.

## Siatka parametrów (dokładnie 12 wariantów)

Ustalone na sztywno, nie strojone pod hipotezę: `funding_zscore_lookback=30`,
`funding_zscore_threshold=2.0`, `atr_period=14`, `atr_exit_multiple=2.0`,
`holding_period_bars=60`.

Warianty (3 × 2 × 2 = 12):

| `lookback_bars_4h` | `lookback_bars_1d` | `volatility_target` |
|---|---|---|
| 30 | 10 | 0.15 |
| 30 | 10 | 0.25 |
| 30 | 20 | 0.15 |
| 30 | 20 | 0.25 |
| 60 | 10 | 0.15 |
| 60 | 10 | 0.25 |
| 60 | 20 | 0.15 |
| 60 | 20 | 0.25 |
| 90 | 10 | 0.15 |
| 90 | 10 | 0.25 |
| 90 | 20 | 0.15 |
| 90 | 20 | 0.25 |

## Selekcja wariantu

Wyłącznie na VALIDATION (`src.backtesting.walk_forward._select_params`, mechanizm już
istniejący i niemodyfikowany), metryka `sharpe`. TEST nigdy nie wpływa na wybór
wariantu w danym oknie walk-forward. Holdout nigdy nie wpływa na wybór wariantu w
żadnym oknie.

## Przyczynowość wielointerwałowa (brak look-ahead)

Sygnał 1d pochodzi wyłącznie z bara 1d, który NautilusTrader już dostarczył (zdarzenie
`on_bar` już wystąpiło) w chwili przetwarzania bara 4h — ten sam, już przetestowany w
tym repo wzorzec co `CrossAssetMomentum` (subskrypcja drugiego `BarType`, aktualizacja
stanu tylko przy odbiorze tego bara, użycie ostatniej zamkniętej wartości przy
przetwarzaniu bara podstawowego). Test obcięty (truncated-series) w
`tests/data_integrity/` potwierdza to bezpośrednio: sygnały do chwili T identyczne
niezależnie od danych po T.

## Oczekiwane failure modes

- Zbyt niska rotacja przy niskim `lookback_bars`/rygorystycznej zgodności 4h+1d →
  `min_oos_trades` (30) niespełnione, szczególnie na SOLUSDT (krótsza historia).
- Zgodność 4h+1d rzadka statystycznie → wysoki odsetek barów bez sygnału, niska liczba
  transakcji niezależnie od symbolu.
- Weto funding rzadko aktywny (z-score>2 to z definicji rzadkie zdarzenie) → filtr
  może nie zmieniać wyniku wystarczająco, by uzasadnić dodaną złożoność - to
  akceptowalny, uczciwy wynik, nie powód do zmiany progu po zobaczeniu danych.
- DSR≥0.95 przy rosnącym globalnym liczniku prób - jak pokazał każdy dotychczasowy
  audyt tej fabryki, to bardzo wysoki próg; oczekiwany, zgodny z metodologią wynik to
  `NO_CANDIDATE`/`REJECTED`, nie sukces z góry zakładany.
- Zgodność kierunku 4h+1d może skorelować z pojedynczym dominującym reżimem
  (np. tylko trwały byczy rynek BTC 2023-2024) - stąd wymóg `min_independent_symbols_
  positive>=2` i analiza per-regime w raporcie końcowym.

## Kryteria odrzucenia

Dokładnie te z `configs/research_protocol.yaml` `promotion_gate` - żadne złagodzone,
żadne pominięte. Zobacz "Weryfikacja" w briefie użytkownika. Status `REJECTED` lub
`NO_CANDIDATE` jest równie ważnym, poprawnym wynikiem badawczym jak `RESEARCH_CANDIDATE`
- nie jest to porażka implementacji.
