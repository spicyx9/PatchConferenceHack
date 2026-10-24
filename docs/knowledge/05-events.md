# Événements : sources, endpoints, règles

Aucun projet existant ne couvre "tous les événements autour d'une conférence" : ils collectent par ville. La couche rattachement événement ↔ conférence est à écrire (w04 + w08).

## Sources et méthode (ordre de priorité pour Universe)

| Source | Méthode | Auth | Données | Pièges |
|---|---|---|---|---|
| Luma discover | `GET https://api2.luma.com/discover/get-paginated-events?latitude=37.8060&longitude=-122.4320&pagination_limit=50[&pagination_cursor=...]` headers `Accept: application/json`, `Referer: https://luma.com/` | aucune | api_id, titre, dates, fuseau IANA, lieu, coordonnées, hôtes, ticketing, nb invités | Le paramètre `cursor` est accepté et ignoré (boucle infinie, 45 au lieu de 779). Utiliser `pagination_cursor`. Ne pas passer `slug`. Drainer jusqu'à `has_more=false`, détecter curseur répété (`cursor_stuck`), max 60 pages, délai 300 ms. Pas de total : l'épuisement est la preuve. Rayon, pas frontière (2/3 des résultats dans SF même). Descriptions absentes du feed : enrichir par page événement. Invités visibles : partiels, nom + photo, pas de LinkedIn. Mot-clé non natif : filtrer côté Conferge |
| Luma page événement | `GET https://luma.com/<slug>` via Web Unlocker, JSON dans `__NEXT_DATA__` | aucune | description, hôtes, lieu exact après inscription parfois | Lieu "register to see address" : null, pas une devinette |
| Partiful Explore | 1. `GET https://partiful.com/explore/sf` → extraire `buildId` dans `__NEXT_DATA__` ; 2. `GET https://partiful.com/_next/data/{buildId}/explore/sf.json` ; unir `trendingSection.items`, `sections[].items`, `feedItems` ; `pageProps.regionEventCounts.SF` = total déclaré | aucune | id, titre, dates, lieu, image, RSVP | buildId tourne à chaque déploiement (404 → re-scraper une fois). Couverture faible (environ 42 events SF/cycle). Invités : uniquement avec session connectée (Browser API) sur les events où le compte est inscrit |
| Eventbrite | `POST https://www.eventbrite.com/api/v3/destination/search/` avec cookies navigateur rejoués (CSRF) ; filtres ville, dates, mots-clés | cookies | titre, description, organisateur, dates, lieu, prix, statut | Plafond environ 950 résultats par requête (19 pages de 50) : découper récursivement la plage de dates jusqu'à passer sous le cap ; un jour qui reste au-dessus = `page_cap` explicite. API officielle de recherche fermée depuis 2020 |
| Agrégateurs de soirées | `https://conferenceparties.com/<slug>/` (table Time, Sponsor, Event & RSVP Link, Location, Added) (raidandev.org et reinventradar.com retirés le 2026-10-24 : re:Invent Las Vegas uniquement) | aucune | nom, jour, heure, host, lieu, lien RSVP (Luma, Eventbrite, Meetup), date d'ajout | Parseur générique = toutes les confs du site (30+). Page github26 vide pour Universe. Colonne Added = signal Live Replanning |
| Site officiel Universe | `githubuniverse.com`, `reg.githubuniverse.com` : pages dynamiques, chercher le JSON derrière (XHR) sinon Browser API | aucune | sessions, speakers, sponsors, salles, horaires, evening events | Un GET simple ne donne pas le catalogue complet |
| Sessionize | `GET https://sessionize.com/api/v2/{endpointId}/view/All` | aucune (endpoint publié par l'organisateur) | sessions, speakers (bio, liens sociaux), salles | Trouver l'endpointId dans le code du site officiel |
| Sched | pages publiques `<event>.sched.com` | aucune | sessions, speakers, sponsors | API export réservée à l'organisateur |
| Meetup | GraphQL `api.meetup.com/gql-ext` (`keywordSearch`, lat/lon) ou HTML + JSON-LD | OAuth Pro pour l'API officielle (février 2025) | titre, dates, groupe, lieu, RSVP | 500 points / 60 s ; bloque les IP datacenter : passer par Web Unlocker |
| Facebook Events | Bright Data dataset `gd_m14sd0to1jz48ppm51` (collect by URL, discover by URL ou par lieu) ; fallback npm `facebook-event-scraper` (sans licence : faits seulement) | Bright Data | titre, description, lieu + coordonnées, offset UTC, hôtes, usersResponded, isCanceled, billet | `discover_by_*` limité à 10 par entrée par défaut : fixer `limit_per_input` |
| SERP longue traîne | Bright Data SERP (`search_engine_batch` en MCP ou `core.brightdata.serp`), résultats Google en JSON, pagination `cursor`, 10 requêtes par appel | Bright Data | URLs candidates + snippets | Un résultat SERP n'est jamais un événement : router l'URL vers le connecteur (Luma, Eventbrite, Partiful, Facebook) sinon `extract` |
| Posts X et LinkedIn | Web Scraper APIs posts + SERP ("see you at Universe", "who's going") | Bright Data | annonces, who's going | Signal, pas fait : présence `probable` |
| Calendriers communautaires SF | cerebralvalley.ai, AGI House, Frontier Tower, YC events, Linktree d'organisateurs | aucune | liens sortants Luma/Partiful/Eventbrite | Longue traîne, cas par cas |
| Instagram | Bright Data posts + extraction LLM vision des affiches (ai-eventscraper `flyer_extractor.py`) | Bright Data | affiche, date, lieu | Phase 2 |
| Ticketmaster, AllEvents, 10times, Devpost, dev.events | APIs ou pages publiques | clé ou aucune | événements grand public, hackathons | Compléments, pas pour Universe |

## Requêtes SERP de découverte (w04)

```
"GitHub Universe" San Francisco afterparty
"GitHub Universe" SF meetup
"GitHub Universe" hackathon
"GitHub Universe" happy hour
"Universe" developer event San Francisco October 2026
<sponsor> San Francisco October 2026 party
<sponsor> SF workshop October 2026
site:luma.com San Francisco October 27 2026
site:luma.com San Francisco October 28 2026
site:partiful.com San Francisco October 2026
site:eventbrite.com San Francisco GitHub developer October 2026
site:linkedin.com/events San Francisco October 2026
```
Frontière de découverte : conférence → ville + dates → sponsors → organisateur → speakers → lieux → communautés locales → événements trouvés → leurs co-organisateurs, lieux, sponsors.

## Rattachement événement ↔ conférence

Score 0 à 1 et signaux : `mentions_conference` (titre ou description), `date_within_window` (dates de la conf ±2 jours), `geo_within_radius` (rayon 8 km autour de Fort Mason), `host_is_sponsor_or_speaker`, `topic_overlap` (embeddings ou LLM sur sujets de la conf), `listed_on_aggregator`. Seuil d'inclusion 0.5, tout stocké avec le score.

## Rapport de terminaison (obligatoire)

```json
{"source":"luma","started_at":"...","finished_at":"...","requests":16,"pages":16,"raw_rows":779,"unique_ids":779,"termination":"exhausted","expected_count":null,"previous_median_count":770,"warnings":[]}
```
Alertes : curseur répété, page identique, has_more vrai sans nouvel id, zéro résultat, chute > 40 % vs médiane, champ critique disparu, HTML au lieu de JSON.

## Schéma Event (voir core/schemas.py)

Canonique + N sources. Champs : id, canonical_key (titre normalisé | début UTC arrondi 30 min | geohash 7), title, description, event_type (meetup, afterparty, dinner, workshop, hackathon, talk, breakfast, happy_hour, other), start/end (local, timezone, utc, offset, timezone_source), format (in_person, online, hybrid), venue (name, address, city, country, lat, lng, geo_precision), organizers (name, platform_id, url, socials), speakers (PersonRef), pricing (is_free, min, max, currency, ticket_url), capacity (limit, registered, sold_out), registration (status, url), status, conference_link (conference_id, score, signals), categories, sources[] (platform, source_id, url, fetched_at, fetch_method, run_id, content_hash, raw), first_seen_at, last_seen_at, last_changed_at, quality (merge_confidence, missing_fields).

## Repos (voir 12-repos-to-reuse.md)

- ai-eventscraper (MIT) : `backend/scrapers/base.py`, `luma.py`, `meetup.py`, `eventbrite.py`, `fb_wall.py`, `social.py`, `instagram/flyer_extractor.py`, `orchestrator.py`, `filters.py`, `timezone.py`. Corriger : Kuala Lumpur codé en dur (géo, fuseau), date du jour si date introuvable (interdit), fusion de deux events même titre même jour.
- e-Reese (TypeScript, sans licence claire) : spécification. `src/sources/luma/fetch.ts`, `partiful/fetch.ts`, `eventbrite/partition.ts`, `oracle.ts`, `dedupe/cross-source.ts` (titre normalisé, ±30 min, 500 m, trigramme 0.85, `ambiguous`).
- kubecon-eu-mcp (MIT) : `party_parser.py` (conferenceparties), `ical_parser.py`, `data_service.py`, `models.py`. CI cassée (SDK MCP v2) : parseurs oui, serveur non. Jours codés en dur à paramétrer.
- yyu0310/luma-event-scanner : scoring champs forts (host) vs faibles (description), mémoire des events vus.
- Mezfinance/Token2049-side-event-list : extraction des organisateurs, lieu caché via post X.
- MattB543/asheville-event-feed (MIT) : connecteurs Meetup GraphQL, Ticketmaster, JSON-LD, ICS.
- mihirkavi/luma-discovery : client TS + MCP Luma `searchNearby`.
