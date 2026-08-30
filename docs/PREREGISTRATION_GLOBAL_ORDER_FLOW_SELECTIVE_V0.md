# Prerejestracja global-order-flow selective meta-model v0

Status: **ZAMROŻONY KIERUNEK BADAWCZY / NIE GOTOWY DO IMPLEMENTACJI**.

Ten dokument powstał przed wynikami czerwca 2026. Nie zezwala na SHADOW,
PAPER, DEMO ani LIVE. Implementacja jest zablokowana do czasu spełnienia
bramek danych i egzekucji poniżej.

## Hipoteza główna

Wspólna, kauzalna składowa signed order flow BTC/ETH/SOL na spot i perpetual
może zawierać informację o późniejszych zwrotach, której nie zawiera sam ruch
ceny. Najlepsze okazje powinny występować wtedy, gdy:

1. własny flow instrumentu jest zgodny z międzyrynkowym common flow;
2. cena nie zdążyła jeszcze w pełni zareagować;
3. funding/basis, płynność i reżim ryzyka nie wskazują crowdingu albo stresu;
4. dolna, skalibrowana granica EV pokrywa pełny koszt egzekucji i 3 bps bufora.

To hipoteza o rzadkiej selekcji, nie o ciągłym przewidywaniu kierunku.
Domyślną decyzją pozostaje `WAIT`.

## Uzasadnienie zewnętrzne

- Anastasopoulos et al., *Order flow and cryptocurrency returns*, Journal of
  Financial Markets 79 (2026), 101047:
  https://doi.org/10.1016/j.finmar.2026.101047 — międzynarodowy/common order
  flow ma moc predykcyjną OOS, zwłaszcza w modelach nieliniowych.
- Bysik i Ślepaczuk, *Machine Learning-Based Bitcoin Trading Under Transaction
  Costs* (2026): https://arxiv.org/abs/2606.00060 — naiwne sygnały godzinowe
  przegrywają po kosztach, a cost-aware execution filter ograniczający obrót
  jest ważniejszy niż samo zwiększanie złożoności modelu.
- Kim i Hansen, *The Quarter-Hour Effect* (2026):
  https://arxiv.org/abs/2607.09426 — okresowy order imbalance może nieść
  informację na horyzontach 4–12 h, ale krótkookresowy komponent jest mniejszy
  od typowych kosztów. Greenfield traktuje to jako ostrzeżenie przed skalpingiem
  bez wystarczającego EV.

Źródła uzasadniają test, nie gwarantują zysku ani przenoszalności wyników.

## Dane i bramki wejściowe

Implementacja może rozpocząć się dopiero, gdy jednocześnie istnieją:

- minimum 12 pełnych, zamkniętych i `oos_ready=true` miesięcy Gold 1 min dla
  BTCUSDT, ETHUSDT i SOLUSDT, spot oraz perpetual;
- wspólny point-in-time zegar, bez forward-fill przez luki i bez look-ahead;
- funding, mark/index/premium i dostępne OI przypięte as-of;
- empiryczny model maker/taker dla każdego symbolu z minimum 100 niezależnych
  prób na bucket symbol/mode oraz późniejszy, rozłączny test kalibracji;
- niezmienione risk veto i kill-switch.

Brak którejkolwiek bramki oznacza `WAIT` i brak treningu produkcyjnego.

## Zamrożona architektura oceny

1. **Model fillu** — osobno estymuje PostOnly full fill, partial fill i miss po
   timeout. Używa tylko danych dostępnych przed wysłaniem zlecenia i kalibruje
   się wyłącznie na execution probes.
2. **Model wyniku po fillu** — prognozuje konserwatywny net return/EV po fee,
   spreadzie, slippage, adverse selection, timeout i funding. Nie używa wyniku
   modelu fillu jako etykiety kierunkowej.
3. **Ranking** — raportuje z góry ustalone progi top 1% (primary) oraz top 5%
   (secondary sensitivity). Nie wolno wybierać progu po wyniku testu.
4. **Decyzja** — wejście jest tylko kandydatem badawczym, gdy dolna granica
   predykcji net EV przekracza koszt p95 plus 3 bps, risk veto jest fałszywe,
   a oba modele są skalibrowane na rozłącznych okresach.

## Cechy dopuszczone w v0

- signed trade flow i jego causal rolling z-score osobno dla spot/perp;
- równoważony common-flow BTC/ETH/SOL oraz residual flow instrumentu;
- opóźniona reakcja ceny względem flow, realized volatility i volume regime;
- spot–perp basis, funding, mark/index premium i point-in-time OI;
- faza zegara UTC, w tym quarter-hour oraz odległość od settlement funding.

Nie wolno dodawać cech po obejrzeniu wyników OOS. L2 może być osobnym późnym
wariantem, ale nie może zmienić definicji v0.

## Walk-forward i falsyfikacja

- expanding/rolling walk-forward z co najmniej sześcioma rozłącznymi foldami;
- purge i embargo co najmniej równe maksymalnemu horyzontowi etykiety;
- primary horizon 4 h; 8 h i 12 h są secondary i raportowane bez wyboru
  najlepszego po fakcie;
- benchmarki: zawsze `WAIT`, prosty liniowy model oraz zamrożone baselines;
- raport osobno dla BTC/ETH/SOL, każdego miesiąca i reżimu;
- wymagane dodatnie mean i median net, stabilność znaku w większości foldów,
  bootstrap przedziału EV oraz brak koncentracji wyniku w kilku zdarzeniach;
- wynik ujemny, niestabilny albo zależny od maker fillu bez kalibracji kończy
  hipotezę jako `REJECTED`, bez dostrajania na tych samych foldach.

## Kryterium dalszego przejścia

Nawet pozytywny walk-forward daje wyłącznie `RESEARCH_CANDIDATE`. Osobny,
nienaruszony miesiąc forward-OOS, stabilna kalibracja kosztów i pełna bramka
ryzyka są konieczne przed rozważeniem SHADOW. Realny kapitał pozostaje poza
zakresem tej prerejestracji.
