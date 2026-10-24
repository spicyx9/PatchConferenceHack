# Agents : Reverse Planning, Smart Networking, Anti-FOMO, Replanning, Follow-up, ROI

Architecture multi-agents sur graphe partagé : chaque agent lit et écrit FalkorDB via `core.store`, aucun état privé. C'est le critère FalkorDB "état partagé entre agents".

Séparation stricte : faits (providers) → graphe → retrieval et scoring (Cypher + règles) → décision (optimiseur déterministe) → LLM (extraction d'objectifs, explication, rédaction). Le LLM ne calcule pas les conflits et n'invente pas une fonction objectif.

## Goal parser (agents/planner)

Entrée : texte libre. Sortie : liste de Goal {text, topics[], target_roles[], count, weight} avec poids sommés à 1. Garde-fou (pattern Devoxx AI Schedule `InterestValidatorAgent`) : valider et nettoyer avant d'engager quoi que ce soit ; si vide ou incohérent, objectifs par défaut du profil. Écrit HAS_GOAL, TARGETS, TARGETS_ROLE.

## Scoring d'opportunité

Pour chaque candidat o (personne, session, side event) :
U(o) = wg G(o) + wp P(o) + ws S(o) + wn N(o) - wt T(o) - wc C(o) - wr R(o)
G alignement objectifs (somme pondérée des chemins Goal → o), P valeur des personnes présentes (cibles confirmées × 2, probables × 1), S pertinence sujet (similarité), N sérendipité (nouveauté d'entreprise non couverte), T temps consommé (durée + trajet), C coût, R incertitude (confiance des arêtes, présence probable, lieu caché). Poids par défaut 0.35, 0.25, 0.15, 0.10, 0.07, 0.04, 0.04. Chaque score garde son chemin et une explication texte.

## Reverse Planning (agents/planner)

1. Candidats : `events_for_goal` + sessions officielles + side events AROUND score ≥ 0.5.
2. Score U(o) pour chacun.
3. Optimiseur : maximiser Σ U(o_i) sous contraintes : pas de chevauchement (en comptant le trajet entre lieux), max N items par jour (défaut 6), créneaux bloqués (vol, hôtel check-in), sessions fixées par l'utilisateur, budget. Base : port Python de re:Invent Pathfinder (`apps/api/app/optimizer`, `ranking`, `explain`, `mutations`, MIT) ou PuLP (ConferenceScheduler, MIT). Un agent par jour en parallèle (pattern Devoxx : 30 s → 5 s).
4. Sortie : programme jour par jour, chaque item avec score, raison, chemin, trajet depuis l'item précédent ; plus la liste des rejetés et pourquoi (Pathfinder renvoie les alternatives).

## Smart Networking (agents/networking)

Voir 08-people.md : présélection déterministe → scoring LLM top 20 → bonus et malus graphe → top 10 avec qui, pourquoi, où, comment, présence, confiance. Pénalise MET et CONTACTED, favorise entreprises partiellement couvertes.

## Anti-FOMO (agents/antifomo)

Pour chaque paire en conflit (`conflicts`) : U des deux, personnes cibles présentes, sujets, distance et trajet, nouveauté, popularité (registered, série temporelle des inscrits si disponible). Verdict + explication + "ce que tu rates" + alternative (l'autre event a-t-il une after ? la personne cible est-elle aussi à un autre moment ?). Ne pas décider par pertinence thématique seule : par opportunité.

## Live Replanning (agents/replanner)

Événements : new_event, time_change, sold_out, cancelled, venue_change, person_target_available, meeting_accepted, meeting_declined, flight_delay, user_skipped, new_contact_met. Mise à jour du graphe, puis re-optimisation à changement minimal (`original_schedule` de ConferenceScheduler ou mutations Pathfinder : proposer → confirmer → exécuter → vérifier). Sortie : diff (ajouté, retiré, déplacé) avec raisons : "Je remplace X par Y. X a perdu son speaker cible. Y a deux personnes alignées avec ton objectif. Le trajet ajoute 8 min, aucun rendez-vous touché." Bouton de démo `POST /simulate-change` avec scénarios fixtures (un event devient complet, un nouvel event apparaît avec 2 personnes cibles, un talk est déplacé).

## Follow-up (agents/followup, minimal)

Après MET avec note : message généré à partir du chemin qui a justifié la rencontre et de la note, proposé à valider, jamais envoyé seul. Prochaine action suggérée.

## Conference ROI (minimal)

Requête graphe : dépenses (Flight + Lodging choisis) vs rencontres (MET) vs contacts qualifiés (MET vers personne cible d'un Goal) vs opportunités (Meeting ADVANCES Goal). Affiché en 4 chiffres. Les résultats du voyage N recalibrent les poids du voyage N+1 (plus tard).

## Repos

- 0gulcandogann/reinvent-pathfinder (MIT, Python) : optimizer, ranking, explain, mutations, mcp. Le plus précieux. Validation live partielle selon l'auteur.
- PyconUK/ConferenceScheduler (MIT, PuLP) : replanification à changement minimal.
- glaforge/devoxx-ai-schedule (Java) : patron validator, builder par jour, rationales.
- anthonyisaa/claude-code-meetup-app (MIT) : matching deux étages, consentement mutuel, Beacon Mode (idée).
- OSU-NLP-Group/TravelPlanner : benchmark de contraintes.
- TimefoldAI/timefold-solver (Apache-2.0, Java) : V2 seulement.
