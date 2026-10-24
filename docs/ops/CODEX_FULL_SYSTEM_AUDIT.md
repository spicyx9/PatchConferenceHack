# CODEX — AUDIT INTÉGRAL DE CONFERGE (MISSION EN LECTURE SEULE SUR LE PRODUIT)

## Mandat

Tu es un auditeur technique indépendant et approfondi du projet Conferge. Tu dois **comprendre, cartographier, vérifier et évaluer l'intégralité du système existant**, pas coder une nouvelle fonctionnalité. Le résultat doit permettre à un humain qui ne développe pas de répondre précisément : **qui fait quoi, qui appelle qui, quels services sont branchés, ce qui fonctionne en live, ce qui fonctionne avec des fixtures, ce qui est incomplet, et pourquoi**.

Dépôt : https://github.com/spicyx9/HTest
Point de référence observé lors de la rédaction : main a5e6479080fa7a58e47fcea38ef239604b60bd1f, avec environ 399 fichiers suivis, dont 144 dans conferge/ et 105 sous tests/. **Ce SHA est une référence historique, pas une consigne de travailler sur un code ancien**. Au démarrage, identifier la tête actuelle de main, les PR ouvertes, et figer un SHA précis pour l'audit. La PR #27 touchait récemment au contrat de provenance des arêtes et au suivi E2E : lire son état actuel séparément si elle n'est pas fusionnée.

Contexte : Hackathon Patch the Conference, Bright Data + FalkorDB. Produit : un agent qui maximise les opportunités professionnelles d'un déplacement de conférence. Démo : GitHub Universe 2026 (SF, Oct 28–29), utilisateur NYC → SF Oct 27–30, objectifs investisseurs seed, fondateurs d'agents IA, responsables produit GitHub Copilot.

## Conditions de sécurité et d'exécution

- **AUDIT UNIQUEMENT : aucune modification du code produit, des schémas, des dépendances, des secrets, des fixtures, des workflows, de README, de main ou des autres worktrees.**
- Travailler dans un worktree indépendant et dans une branche d'audit distincte de celles des agents Claude. Vérifier pwd, git rev-parse HEAD, git branch --show-current, git status --porcelain et l'état des PR. Si impossible d'isoler, poursuivre une analyse sans mutation et signaler le blocage.
- Autorisation d'écrire **uniquement des fichiers de rapport** sous docs/audits/codex-full/ dans le worktree d'audit. Ne pas commit, push, ouvrir PR, merger, rebase, force-push ni toucher aux branches de travail sans autorisation explicite de l'utilisateur. Laisser les rapports sur le disque pour revue.
- Les tests peuvent créer des caches, une venv et des fichiers temporaires dans le worktree d'audit. Ne jamais exécuter un test qui efface un graphe FalkorDB existant, modifie des données de l'utilisateur ou lance des appels facturables. Si un test E2E a besoin de Docker, utiliser **un graphe ou conteneur jetable explicitement isolé**, vérifier le port et le nom du graphe avant tout reset.
- Ne jamais afficher, copier ou commiter .env, clés API, cookies, tokens, sessions privées, données personnelles non publiques. Les tests réseau payants (Bright Data), les appels vers LinkedIn, l'inscription à des événements, les achats et les envois de messages sont **interdits** sans autorisation spécifique. Une clé absente se documente comme absente ; aucune donnée n'est inventée.
- Pas de suppression, pas d'amélioration opportuniste pendant l'audit. Transformer toute correction proposée en finding exploitable et test de reproduction ; l'intégrateur décidera de la suite.
- Si certains tests ou inspections sont impossibles, classer « NON TESTÉ / BLOQUÉ » ; **ne jamais écrire PASS** sans preuve d'exécution. La CI verte n'est pas synonyme de produit entièrement connecté.
- Chaque fait substantiel doit citer un fichier ET une plage de lignes (path:line-line), ou un résultat de test/commande horodaté. Séparer les faits observés, inférences et déclarations du README/PR. Les docs de recherches sont des hypothèses, jamais la vérité si le code dit autre chose.

## 0. Préparer le corpus et l'inventaire exhaustif

Lire dans cet ordre : AGENTS.md, CLAUDE.md, docs/CONTRACTS.md, docs/WORKSTREAMS.md, DECISIONS.md, README.md, Makefile, pyproject.toml, uv.lock, docker-compose.yml, .env.example, .github/workflows/ci.yml, docs/knowledge/00-INDEX.md, docs/knowledge/17-falkordb-research-audit-2026-10-24.md, docs/ops/E2E_FINDINGS.md, docs/ops/RESILIENCE_FINDINGS.md, docs/ops/NIGHT_RUN.md.

