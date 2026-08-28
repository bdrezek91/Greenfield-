# Prerejestracja: `order_flow_toxicity_veto` (Track B)

Status: **ZAMROŻONE** przed pierwszym uruchomieniem walk-forward. Hipoteza, reguła
kompozytowa, wagi/progi, uniwersum i kryteria danych poniżej nie zmieniają się w tym
cyklu badawczym. Jakakolwiek zmiana wymaga nowego cyklu i nowej prerejestracji.

## Metadane zamrożenia

- Branch: `druga-proba-scalpingu`
- Commit bazowy (przed implementacją): `62d5627` (HEAD w chwili zamrożenia)
- Kontekst: GREENFIELD PROFITABILITY PIVOT, TOR B — empiryczna użyteczność
  ATAS-like order-flow jako **weto** na sygnałach istniejącej bazowej strategii,
  nie osobna strategia kierunkowa.

## Mechanizm ekonomiczny

Hipoteza: sygnał wejścia bazowej strategii (breakout, `src.strategies.breakout.
Breakout`, `lookback_bars=20` — najlepszy DSR w turnieju, patrz tournament
checkpoint w `docs/CLAUDE_CODE_CONTINUATION.md`) jest gorszej jakości, gdy w
chwili wejścia realny order flow **przeczy** kierunkowi breakoutu — klasyczny
"fakeout" napędzany słabym uczestnictwem agresywnego flow, absorpcją po
przeciwnej stronie, albo świeżym sweepem płynności w kierunku PRZECIWNYM do
wejścia. Weto blokuje wejście w takich chwilach; nigdy nie dodaje nowych wejść
(strictly more conservative niż plain Breakout, ten sam wzorzec co
`BreakoutMcConfirmation.mode="filter"`).

To NIE jest duplikat `src.engines.order_flow_evidence.order_flow_family_evidence`
(osobny, węższy, LIVE confirmation-score building block dla Meta Engine, celowo
ograniczony do trade_vwap+trade_delta, explicite wyłączający CVD/L2/footprint —
patrz jego własny docstring) ani `src.strategies.breakout_mc_confirmation`
(momentum-money-flow z klines, nie order flow). Reużywa wyłącznie istniejące,
przetestowane prymitywy:

- `src.features.order_flow.TradeFlowAccumulator` → CVD, `trade_delta` (per bucket).
- `src.features.auction.footprint_frame` → per-price-level buy/sell volume
  wewnątrz bara (footprint) → proxy absorpcji/wyczerpania.
- `src.features.auction.volume_profile` / `rolling_volume_profile_frame` →
  POC/VAH/VAL.
- `src.features.auction.anchored_vwap_frame` → VWAP/AVWAP.
- Sweep: ten sam mechaniczny Donchian-wick-rejection prymityw co
  `src.strategies.liquidity_sweep_confluence.LiquiditySweepConfluence` (bez
  OI-confirmation — tu tylko jako jeden składnik toxicity, nie osobna reguła
  wejścia).

## Znane, jawnie ujawnione uproszczenie: brak L2-book absorpcji

Prawdziwa ATAS-style "absorpcja" (duża stojąca płynność w L2 book pochłania
agresywny flow bez ruchu ceny) wymaga replay pełnego L2 book
(`src.features.order_flow.L2ImbalanceAccumulator`), co jest obliczeniowo
znacznie droższe i — jak pokazuje sprawdzenie danych poniżej — na razie i tak
niedostępne w wystarczającej ilości. Ten cykl definiuje absorpcję/wyczerpanie
WYŁĄCZNIE z footprint (trades), nie z L2 book stanu: wysoki wolumen na poziomie
ceny bez dalszej progresji ceny = absorpcja; malejący delta w stronę ekstremum
trendu = wyczerpanie. To jest jawne uproszczenie, nie ukryta luka — jeśli ten
kierunek kiedyś przejdzie dalej niż ten cykl, L2-based absorpcja jest osobnym,
przyszłym rozszerzeniem, nie czymś do dociągnięcia teraz pod already-widziany
wynik.

## Kompozytowy sygnał toxicity (dokładna reguła, ustalona PRZED uruchomieniem)

Przy każdym kandydacie wejścia bazowej strategii (breakout w górę lub w dół),
policz cztery binarne sub-sygnały na tym samym barze (wszystkie przyczynowe,
as-of, ten sam no-leakage wzorzec co `Breakout`/`BreakoutMcConfirmation`):

1. **CVD/delta divergence**: `trade_delta` bieżącego bucketu ma znak PRZECIWNY
   do kierunku breakoutu → +1 toxicity.
2. **Absorption/exhaustion (footprint)**: dominujący wolumen footprint na
   poziomie ceny bliskim ekstremum bara jest po stronie PRZECIWNEJ do kierunku
   breakoutu (sprzedaż dominuje na nowym high / kupno dominuje na nowym low)
   → +1 toxicity.
3. **Sweep w złym kierunku**: wick bara przebija PRZECIWNY (nie ten sam, co
   breakout) niedawny swing high/low i zamyka się z powrotem wewnątrz zakresu
   w ciągu ostatnich `sweep_lookback_bars` barów → +1 toxicity (świeże,
   niedawne odrzucenie płynności w kierunku przeciwnym do wejścia sugeruje, że
   "smart money" właśnie zostało odrzucone w tamtą stronę, nie w stronę
   breakoutu).
