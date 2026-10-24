# Repos GitHub : prendre, adapter, éviter

Tous vérifiés existants le 23 octobre 2026. Cloner en lecture seule dans `vendor/` (gitignored) pour lire, copier les fichiers utiles avec l'en-tête "adapted from <url> (<licence>)".

## À copier (MIT ou Apache)

| Repo | Prendre | Pour |
|---|---|---|
| aiecosystemengineer/ai-eventscraper | backend/scrapers/base.py, luma.py, meetup.py, eventbrite.py, fb_wall.py, social.py, instagram/flyer_extractor.py, orchestrator.py, filters.py, timezone.py | w01 w02 w04 |
| njoerd114/kubecon-eu-mcp | src/kubecon_eu_mcp/party_parser.py, ical_parser.py, data_service.py, models.py | w02 w03 |
| kbhujbal/Multi-Agent-AI-Travel-Advisor | backend/services/base.py, backend/models/schemas.py, pattern services/*/service.py | w05 w06 w11 |
| johnbalvin/pyairbnb | pip install, search_all, get_price, get_calendar | w05 |
| AWeirdDev/flights (fast-flights) | pip depuis git épinglé, integrations.BrightData | w06 |
| 0gulcandogann/reinvent-pathfinder | apps/api/app/optimizer, ranking, explain, mutations, docs/optimizer.md, docs/architecture.md | w10 w09 |
| PyconUK/ConferenceScheduler | src/conference_scheduler (PuLP, original_schedule) | w10 |
| anthonyisaa/claude-code-meetup-app | ARCHITECTURE.md, src/ (matching deux étages), supabase/migrations | w07 w09 |
| FalkorDB/GraphRAG-SDK | pip install graphrag-sdk, GraphSchema | w08 |
| FalkorDB/falkordb-py, FalkorDB/skills | client, skills Claude Code | w08, orchestrateur |
| brightdata/sdk-python | client officiel (optionnel, sinon httpx direct) | core |
| brightdata/skills | skills Claude Code Bright Data à installer dans .claude/skills | orchestrateur |
| brightdata/ai-lead-generator, brightdata-agent-showcase | pattern Bright Data → OpenAI → résultat | w07 |
| luminati-io/LinkedIn-Scraper | appels datasets profils, entreprises, posts | w07 |
| luminati-io/google-flights-api, google-hotels-api, airbnb-properties-information-scraper, Booking-dataset-sample, Airbnb-dataset-samples | schémas de sortie réels pour fixtures | w05 w06 w13 |
| MattB543/asheville-event-feed (MIT selon README) | connecteurs Meetup GraphQL, Ticketmaster, JSON-LD, ICS | w02 |
| doluz/afterparty | client Partiful connecté, getGuests paginé | w07 phase 2 |
| HaroldLeo/google-flights-mcp | serpapi_client.py (booking_token) | w06 |
| openbnb-org/mcp-server-airbnb | démo agent | w12 |

## À lire, ne pas copier (sans licence ou licence contaminante)

| Repo | Lire | Raison |
|---|---|---|
| e-Reese/luma-partiful-eventbrite-event-aggregator | src/sources/luma/fetch.ts, partiful/fetch.ts, eventbrite/partition.ts, oracle.ts, dedupe/cross-source.ts, migrations | licence absente ou ISC selon le rapport ; réécrire en Python à partir des faits |
| brightdata/pepolehub | src/lib/brightdata/search.ts, linkedin.ts, src/lib/research/graph.ts | licence ambiguë |
| francescov1/facebook-event-scraper | parser Facebook | pas de licence |
| yyu0310/luma-event-scanner, Mezfinance/Token2049-side-event-list, mihirkavi/luma-discovery, prajjwal1/nyc, mayckolco/luma-event-scraper | idées : scoring champs forts, extraction organisateurs, lieu caché via X, seen_events.json | licences non vérifiées |
| liketrek/TREK | tournée 2-opt, hôtel ancre | AGPL |
| glaforge/devoxx-ai-schedule | patron d'agents | Java, licence non vérifiée |
| balouf/gismo (moteur Swapcard, MIT) | TF-IDTF + DIteration | inspiration scoring |

## À éviter

digital-engineering/airbnb-scraper (abandonné, GPL), ZoranPandovski/BookingScraper (GPL, pas de dates), scrapehero-code/booking-hotel-scraper (2020), dsec-hub/event_api_scraper (Luma un seul GET), hankmint/event-scraper (clé Knod payante), ScrapingBee/google-flights-scraper (tutoriel), duffelhq starter (données test), scrapers Kayak anciens, dtrungtin/actor-airbnb-scraper (2023), amadeus-python (archivé).

## Équivalents de Conferge

Aucun open source côté participant. Voir 14-market-landscape.md.
