# Prompts : deux fichiers par fenêtre

- `wNN-<slug>.md` : la mission (chemins canoniques du repo, livrables, acceptation). C'est le prompt à donner à la fenêtre.
- `wNN.md` : la spécification technique détaillée (endpoints, paramètres, dataset IDs, règles, découpage en subagents). La fenêtre la lit juste après la mission. Les chemins y sont écrits dans une ancienne convention : lire `backend/app/providers/events/<x>` comme `conferge/events/<x>`, `backend/app/providers/stays` comme `conferge/lodging`, `backend/app/providers/flights` comme `conferge/flights`, `backend/app/providers/people` comme `conferge/people`, `backend/app/graph` comme `conferge/graph`, `backend/app/agents/<x>` comme `conferge/agents/<x>`, `backend/app/travel` comme `conferge/travel`, `backend/app/api` comme `conferge/api`, `frontend/` comme `static/`, `backend/app/core` comme `conferge/core`. Les fixtures suivent WORKSTREAMS.md (`fixtures/<slug>.json`).
- `_common.md` : préambule que l'orchestrateur préfixe.
- `docs/knowledge/` : la base de connaissances complète (lire 00 à 04 puis le fichier du bloc).

Règles qui priment en cas de contradiction entre les deux fichiers : CLAUDE.md, puis `wNN-<slug>.md`, puis `wNN.md`.

Fixtures et secours : CLAUDE.md règle 7 (fallback fixture seulement sur demande explicite) s'applique aux connecteurs : un connecteur ne substitue jamais une fixture en silence, il renvoie `status=degraded|failed`. La bascule vers une fixture est faite par la couche API (`conferge/api`) avec `data_mode=fixture` affiché, et par les probes quand la clé manque, toujours étiquetée.

Schémas : `conferge/core/schemas.py` v0.2 ajoute des champs optionnels (topics, registered_count, price breakdown, baggage, path) ; `extra="forbid"` reste. Un champ manquant = proposition à la fenêtre 0, pas d'édition locale.