4. **VWAP/AVWAP deviation przeciwny**: cena wejścia jest PO PRZECIWNEJ stronie
   sesyjnego VWAP niż kierunek breakoutu (long breakout, ale cena poniżej
   VWAP — lub odwrotnie) → +1 toxicity.

**Reguła kompozytowa (ustalona, nie strojona)**: `toxicity_score = suma
czterech sub-sygnałów (0-4)`. Weto aktywuje się przy `toxicity_score >=
veto_threshold`, `veto_threshold = 2` (większość, nie pojedynczy sub-sygnał —
jeden nietrafiony sub-sygnał nie blokuje sam z siebie, spójne z tym, że
żadny pojedynczy indicator w tym repo nie jest samodzielną regułą wejścia).
Brak wystarczającej historii albo wymaganej cechy dla KTÓREGOKOLWIEK
sub-sygnału → cały kandydat ma status `INSUFFICIENT_FEATURES` i zostaje
wykluczony z decyzji (odpowiednik `WAIT`). Nie wolno liczyć brakującego głosu
jako 0, ponieważ dawałoby to asymetryczny, fail-open bias na korzyść wejścia.
Warmup jest raportowany osobno i nie wchodzi do metryk skuteczności weta.

POC/VAH/VAL (`volume_profile`) jest liczony i raportowany jako DIAGNOSTYKA
(czy wejście jest wewnątrz/poza value area), ale **nie wchodzi do
toxicity_score w tym pierwszym cyklu** — piąty potencjalny sub-sygnał
zostawiony jawnie poza regułą v1, dokładnie tak jak RSI/divergence zostały
zostawione poza `market_cipher_like` v1. Rozszerzenie o POC/VAH/VAL jako
piąty głos byłoby osobnym, przyszłym cyklem z własną prerejestracją, nie
czymś dodawanym po zobaczeniu wyników v1.

## Uniwersum i dane

- Symbole: `BTCUSDT`, `ETHUSDT`, `SOLUSDT` — osobno + wariant pooled (union
  obserwacji, jeden wspólny próg), jeden wspólny zestaw reguł/parametrów.
- Wejście: Silver-tier znormalizowane `trades` (dla CVD/delta/footprint/VWAP)
  + istniejące klines (dla struktury breakoutu/sweepu, jak dziś).
- Markout targets (diagnostyka, nie reguła wejścia): 5s/30s/60s do przodu od
  chwili sygnału, ten sam bisect-na-posortowanych-znacznikach wzorzec co
  `src.execution.calibration.compute_markout_calibration`, ale osobna, nowa
  funkcja operująca na SYGNALE (nie na wypełnionym zleceniu) — celowo NIE
  reużywa `compute_markout_calibration` wprost, bo ta funkcja wymaga
  `JoinedExecutionObservation` (realne zlecenie), którego tu nie ma (to
  czysty research na sygnale, zero zleceń).

## Wymagany próg wystarczalności danych (ustalony PRZED sprawdzeniem)

Walk-forward z embargo + co najmniej 3 nienakładającymi się OOS foldami +
bootstrap stabilności parametrów wymaga, ustalając próg PRZED sprawdzeniem
faktycznej dostępności: **co najmniej 20 ciągłych dni** (bez luk) w pełni
znormalizowanych (Silver, `channel=trades`) danych na symbol. To świadomie
mniej niż 60-dniowy holdout `market_cipher_like` (sygnał tu odpala się dużo
częściej niż raz dziennie, więc liczba obserwacji na dzień jest znacznie
wyższa), ale wciąż rząd wielkości potrzebny do sensownego embargo +
wielokrotnych OOS foldów, nie do jednego okna.

Jeśli dostępność nie spełnia progu: verdict = `INSUFFICIENT_DATA`, nie
`NO_CANDIDATE` (nie testowano hipotezy, tylko brakuje materiału) i nie próba
uruchomienia walk-forward na niewystarczających danych z nadzieją, że i tak
coś wyjdzie. Ten próg NIE jest obniżany po zobaczeniu faktycznej
dostępności — sprawdzenie dostępności jest wykonywane PO zamrożeniu progu,
`scripts/check_order_flow_toxicity_data_sufficiency.py`.

## Sizing i wyjście

Nie dotyczy tego cyklu wprost (weto nie zmienia sizing/wyjścia bazowej
strategii) — identyczne z `Breakout`/`BreakoutMcConfirmation`, żaden nowy
mechanizm.

## Kryteria odrzucenia / promocji

- `INSUFFICIENT_DATA`: próg 20 ciągłych dni na symbol nie jest spełniony.
- `NO_CANDIDATE`: dane wystarczające, ale weto nie poprawia DSR-adjusted
  net-of-cost performance bazowej strategii istotnie (walk-forward TEST,
  nigdy VALIDATION) po korekcie multiple-testing.
- `RESEARCH_CANDIDATE`: weto poprawia performance istotnie na TEST, po
  embargo/bootstrap/multiple-testing — nadal wymaga realnego SHADOW/PAPER
  evidence przed jakąkolwiek promocją dalej, zgodnie ze standing instruction.