1. Lister **TOUS** les fichiers suivis (par ex. git ls-files), classés par domaine, rôle et type (source, interface, test, fixture, documentation, script, asset, dépendance).
2. Pour chaque module Python, relever ses imports, classes, fonctions publiques, usages internes entrants, usages sortants, dépendances, éventuels effets de bord et preuves de test. Ne pas se limiter aux __init__.py et README.
3. Construire un graphe d'appels statique, puis valider les liens critiques par exécution ou tests. Les imports dynamiques et registres d'agents comptent ; un fichier présent mais jamais importé n'est **pas** une fonctionnalité branchée.
4. Relever la différence entre ancien plan (docs/knowledge et anciens prompts backend/app) et architecture réelle conferge/. Marquer les documents périmés ; n'inventer aucun dossier.
5. Examiner main, les PR récentes, les commits et les fichiers de probes pour repérer les fonctionnalités récemment branchées et les contradictions entre rapports historiques et HEAD.

## 1. Architecture système « qui fait quoi / branché à quoi »

Construire le diagramme d'architecture **réelle**, fondé sur imports et appels, avec flèches orientées, distinction sync/async, réseau, persistance et fallbacks.

Obligatoire :
- CLI/launcher : scripts/run_demo.py, Makefile, configuration uv/Docker/environnement ;
- fournisseurs : conferge/events/{official,luma,partiful,eventbrite,aggregators,discovery}, conferge/people, conferge/flights, conferge/lodging, conferge/travel ;
- clients partagés : conferge/core/brightdata.py et contrats core/schemas.py, core/contracts.py, core/settings.py, core/store.py ;
- orchestration et déduplication : conferge/integration/{sources,assemble,stays_flights,pipeline,checks,components,report} ;
- graphe : conferge/graph/{bundle,ingest,schema,queries,ranking,paths,explain,memory,agent_state,textgraph,seed} ;
- décision : conferge/agents/{planner,networking,antifomo,replanner} ;
- serveur : conferge/api/{app,data,logic,providers} ;
- UI : static/{index.html,app.js,styles.css} ;
- moteur de secours : conferge/demo, fixtures/, probes/ ;
- déploiement, supervision, tests et outils : scripts/ops/, .github/, tests/.

Pour chaque flèche A → B, relever : fonction appelante, fonction appelée, signature, objet transmis, dépendance, cas de succès, cas d'erreur, et si la connexion est effectivement exercée par la démo.

Livrer une matrice « Module → responsabilité → importe / appelé par → sortie → destination → live/fixture → preuve → statut ». Statuts imposés : WIRED_AND_TESTED, WIRED_UNTESTED, IMPLEMENTED_NOT_WIRED, FALLBACK_ONLY, FIXTURE_ONLY, STUB, DEAD_CODE, BLOCKED, NOT_IMPLEMENTED. Ne pas confondre code présent et code exécuté.

## 2. Traçabilité de chaque parcours de données de bout en bout

Décrire, avec fonctions/fichiers/lignes, au moins ces parcours :

A. RainFocus/GitHub Universe → sessions/speakers/companies normalisés → dédup → API + graphe → recommandations.
B. Luma et Partiful → pagination/exhaustivité → événements → side-event/conference relation → graphe → plan ; distinguer données publiquement accessibles des invités privés.
C. Eventbrite, agrégateurs, Bright Data SERP et Facebook → découverte URL → scraping → qualification association à conférence → dédup événements.
D. Personne nommée publiquement → association à événement → rapprochement LinkedIn/GitHub/X → identité, rôle, présence, pertinence → classement ; démontrer si conferge/people est réellement consommé par integration/sources ou si seul le catalogue officiel est utilisé.
E. Vol et logement → Bright Data datasets / pyairbnb / fast-flights / SerpApi → prix, devise, bagages, taxes, disponibilité, dates → assemblage → API → UI → calcul budget.
F. Saisie d'objectif → parsing Goal → écriture FalkorDB → ranking people_for_goal → API /people + /plan → carte UI et chemin « why? ».
G. Anti-FOMO : événements en conflit + trajets + personne rare + opportunités alternatives → optimiseur → endpoint → panneau UI.
H. Simuler une annulation → changement de données, graphe Change/AFFECTS, invalidation plan, moteur replanner → diff visible → état après relecture.
I. Enregistrer MET, CONTACTED, ATTENDED, SKIPPED → écritures FalkorDB → lectures par agents → nouveau ranking → restart API → reset → vérifier l'historique conservé / invalidé.
J. Absence de FalkorDB / Bright Data / fournisseurs → mode degraded/fixture et comportement UI ; prouver l'absence de fallback trompeur.
K. Indicateurs ROI et cartes/transports : source, calcul, sauvegarde, état du branchement.

