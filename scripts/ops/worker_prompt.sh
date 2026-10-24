#!/usr/bin/env bash
# Prints the full prompt for worker NN (slug). Usage: worker_prompt.sh 01 luma-partiful
set -euo pipefail
ID="$1"; SLUG="$2"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BLOCK=""
case "$ID" in
  01|02|03|04) BLOCK="docs/knowledge/05-events.md" ;;
  05) BLOCK="docs/knowledge/06-lodging.md" ;;
  06) BLOCK="docs/knowledge/07-flights.md" ;;
  07) BLOCK="docs/knowledge/08-people.md" ;;
  08) BLOCK="docs/knowledge/09-graph.md" ;;
  09|10) BLOCK="docs/knowledge/10-agents-planning.md docs/knowledge/09-graph.md" ;;
  11) BLOCK="docs/knowledge/11-travel.md" ;;
  12|13|15) BLOCK="docs/knowledge/03-demo-scenario.md docs/knowledge/14-market-landscape.md" ;;
esac
cat <<EOF
Tu es la fenetre w${ID} (${SLUG}) du projet Conferge, hackathon Patch the Conference, 24 octobre 2026, soumission 17h30. Tu travailles dans ce worktree, branche w${ID}-${SLUG}. Personne ne repondra a tes questions : tu decides, tu notes la decision dans ta PR. Tu ne t'arretes pas avant que ta PR soit ouverte et la CI verte.

Premiere action, avant toute lecture ou modification : execute pwd et git branch --show-current. Le repertoire doit se terminer par PatchConferenceHack-w${ID}-${SLUG} et la branche doit etre w${ID}-${SLUG}. Si ce n'est pas le cas, n'ecris rien : cree le fichier logs/BLOCKED-w${ID}.md a la racine de ce repertoire avec le pwd et la branche constates, et termine. Tous tes appels d'outils utilisent des chemins relatifs a ce worktree ou absolus sous ce worktree ; jamais un chemin vers un autre worktree ni vers le repo principal.

Lis dans l'ordre : CLAUDE.md, docs/CONTRACTS.md, docs/WORKSTREAMS.md, conferge/core/schemas.py, conferge/core/contracts.py, conferge/core/brightdata.py, conferge/core/store.py, docs/prompts/README.md, docs/knowledge/00-INDEX.md, 01-vision.md, 02-hackathon.md, 03-demo-scenario.md, 04-engineering-rules.md, 12-repos-to-reuse.md, 13-brightdata.md, ${BLOCK}, puis docs/prompts/w${ID}-${SLUG}.md (ta mission, chemins canoniques) et docs/prompts/w${ID}.md (specification detaillee, chemins a traduire selon docs/prompts/README.md).

Execute integralement la mission. Tu ne modifies que les chemins de ta fenetre listes dans docs/WORKSTREAMS.md. Jamais conferge/core, Makefile, CI, docs partages : besoin d'un changement = section "Proposition fenetre 0" dans ta PR. Subagents en parallele pour les taches independantes, tous dans ce meme worktree. Commits petits et frequents, messages conventionnels. make check vert avant chaque push. Donnee absente = null, jamais inventee. Chaque enregistrement porte source_mode et collected_at. Pas de cle Bright Data ni OpenAI ce soir : live tente si endpoint public, sinon status degraded ou failed et fixture etiquetee. Si quelque chose t'empeche d'avancer (isolation, outil manquant, conflit), consigne-le dans logs/BLOCKED-w${ID}.md et dans ta PR plutot que de modifier un chemin hors perimetre.

Fin : git push -u origin w${ID}-${SLUG}, puis gh pr create --base main --title "w${ID}: <resume>" --body avec : ce qui est live, ce qui est fixture, blocages, fichiers touches, propositions pour la fenetre 0. Ne merge pas. Si la CI de ta PR est rouge, corrige et repousse jusqu'au vert. Termine seulement quand gh pr checks indique success.
EOF
