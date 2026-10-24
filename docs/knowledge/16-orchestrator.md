# Orchestrateur (fenêtre 0)

Claude Code lancé avec `--dangerously-skip-permissions` sur `main`, Mac allumé. Il ne code pas les blocs : il lance, surveille, relance, merge, intègre.

## Boucle

1. Lire docs/knowledge/00 à 04, 15, 16 et docs/prompts/*.md.
2. Vérifier le socle (make up, test, lint, /health). S'il manque quelque chose de core/, le faire d'abord.
3. Pour chaque fenêtre de la vague courante : lancer un subagent en arrière-plan, cwd `../conferge-wNN`, avec le prompt `docs/prompts/wNN.md` précédé du contexte (lire 00 à 04 et le fichier du bloc). Max 6 en parallèle (limite Codex multi_agent, confortable pour Claude Code).
4. Toutes les 10 minutes : `gh pr list`, état CI, STATUS.md mis à jour (tableau fenêtre | branche | état | dernier commit | PR | CI | blocage).
5. PR CI verte et dossier respecté → merge (squash). PR qui touche core/ hors de son dossier → commenter, demander un split via un nouveau subagent sur la même branche.
6. Subagent terminé avec PR mergée → fenêtre suivante de la vague. Subagent mort ou bloqué > 20 min sans commit → relancer le même prompt avec en tête "reprends depuis l'état de la branche, lis STATUS.md et DECISIONS.md".
7. Après chaque merge : rebase des branches encore ouvertes sur main (git rebase, pas merge) pour limiter les conflits.
8. Vague finale : intégration (scénario de référence de bout en bout, badges, démo).

## STATUS.md (format)

```
# STATUS (mis à jour <ISO>)
| fenêtre | branche | état (queued|running|pr_open|merged|failed) | dernier commit | PR | CI | note |
## Prochaines actions
## Blocages (décision prise, pas de question)
```

## Contexte de l'orchestrateur

Son propre contexte finit par saturer. Donc : tout ce qu'il sait est dans STATUS.md et DECISIONS.md. S'il est relancé, il repart de là. Il ne lit jamais les diffs complets des PR, seulement CI, fichiers touchés et résumé.

## Vagues

- Vague 1 (soir, sans clé) : 01, 02, 03, 08, 12, 13.
- Vague 2 (soir) : 04 (partie fixtures), 09, 10, 11 sur fixtures.
- Vague 3 (9h, clés) : sondes dans 05, 06, 07 (make probe-*), puis adaptateurs.
- Vague 4 (11h) : 04 live, 09, 10, 11 branchés sur le réel.
- Vague 5 (13h) : intégration, scénario de référence, Qodo reviews traitées.
- 15h : gel. Démo, script, enregistrement, soumission 17h30.

## Checklist du matin (9h, humains)

- Demander à WeMakeDevs : format de soumission, multi-tracks, accès du juge Qodo au repo privé (ou passer public).
- Récupérer clé Bright Data (zones Unlocker, SERP, Browser) et crédits OpenAI aux workshops. Les mettre dans `.env` du repo principal et des worktrees (`make env-sync`).
- Installer l'app Qodo sur le repo si pas fait.
- Lancer `make probe-stays`, `make probe-flights`, `make probe-people` et lire `probes/*.md` avant de laisser l'orchestrateur passer à la vague 3.
