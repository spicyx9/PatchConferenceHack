# Vols : Google Flights via Bright Data, fast-flights en secours

APIs fermées : Amadeus Self-Service décommissionné le 17 juillet 2026, Kiwi Tequila sur invitation, Skyscanner et Kayak partenaires seulement, Duffel test = compagnie fictive "Duffel Airways" (jamais affiché), Travelpayouts = cache 2 à 7 jours (marqué cached, affichage tendance seulement). Google Flights par scraping est la seule source large et accessible le jour même.

## Décisions

1. Principal : Bright Data Google Flights Scraper API, dataset `gd_mhng7wen1rw0a3gvpf`.
   - Discovery : `POST https://api.brightdata.com/datasets/v3/scrape?dataset_id=gd_mhng7wen1rw0a3gvpf&type=discover_new&discover_by=input_filters&include_errors=true` avec `{"input":[{"origin":"JFK","destination":"SFO","departure":"2026-10-27","return":"2026-10-30","trip_type":"round_trip","adults":1,"children":0,"infants_in_seat":0,"infants_on_lap":0,"cabin":"economy"}],"limit_per_input":10}`. Sur HTTP 202 : polling du `snapshot_id`.
   - Le schéma de discovery ne garantit que `url`. Donc discovery = candidats, puis `collect_by_url` sur ces URLs pour obtenir `url`, `itinerary_id`, `search`, `pricing`, `providers` (booking options), `legs` (1 one way, 2 round trip, 3+ multi city).
   - Les sous-champs de `pricing`, `legs`, `providers` ne sont pas documentés publiquement et les exemples se contredisent : adaptateur écrit à partir de la réponse réelle (test bloquant du matin).
   - Règle de décision : si `legs` et `pricing` reviennent vides, inverser (fast-flights via Bright Data en principal, Bright Data = transport).
   - Un seul IATA par champ : fan-out côté Conferge, 9 entrées JFK/LGA/EWR × SFO/OAK/SJC en parallèle (un input par requête pour rester synchrone). `trip_type` multi_city existe mais pas de liste de segments en discovery : passer par une URL `tfs` en collect.
   - Pas de filtre escales, bagages ou devise en discovery : via URL `tfs` filtrée en collect ou via fast-flights.
2. Secours n°1 : fast-flights (AWeirdDev/flights, MIT, 2 100 étoiles), épinglé sur un commit git (pas la 3.1.0 PyPI, régression signalée : groupes omis, `tfu` perdu ; HaroldLeo/google-flights-mcp épingle `7c105db`), routé via `integration=BrightData(zone=...)`. Déclenché si Bright Data dépasse le délai, renvoie vide, ou sans prix. Sert aussi pour les filtres bagages, escales, `hide_separate_and_self_transfer`, `exclude_basic_economy`. Issue #97 : correspondances autonomes parfois absentes.
   ```python
   from fast_flights import FlightQuery, Passengers, create_query, get_flights
   from fast_flights.integrations import BrightData
   q = create_query(flights=[FlightQuery(date="2026-10-27", from_airport="JFK", to_airport="SFO", max_stops=1), FlightQuery(date="2026-10-30", from_airport="SFO", to_airport="JFK", max_stops=1)], trip="round-trip", seat="economy", passengers=Passengers(adults=1), currency="USD", carry_on_bags=1, hide_separate_and_self_transfer=True)
   res = get_flights(q, integration=BrightData(zone=os.environ["BRIGHTDATA_UNLOCKER_ZONE"]))
   ```
3. Secours n°2 : SerpApi `engine=google_flights` (250 recherches gratuites/mois, `no_cache=true` obligatoire, `departure_id=JFK,LGA,EWR` accepté, `departure_token` pour le retour, `booking_token` pour les options de réservation). Utilisé seulement pour enrichir les 3 meilleures offres avec `booking_options`.
4. Alternative connue : punitarani/fli (MIT, 3 200 étoiles, aéroports multiples, MCP) mais HTTP 429 signalé.

## Règles de vérité

- Tout prix Google Flights est `indicative_metasearch`, horodaté `collected_at` serveur. Afficher "prix observé il y a N s, continuer sur Google Flights", jamais "prix garanti".
- Montants en chaînes décimales, `raw_text` conservé ("$1,139").
- Bagages tri-état : null inconnu, false seulement si la source l'affirme. Google précise que le prix peut exclure bagages et frais de carte.
- `segments` = vols physiques, `stops` = segments - 1, `connection_type` managed | self_transfer | protected_self_transfer | unknown (ne jamais déduire du changement de compagnie).
- `itinerary_id` = hash des segments physiques (carrier + numéro + départ UTC + arrivée UTC), `offer_id` = hash(itinerary_id + provider + fare + bagages). Le prix ne fait pas partie de l'identité. Même vol chez deux sources = un itinéraire, plusieurs offres.
- Lien : `url_type` google_flights_booking (avec tfs), google_flights_search, seller_deeplink, airline. Ne jamais fabriquer une URL compagnie absente de la réponse.
- Heures locales + fuseau IANA (table IATA → IANA, paquet `airportsdata`) + UTC. Cache 15 à 30 min par requête.
- Propositions proactives (w11 consomme) : chercher aussi départ J-1 et retour J+1 ; si écart de prix > 80 $ ou event la veille, proposer.

## Schéma FlightOffer (voir core/schemas.py)

offer_id, dedup_key, trip_type, query (origins, destinations, departure_date, return_date, cabin, passengers), slices[] (duration_minutes, stops, self_transfer, connection_type, segments[] (marketing_carrier{iata,name}, operating_carrier, flight_number, aircraft, departure{airport_iata, airport_name, terminal, local_datetime, timezone, utc_datetime}, arrival{...}, duration_minutes), layovers[] (airport_iata, duration_minutes, overnight, airport_change)), price (amount str, currency, scope total_all_passengers | per_adult | unknown, price_type, raw_text), baggage (carry_on_included, checked_bags_included, price_includes_requested_bags, basic_economy), sources[] (provider, method, upstream, collected_at, source_timestamp, expires_at, raw_ref, booking_options[]), booking (url, url_type), collected_at, warnings[] (price_indicative, baggage_unverified, self_transfer, stale_over_30min, test_data, missing_flight_number, timezone_inferred).

## Budget

9 paires × 10 enregistrements = 90 par recherche, 55 recherches dans les 5 000 gratuits. Au-delà environ 0,135 $ par recherche.

## Repos

- AWeirdDev/flights (fast-flights) MIT : secours principal.
- luminati-io/google-flights-api : scraper Playwright gratuit avec sélecteurs CSS fragiles (`li.pIav2d`), exemples SERP qui renvoient du HTML. Référence seulement.
- HaroldLeo/google-flights-mcp : modèle hybride fast-flights + SerpApi, client SerpApi avec booking_token.
- punitarani/fli MIT : alternative aéroports multiples.
- Écartés : ScrapingBee (tutoriel), Duffel starter (données test), scrapers Kayak anciens.
