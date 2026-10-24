# Audit Bright Data de bout en bout, 2026-10-24

Question d'Ilan, mot pour mot : « vérifier que Bright Data va bien chercher toutes les données dont on a besoin, et que ce n'est pas des données synthétiques ; que le scraping scrape les bonnes informations et toutes les informations dont on a besoin ; qu'elles soient bien traitées et bien retransmises dans l'interface ».

Périmètre : `spicyx9/PatchConferenceHack`, `origin/main` à `cd49ec3` (PR 27), worktree `PCH-bd`, branche `audit/brightdata-e2e`. Lecture seule du code, aucun correctif.

## Conditions de l'audit

- **Clé Bright Data : absente sur cette machine.** Mesuré : `grep` de `BRIGHTDATA` dans `.env`, `.env.local` et `.env.example` des 14 worktrees `PCH*` (seuls les `.env.example` vides et deux `.env` ne contenant que FalkorDB), `env | grep -i bright` vide, aucun fichier shell (`~/.zshrc`, `~/.zprofile`, `~/.zshenv`, `~/.bash_profile`, `~/.profile`) ne la mentionne, aucun dossier `HTest` sur la machine. Demandée à Ilan par message à 20h3x UTC ; pas de réponse au moment d'écrire.
- **Donc zéro appel Bright Data payant lancé par cet audit.** Les sondes `make probe-lodging`, `make probe-flights`, `make probe-brightdata-travel` ont été relancées sans clé (résultat : `missing_credentials` partout, fichiers `probes/*.md` restaurés ensuite avec `git checkout` pour ne pas écraser les rapports live d'Axel). `make probe-linkedin` refuse l'argument positionnel que `scripts/run_probe.py` lui passe (`linkedin.py: error: unrecognized arguments: linkedin`) : la cible `make probe-linkedin` est cassée.
- **Preuve live disponible : les enregistrements collectés par Axel** avec sa clé, aujourd'hui, committés dans `data/cache/stays.json` (21 séjours, `collected_at` 18:41:15 UTC, snapshots `sd_mvmqn1ir1b96s56ixb` Booking et `sd_mvmqn1lb1iu27stdzv` Airbnb), `data/cache/flights.json` (34 itinéraires, 18:18:14 UTC, une page Web Unlocker), `data/cache/linkedin_public.json` (10 profils, 19:14 à 20:07 UTC), plus `probes/brightdata-travel.md` (run 18:41 UTC) et `data/block_matrix.json` (run 19:01 UTC). Ce sont des réponses Bright Data réelles mais passées : l'audit ne peut pas prouver que la clé marche encore à l'heure de la démo.
- Métadonnées des datasets vérifiées via le connecteur MCP Bright Data du poste (`get_scraper_details`, `list_dataset_fields`, lecture de catalogue, non facturée) : les six identifiants du code existent et les champs d'entrée du code correspondent (détail dans la matrice).
- Parcours de bout en bout mesuré sur une copie de la démo lancée pour l'audit : `FALKORDB_PORT=6380 uv run python scripts/run_demo.py --port 8010 --graph conferge_bd_audit --reset-graph` (mode par défaut : `--mode fixture`, `--travel cached`, `--linkedin cached`), API `http://127.0.0.1:8010/api/v1/*`, graphe FalkorDB `conferge_bd_audit` lu par `conferge.graph.queries.run_read`, DOM lu dans le navigateur intégré. Tests : `uv run pytest -q` → 1194 passed, 25 skipped (34 s) ; 39 fichiers de tests touchent Bright Data, tous sur mocks.

## Verdict en une ligne par usage

| Usage | Produit Bright Data | Verdict | Preuve |
|---|---|---|---|
| Séjours Booking (recherche) | dataset `gd_m4bf7a917zfezv9d5` | **LIVE PARTIEL** (prix total et coordonnées oui ; taxes, frais, disponibilité null) | 15 enregistrements à 18:41 UTC, 6 affichés, tracés jusqu'au DOM |
| Séjours Booking (vérification page hôtel) | dataset `gd_mdy9ld3p1e0oqlj9g4` | **NON TESTÉ live** (aucune trace de résultat : `availability` unknown, `verified_at` null sur les 15) | `data/cache/stays.json`, `probes/brightdata-travel.md` |
| Séjours Airbnb | dataset `gd_ld7ll037kqy322v05` | **LIVE PARTIEL** (6 totaux datés ; taxes null, disponibilité unknown ; aucun affiché) | 6 enregistrements, snapshot `sd_mvmqn1lb1iu27stdzv` |
| Séjours Google Hotels | dataset `gd_mg3gjfmg12tc2n5d4d` | **NON TESTÉ live, 0 enregistrement** (panne fournisseur `no_peers` à 18:12 UTC, mapping jamais validé) | `data/block_matrix.json`, `probes/brightdata-travel.md` |
| Séjours pages de recherche (Hilton, Kayak, Hotels.com, Expedia, Marriott) | Web Unlocker zone `web_unlocker1` | **LIVE PARTIEL, 0 prix** (Hilton 20 hôtels sans tarif daté ; 4 sites refusés, KYC requis) | `probes/brightdata-travel.md` |
| Vols Google Flights (dataset) | dataset `gd_mhng7wen1rw0a3gvpf` | **NON TESTÉ live, 0 enregistrement** (3 snapshots encore `running` après 396 s ; `data/snapshots/` vide) | `probes/brightdata-travel.md`, `data/block_matrix.json` |
| Vols Google Flights (page) | Web Unlocker | **LIVE PARTIEL** (34 allers avec numéro de vol ; prix stocké null, retour non collecté) | `data/cache/flights.json`, tracé jusqu'au DOM |
| Vols fast-flights via zone SERP | SERP (transport) | **NON TESTÉ live** (sans clé, fast-flights part en direct : 101 offres, hors Bright Data) | `scratch` probe sans clé |
| Personnes LinkedIn (profils) | dataset `gd_l1viktl72bvl7bjuj0` | **LIVE PARTIEL** (9 profils nom + entreprise ; `headline` absent sur 10/10) | `data/cache/linkedin_public.json`, DOM |
| Personnes LinkedIn (recherche d'URL) | SERP | **NON TESTÉ live** (jamais appelé par la démo ; `make probe-linkedin` cassé) | `scripts/run_demo.py:74` `allow_collect=False` |
| Découverte d'événements (requêtes Google) | SERP | **FIXTURE SEULEMENT** (jamais lancé live ; replay synthétique étiqueté) | `probes/discovery.md`, `fixtures/discovery.json` |
| Découverte Facebook Events | dataset `gd_m14sd0to1jz48ppm51` | **NON TESTÉ live** (noms de champs « UNVERIFIED » dans le code) | `conferge/events/discovery/facebook.py:11-15` |
| Catalogue officiel RainFocus | Web Unlocker (facultatif) | **LIVE OK sans Bright Data** (JSON public direct ; Unlocker = repli) | `probes/official.md` |
| Uber (estimation trajet) | Web Unlocker | **NON TESTÉ live** | `probes/travel.md` |

## Matrice détaillée

Colonnes : 1) produit, paramètres, dataset ; 2) ce qui revient ; 3) besoin de l'app (`conferge/core/schemas.py`) et manques ; 4) normalisation ; 5) chemin vers l'écran ; 6) risque de donnée synthétique.

