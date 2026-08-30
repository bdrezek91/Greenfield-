# Prerejestracja passive-toxicity execution gate v0

Status: **ZAMROŻONA HIPOTEZA BADAWCZA / BEZ PRAWA DO EGZEKUCJI**.

Dokument powstał 2026-08-30 przed wynikiem czerwca i przed uzyskaniem pełnej
kalibracji Bybit Demo. Nie jest strategią kierunkową i nie zezwala na SHADOW,
PAPER, DEMO ani LIVE.

## Hipoteza

Największą poprawę ekonomiczną może dać nie częstsze przewidywanie kierunku,
lecz unikanie toksycznych filli pasywnych. Dla sygnału, który niezależnie
przeszedł bramkę badawczą, stan książki tuż przed wejściem może pozwolić wybrać:

- `SKIP`, gdy oczekiwany fill jest toksyczny albo edge nie pokrywa kosztów;
- `POST_ONLY`, gdy absorpcja jest wystarczająca, książka stabilna, a dolna
  granica EV po fillu jest dodatnia;
- `TAKER` wyłącznie wtedy, gdy koszt zwłoki i miss przewyższa oszczędność maker,
  a konserwatywny EV nadal pokrywa pełny taker cost oraz bufor.

Domyślna decyzja to `SKIP`. Risk veto pozostaje nadrzędne.

## Uzasadnienie zewnętrzne

- Chang, *Do Order-Book States Predict Passive-Buy Toxicity? Evidence from BTC
  Perpetual Futures* (2026), https://doi.org/10.2139/ssrn.6693260: relacja
  agresywnej presji do bliskiej ceny zdolności absorpcji i kruchość płynności
  wyjaśniają adverse selection lepiej niż sam order-flow imbalance.
- Bieganowski i Ślepaczuk, *Explainable Patterns in Cryptocurrency
  Microstructure* (2026), https://arxiv.org/abs/2602.00776: podobne cechy
  mikrostruktury mają stabilne kształty predykcyjne między aktywami, ale
  maker i taker zachowują się odmiennie podczas stresu.
- Albers et al., *The “Neutrinos” of the Order Book* (2026),
  https://ssrn.com/abstract=6250738: ogromna część komunikatów PostOnly może
  być odrzucana, więc samo wystawienie limitu nie jest dowodem fillu ani
  oszczędności kosztu.

Źródła uzasadniają falsyfikowalny test. Nie dowodzą zysku Greenfield.

## Twarde bramki danych

Implementacja modelu może rozpocząć się dopiero po spełnieniu wszystkich:

1. minimum 30 pełnych dni zweryfikowanego L2 + trades dla każdego z
   BTCUSDT, ETHUSDT i SOLUSDT na tym samym venue;
2. odtworzona sekwencja książki z wykryciem gap/reconnect i bez forward-fill
   przez luki;
3. minimum 100 niezależnych execution probes per `symbol × maker/taker` oraz
   rozłączny późniejszy okres kalibracyjny;
4. wiarygodne etykiety full fill, partial fill, miss po timeout i signed
   markout 1 s / 5 s / 10 s;
5. niezmieniony, nadrzędny risk veto i brak otwartej ekspozycji przed próbą.

Brak jednej bramki oznacza `SKIP` i brak treningu produkcyjnego.

## Zamrożone cechy v0

Wyłącznie informacje dostępne przed wysłaniem zlecenia:

- agresywny signed flow 1 s / 5 s / 20 s;
- near-touch depth po stronie bronionej oraz `pressure / absorption capacity`;
- spread, depth slope/convexity i kruchość top 5/10 poziomów;
- anulowanie, replenishment i tempo cofania kwotowań;
- krótkie spot–perp divergence, volatility i volume regime;
- symbol, strona, odległość limitu od touch oraz faza zegara UTC.

Nie wolno dodawać cech po obejrzeniu forward-OOS.

## Modele i etykiety

1. Model fillu: osobne prawdopodobieństwa full/partial/miss w zamrożonych
   timeoutach 5 s, 20 s i 60 s.
2. Model toksyczności: signed markout po fillu na 1 s, 5 s i 10 s wraz z fee.
3. Decyzja: dolna skalibrowana granica EV dla `POST_ONLY` i `TAKER`; wygrywa
   tylko wariant dodatni po pełnych kosztach i dodatkowym 3 bps buforze.
4. Benchmarki: zawsze `SKIP`, zawsze `TAKER` oraz naiwny zawsze `POST_ONLY`.

## Walidacja i falsyfikacja

- walk-forward po dniach z purge/embargo co najmniej 60 s;
- calibration error/Brier score dla fillu oraz MAE i coverage przedziałów dla
  markoutu;
- wynik osobno dla BTC/ETH/SOL, strony, reżimu oraz trybu maker/taker;
- primary: poprawa dolnej granicy net EV wobec `always taker` bez wzrostu
  tail loss; top 1% okazji primary, top 5% tylko secondary;
- wymagany stabilny znak w większości foldów i brak koncentracji w jednym dniu;
- wynik zależny od jednego symbolu, jednego kryzysu lub niestabilnej kalibracji
  kończy hipotezę jako `REJECTED`, bez strojenia na tych samych danych.

Pozytywny wynik daje wyłącznie `RESEARCH_CANDIDATE`. Osobny nienaruszony
forward-OOS oraz wszystkie istniejące bramki ryzyka pozostają wymagane przed
jakimkolwiek rozważeniem SHADOW.
