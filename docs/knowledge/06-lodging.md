# Logements : Booking, Airbnb, Google Hotels

Aucune API officielle accessible en 24 h : Booking Demand API et Expedia Rapid = partenaires sous contrat, Google Hotels = pas d'API publique de lecture des prix, Amadeus Self-Service fermé le 17 juillet 2026. Seule voie : scraping structuré Bright Data + pyairbnb.

## Décisions

| Plateforme | Principal | Secours | Notes |
|---|---|---|---|
| Booking.com | Bright Data `gd_m4bf7a917zfezv9d5` recherche (location, check_in, check_out ISO `2026-10-27T00:00:00.000Z`, adults=1, children=0, rooms=1, currency=USD, country=us) puis `gd_mdy9ld3p1e0oqlj9g4` sur l'URL de fiche reconstruite avec `checkin`, `checkout`, `group_adults=1`, `no_rooms=1`, `selected_currency=USD`, `sb_price_type=total` pour le top 15 | Bright Data Browser sur la page de recherche | WAF AWS, GraphQL interne inutilisable : pas de scraper maison. Repos Booking GitHub tous écartés |
| Airbnb | pyairbnb (MIT, poussé août 2026, `pip install pyairbnb`) : `search_all(check_in, check_out, ne_lat, ne_long, sw_lat, sw_long, currency="USD", ...)` puis `get_price(room_id, check_in, check_out)` ; bounding box environ 3 km autour de Fort Mason ; `get_calendar` pour confirmer | Bright Data `gd_ld7ll037kqy322v05` méthode "Search Airbnb by location" derrière la même interface | Sans dates pyairbnb ne renvoie pas de prix. Frais de ménage et service seulement avec dates + voyageurs. Coordonnées floutées : `geo_precision: approximate`. Basculer sur Bright Data sur erreur de schéma, blocage, timeout ou champs prix absents, pas sur zéro résultat |
| Google Hotels | Bright Data `gd_mg3gjfmg12tc2n5d4d` discover by search (search_term "hotels near Fort Mason Center San Francisco", check_in_date, check_out_date, guest_number=1, country=us, currency=USD) ; 31 champs dont `booking_options`, `lat`, `long`, `currency` | SerpApi `engine=google_hotels` (250 recherches gratuites/mois, `rate_per_night`, `total_rate`, `property_token`) ; `janik4321sdfa/google-hotels-python` (protobuf `ts`, sans clé) | Pivot de déduplication : `booking_options` liste plusieurs OTA par hôtel. Échantillon public : `rating`, `review_count`, `address` souvent null |
| Agoda, Trip.com | Bright Data datasets dédiés (Agoda `gd_mdyifvvo181pcrpew6`) | | Après MVP |
| Expedia, Hotels.com, Vrbo | indirect via `booking_options` Google Hotels | | Pas de scraper Bright Data de recherche avec prix identifié |
| Tripadvisor | Bright Data : avis seulement | | Pas de prix datés |
| Hostelworld | Apify actor | | Niche |
| LiteAPI (Nuitée) | clé sandbox gratuite, `POST /hotels/rates` avec `hotelIds`, `occupancies`, `currency`, `guestNationality`, `offerId` réservable | | Seule source de tarifs réellement réservables, inventaire grossiste. Moyen terme |

## Pipeline (w05)

1. Géocodage : lieu de la conf → lat/lng → bounding box 3 km. Plus tard : barycentre des events intéressants.
2. Découverte en parallèle (asyncio.gather) : Booking search, Airbnb search_all, Google Hotels search. `limit_per_input` 20.
3. Vérification sur le top 15 : Booking fiche `sb_price_type=total`, Airbnb `get_price`, Google Hotels `property_token`. Horodater `checked_at`, `valid_until` = +30 min.
4. Normalisation vers Lodging avec `price_status`. Exclure sans prix, sans total ou `availability=false`.
5. Dédup inter-plateformes : distance < 75 m + nom normalisé (minuscules, retirer "hotel", "by", marques) ; Airbnb et Vrbo jamais fusionnés agressivement.
6. Distance et temps vers Fort Mason et vers chaque event du plan (OSRM public ou table haversine + vitesse marche 5 km/h, transit via 511.org). `distance_to_venue_m`.
7. Cache : clé (provider, id, check_in, check_out, adults, currency), 30 min pour vérifié, 6 h pour découverte.

## Règles de vérité prix

- `price_status` : `verified_bookable` (fiche datée revérifiée, total TTC, dispo confirmée, < 30 min), `quoted_total` (total daté issu d'une recherche), `indicative` (à partir de, par nuit sans total), `unavailable`.
- Stocker le total du séjour et recalculer `nightly_avg` = total / nuits, marqué calculé. Jamais l'inverse.
- Taxes et frais : `includes_taxes`, `includes_all_fees`, `payable_at_property` séparés. Resort fee payable sur place ≠ taxe incluse. Frais inconnu = null et `completeness: unknown_or_partial`.
- Devise forcée côté source (`currency`, `selected_currency`). Si conversion : objet séparé avec `fx_rate`, `fx_timestamp`.
- Contexte de marché persisté : country us, language en, currency USD, platform desktop, authenticated false. Deux prix de deux pays ne sont pas comparables.
- Lien de réservation : URL avec dates et occupation pré-remplies. Booking : `https://www.booking.com/hotel/us/<slug>.html?checkin=2026-10-27&checkout=2026-10-30&group_adults=1&no_rooms=1&selected_currency=USD`. Airbnb : `https://www.airbnb.com/rooms/<id>?check_in=2026-10-27&check_out=2026-10-30&adults=1`. Google Hotels : URL de la fiche avec `ts` (ne pas construire à la main, prendre celle renvoyée).

## Schéma Lodging (voir core/schemas.py)

id (provider:id), provider, source_method, name, type (hotel, apartment, hostel), location (address, city, country, lat, lng, geo_precision, distance_to_venue_m), stay (check_in, check_out, nights, adults, children, rooms), price (currency, nightly_avg, base_total, cleaning_fee, service_fee, taxes, other_fees, total, includes_taxes, includes_all_fees, original_currency, fx_rate, fx_rate_date, price_status), availability (available, rooms_left, checked_at, valid_until), conditions (free_cancellation, cancellation_deadline, payment, breakfast_included, min_nights), rating (score, scale, count), photos, booking_url, dedup_group, raw_ref, market_context, collected_at.

## Repos

- johnbalvin/pyairbnb (MIT) : principal Airbnb. Dépend de curl_cffi. Hash StaysSearch récupéré dynamiquement.
- kbhujbal/Multi-Agent-AI-Travel-Advisor (MIT) : garder `backend/services/base.py`, `backend/models/schemas.py`, pattern `service.py` parallèle. Jeter les parseurs (RapidAPI, Airbnb peut sortir 0 $).
- luminati-io/google-hotels-api, luminati-io/Booking-dataset-sample, luminati-io/Airbnb-dataset-samples : schémas de sortie réels pour les fixtures.
- openbnb-org/mcp-server-airbnb (MIT) : démo agent.
- Écartés : digital-engineering/airbnb-scraper (abandonné, GPL), ZoranPandovski/BookingScraper (GPL, pas de dates), scrapehero-code/booking-hotel-scraper (2020).

## Test bloquant du matin (9h)

Un appel réel par dataset avec la clé, réponse brute sauvée dans `probes/stays-*.json`, puis écrire les adaptateurs à partir des vrais champs. Les noms des champs prix, taxes, annulation ne sont pas documentés publiquement. `get_scraper_details` via MCP ou `https://docs.brightdata.com/scrapers/<dataset_id>.json`.