À chaque étape, suivre les IDs stables, relations, dates IANA/UTC, evidence, source_mode, source_url, confiance, null vs valeur par défaut, coûts, et les éventuelles pertes d'information.

## 3. INVENTAIRE API ET FRONTEND : 100 % des routes et boutons

Extraire la table actuelle de routes FastAPI, y compris /health, /api/v1/sources, /conference, /goal, /plan, /brightdata, /search, /antifomo, /people, /events, /sessions, /stays, /flights, /travel, /travel/map, /graph, /graph/path, /met, /attended, /skipped, /scenarios, /simulate-change, /agents/state, /reset, /proposal/accept, /roi et /.

Pour CHAQUE route réellement présente :
- méthode, chemin exact, input/query Pydantic, validation, fonction handler, modules/fonctions consommés ;
- provenance de la réponse, mode, warning, statut et conditions d'absence de résultat ;
- GraphStore read/write et tout état en mémoire ;
- appelant UI (élément, événement JS, fetch correspondant) et affichage ;
- test existant qui la couvre, test réel manquant, risque ;
- un exemple de payload réel de fixture sanitizé obtenu en test, ou « non exécuté ».

Pour CHAQUE bouton/interaction visible : est-il fonctionnel, simulé, non câblé, en erreur ou caché ? Identifier notamment "Show in FalkorDB Browser", "met", Anti-FOMO, simulate-change, reset, recherche, changements de Goal, onglets, filtres, voyages et badges.

Ne pas conclure « API complète » sur la simple présence des routes. Rechercher les réponses 200 qui masquent silencieusement des erreurs provider.

## 4. Sources d'acquisition et BRIGHT DATA

Dresser une matrice par site, API ou provider :
RainFocus, Sessionize, Luma, Partiful, Eventbrite, conferenceparties, raidandev, reinventradar, Facebook public, Bright Data SERP, Web Unlocker, Browser/MCP/CLI s'ils existent vraiment dans le code, LinkedIn Profiles, LinkedIn Companies, X, Crunchbase, Google Flights Bright Data, Booking, Google Hotels, Airbnb/pyairbnb, fast-flights, SerpApi, BART, OSRM, Uber.

Par fournisseur : présent ou seulement mentionné dans docs ; point d'entrée ; prérequis/credentials ; méthode ; pagination/cursor/termination ; statut live vérifié vs mock/fixture ; couverture mesurée ; normaliseur ; champ manquant ; risques 403/429 ; retry/backoff/Retry-After ; coût unitaire vs réel mesuré ; script probe ; délai/timeout ; format de sortie ; date des dernières observations.

Spécifiquement :
- BrightDataClient.from_env, not_ready, scrape_dataset, trigger_dataset, snapshot_progress, snapshot_results, serp et unlock ;
- vérifier si une collecte Bright Data a réellement eu lieu (ou uniquement missing_credentials) ; ne pas créditer Bright Data pour la collecte via httpx ou pyairbnb ;
- distinguer compteur /api/v1/brightdata = requêtes locales enregistrées, vraie consommation facturée et statistiques commerciales ;
- vérifier le chemin complet dataset ID → paramètres d'entrée → réponse réelle → normaliseur → graphe → UI ;
- comparer ce que nos adaptateurs publics font sans Bright Data avec ce que Bright Data serait censé améliorer ; NE PAS appeler des APIs facturables pendant cet audit ;
- distinguer recherche de personnes et preuve d'assistance à une conférence, et n'accéder à aucune guest list privée non autorisée.

## 5. Données, contrats, déduplication, confiance et légitimité

Auditer tous les modèles de conferge/core/schemas.py et les objets wrappers (SourceRecord, DiscoveryResult, RunReport, DataEnvelope, AgentContext, AgentResult), compatibilité Pydantic, extra=forbid, valeurs par défaut.

