# Préambule commun (l'orchestrateur le préfixe à chaque prompt)

Tu es la fenêtre wNN du projet Conferge (hackathon Patch the Conference, 24 octobre 2026, soumission 17h30). Tu travailles dans le worktree de ta branche `wNN-<slug>` (créé par scripts/create_worktrees.sh), tu ne touches qu'aux chemins listés dans docs/WORKSTREAMS.md pour ta fenêtre. `conferge/core/`, Makefile, CI, docs partagés appartiennent à la fenêtre 0 : besoin d'un changement = proposition écrite dans ta PR, pas d'édition.

Avant de coder, lis dans l'ordre : CLAUDE.md, docs/WORKSTREAMS.md, docs/CONTRACTS.md, conferge/core/schemas.py, contracts.py, brightdata.py, store.py, puis docs/knowledge/00-INDEX.md, 01, 02, 03, 04, 12, 13, puis le fichier knowledge de ton bloc, puis docs/prompts/wNN-<slug>.md (mission) et docs/prompts/wNN.md (spec détaillée, voir docs/prompts/README.md pour la correspondance des chemins).

Execution Rules : subagents en parallèle pour toute tâche indépendante (Codex : multi_agent activé) ; commits petits et fréquents, messages conventionnels ; push dès qu'une étape est verte ; CI rouge = corriger et repousser ; aucune question à personne, décision = ligne dans ta PR et dans DECISIONS.md via la fenêtre 0 ; jamais de tiret cadratin.

Livrable commun : `run(query)` conforme aux contrats ; `make probe-<slug>` (scripts/probes/<slug>.py) qui tente le live, rapporte `status`, terminaison, exemples de réponses réelles tronquées dans probes/<slug>.md ; `fixtures/<slug>.json` conforme aux schémas ; tests unitaires avec httpx mock ; tests live marqués `live` sautés sans clé. Donnée absente = null. Chaque enregistrement porte source_mode et collected_at.

Fin : PR vers main titrée `wNN: <résumé>`, description = live, fixture, blocages, fichiers touchés. La fenêtre 0 merge (CI verte + chemins respectés). Ne merge pas toi-même. Termine quand la PR est ouverte et verte.
