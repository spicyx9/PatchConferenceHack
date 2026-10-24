# Personnes et entreprises (Smart Networking)

Objectif : identifier qui participe aux événements et enrichir les profils. Recherche dédiée (prompt 6) en cours : ce fichier contient ce qui est déjà établi, à compléter par w07 quand les résultats arrivent (ajouter dans ce fichier, section "Résultats recherche 6").

## Quatre sources de personnes, par qualité décroissante

1. Speakers (site officiel, Sessionize, Sched) : nom, titre, entreprise, talk, bio, liens sociaux. Présence `confirmed`. Source la plus riche et la plus ciblable.
2. Hosts et co-hosts des side events (Luma, Partiful, agrégateurs, sites exposants) : entreprise organisatrice, personnes nommées. Présence `confirmed` à leur event.
3. Sponsors et exposants (site officiel) : entreprises → employés pertinents via LinkedIn companies + people search. Présence `probable`.
4. Inscrits visibles (Luma partiel, nom + photo, parfois entreprise ; Partiful seulement connecté ; Meetup partiel ; posts X et LinkedIn "see you at") : présence `probable`, nom seul → recherche SERP nom + entreprise → profil LinkedIn avec `identity_confidence` (voir "Trois scores séparés").

Les listes d'inscrits ne sont jamais la source principale : à 5 semaines elles sont à 10 ou 20 %, à 5 jours (Universe) elles sont pleines.

## Enrichissement

- LinkedIn via Bright Data Web Scraper APIs : profils (titre, entreprise, expériences, bio, posts récents), entreprises (taille, secteur, description), posts. Synchrone ou batch, délai 30 s à 2 min, 1,50 $ / 1 000. Exemples : luminati-io/LinkedIn-Scraper.
- Appariement nom → URL LinkedIn : SERP Bright Data `"<nom>" "<entreprise>" site:linkedin.com/in`, scorer titre + entreprise + ville ; seuils dans "Trois scores séparés" (lien automatique si `identity_confidence` >= 0.85, sinon revue ou `linkedin_url` null).
- GitHub (API publique, pas de Bright Data) pour les ingénieurs : repos, langages, bio.
- X : Web Scraper API posts, pour sujets et présence probable.
- Crunchbase et pages portfolio VCs via Web Unlocker : `Company.investor`, INVESTED_IN.
- Sujets : extraits par LLM depuis bio + talk + posts + repos, normalisés sur une taxonomie courte (AI agents, developer tools, MCP, Copilot, devsecops, infra, seed investor, ...). GraphRAG-SDK peut faire l'extraction texte → Topic.

## Matching deux étages (pattern Claude Connect, anthonyisaa/claude-code-meetup-app, MIT)

1. Présélection déterministe : candidats partageant au moins un sujet ou rôle cible avec les objectifs, top 50 par recouvrement.
2. Scoring LLM sur le top 20 : pertinence par objectif pondéré, raison en une phrase, phrase d'accroche générée à partir de ses talks, posts, entreprise. Fallback déterministe si LLM indisponible.
3. Bonus et malus depuis le graphe : chemin multi-sauts vers un objectif (+), déjà MET ou CONTACTED (fort malus), entreprise déjà couverte (malus), présence confirmée (+), accessible (host, speaker avec after party) (+).
4. Sortie Smart Networking : qui, pourquoi (chemin), où (event ou talk, salle, heure), comment (accroche), présence confirmed | probable, confiance.

## Pipeline PeopleHub (brightdata/pepolehub, licence ambiguë : pattern seulement)

Requête en langage naturel → recherche Google → scraping LinkedIn via Bright Data (déclenchement puis interrogation asynchrone, premier appel environ 120 s : prévoir un traitement en arrière-plan) → rapport. Cache 180 jours.

## Listes d'invités avec compte connecté

doluz/afterparty (MIT, Python, FastAPI) : synchronise les events Partiful du compte et leurs guest lists (`getGuests` paginé par curseur) vers PostgreSQL. Utilisable uniquement sur les events où le compte est inscrit. Phase 2.

## Schéma Person

id, name, title, company (CompanyRef), linkedin_url, github_url, x_handle, bio, topics[], roles[] (founder, investor, pm, engineer, devrel), presences[] (event_id ou session_id, status confirmed | probable, source), match_confidence, sources[], fetched_at.

## Fixtures

120 personnes cohérentes avec les 40 sessions et 30 side events de la fixture events : chaque speaker est une personne, chaque side event a 1 ou 2 hosts, 8 investisseurs seed, 15 fondateurs agents IA, 5 PM Copilot, le reste varié.

## Résultats recherche 6

(à compléter)

## Compléments (avant vague 3)

### LinkedIn via Bright Data : couverture réelle

Depuis le 13 novembre 2025, Experience/Position/Education de LinkedIn Profiles sont remplis à environ 2 % ; `current_company.industry` n'est pas supporté. S'appuyer sur `current_company`, `about`, `city`, posts, et LinkedIn Companies (`gd_l1vikfnt1wgvvqz95w`). Proxycurl fermé le 4 juillet 2025.

### Trois scores séparés, jamais confondus

- `presence_confidence` : checked_in 1.0, announced_speaker 0.85, registered 0.8, declared 0.65, possible 0.3, relationship_only 0.05.
- `identity_confidence` : nom seul plafonné à 0.40 ; lien automatique si >= 0.85 ; revue entre 0.60 et 0.85.
- `relevance_score`.
- `score_final = relevance × presence × identity × meetability`.
- Toute raison de classement cite un `source_id`.
- Dédup : RapidFuzz + clés fortes (URL LinkedIn, login GitHub, handle X, id Luma/Partiful) ; fusions réversibles via `appearances` immuables.
