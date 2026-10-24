# Patch the Conference : règles et critères

Bright Data x WeMakeDevs, 625 2nd St, San Francisco, samedi 24 octobre 2026. Pages : https://luma.com/ptc et https://www.wemakedevs.org/hackathons/ptc (ressources : /resources).

## Thème

Unique : trouver ce qui est cassé dans les conférences et livrer le correctif (ex. qui rencontrer, quel talk vaut le coup). Aucun sujet imposé, aucune donnée fournie, rien de nouveau annoncé le jour J. Pré-build autorisé sans pénalité.

## Agenda

- 9h portes, petit-déjeuner, prise en main
- 10h à 11h workshops sponsors (clés et crédits remis)
- 11h à 14h build
- 14h pizza
- 14h à 17h30 build et soumission (ferme)
- 17h30 à 18h30 présentations et jugement sur scène (2 à 3 minutes par équipe)
- 18h30 gagnants, 19h fin

Jury : Google, OpenAI, Apple, Amazon, Microsoft. Scoring public avec commentaires. Personne n'ouvre le repo sauf pour Qodo. Tout repose sur la démo.

Équipes solo à 4. 21+, pièce d'identité à la porte. Pour tous : 50 $ crédits OpenAI + 50 $ crédits Bright Data (réclamés sur place).

## Tracks et prix (un prix par track, meilleur usage de l'outil, pas de classement général)

### Track 1 FalkorDB : iPhone Duo ou 2 000 $
Critères : graphe au cœur (requêtes multi-sauts, mémoire entre sessions, état partagé entre agents), réponses explicables (chemin dans le graphe), vrai problème de conférence, démo live. Idées du sponsor : concierge de conférence, agent networking "qui rencontrer" avec mémoire, planificateur multi-agents.

### Track 2 Bright Data : 1 500 $
Critères : donnée difficile à obtenir au cœur (sites qui bloquent), qualité et fraîcheur, utilité, démo live. Produits : Web Scraper APIs (Booking, Tripadvisor, Trip.com, Airbnb), Scraper Studio, Web Unlocker API, Browser API, MCP, SERP API. Idées du sponsor : stay finder, side event radar, who-to-meet scout (LinkedIn + données entreprises), "should I go?" agent.

### Track 3 TrueForge + OpenAI : 1 000 $
Non visé.

### Track 4 Qodo : 500 $
Critères : app Qodo installée sur le repo dès le début, PR petites et claires, corrections issues des reviews montrées en démo, repo propre. Juge la façon de coder, pas l'idée. À cumuler.

## Ce que la démo doit montrer, par track

- FalkorDB : le browser FalkorDB (port 3000) avec le chemin qui s'allume pour une recommandation ; une requête multi-sauts visible ; un bouton "rencontré" qui change le classement à la session suivante.
- Bright Data : un appel en direct sur une page qui bloque curl (LinkedIn, Booking, page dynamique Universe) ; le badge "fixture" absent sur ce qu'on montre ; `collected_at` affiché.
- Qodo : 2 ou 3 corrections issues de reviews Qodo gardées en exemple.

## Non précisé par les organisateurs (à demander à 9h)

Format de soumission. Un même projet peut-il concourir sur plusieurs tracks. Visibilité du repo privé pour le juge Qodo.

## Sponsors (contexte)

- WeMakeDevs : moteur GTM pour outils dev, fondé par Kunal Kushwaha (CNCF Ambassador, GitHub Star).
- Bright Data : ex-Luminati (2014), CEO Or Lenchner, 300 M$+ ARR 2025, 50 000+ clients, 72 M+ IP résidentielles. Comptes neufs : 5 000 enregistrements ou requêtes gratuits par mois sur plusieurs produits.
- FalkorDB : Tel Aviv 2023, CEO Guy Kurland, seed 3 M$ (juin 2024), base graphe sur Redis avec Cypher, GraphBLAS, GraphRAG-SDK, 10 500 étoiles.
- Qodo : ex-CodiumAI, 2018, CEO Itamar Friedman, Série B 70 M$ (mars 2026). App : github.com/apps/qodo-merge-pro.
