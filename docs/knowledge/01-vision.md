# Conferge : vision

Nom provisoire. Hackathon Patch the Conference, 24 octobre 2026.

## Philosophie (mot pour mot)

Un agent qui maximise les opportunités professionnelles d'un déplacement. Le voyage n'est qu'un moyen d'atteindre cet objectif.

Notre objectif n'est pas simplement d'aider quelqu'un à assister à une conférence. C'est de lui permettre d'en tirer le maximum de valeur. "Don't just attend conferences. Be in the right place, with the right people, at the right time."

Nous ne construisons pas un concurrent de Booking, Luma ou LinkedIn. Nous construisons la couche d'intelligence qui connecte ces plateformes autour d'un objectif personnel. À terme, l'utilisateur pourrait ne même plus choisir sa conférence : il indiquerait son objectif, ses disponibilités et son budget, et Conferge identifierait où se déplacer.

## Comment l'outil fonctionne

1. L'utilisateur définit sa mission : conférence, objectifs, profil, dates, budget. Il peut aussi partir de ses objectifs et laisser l'outil proposer les événements.
2. Travel Agent : vols, hôtels, Airbnb, transports, coûts. L'hôtel est recommandé selon la position de tous les événements intéressants, pas uniquement la conférence principale.
3. Event Discovery : site officiel, Luma, Partiful, Eventbrite, Meetup, pages Facebook, sites communautaires, side events, soirées, hackathons, workshops, dîners, networking. Base unique, doublons supprimés, dates, lieux et conditions vérifiés.
4. Networking Agent : intervenants, organisateurs, participants accessibles, enrichis via LinkedIn et sources publiques, classés selon les objectifs, avec explication, en distinguant présence confirmée et présence potentielle.
5. Opportunity Graph (FalkorDB) : relie personnes, entreprises, sujets, talks, événements, lieux, objectifs. Révèle les relations indirectes. Chaque recommandation est justifiée par une chaîne de relations vérifiables.
6. Planning Agent : arbitre selon pertinence des personnes, sujets, coût, horaires, déplacements, disponibilités. Reverse Planning : on part des objectifs pour décider où aller. Anti-FOMO : recommande quand plusieurs événements se chevauchent et explique ce qu'on gagne ou manque.
7. Pendant et après : Live Replanning, notes après rencontre, Follow-up Agent (messages personnalisés, relances à valider), Conference ROI (dépenses, rencontres, contacts qualifiés, opportunités).

## Les 7 fonctionnalités, par priorité

| Fonctionnalité | Fonctionnement | Priorité |
|---|---|---|
| Opportunity Graph | Relier personnes, entreprises, conférences, side events, sujets et lieux pour découvrir des opportunités indirectes | Essentielle |
| Reverse Planning | Partir d'un objectif ("rencontrer 5 investisseurs IA"), puis construire le programme adapté au lieu de simplement afficher les événements | Essentielle |
| Smart Networking | Identifier qui rencontrer, pourquoi, où cette personne pourrait être présente et comment l'approcher | Essentielle |
| Anti-FOMO Agent | Comparer deux événements simultanés et recommander celui qui offre le plus de valeur selon les objectifs | Forte |
| Live Replanning | Recalculer le programme lorsqu'un événement apparaît, change d'horaire ou devient complet | Forte |
| Follow-up Agent | Mémoriser les rencontres, générer les messages de suivi et préparer les prochaines actions | Forte |
| Conference ROI | Mesurer les dépenses, les rencontres, les contacts qualifiés et les opportunités commerciales générées | Secondaire |

Transversal : mémoire entre sessions (arêtes MET, ATTENDED, SKIPPED, CONTACTED persistées, qui modifient les classements suivants) et chaque recommandation affiche son chemin dans le graphe.

## Exemple canonique d'Opportunity Graph

L'utilisateur renseigne : "Je suis fondateur d'une startup IA. Je viens à GitHub Universe. Je veux rencontrer des investisseurs, des fondateurs et des ingénieurs spécialisés dans les agents IA."

L'agent découvre : objectif → correspondance de sujets → talk sur les agents IA (conférence principale) et meetup sur les agents IA (side event Luma) → personnes et entreprises reliées (intervenants, organisateurs, profils accessibles, sujets communs) → recommandation explicable : "Ce meetup est particulièrement pertinent car deux intervenants travaillent sur les technologies que tu recherches."

FalkorDB ne sert pas à afficher un joli graphique : les connexions dans le graphe produisent les recommandations.

## Périmètre hackathon vs produit complet

| Fonctionnalité | Hackathon | Produit complet |
|---|---|---|
| Import d'une conférence réelle | Oui | Oui |
| Recherche de side events | Oui | Oui |
| Extraction des talks et speakers | Oui | Oui |
| Construction du graphe FalkorDB | Oui | Oui |
| Networking personnalisé | Oui | Oui |
| Planning optimisé | Oui, version simple | Oui, dynamique |
| Recherche vols / hôtels | Comparaison simple | Recherche approfondie |
| Réservations et inscriptions | Liens ou préparation | Intégrations avec validation |
| Live Replanning | Démonstration simple (bouton simuler un changement) | Mise à jour continue |
| Conference ROI et relances | Prototype éventuel | Complet |

## Décisions figées

- Pas de TrueForge. Deux tracks visés : FalkorDB et Bright Data. Qodo en fond.
- Interface : une seule page de démo avec onglets (Dashboard, Travel, Events, Graph, People). Les 5 espaces complets et l'AI Copilot : plus tard.
- Réservations, inscriptions, prises de contact avec confirmation humaine : plus tard. Pour la démo, liens directs.
- Module Voyage : pas de question "dates fixes". L'agent propose de lui-même ("event la veille, arriver jeudi ?", "vol moins cher en partant samedi ?"). Gmail réel connecté (OAuth) pour les confirmations, fixtures mails seulement en secours. Uber : estimateur public, étiqueté estimation. BART et Caltrain : exact.
- Hôtel recommandé selon la position de tous les events intéressants : plus tard, mais la distance à chaque lieu est calculée dès maintenant.
