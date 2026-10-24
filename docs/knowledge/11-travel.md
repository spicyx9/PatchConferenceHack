# Voyage : itinéraire, trajets, propositions, Gmail, carte

## Entrées

Ville de départ, dates de la conf, contraintes (horaires de départ dérivés : conférence mercredi matin → arrivée mardi soir ou mercredi tôt), distance maximum à l'événement ou prévoir les trajets, budget.

## Propositions proactives (pas de question "dates fixes")

- Event intéressant la veille (score U élevé le J-1) → "arriver le 27 pour le Syntax Meetup ?" avec différence de prix vol + une nuit.
- Vol moins cher à ±1 jour (écart > 80 $) → "décaler le retour au 31, 120 $ de moins ?".
- L'utilisateur accepte ou refuse, le programme se recalcule (replanner).

## Trajet étape par étape

- Aéroport → centre : SFO → BART vers Embarcadero (horaires et tarif exacts via 511.org API gratuite ou table statique), OAK → BART, SJC → Caltrain. Uber : estimateur public via Web Unlocker, étiqueté "estimation". Depuis l'aéroport vers Fort Mason : BART + Muni ou Uber.
- Entre lieux du programme : distance haversine + marche 5 km/h, OSRM public pour les itinéraires, transit 511.org. `minutes_walk`, `minutes_transit`, `uber_estimate_usd`.
- Sortie : liste ordonnée d'étapes {from, to, mode, departure, arrival, price, source, url}.

## Liens de réservation

Toujours des liens directs pré-remplis (voir 06 et 07). Jamais de réservation exécutée.

## Carte

Leaflet + OpenStreetMap, zéro clé. Marqueurs : conférence, hôtels candidats (couleur par price_status), side events du programme, aéroport, trajets en polylignes. Données servies par `GET /travel/map`.

## Gmail

OAuth Google (Gmail API, scope readonly) sur la boîte de l'utilisateur. Recherche des confirmations (vol, hôtel, billet conf, inscriptions Luma et Partiful) par requête Gmail (`from:luma.com OR from:partiful.com OR subject:confirmation OR subject:itinerary newer_than:60d`), extraction structurée par OpenAI (type, dates, lieu, montant, référence), écriture dans le graphe (ATTENDED prevu, Flight et Lodging confirmés). Fixtures `fixtures/emails/` (6 confirmations types) uniquement en secours si l'OAuth casse sur scène.

## Schéma Itinerary

trip {origin_city, destination_city, depart_date, return_date, flexible_proposals[]}, legs[] {from, to, mode, departure_local, arrival_local, price {amount, currency, status exact | estimate}, provider, url}, lodging_choice (Lodging id), flight_choice (FlightOffer id), budget {planned, total_estimate, breakdown}.

## Repos

- kbhujbal/Multi-Agent-AI-Travel-Advisor : `backend/services/logistics/google_maps.py`, `currency.py` pour la forme.
- liketrek/TREK (AGPL, ne pas copier) : idée tournée d'une journée (plus proche voisin puis 2-opt, hôtel comme ancre).
- google/adk-samples travel-concierge : découpage avant, pendant, après.