### Séjours Booking (recherche)

1. `conferge/lodging/booking.py:155-166` : `POST /datasets/v3/scrape` (`conferge/core/brightdata.py:178-211`), `collect_by_url`, une entrée `{url: https://www.booking.com, location, check_in/check_out ISO Z, adults, children, rooms, currency, country}`, `limit_per_input = q.limit`. Catalogue Bright Data (MCP) : champs d'entrée identiques, `final_price` = « Total price after discounts and taxes », `map_coordinates`, `review_score`, `total_listings_found`.
2. Live d'Axel 18:41 UTC : 15 lignes, 15 prix, min 252 max 1213 USD, statut `degraded/page_cap` (plus de résultats que la limite). Exemple : `booking:1887396` Chelsea Inn, 500.00 USD, 761 m, note 8.2/10, 1861 avis, URL avec `checkin/checkout/group_adults=2/sb_price_type=total`. Champs null : `taxes`, `fees_total`, `includes_all_fees`, `free_cancellation`, `availability=unknown`, `verified_at=None`.
3. Besoin : nom, total, devise, dates, lieu, URL source, `collected_at` : présents. Manque : taxes, frais et disponibilité, donc jamais `verified_bookable` (`conferge/lodging/normalize.py:48-71`).
4. `_search_quote` lit `final_price` et `tax_description` (`booking.py:341-362`) ; zéro ou vide → `None` (`conferge/lodging/_common.py:49-70`) ; lignes avec `error` exclues et comptées (`conferge/lodging/_bd.py:70-77`) ; dates et occupants écho différents de la requête → prix supprimé avec avertissement (`normalize.py:118-124`) ; `nightly_avg` dérivé du total, jamais l'inverse (`normalize.py:137-143`). Aucun prix inventé.
5. `data/cache/stays.json` → `travel_cache.load` relabellise `live` → `cached` (`conferge/integration/travel_cache.py:59-62`) → `pick_stays` garde 6 par tier (`conferge/integration/stays_flights.py:40,73-81`) → graphe `(:Lodging {id:'booking:1887396', total_price:'500.00', price_status:'quoted_total', source_mode:'cached'})` → `GET /api/v1/stays` (`conferge/api/app.py:526-529`, `conferge/api/logic.py:428-445`) : `total_price 500.00 USD, price_status quoted_total, source_mode cached, source.label "Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking)", snapshot sd_mvmqn1ir1b96s56ixb` → DOM (`static/app.js:1127-1180`) : « Chelsea Inn | price Quoted total | availability Not provided | Bright Data · dataset | Total: 500.00 USD | Distance to venue: 761 m | View offer » avec le lien Booking exact. **Valeur identique de bout en bout.** Mais la carte ne porte aucun mot « Cached » : `sourceBadge` renvoie une chaîne vide pour `live`, `cached` et `fixture` (`static/app.js:200-203`).
6. Fixture `fixtures/lodging.json` : noms « (fictional fixture) », `source_mode fixture`, utilisée seulement si `data/cache/` manque (`scripts/run_demo.py:159`).

