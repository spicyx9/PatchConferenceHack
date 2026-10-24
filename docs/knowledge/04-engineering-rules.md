# Règles d'ingénierie (non négociables)

## Execution Rules (reprises dans CLAUDE.md)

- Subagents en parallèle pour toute tâche indépendante (2 ou plus). Séquentiel uniquement si B dépend de la sortie de A ou d'un fichier partagé. Codex : activer multi_agent dans la config.
- Commits petits et fréquents, un par changement logique, messages conventionnels (feat:, fix:, docs:, test:). Push dès qu'une étape est verte.
- CI rouge : corriger et repousser, sans demander. Merge automatique dès CI verte.
- Aucune question à l'utilisateur. Toute décision = une ligne dans DECISIONS.md.
- Jamais de tiret cadratin ni demi-cadratin dans les textes et commentaires.

## Propriété

- Une fenêtre n'écrit que dans son dossier, `tests/<dossier>/` et `fixtures/<dossier>.json`.
- Tout changement dans `backend/app/core/` passe par une PR séparée, minuscule, mergée avant de continuer. Les schémas ne se modifient pas en passant.
- Chaque dossier expose `run(query)` et une cible `make probe-<dossier>` qui écrit `probes/<dossier>.md` (ce qui marche en live, ce qui est fixture, exemples de réponses réelles).
- Le graphe ne s'écrit que via `core.store`.

## Vérité des données

1. Déterministe d'abord : APIs, endpoints et solveurs décident ; le LLM interprète les objectifs, enrichit les entités et explique. Le LLM ne décide pas seul d'un agenda et n'invente jamais un prix, une date ou une disponibilité.
2. Inconnu = null. Jamais la date du jour à la place d'une date introuvable. Jamais 0 à la place d'un frais inconnu. Jamais une dispo déduite d'un prix affiché.
3. Brut conservé : chaque enregistrement source garde `payload` brut, `content_hash`, `first_seen_at`, `last_seen_at`, `fetched_at`. Hash identique : seul `last_seen_at` bouge. Hash différent : nouvelle version.
4. Absence ≠ annulation. Un événement disparu ne devient `removed` qu'après une collecte `exhausted` où il manque, idéalement plusieurs. Les statuts explicites (cancelled, postponed, sold_out) priment.
5. Rapport de terminaison obligatoire par collecte (RunReport) : `exhausted` seul succès ; `cursor_stuck`, `page_cap`, `rate_limited`, `blocked`, `schema_changed`, `error` sont dégradés ; zéro résultat est une erreur ; alerte si volume < 60 % de la médiane précédente ; comparer au total déclaré par la source quand il existe.
6. Dédup conservative : même URL ou même id externe = same ; titre normalisé + début à ±30 min + (distance ≤ 500 m ou même organisateur ou même lieu) = same ; sinon `ambiguous`, jamais fusion forcée. Toujours conserver toutes les lignes source sous l'événement canonique. Garder `merge_confidence` et les raisons.
7. Dates : stocker local + fuseau IANA + UTC + offset + `timezone_source`. Coordonnées : `geo_precision` exact | approximate | city_only | unknown et `source` (source ou geocoded).
8. Prix logement : `price_status` verified_bookable | quoted_total | indicative | unavailable. Un lien n'est "réservable" qu'en verified_bookable (fiche datée revérifiée, total TTC, dispo confirmée, horodatée < 30 min). `adults=1` explicite partout. Devise forcée côté source, jamais convertie en place.
9. Prix vol : montants en chaînes décimales, `price_type` indicative_metasearch | cached | confirmed_offer, `collected_at` serveur à la seconde, `connection_type` unknown si non fourni, bagages tri-état (null = inconnu).
10. Chaque arête du graphe porte `source`, `confidence`, `observed_at`. Speaker confirmé ≠ "a liké". Présence `confirmed` ou `probable`.

## Bright Data

- REST direct depuis le backend via `core.brightdata` : `/datasets/v3/scrape` synchrone (< 1 min) sinon `trigger` + `snapshot_id` avec polling. MCP uniquement pour explorer les scrapers (search_scrapers, get_scraper_details) et pour la démo agent.
- Hiérarchie par source : scraper structuré > SERP JSON > Web Unlocker (HTML à parser) > Browser API (interaction JS). Browser API seulement quand une session connectée ou un scroll est nécessaire (Partiful invités, Luma invités, Facebook, pages dynamiques Universe).
- Si la clé manque ou si l'appel échoue : `BrightDataUnavailable`, le provider bascule sur sa fixture et renvoie `data_source: fixture`. La démo tourne de bout en bout sans clé.
- Toujours fixer `limit_per_input` et `country` (us). Conserver `snapshot_id` ou request id dans `raw_ref`.
- Budget : 5 000 enregistrements gratuits par mois par produit, puis 1,50 $ / 1 000 (retenir ce tarif, pas les "à partir de"). Volume hackathon : quelques centaines.

## Repos externes

- MIT ou Apache : copier, en citant le repo dans l'en-tête du fichier.
- Sans licence (e-Reese, francescov1/facebook-event-scraper) : prendre les faits (endpoints, paramètres, règles), réécrire le code.
- GPL ou AGPL (TREK, ZoranPandovski/BookingScraper, Conpaws) : ne pas copier.
- Ne jamais croire un README : vérifier dans le code (exemple : dsec-hub/event_api_scraper annonce Luma paginé, le code fait un seul GET).

## Qualité

- Tests unitaires par module avec httpx mock ; tests d'intégration marqués `live` et sautés sans clé.
- Ruff clean. Types pydantic v2 partout. Logs structurés (json) avec source, durée, terminaison.
- Qodo installé sur le repo ; garder 2 ou 3 corrections issues de ses reviews pour la démo.