Pour chaque transformation, vérifier :
- sémantique live/cached/fixture/mixed et degraded_no_graph (le dernier est un état de calcul, pas une source) ;
- null ne devient pas 0, "confirmed" sans preuve ni "verified_bookable" sans disponibilité ;
- source_url, retrieved/collected/observed_at, source_mode et raw_ref sont conservés ou intentionnellement supprimés ;
- doubles comptages des chemins par source racine (noisy-OR) et dédup Person/Event/Company ;
- identité ≠ présence ≠ pertinence ≠ rencontrabilité ;
- traitement des corrections, dates, fuseaux, événement hors région, annulation ;
- conservation des preuves de présence et de relation à la conférence (official, confirmed, candidate) ;
- déclarations chiffrées dans README, docs/submission et probes vs sortie réellement mesurée.

Rechercher explicitement les chaînes critiques : "fixture", "fallback", "missing_credentials", "except Exception", "return []", "return None", "unknown", "unavailable", "source_mode", "data_source", "status", "confirmed", "live", "observed_live", "price_status".

## 6. FalkorDB : preuve qu'il décide, non qu'il décore

- Inspecter GraphStore (allowlist, validation des propriétés, MERGE, indexes, query/read boundary, index_status, reset), version Docker 6.0.3, SDK 1.8.0, port 6380 ou variable FALKORDB_PORT, Browser 3000, volume et stratégie de réinitialisation.
- Vérifier les index exact/full-text réellement OPERATIONAL, les requêtes Cypher exécutables sur la version pinnée, les limites, paramétrage et les horizons de parcours.
- Étudier GraphBundle, ordre d'ingestion, HOSTS/SPEAKS_AT/WORKS_AT, Goal→Topic, événements AROUND/PART_OF, SourceEvidence, preuves des arêtes ATTENDS_CONFIRMED.
- Montrer une recommandation dont la sélection ET l'explication viennent effectivement d'une traversée FalkorDB ; demander la différence avec et sans graphe ; vérifier le mode degraded_no_graph.
- Auditer graph/ranking.py vs api/logic.py vs agents/planner vs conferge/demo : quel est le ranking canonique, quand déclenché, qui écrit et qui lit ? Chercher duplications et divergences de scores.
- Vérifier IDs d'interactions : multiples MET d'une même personne, CONTACTED/ATTENDED/SKIPPED, user_id, portée inter-sessions, lecture après restart.
- Critique connue à examiner au SHA actuel : docs/ops/E2E_FINDINGS.md, **F4** : /reset efface-t-il Change et PLANS/SKIPS alors que l'agent-state promet conservation/invalidation ? Reproduire avant de classer. Vérifier statut de la PR #27.
- Partage de mémoire : les agents lisent-ils réellement PLANS, SKIPS, AFFECTS via FalkorDB ou passent-ils encore l'essentiel du state par objets Python ? Inspecter agent_state.py et graph_state.py des agents.
- Différencier vrai FalkorDB, MemoryGraph fake test, graphe sérialisé par l'API et représentation Cytoscape.
- Mesurer l'impact d'une coupure FalkorDB puis d'un retour ; ne pas présenter le fallback Python comme graph-native.

## 7. Planning, agents, voyage, mémoire et ROI

Pour chacun des agents planner, networking, antifomo, replanner et people, ainsi que travel et ROI :
- registre réellement découvert au runtime, constructeur, instance module-level, entrée, sortie, source de ranking, dépendance graphe, mémoire locale vs partagée, dégradation ;
- fonction objectif, poids et différences entre scoring API/graph/planner/antifomo ;
- contraintes fortes : conflits horaires, trajet, événements en ligne/hors fuseau, nuit, créneaux verrouillés, budget, frais inconnus, impossibilité de déplacement ;
- qualité Anti-FOMO : personnes uniques, alternatives, doublons, opportunities marginales, pas seulement note élevée ;
- changements : preuve d'annulation réelle ou simulation et diff minimal ; versions de plan et conservation de l'historique ;
- follow-up : réellement disponible ou seulement annoncé ? Y a-t-il un endpoint et un service qui génère des messages sans envoi non autorisé ?
- Conference ROI : que mesure exactement GET /roi ? Les dépenses prix réel/fixture et résultats sont-ils correctement distingués ?
- deux billets one-way ne deviennent pas un prix aller-retour vérifié ; en cas de prix manquant, total et remaining sont null plutôt que faussement calculés.

## 8. Qualité, exploitation et résilience

