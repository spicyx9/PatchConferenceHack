# Bright Data : produits, endpoints, datasets, coûts

## Variables d'environnement

BRIGHTDATA_API_KEY, BRIGHTDATA_UNLOCKER_ZONE, BRIGHTDATA_SERP_ZONE, BRIGHTDATA_BROWSER_WSS (wss://brd-customer-...:...@brd.superproxy.io:9222), OPENAI_API_KEY, FALKORDB_HOST, FALKORDB_PORT, SERPAPI_KEY (optionnel), GMAIL_CREDENTIALS_JSON (optionnel).

## Produits et quand les utiliser

| Produit | Endpoint | Usage Conferge | Coût PAYG |
|---|---|---|---|
| Web Scraper API (datasets) | `POST https://api.brightdata.com/datasets/v3/scrape?dataset_id=...&include_errors=true` (synchrone, < 1 min, sinon HTTP 202 + snapshot_id) ; `POST /datasets/v3/trigger?dataset_id=...` puis `GET /datasets/v3/progress/{snapshot_id}` et `GET /datasets/v3/snapshot/{snapshot_id}?format=json` ; discovery : `&type=discover_new&discover_by=input_filters` ou `discover_by=location` ; body `{"input":[...],"limit_per_input":N}` ; header `Authorization: Bearer KEY` | Booking, Airbnb, Google Hotels, Google Flights, LinkedIn profils/entreprises/posts, Facebook Events, X posts | 5 000 enregistrements gratuits/mois, puis 1,50 $ / 1 000 |
| SERP API | `POST https://api.brightdata.com/request` avec `{"zone": SERP_ZONE, "url": "https://www.google.com/search?q=...&gl=us&hl=en&brd_json=1", "format": "raw"}` ; ou MCP `search_engine` / `search_engine_batch` (10 requêtes) | découverte longue traîne, nom + entreprise → LinkedIn, Google Flights en secours (HTML seulement, pas de brd_json pour travel/flights) | 5 000 gratuits, 1,50 $ / 1 000 |
| Web Unlocker | `POST https://api.brightdata.com/request` avec `{"zone": UNLOCKER_ZONE, "url": ..., "format": "raw"}` | pages Luma, sites exposants, agrégateurs, Crunchbase, Uber estimateur, Meetup HTML | 5 000 gratuits, 1,50 $ / 1 000 |
| Browser API (Scraping Browser) | Playwright `chromium.connect_over_cdp(BRIGHTDATA_BROWSER_WSS)` | pages dynamiques Universe, Partiful et Luma invités (session connectée), Facebook, scroll infini | 5 à 8 $/GB (contradiction entre pages) |
| Crawl API | `POST /datasets/v3/trigger` crawl | site officiel entier, calendriers | 1,50 $ / 1 000 |
| MCP | `https://mcp.brightdata.com/mcp?token=KEY` ou `npx @brightdata/mcp` ; outils search_engine, scrape_as_markdown, scrape_batch, extract, search_scrapers, get_scraper_details, run_scraper, get_scraper_progress, get_scraper_results, scraping_browser_* | exploration des scrapers le matin, démo agent | 5 000 requêtes gratuites/mois |
| CLI brightdata/cli | `scraper run`, `search`, `scrape` | tests rapides | idem |

## Dataset IDs connus (à confirmer le matin avec get_scraper_details, ne jamais coder en dur sans vérification)

| Dataset | ID | Entrées | Sortie connue |
|---|---|---|---|
| Booking listings search | gd_m4bf7a917zfezv9d5 | location, check_in, check_out (ISO Z), adults, children, rooms, currency, country, property_type | id, nom, ville, prix, devise, dates, dispo |
| Booking hotel listings with pricing (by URL) | gd_mdy9ld3p1e0oqlj9g4 | URL de fiche avec checkin, checkout, group_adults, no_rooms, selected_currency, sb_price_type=total | prix total, taxes, annulation (noms de champs à relever) |
| Airbnb search by location | gd_ld7ll037kqy322v05 | location, check_in, check_out, guests | prix (souvent null dans l'échantillon), availability, coordonnées, amenities |
| Google Hotels discover by search | gd_mg3gjfmg12tc2n5d4d | search_term, check_in_date, check_out_date, guest_number, country, currency | 31 champs : booking_options, lat, long, currency, rating |
| Google Flights | gd_mhng7wen1rw0a3gvpf | discover_by=input_filters : origin, destination, departure, return, trip_type, adults, children, infants_*, cabin ; collect_by_url : URL tfs | url, itinerary_id, search, pricing, providers, legs |
| Facebook Events | gd_m14sd0to1jz48ppm51 | collect by URL ; discover by page URL ou par lieu | id, titre, date, lieu, organisateur, usersResponded, ticket, description, isCanceled |
| Agoda listings with pricing | gd_mdyifvvo181pcrpew6 | URL avec checkIn, los, adults, currencyCode, finalPriceView=2 | prix final, original, taxes |
| LinkedIn profiles, companies, posts ; X posts ; Instagram | à chercher via search_scrapers("linkedin") le matin | URL ou nom | profil, expériences, posts |

Pas de scraper préconstruit Luma, Partiful ou Meetup : connecteurs maison (JSON publics) ou Scraper Studio.

## Gestion d'échec (core/brightdata.py)

- Retry x3 backoff exponentiel sur 429, 5xx, timeout. Timeout 60 s. `limit_per_input` toujours fixé.
- Enregistrements avec champ `error` ou prix null : exclure et compter dans RunReport.warnings.
- Clé absente ou échec final : lever BrightDataUnavailable ; le provider bascule sur `fixtures/<dossier>.json` et renvoie `data_source: fixture`.
- Sauvegarder chaque réponse brute dans `probes/raw/<dataset>-<timestamp>.json` pendant le hackathon (gitignored).

## Pages produit et docs

https://docs.brightdata.com/products/scrapers/google/send-first-request, https://docs.brightdata.com/api-reference/scrapers/search-engines-apis/google-flights-discover-by-input-filters, https://docs.brightdata.com/products/serp-api/query-parameters/google, https://docs.brightdata.com/products/mcp-server/tools, https://github.com/brightdata/brightdata-mcp, https://github.com/brightdata/sdk-python, https://github.com/brightdata/skills

## Limites et IDs complémentaires (avant vague 3)

- Limites : moins de 20 inputs par requête synchrone ; 25 réponses 429 en 5 min bloquent l'IP ; snapshots conservés 30 jours ; 5 000 crédits gratuits partagés au niveau du compte (pas par produit).
- IDs complémentaires (à confirmer avec get_scraper_details) :

| Dataset | ID |
|---|---|
| LinkedIn discover by name | gd_m8d03he47z8nwb5xc (tester aussi gd_l1viktl72bvl7bjuj0 avec `discover_by=name`) |
| LinkedIn posts | gd_lyy3tktm25m4avu764 |
| X profiles | gd_lwxmeb2u1cniijd7t4 |
| X posts | gd_lwxkxvnf1cynvib9co |
| Crunchbase | gd_l1vijqt9jfj7olije |
| Google Maps | gd_m8ebnr0q2qlklc02fz |
| Facebook Events | gd_m14sd0to1jz48ppm51 |
