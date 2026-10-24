# Préambule commun (l'orchestrateur le préfixe à chaque prompt)

Tu es la fenêtre wNN du projet Conferge (hackathon Patch the Conference, 24 octobre 2026, soumission 17h30). Tu travailles dans le worktree de ta branche, tu ne touches qu'à ton dossier, `tests/<dossier>/` et `fixtures/<dossier>.json`. Tout changement dans `backend/app/core/` passe par une PR séparée minuscule, mergée avant de continuer.

Avant de coder, lis : docs/knowledge/00-INDEX.md, 01-vision.md, 02-hackathon.md, 03-demo-scenario.md, 04-engineering-rules.md, 12-repos-to-reuse.md, 13-brightdata.md, puis le fichier de ton bloc indiqué dans ton prompt. Lis backend/app/core/schemas.py, contracts.py, brightdata.py, store.py, fixtures.py : ce sont les contrats, tu les respectes.

Execution Rules : subagents en parallèle pour toute tâche indépendante (Codex : multi_agent activé) ; commits petits et fréquents avec messages conventionnels ; push dès qu'une étape est verte ; CI rouge = corriger et repousser ; aucune question à personne, décision = ligne dans DECISIONS.md ; jamais de tiret cadratin.

Livrable commun à chaque fenêtre : ton module expose `run(query)` conforme aux contrats ; une cible `make probe-<dossier>` qui tente le live, bascule sur fixture si clé absente, et écrit `probes/<dossier>.md` (ce qui marche, exemples de réponses réelles tronquées, terminaisons) ; une fixture `fixtures/<dossier>.json` conforme au schéma ; tests unitaires avec httpx mock ; tests live marqués `live` sautés sans clé. Toute donnée absente est null. Chaque réponse porte `data_source: live|fixture` et `collected_at`.

Fin : PR vers main titrée `wNN: <résumé>`, description = ce qui est live, ce qui est fixture, ce qui reste. Merge dès CI verte (squash). Puis mets à jour STATUS.md (ta ligne) et termine.
