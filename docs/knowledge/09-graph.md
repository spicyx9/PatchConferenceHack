# Opportunity Graph (FalkorDB)

Graphe "conferge". Docker `falkordb/falkordb:latest`, port 6379, browser sur 3000 (à montrer au jury). Client `falkordb` Python. Toute écriture via `core.store`.

## Nœuds

User, Goal, Topic, Person, Company, Conference, Session (talk), SideEvent, Venue, Lodging, Flight, Opportunity, Meeting (rencontre réalisée).
Tout nœud : `id` stable, `name`, `source`, `fetched_at`, plus les props du schéma pydantic aplati.

## Arêtes (avec props `source`, `confidence`, `observed_at`)

```
(User)-[:HAS_GOAL {weight}]->(Goal)
(Goal)-[:TARGETS]->(Topic)            // et TARGETS_ROLE {role}
(User|Person)-[:INTERESTED_IN]->(Topic)
(Person)-[:WORKS_AT {role, title}]->(Company)
(Person)-[:GIVES]->(Session)
(Session|SideEvent)-[:ABOUT]->(Topic)
(Session)-[:PART_OF]->(Conference)
(SideEvent)-[:AROUND {score, signals}]->(Conference)
(Company|Person)-[:HOSTS]->(SideEvent)
(Company)-[:SPONSORS]->(Conference|SideEvent)
(Person)-[:ATTENDING {status: confirmed|probable}]->(SideEvent|Session)
(Session|SideEvent)-[:AT]->(Venue)
(Venue)-[:NEAR {distance_m, minutes_walk}]->(Venue)
(Lodging)-[:NEAR {distance_m}]->(Venue)
(Company)-[:INVESTED_IN]->(Company)
(User)-[:MET {at, note}]->(Person)
(User)-[:ATTENDED|SKIPPED|CONTACTED {at}]->(SideEvent|Session|Person)
(Opportunity)-[:LEADS_TO {score, explanation}]->(Person|SideEvent|Session)
(Opportunity)-[:SERVES]->(Goal)
(Meeting)-[:WITH]->(Person)  (Meeting)-[:ADVANCES]->(Goal)
```

## Requêtes nommées (graph/queries.py), chacune renvoie résultat + chemins (nœuds + arêtes) pour l'explicabilité

- `people_for_goal(user_id, goal_id, limit)` : multi-sauts jusqu'à 4 : Goal → Topic ← ABOUT Session ← GIVES Person ; Goal → Topic ← ABOUT SideEvent ← HOSTS Company ← WORKS_AT Person ; Goal → TARGETS_ROLE → Person via WORKS_AT.role ; exclut MET et CONTACTED.
- `events_for_goal(user_id, goal_id)` : sessions et side events reliés aux topics ou aux personnes cibles, avec nombre de personnes cibles présentes.
- `conflicts(conference_id)` : paires d'events qui se chevauchent (start < other.end and end > other.start), avec distance entre lieux.
- `path_user_to_person(user_id, person_id)` : plus court chemin (max 5) pour l'explication.
- `company_coverage(user_id, company_id)` : qui a déjà été rencontré dans cette entreprise, qui reste.
- `people_met_before(user_id)` : mémoire entre sessions.
- `replan_after_change(event_id, change)` : events et personnes impactés par un changement.
- `graph_for_ui(conference_id)` : nœuds et arêtes pour cytoscape (limite 400 nœuds, filtre par type).

## Exemple de chemin expliqué

User → HAS_GOAL "rencontrer des fondateurs d'agents IA" → TARGETS Topic "AI agents" ← ABOUT Session "Building agents with MCP" ← GIVES Person "Marie X" → WORKS_AT Company "Y" → HOSTS SideEvent "Agents After Dark" (28 oct, 19h, 1,2 km de Fort Mason).
Texte : "Marie X donne le talk 'Building agents with MCP' le 28 à 14h et sa boite Y organise Agents After Dark le soir même à 12 min : deux occasions de la rencontrer."

## Ingestion

- Données structurées (events, sessions, personnes, entreprises, logements, vols) : MERGE direct via `core.store` depuis les providers, idempotent.
- Textes (bios, descriptions, abstracts) : FalkorDB GraphRAG-SDK (Apache-2.0, `pip install graphrag-sdk`) avec un `GraphSchema` restreint (Person, Company, Topic, Session, SideEvent et leurs relations) pour extraire Topic et ABOUT. Index vectoriel sur Topic.name et Session.abstract pour la similarité objectif ↔ sujet.
- Rattachement événement ↔ conférence : arête AROUND avec score et signaux (voir 05-events.md).
- Provenance sur chaque arête. Jamais une arête ATTENDING confirmed depuis un post social.