### Séjours Booking (vérification page hôtel)

1. `booking.py:224-275`, dataset `gd_mdy9ld3p1e0oqlj9g4` sur l'URL hôtel reconstruite avec le séjour (`stay_url`, `booking.py:78-91`). Catalogue : sortie `pricing`, `availability`, `check_in`, `check_out`.
2. Aucune trace d'un résultat : les 15 enregistrements du cache ont `detail` absent (`availability unknown`, `verified_at null`). `probes/brightdata-travel.md` ne mentionne pas ce dataset. NON TESTÉ.
3. C'est la seule voie vers `verified_bookable` ; sans elle, « Quoted total » est le plafond.
4. Promotion à `verified` uniquement sur signal explicite taxes incluses et disponibilité (`booking.py:380-448`) ; prix « per night » ignoré ; écart de dates → ignoré avec avertissement.

### Séjours Airbnb (dataset)

1. `conferge/lodging/airbnb.py:354-359` : `discover_by_location`, `{location, check_in, check_out, num_of_adults, currency, country}` ; catalogue MCP : mêmes noms de champs.
2. Live 18:41 UTC : 6 lignes, 6 prix (647 à 791.12 USD), `ok/exhausted`, snapshot `sd_mvmqn1lb1iu27stdzv`. Taxes, frais, disponibilité null. Block matrix 19:01 : 5 lignes avec erreur `aborted_page` sur une partie.
3. Manque : taxes jamais exposées (docstring `airbnb.py:17-20`), donc `quoted_total` au mieux.
4. `_brightdata_lodging` (`airbnb.py:698-736`) : total retenu seulement si `travel_details.check_in/check_out` égalent la requête, sinon prix « from » nocturne ou rien ; `price=0` → None.
5. Les 6 lignes sont dans le cache mais **aucune n'est affichée** : `pick_stays` prend 6 séjours, Booking et Airbnb sont au même tier 0 et l'ordre de service place Booking d'abord. L'écran annonce « Stays via Bright Data: 6/6 », tous Booking.

