# 13 fenêtres

Un worktree par branche dans `../conferge-wNN`, créé par `scripts/create_worktrees.sh`. Prompt dans `docs/prompts/wNN.md`. Chaque fenêtre lit 00 à 04 puis son fichier de bloc.

| # | Branche | Dossier(s) | Mission | Dépend de | Clé Bright Data |
|---|---|---|---|---|---|
| 01 | w01-events-luma-partiful | backend/app/providers/events/luma, partiful | endpoints JSON publics, pagination, RunReport, enrichissement page | core | non (Unlocker optionnel) |
| 02 | w02-events-eventbrite-aggregators | providers/events/eventbrite, aggregators | découpage récursif, parseur conferenceparties + raidandev + reinventradar | core | non |
| 03 | w03-events-official | providers/events/official | sessions, speakers, sponsors Universe (JSON derrière la page sinon Browser API), Sessionize, Sched | core | Browser si besoin |
| 04 | w04-events-discovery | providers/events/discovery | SERP batch, Facebook Events, routage des URLs, rattachement événement ↔ conférence (score) | core, 01, 02 pour le routage | oui |
| 05 | w05-stays | providers/stays | Booking, Google Hotels, Airbnb (pyairbnb puis Bright Data), vérification, price_status, distances | core | oui |
| 06 | w06-flights | providers/flights | Bright Data discover → collect, fan-out 9 paires, fast-flights épinglé, dédup | core | oui |
| 07 | w07-people | providers/people | speakers et hosts → SERP → LinkedIn, enrichissement, matching deux étages | core, 03, 01 | oui |
| 08 | w08-graph | backend/app/graph | schéma, requêtes nommées, ingestion, GraphRAG textes, rattachement, graph_for_ui | core | non |
| 09 | w09-agents-planner-networking | backend/app/agents/planner, networking | goal parser, scoring U(o), Reverse Planning, Smart Networking | 08 (fixtures sinon) | OpenAI |
| 10 | w10-agents-antifomo-replanner | agents/antifomo, replanner | port Pathfinder, conflits, replanification minimale, simulate-change | 08 (fixtures sinon) | OpenAI |
| 11 | w11-travel | backend/app/travel | itinéraire, trajets, propositions de dates, Gmail OAuth, données carte | 05, 06 (fixtures sinon) | Unlocker (Uber) |
| 12 | w12-api-frontend | backend/app/api, frontend | routes complètes, page de démo 5 onglets, cytoscape, Leaflet, badges source | contrats | non |
| 13 | w13-fixtures-demo | fixtures, scripts/gen_fixtures.py, demo | fixtures cohérentes entre blocs, scénarios simulate-change, script 3 min, run de secours | contrats | non |

Ordre : ce soir 01, 02, 03, 04 (partie SERP sans clé en fixture), 08, 12, 13, 09 et 10 sur fixtures, 11 sur fixtures. Demain 9h avec les clés : sondes puis 05, 06, 07, 04 live, puis intégration (orchestrateur). 15h : gel des features, démo, script, enregistrement. 17h30 soumission.

Répartition outils : Claude Code sur 08, 09, 10, 07 et l'orchestrateur ; Codex sur 01 à 06, 11, 12, 13. Les prompts sont identiques pour les deux.