- Recenser versions, dependencies réellement importées, extras optionnels, uv.lock, configuration Docker, ports et collisions avec Redis pur, preflight, timeouts.
- Recenser tous les tests et les mapper aux modules et endpoints : unit / mocked / fixture / actual FalkorDB / local HTTP failure / internet live. Compter depuis la commande de test réelle, pas depuis un README figé.
- Exécuter en environnement isolé, si autorisé et possible : uv sync --group dev ; make check ; make e2e ; tests/resilience/ ; probes locales sans réseau. Avant chaque test E2E, vérifier qu'il ne supprime PAS la base de démonstration de l'utilisateur ; préférer des ports et noms de graphes jetables.
- Examiner .github/workflows/ci.yml : quels tests sont lancés par CI et lesquels (Docker, E2E, live, Browser) sont absents/non bloquants ?
- Vérifier les six cas de docs/ops/RESILIENCE_FINDINGS.md : graph down, key missing, provider timeout, price missing, foreign timezone, 429.
- Tester les effets des annulations de coroutines entourant asyncio.to_thread (les threads natifs peuvent continuer), le retry 429/Retry-After, la possibilité qu'un test prétendument hors ligne invoque curl_cffi/libcurl.
- Scripts ops : worktrees séparés, PID, logs, locks, mise à jour de STATUS.md, worker mort, auto-merge, propriété des fichiers, limits/retries, CI status et risques de course ; ne pas redémarrer ni modifier un worker en cours.
- Sécurité à l'échelle réelle : injection dans contenu web non fiable, URL non validée/SSRF, XSS dans la UI, sorties JSON, gestion des secrets, logs, CORS et accès endpoints mutables, authentification multi-utilisateurs, exposition de Docker ports. Séparer risque prouvé et risque hypothétique du prototype.
- Vérifier rapidement les licences pertinentes : FalkorDB SSPL, dépendances (pyairbnb, fast-flights), librairies de scraping et réutilisations externes. Aucun avis juridique définitif.

## 9. Documentation et promesses : vérification systématique

Comparer CHAQUE assertion concrète de README.md, docs/submission/SUBMISSION.md, docs/DEMO.md, demo/, STATUS.md et probes/ avec le code et les mesures :
- 7 fonctionnalités décrites dans la vision ;
- chiffres de collecte 1 092 Luma bruts vs 194 filtrés, 85 Partiful bruts vs 11 filtrés, 161 sessions, 183 personnes, 122 entreprises, 207 événements démo, 697 nœuds/2 195 arêtes, latences annoncées ; identifier snapshots et dates ;
- compte de tests (926/957/987 selon la version) : indiquer source et SHA, jamais des totaux cumulés ;
- « Bright Data live » : prouver une requête authentifiée et les données exploitées ; sinon mentionner seulement l'implémentation et missing_credentials ;
- « all features working » : suivre effectivement route + UI + source + tests ;
- l'affirmation de mémoire partagée et conservée entre sessions ;
- l'existence ou non de Qodo reviews (ne pas les inventer) ;
- captures/screenshots versus interface à HEAD et documents périmés ;
- preuves de runs live de graph et providers : distinguer les mesures réelles déjà historiques des tests que tu as toi-même effectués.

Dresser une matrice FEATURE → PROMISE → ENTRYPOINT → BACKEND → GRAPH → UI → TEST → LIVE / FIXTURE / PARTIAL / ABSENT → EVIDENCE → VERDICT.

## 10. Livrables à produire dans docs/audits/codex-full/

