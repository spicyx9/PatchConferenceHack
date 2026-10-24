# Nuit sans surveillance : procedure

Tout est dans scripts/ops/. Rien ne depend d'un prompt pour tourner : les workers sont de vrais processus, la surveillance est une boucle bash.

1. `bash scripts/ops/preflight.sh` : claude, gh authentifie, uv, docker, make check vert. Si FAIL, corriger avant de dormir.
2. `bash scripts/ops/launch_wave.sh 1` : lance 6 processus (claude -p, ou codex exec si installe et configure dans workers.conf) chacun dans son worktree ~/HTest-wNN-slug, logs dans logs/wNN.log, pid dans logs/wNN.pid.
3. `caffeinate -i bash scripts/ops/watch.sh 600` : boucle toutes les 10 min : etat des workers et PR, CI, verification des chemins possedes, merge squash automatique si CI verte et chemins respectes, relance d'un worker mort sans PR (3 tentatives max), lancement de la vague 2 quand 3 PR de la vague 1 sont mergees et qu'il reste des slots, STATUS.md reecrit et pousse.
4. Optionnel, en plus : une session Claude Code interactive en fenetre 0 pour relire les PR, appliquer les propositions core et tenir DECISIONS.md. Elle n'est pas necessaire pour que la nuit tourne.

Le matin : lire STATUS.md et logs/watch.log. Mettre les cles dans .env de chaque worktree (ou `for d in ../HTest-w*; do cp .env $d/.env; done`), puis `bash scripts/ops/launch_wave.sh 3`.

Limites connues : `claude -p` applique .claude/settings.json du worktree (allow-list large, denies destructifs) ; une commande refusee par un deny fait echouer l'etape, le worker la contourne ou echoue et est relance. Les limites d'usage du compte Claude peuvent ralentir ; les workers reprennent a la relance.