### Séjours Google Hotels (dataset)

1. `conferge/lodging/google_hotels.py:269-294` : `discover_by_search`, `{search_term, check_in_date, check_out_date, guest_number, country, currency}` ; catalogue MCP identique ; `booking_options` non documenté.
2. 0 enregistrement : snapshot `sd_mvmqtmqu2f5qp48xvg` « ready, 0 records, errors: no_peers (Bright Data provider outage at 18:12 UTC, confirmed by Bright Data email) » (`data/block_matrix.json`) ; `probes/brightdata-travel.md` : `degraded/error, fetched 0`.
3. Rien à l'écran ; le code dit lui-même « UNVERIFIED LIVE » (`google_hotels.py:9-12`).
4. Prix sans portée explicite (total ou nuit) gardé en texte brut seulement (`google_hotels.py:173-220`).

### Séjours pages de recherche (Web Unlocker)

1. `conferge/lodging/unlocker.py:36-57` : `POST /request {zone, url, format: raw}` (`brightdata.py:264-281`) sur Kayak, Hotels.com, Expedia, Marriott, Hilton.
2. Hilton : 20 hôtels, 0 prix (tarifs datés chargés côté client) ; 4 sites : « Residential Failed (bad_endpoint), KYC required » (`probes/brightdata-travel.md`, `unlocker_parsers.py:3-9`).
4. Un prix de page de recherche ne dépasse jamais `indicative` (`unlocker.py:147-171`) ; tarif Hilton non daté exposé comme `undated_lead_rate`, jamais comme prix (`unlocker_parsers.py:110-156`). Correct.

### Vols Google Flights (dataset)

1. `conferge/flights/brightdata_provider.py:44,69-84` : `discover_by_input_filters` `{origin, destination, departure, return, trip_type "Round trip", adults, cabin "Economy", currency, country}` puis `collect_by_url` ; catalogue MCP : champs identiques, sortie `pricing`, `providers`, `legs`, `search`.
2. 0 enregistrement reçu à ce jour : snapshots `sd_mvmqn1kd1ty930z4jj`, `sd_mvmqn1l21499xs75pl`, `sd_mvmqn23o2mnatsrk8y` encore `running` après 396 s ; `sd_mvmr6icq29xwep13p7` `running` à 19:01 UTC ; `data/snapshots/` n'existe pas dans le dépôt (le fournisseur `snapshot_provider.py:28-30` n'a rien à lire).
3. Le mapping `record_to_raw_offer` (`brightdata_provider.py:354-391`) accepte plusieurs orthographes et renvoie `schema_changed` sinon : **jamais confronté à une vraie ligne**.
5. Panneau pipeline : « Google Flights: Bright Data dataset pending ».

### Vols Google Flights (Web Unlocker)

1. `conferge/flights/unlocker_provider.py:175-183` : une page `https://www.google.com/travel/flights?q=Flights from NYC to SFO on 2026-10-27 through 2026-10-30&curr=USD&hl=en`, parse de `AF_initDataCallback ds:1`.
2. Live 18:18 UTC : 34 itinéraires aller, tous avec numéro de vol et heures locales ; prix lu sur la page = total aller-retour (ex. « 413 USD round trip total »).
3. Besoin : prix, dates, aéroports, URL : présents sauf la tranche retour, que la page ne liste pas.
4. Stocké honnêtement : `trip_type one_way`, `total_price None`, `price_status unknown`, total brut dans `raw_price_text` (`unlocker_provider.py:223-261`, `flights/normalize.py:158-183`).
5. **Divergence stockage / affichage** : `round_trip_total.display` (`conferge/flights/round_trip_total.py:43-51`) réécrit pour l'API `trip_type round_trip, price_status quoted_total, total_price 413, return_slice_collected False` ; `travel_view` l'applique (`logic.py:471-475`). Mesuré : graphe `(:FlightOffer {total_price: null, price_status: 'unknown', trip_type: 'one_way'})` ; API `/flights` et `/travel` : `413 USD quoted_total round_trip` ; DOM : « EWR to SFO … F9 413 USD (round trip total), return not collected | Bright Data · Web Unlocker | Quoted total » et budget « Flights $413 (price quoted_total) ». Le chiffre 413 est bien observé sur la page (pas inventé) et la mention « return not collected » est affichée, mais `quoted_total` n'existe pas dans le contrat vol (`schemas.py:301`) et le graphe dit autre chose que l'écran.
6. Fixture `fixtures/flights.json` : transporteur fictif ZZ, prix `unknown`, refusée si `source_mode != fixture` (`flights/service.py:61-74`) ; servie uniquement sur `allow_fixture=True`.