## Mémoire entre sessions

MET, ATTENDED, SKIPPED, CONTACTED persistent. Le classement suivant les lit : MET et CONTACTED sortent du top, ATTENDED augmente la confiance sur les sujets de l'event, SKIPPED baisse. Le graphe garde les personnes pour la conf suivante dans la même ville.

## Repos

- FalkorDB/falkordb-py (client), FalkorDB/GraphRAG-SDK, FalkorDB/skills (skills Claude Code officiels, à installer dans le repo), FalkorDB/falkordb-browser (dans l'image docker), FalkorDB/code-graph (`find_paths` entre deux nœuds).
- lucasjellema/conference-recommendation-engine-in-graphdb : requête Cypher multi-sauts (moi → sessions suivies → autres participants → speakers qu'ils aiment → leurs sessions) à transposer.
- aws-samples social-graph people recommender (archivé) : référence.

## Pièges FalkorDB 6.x vérifiés

Serveur testé : `falkordb/falkordb:6.0.3` (module graph 60003, Redis 8.10.2), client Python `falkordb==1.8.0`. « Vérifié » = reproduit le 2026-10-24 sur ce serveur dans un graphe jetable.

- **Index full-text en DDL** : `CREATE FULLTEXT INDEX FOR (p:Person) ON (p.name, p.bio)` et `FOR (e:Event) ON (e.title)` ; jamais `db.idx.fulltext.createNodeIndex`. Requête : `CALL db.idx.fulltext.queryNodes('Person', $q) YIELD node, score`. Recréer un index existant lève « already indexed » : à traiter comme un succès. Vérifié, `CALL db.indexes()` renvoie `OPERATIONAL`.
- **Vecteurs** : stocker avec `vecf32([...])`, pas une liste brute, sinon pas d'index vectoriel possible. Vérifié (la propriété `vecf32` s'écrit).
- **OPTIONAL MATCH** : toujours après un `MATCH` qui lie les variables. Sur 6.0.3, `OPTIONAL MATCH` en tête est accepté, mais c'est la forme qui produit des lignes nulles inattendues ; règle maison conservée. La requête `MATCH (p:Person) OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company) RETURN c.name, count(p)` ne plante pas sur 6.0.3 et renvoie bien un groupe `null` (test `tests/graph/test_falkordb_server.py`), donc pas de `coalesce()` ajouté.
- **LIMIT et écritures eager** : `UNWIND range(1,5) AS i CREATE (:X {i:i}) RETURN i LIMIT 1` crée 5 nœuds. Le `LIMIT` ne borne pas les écritures. Vérifié.
- **Unicité des relations non référencées** : `MATCH (a)-[]->(x), (a)-[]->(y) RETURN count(*)` compte 4 lignes pour 2 relations (une même relation sert à `x` et à `y`). Nommer les relations et filtrer (`r1 <> r2`) avant de compter. Vérifié.
- **MERGE sur clé stable seulement** : `MERGE (:M {id:'m', v:1})` puis `MERGE (:M {id:'m', v:2})` crée deux nœuds `id='m'`. Toujours `MERGE (n:Label {id: $id}) SET ...`, ce que fait `GraphStore`. Vérifié.
- **Traversées bornées** : jamais `[*]` sur le graphe complet ; signatures à longueur fixe pour les explications, `[*0..3]` au plus pour l'UI, `*..4` maximum ailleurs.
- **Labels non paramétrables** : `MATCH (n:$label)` est une erreur de syntaxe. Les labels et types de relation sont interpolés depuis une liste blanche (`_ALLOWED_NODE_LABELS`, `_ALLOWED_EDGES` dans `core/store.py`), les valeurs toujours en `$paramètres`. Vérifié.

## Critères juges FalkorDB

- **Graph-native** : le « pourquoi cette personne » est une requête de chemin dans FalkorDB (signatures goal → topic → event → speaker, etc.), pas un score calculé ailleurs puis affiché ; la mémoire (`MET`, `SKIPPED`) vit dans le même graphe et change le classement.
- **Explicabilité et provenance** : chaque arête porte `source`, `source_url`, `confidence`, `observed_at`, `verification` ; le texte d'explication est un template déterministe par type d'arête ; les preuves sont regroupées par source racine (max par source, noisy-OR entre sources).
- **Un juge doit pouvoir lancer le projet** : `make up`, `make install`, `make demo` ; image FalkorDB épinglée (`6.0.3`), port configurable (`FALKORDB_PORT`).
- **README avec modèle et requêtes** : section « Graph model and Cypher queries » du README (nœuds, arêtes, 6 requêtes telles qu'exécutées, index).
