# News/Event v0 — kontrakt do implementacji

Status: TARGET STATE, 2026-09-13. Specyfikacja nie oznacza działającego
collectora ani posiadania historycznego datasetu newsów.

## Minimalny zapis

| Pole | Znaczenie |
| --- | --- |
| source, source_event_id, source_url | Dostawca, jego identyfikator i oryginalny adres |
| published_at | Czas publikacji podany przez źródło, opcjonalny |
| first_seen_at | Moment pierwszej obserwacji przez nasz działający collector |
| retrieved_at | Czas tej konkretnej odpowiedzi/importu |
| provider_observed_at, availability_evidence | Historyczna obserwacja dostawcy i dowód jej pochodzenia, jeśli dostępne |
| available_at | Najwcześniejszy moment, który wolno wykorzystać w danym rodzaju testu |
| timestamp_quality | LIVE_OBSERVED, VERIFIED_ARCHIVE albo UNVERIFIED_HISTORY |
| event_type, entities, symbols | Typ wydarzenia, podmioty i jawnie uzasadnione powiązanie z BTC/ETH/SOL |
| headline, language | Oryginalny nagłówek i język |
| revision_id, supersedes | Oddzielna wersja wiadomości; bez nadpisywania przeszłości |
| payload_sha256, bronze_path, normalizer_version | Powiązanie Silver z niezmiennym źródłem |

Wszystkie czasy mają strefę i są normalizowane do UTC. Brak czasu, niezgodność
zegara albo przyszła publikacja trafiają do kontroli jakości. Nie zastępować
brakującego czasu arbitralną północą, czasem świecy lub datą z URL.

## Dostępność w symulacji

- W forward replay system może używać wersji dopiero po lokalnym first-seen,
  z uwzględnieniem późniejszej publikacji i opóźnienia przetwarzania.
- Dla archiwów dostawcy oddzielić hipotetyczną dostępność na rynku od tego,
  co rzeczywiście znał nasz system. VERIFIED_ARCHIVE wymaga sprawdzonego czasu
  obserwacji i wersji. Nie wystarcza współczesny HTML z dawną datą publikacji.
- UNVERIFIED_HISTORY może służyć do katalogu wydarzeń i eksploracji. Nie
  dopuszczać jej do performance claims opartych na przewadze czasowej.
- Rewizja od czasu T2 nie może zmienić cech ani decyzji odtworzonych dla T1<T2.
- Tłumaczenie, streszczenie i klasyfikacja LLM są pochodnymi. Zachować wersję
  modelu i input hash; oceniać także ryzyko wiedzy o przyszłych wydarzeniach
  w modelu użytym do klasyfikowania historycznych tekstów.

## Deduplikacja i analogie

Oryginalne odpowiedzi pozostają w Bronze. Silver rozróżnia tę samą wersję,
rewizję i publikację syndykowaną przez inne medium. Liczba kopii jednej
wiadomości nie zwiększa liczby niezależnych potwierdzeń.

Analogie używają wyłącznie wcześniejszych zdarzeń i cech dostępnych przed
decyzją. W zbiorze muszą pozostać zarówno zyskowne, jak i stratne podobne
sytuacje. Raport zawiera liczbę niezależnych przykładów, koszty, medianę,
obsunięcia i niepewność. Test porównawczy market-only vs market+news musi
zachować ten sam podział danych i model kosztów.

## Odbiór pierwszego wdrożenia

1. Jeden sprawdzony dostawca, Bronze i odtwarzalny normalizer Silver.
2. Powtórny import nie duplikuje zdarzenia; nowa rewizja zachowuje starą.
3. Testy odrzucają użycie przyszłej rewizji i niezweryfikowanego czasu historii.
4. Ograniczony import na VPS mieści się w rezerwie bajtów i inode'ów.
5. Jeden prerejestrowany event study dla BTC/ETH/SOL po kwalifikacji danych;
   wszystkie wypróbowane warianty trafiają do rejestru, także wyniki ujemne.
6. Panel pokazuje dane źródłowe, dostępność i ograniczenia obok wyników.

Wybór API, retencji i licencji dostawcy pozostaje osobnym krokiem weryfikacji.