### Vols fast-flights via zone SERP

1. `conferge/flights/fastflights_provider.py:117-127` : `fast_flights.integrations.BrightData(api_key, zone)` quand clé et zone SERP existent ; sinon direct, avec avertissement `fast_flights_direct`.
2. Sans clé (cet audit) : 101 offres directes, Bright Data 0. Avec clé : non testé.
6. `record_usage("serp")` est incrémenté (`fastflights_provider.py:121`) mais l'évidence ne porte pas Bright Data, donc l'écran le montre « Fallback fast-flights » (`conferge/api/provenance.py:19-20,94-95`) : compteur et badge ne racontent pas la même chose.

### Personnes LinkedIn (profils)

1. `conferge/integration/people_linkedin.py:43,212-247` : `POST /datasets/v3/scrape` dataset `gd_l1viktl72bvl7bjuj0`, `[{url}]` par lots de 20, 2 reprises, 120 s ; et `GET /datasets/v3/snapshot/<id>` (`people_linkedin.py:186-210`). Catalogue MCP : champs `name`, `position`, `current_company`, `current_company_name`, `experience`, `followers`, `url`, `input_url` (pas de champ `headline`).
2. Cache public : 10 profils, nom et entreprise présents, `headline` absent sur 10/10, 7 avec snapshot `sd_mvms2ssrh1bjodbs9` (19:14 à 19:16 UTC), 3 sans snapshot (collecte directe 20:07 UTC). `probes/linkedin.md` (19:26 UTC) : 9 appariés, 1 nom différent, aucune nouvelle collecte.
3. Besoin : nom, titre, entreprise, URL. Titre manquant partout à l'écran.
4. `name_matches` exige prénom et nom identiques (`people_linkedin.py:390-397`) ; `identity_confidence` 1.0 si l'entreprise concorde, 0.7 sinon ; jamais d'arête `ATTENDS` ni de `presence_confidence` (`people_linkedin.py:21-23,496-529`). Mesuré dans le graphe : 9 `Person` avec `provider brightdata:linkedin`, `linkedin_source_mode cached`, 2 `Company` créées (`Latitude.sh`, `Versent`), 7 `WORKS_AT` existantes corroborées sans réécrire leur provenance `fixture`.
5. `GET /api/v1/people` (`app.py:470-486`) : `linkedin.source_mode cached, company GitHub, headline None, identity_confidence 1.0` → DOM (`static/app.js:175-199`) : « LINKEDIN Not provided · GitHub profile brightdata:linkedin », tooltip `dataset gd_l1viktl72bvl7bjuj0 | snapshot sd_mvms2ssrh1bjodbs9 | collected_at 2026-10-24T19:16:06Z`. Fidèle au cache ; le classement des personnes ne change pas (probe : top 5 identique avant/après).
6. `conferge/people/linkedin.py:9-10` dit « dataset ids come only from the environment, there are no hardcoded defaults », mais `LinkedInDatasets.from_env` (`linkedin.py:308-322`) code en dur `gd_l1viktl72bvl7bjuj0` et `gd_l1vikfnt1wgvvqz95w`. Doc et code divergent ; les identifiants sont bons (vérifiés au catalogue).

### Découverte d'événements (SERP) et Facebook