Aucun rapport superficiel. Créer **ces fichiers de rapport séparés** (docs seulement, sur branche d'audit) :

- 00-EXECUTIVE.md : cartographie en une page, 10 principaux risques, état de couverture, lacunes et urgences ;
- 01-FILE-AND-MODULE-INVENTORY.md : inventaire complet des fichiers/modules et leurs responsabilités, liens entrants/sortants ;
- 02-ARCHITECTURE-AND-CALL-GRAPH.md : vrais graphes Mermaid avec chemins actifs et dépendances optionnelles ;
- 03-DATA-LINEAGE.md : parcours A–K détaillés, schemas, identité, provenances, pertes de champs ;
- 04-API-UI-CONNECTIONS.md : TOUTES les routes FastAPI et boutons UI, callers, fonctions, statut, test ;
- 05-PROVIDERS-BRIGHTDATA.md : fournisseurs directs vs Bright Data, endpoints, statut, couverture, credentials, modes de secours ;
- 06-FALKORDB-STATE-AND-MEMORY.md : modèle, index, requêtes, scoring, mémoire, shared-agent state, reset, comparaison avec/sans graphe ;
- 07-AGENTS-PLANNER-ANTIFOMO.md : responsabilités, matching, ranking, valeurs, conflits, replan, ROI ;
- 08-TRAVEL-PRICES-LOCATIONS.md : vols/hôtels/trajets, coût, réservabilité, dates et preuves ;
- 09-TESTS-CI-E2E.md : commande, résultat, date, SHA, coverage par fonction, tests bloquants ou non ;
- 10-SECURITY-RESILIENCE-OPERATIONS.md : erreurs, retries, limites, secrets, infra, opérations ;
- 11-DOCS-AND-CLAIMS-VERIFICATION.md : chaque chiffre ou promesse du README face à sa preuve ;
- 12-FINDINGS.md : TOUS les findings triés P0/P1/P2/P3 ;
- 13-ROADMAP-NEXT-CHANGES.md : ordre de corrections recommandé, petits lots de PR, fichiers exacts, dépendances et tests de validation ;
- 14-REPRODUCIBILITY.md : commandes et étapes exactes pour un second auditeur, hypothèses de machine, état des services, limites ;
- manifest.json : rapport lisible par machine des modules, routes, connexions, tests, findings et leur niveau de preuve.

Chaque finding dans 12-FINDINGS.md doit suivre ce format :
ID, severity (P0/P1/P2/P3), catégorie, statut (PROUVÉ / PROBABLE / NON TESTABLE / CONTREDIT), description, exemple métier, repro exacte, attendu, observé, source fichier:ligne, cause probable, effets, tests présents, test manquant, solution minimale, owner, dépendances, régression à craindre. Inclure les bugs **et** les intégrations absentes. En tête, une table récapitulative.

## 11. Politique de preuves

- **P0** = erreur de données ou d'affirmation grave, flow central cassé, action destructive, fixture déguisée en live, risque majeur de sécurité/secrets, graph prétendu central mais non utilisé.
- **P1** = module branché mais comportement essentiel incorrect/incomplet, incohérence de contrat importante, panne fréquente ou perte de qualité métier.
- **P2** = robustesse, couverture de test, perf, duplication, observabilité, UX.
- **P3** = dette documentaire ou optimisation mineure.
- Indiquer si chaque finding est **nouveau**, **déjà recensé dans docs/ops**, **corrigé par une PR récente**, **encore ouvert sur main**, ou **dépend d'un test live non autorisé**.
- Une CI verte ne prouve pas un connecteur Bright Data sans clé ; un probe fixture ne prouve pas une connexion live ; un graphe qui s'affiche ne prouve pas que le ranking en dépend ; une réponse HTTP 200 ne prouve pas que ses champs sont vrais.
- Tout chiffre de temps/coût/volume est attaché à la source de la mesure, au SHA, à la date et à l'environnement ; faute de quoi « non vérifié ».
- Pour chaque connexion prétendue, tracer des deux côtés : le producteur et son consommateur, puis idéalement un test qui démontre l'échange.

## 12. Critères de fin de l'audit

Ne pas arrêter après quelques grep, une lecture de README, ou une liste de 10 bugs. L'audit est complet uniquement quand :
- chaque fichier source a été classé, chaque module majeur inspecté et les zones non lues énumérées ;
- toutes les routes réellement actives ont une ligne dans la matrice ;
- les 7 fonctions produit et les parcours A–K ont une trace d'entrée à sortie ou un trou clairement indiqué ;
- les trois frontières source→assemble, assemble→FalkorDB et FalkorDB→agents→API→frontend sont démontrées ;
- Bright Data vs collecteurs directs est séparé par source et par preuve ;
- F4/reset et le cycle MET/restart/graph down sont explicitement vérifiés ou bloqués ;
- chaque test exécuté est lié à sa sortie, sans inventer de verdict live ;
- les contradictions de README, sources et probes sont recensées ;
- un autre ingénieur peut reproduire les findings P0/P1 depuis le rapport.

Terminer par une **réponse en français**, concise et factuelle, contenant : SHA audité, nombre de modules/routes/tests réellement parcourus, tableaux P0/P1, les trois bugs majeurs, les trois dépendances d'intégration les plus fragiles, les modules implémentés mais jamais utilisés, la liste des 15 rapports générés, et ce qui reste non testé. Ne pas prétendre avoir modifié Conferge : tu n'es autorisé qu'à l'auditer.
