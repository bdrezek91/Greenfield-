# TRIPLE BARRIER LABELS V1 — prerejestracja

Status: **PREREGISTERED / DEVELOPMENT-ONLY / NO NEW HOLDOUT AVAILABLE**.
Dokument zamrożono przed uruchomieniem pierwszego wyniku tego eksperymentu.

## Pytanie badawcze

Czy etykieta zależna od ścieżki ceny lepiej definiuje jakość istniejącego
setupu Breakout niż stałe wyjście po 24 godzinach, gdy model, cechy, koszty i
chronologiczne splity pozostają niezmienione?

To jest eksperyment etykiety, nie kolejny search modeli. Nie wolno zmieniać
barier ani parametrów modeli po zobaczeniu wyników.

## Granica po Tournament V1

Końcowy okres 2025-08-29 15:00 UTC–2026-08-24 23:00 UTC został zużyty przez
ML Model Tournament V1. Nie może być ponownie nazywany holdoutem ani służyć do
strojenia. V1 Triple Barrier używa wyłącznie wcześniejszej części danych do
expanding walk-forward development screen. Ostateczny werdykt wymaga nowych,
chronologicznie późniejszych danych, których system nie widział w chwili tej
prerejestracji. Do tego czasu najwyższy możliwy status to
`DEVELOPMENT_PROMISING_NOT_PROMOTABLE`.

## Zamrożona etykieta

- Universe i timeframe: Bybit linear `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `1h`.
- Kandydat: identyczny causal Donchian Breakout, `lookback_bars=20`.
- Entry/reference: close bara sygnałowego; kierunek pochodzi z Breakout.
- Risk unit: causal ATR(14) dostępny na barze decyzji.
- Profit-take: `+2.0 ATR` w kierunku pozycji.
- Stop-loss: `-1.0 ATR` względem wejścia.
- Vertical barrier: 24 pełne bary po sygnale.
- Long używa przyszłych high do PT i low do SL; short odwrotnie.
- Pierwsze dotknięcie kończy label window. Jeżeli PT i SL są możliwe na tej
  samej świecy godzinowej, przyjmujemy konserwatywnie stop-loss; nie zgadujemy
  kolejności intrabar.
- Jeżeli żadna pozioma bariera nie zostanie dotknięta, wyjście następuje po
  close vertical barrier.
- `gross_return` jest kierunkowym zwrotem od entry do ceny bariery/vertical
  close. `label=1` tylko gdy gross return po zamrożonym koszcie base 20 bps jest
  dodatni; inaczej `label=0`.
- Kandydaci pozostają nienakładający się przez pełne 24 bary, niezależnie od
  wcześniejszego dotknięcia bariery. Zapobiega to zwiększaniu liczby setupów
  przez samą zmianę labelu.

## Matched experiment

Porównujemy dwie wersje tego samego datasetu kandydatów:

1. frozen fixed-horizon label z Tournament V1;
2. zamrożony Triple Barrier label powyżej.

Obie wersje używają tych samych timestampów kandydatów, `FEATURE_COLUMNS`,
fit/calibration/test boundaries, base/adverse/severe costs i safety margin.
Jeżeli kandydat nie może istnieć w obu wersjach, odpada z obu (intersection),
aby zmiana liczebności nie udawała poprawy labelu.

Modele i parametry są zamrożonymi zwycięzcami development selection z V1:

- Logistic Regression: `C=0.1`;
- Random Forest: `max_depth=4`, `min_samples_leaf=10`;
- ExtraTrees: `max_depth=8`, `min_samples_leaf=20`;
- XGBoost: `max_depth=3`, `learning_rate=0.03`, `n_estimators=250`,
  `min_child_weight=3.0`;
- LightGBM: `max_depth=3`, `learning_rate=0.03`, `n_estimators=150`,
  `num_leaves=15`.

Nie ma nowego hyperparameter search. Seed 42 i pojedynczy wątek pozostają.

## Walidacja i accounting

- Pięć expanding walk-forward folds na okresie przed zużytym holdoutem V1.
- Purge używa rzeczywistego `label_end_time`; embargo wynosi 24 godziny.
- Ostatnie 20% każdego train fold jest wyłącznie calibration tail.
- Wszystkie 10 matched model/label triali trafiają do globalnego trial ledger,
  również błędy i wyniki ujemne.
- Raport: net PnL/Sharpe/Sortino/max DD/Calmar/expectancy/trades/turnover,
  base/adverse/severe, Brier/reliability/AUC, per symbol, fold stability, DSR
  liczony względem globalnego trial count. PBO tylko jeśli poprawna liczba
  partycji pozwala go wyznaczyć; brak nie jest zerem.

## Development gate

Triple Barrier może otrzymać wyłącznie status
`DEVELOPMENT_PROMISING_NOT_PROMOTABLE`, jeżeli jednocześnie:

- medianowy adverse net Sharpe po foldach poprawia matched fixed-horizon o co
  najmniej 0.25;
- aggregate base i adverse net PnL są dodatnie;
- base i adverse mają co najmniej 30 transakcji;
- co najmniej 2/3 symboli ma dodatni adverse net PnL;
- Brier nie pogarsza się o więcej niż 0.01;
- żaden symbol nie generuje ponad 70% dodatniego PnL;
- DSR > 0.95 po globalnym trial accounting.

Niespełnienie = `REJECT` albo `INCONCLUSIVE`. Nawet pełne spełnienie nie
upoważnia do SHADOW/PAPER/LIVE bez nowego future holdoutu.

## Bezpieczeństwo

Eksperyment jest wyłącznie RESEARCH/BACKTEST. Nie importuje gatewaya wykonania,
nie składa Demo ani realnych orderów, nie zmienia API permissions i nie dotyka
działających collectorów.