1. `conferge/events/discovery/serp.py:189-230` : `POST /request {zone: SERP, url: google.com/search?q=…}` (`brightdata.py:253-262`), 36 requêtes planifiées ; pages candidates ensuite via Web Unlocker ou GET direct (`serp.py:408-430`). Facebook : `facebook.py:45,133-150`.
2. Jamais lancé live : `probes/discovery.md` 07:32 UTC `failed / key missing` ; aucun run plus tard. Fixture `fixtures/discovery.json` : « synthetic SERP replay built from real URLs… pairing is constructed, not observed », étiquetée `fixture`. En mode `--mode fixture` (défaut de `make demo`, `run_demo.py:113`), les événements affichés viennent des fixtures Luma, Partiful, Eventbrite, agrégateurs et RainFocus (captures publiques réelles rejouées, `source_mode fixture`), pas de Bright Data.
6. Les événements de la page d'accueil portent « Luma capture » et le badge global « Mixed sources » ; la provenance `fixture` est explicite dans `/api/v1/sources`.

### Catalogue officiel RainFocus

1. `conferge/events/official/rainfocus.py:156-176` : GET du portail via Web Unlocker si clé et zone, sinon direct ; le POST `api/search` reste direct.
2. `probes/official.md` 06:33 UTC : 210 éléments live, « Bright Data: not needed » ; block matrix : la page catalogue est une coquille JS pour tous les transports, y compris Unlocker. LIVE OK sans Bright Data.

## Les 5 écarts les plus graves (ligne à corriger)

1. **Le panneau Bright Data affiche une heure de collecte fausse.** « From the Bright Data cache: 64 records … collected 11:18 AM to 01:35 PM » : la borne 13:35 PDT (20:35 UTC) est l'heure de démarrage de la démo, pas une collecte. Cause : `/brightdata` prend `r["collected_at"]` des lignes pipeline (`conferge/api/app.py:396-398`), qui est `report.finished_at` (`conferge/integration/pipeline_view.py:47`), et le rapport LinkedIn a `finished_at = now` (`conferge/integration/people_linkedin.py:549-556`). Correction : utiliser le `collected_at` des enregistrements, pas la fin du rapport.
2. **Le compteur « Records collected through Bright Data: 64 » et le coût « $0.0960 » ne mesurent pas la consommation facturée.** 64 = 30 lignes de dataset + 34 itinéraires extraits d'une seule page Web Unlocker (1 requête). `_USAGE` compte des lignes renvoyées (`conferge/core/brightdata.py:27-30,46`) ; le coût applique 1,50 $/1000 enregistrements à des lignes Unlocker, facturées par requête (`pipeline_view.py:23-24,45-47`). Aucun en-tête de coût n'a jamais été observé (`people_linkedin.py:177-179` les capture, dictionnaire vide dans les caches). Correction : afficher requêtes et lignes séparément, et retirer le coût ou l'étiqueter « liste de prix, non facturé ».
3. **Le vol affiché contredit son enregistrement en graphe.** Graphe : `one_way, total_price null, price_status unknown` ; API et écran : `round_trip, 413 USD, quoted_total`, et le budget additionne 413. La relecture est à `conferge/flights/round_trip_total.py:43-51` et `conferge/api/logic.py:471-475`. La mention « return not collected » est visible, mais un jury qui lit FalkorDB et l'écran voit deux vérités. Correction : soit stocker `raw_price_text` et la vue identiques (statut `observed_live` + libellé « round trip total shown on page »), soit ne pas additionner dans le budget.
4. **Aucune carte séjour ou vol ne dit « Cached » ni la date de collecte.** `sourceBadge` renvoie vide pour `live`, `cached` et `fixture` (`static/app.js:200-203`) ; le tooltip du badge « Bright Data · dataset » (`static/app.js:132-157`) n'inclut pas `collected_at`. Les prix datent de 18:18 et 18:41 UTC et seront vieux de 19 h au moment de la démo. Règle 5 de `CLAUDE.md` : chaque enregistrement dit s'il est live, cached ou fixture. Correction : ajouter `collected_at` au tooltip et un badge « Cached · 11:41 AM » sur la carte.
5. **Deux produits Bright Data vendus dans le pitch n'ont jamais produit un enregistrement : Google Flights dataset et Google Hotels dataset.** `data/snapshots/` absent, mapping `record_to_raw_offer` (`brightdata_provider.py:354-391`) et `google_hotels.to_lodging` (`google_hotels.py:173-220`) jamais confrontés à une vraie ligne. Si la démo bascule en `--travel live`, le routeur attend ces datasets (`flights/service.py:77-93`, `lodging/service.py:63-73`) avant les replis. Correction : laisser `--travel cached` pour la démo et retirer ces deux datasets du discours, ou lancer `scripts/probes/flights_collect.py` avec la clé et vérifier le mapping avant 13h30.

Écarts secondaires : `make probe-linkedin` cassé (argument positionnel) ; `fast_flights` incrémente le compteur SERP sans évidence Bright Data (`fastflights_provider.py:121` vs `provenance.py:94-95`) ; `LinkedInDatasets.from_env` contredit sa docstring (`people/linkedin.py:9-10` vs `312-322`) ; 6 séjours Airbnb Bright Data collectés et jamais affichés (`stays_flights.py:40,73-81`) ; `headline` LinkedIn vide sur 10/10 profils (le dataset expose `position`, `profile_from_record` le lit en second, `people_linkedin.py:355-383` ; sans les fichiers `data/probes/` absents ici, impossible de dire si Bright Data l'a renvoyé).

## Ce qui est sain (vérifié)

- Aucun prix inventé : zéro ou vide → `None` (`_common.py:49-70`), `nightly_avg` dérivé du total uniquement, prix de page de recherche plafonné `indicative`, prix sans devise supprimé (`flights/normalize.py:180-183`).
- Aucune confirmation sans preuve : LinkedIn n'écrit jamais `ATTENDS` ; `verified_bookable` exige re-vérification datée < 30 min, disponibilité et taxes incluses (`normalize.py:48-71`).
- Fixtures explicites : chargement refusé sans `explicit_opt_in` (`brightdata.py:284-292`, `flights/service.py:61-74`) ; `fixtures/flights.json` transporteur fictif ZZ ; `fixtures/lodging.json` noms « (fictional fixture) » ; `fixtures/api.json` `_meta.note` « FICTIONAL ».
- Relabel `live` → `cached` correct dans le cache voyage (`travel_cache.py:59-62`), la mémoire disque lodging (`lodging/service.py:51-60`) et le pool LinkedIn (`people_linkedin.py:272-296`) ; dans le graphe mesuré, `Lodging` et `FlightOffer` portent `source_mode cached`, `Person` LinkedIn `linkedin_source_mode cached`, les 215 `Person` et 207 `Event` restent `fixture`.
- Sans clé, tout échoue visiblement : `missing_credentials` dans chaque rapport, `/brightdata` répond `data_source unknown` et `ready: false` sur les trois API, `_request` lève avant tout appel (`brightdata.py:147-148`). Aucun `except Exception` ne substitue une fixture : les 30 occurrences lues produisent un `RunReport failed` ou un avertissement.
- La valeur affichée est bien la valeur collectée : Chelsea Inn 500.00 USD identique dans le cache, le graphe, `/api/v1/stays` et le DOM ; URL Booking identique au caractère.

## Ce qui n'a pas pu être testé, et pourquoi

- Tout appel live Bright Data (SERP, Web Unlocker, les six datasets) : pas de clé sur cette machine ; demande envoyée à Ilan, Axel la détient sur HTest.
- Google Flights dataset et Google Hotels dataset : zéro ligne reçue à ce jour, même par Axel.
- Vérification Booking (`gd_mdy9ld3p1e0oqlj9g4`), Facebook Events, Uber, recherche LinkedIn par SERP : aucune trace de run live dans le dépôt.
- `make probe-linkedin` : la cible passe un argument que le script refuse.
- Coût réel : aucun en-tête de coût dans les réponses capturées ; seul le tableau de bord Bright Data d'Axel peut le donner.
- Fraîcheur à 13h30 : les enregistrements servis auront 19 h ; sans clé, rien ne peut être recollecté.

Fichier : `/Users/ilansainteagathe/Desktop/Patchconferencehack/PCH-bd/docs/audits/BRIGHTDATA_E2E_2026-10-24.md`.
