# User Stories — Waterflow 2

## Profils utilisateurs

| Profil | Description | Authentification |
|---|---|---|
| **Client** | Collectivité territoriale (mairie, syndicat des eaux) | Clé API (`X-API-Key`) |
| **Analyste qualité** | Expert interne analysant la qualité de l'eau | Token Bearer (rôle `analyste`) |
| **Responsable exploitation** | Responsable de la supervision technique de la plateforme | Token Bearer (rôle `exploit`) |

---

## US-01 — Soumettre des mesures manuellement

**En tant que** client,  
**je veux** déposer les résultats d'analyse physico-chimique de l'eau via l'API,  
**afin d'** obtenir immédiatement une prédiction de potabilité.

**Critères d'acceptation :**
- L'API accepte un JSON avec les 9 paramètres (ph, Hardness, Solids, Chloramines, Sulfate, Conductivity, Organic_carbon, Trihalomethanes, Turbidity)
- Si un paramètre manque, l'API retourne une erreur 400 avec le détail des champs manquants
- La réponse inclut : `prelevement_id`, `prediction.potable`, `prediction.label`, `prediction.probability`
- Le prélèvement est persisté en base avec `source = 'manual'`

**Route :** `POST /ingest/manual`

---

## US-02 — Déposer une fiche de laboratoire (OCR)

**En tant que** client,  
**je veux** uploader une fiche PDF ou image issue du laboratoire d'analyse,  
**afin d'** automatiser la saisie des mesures sans ressaisie manuelle.

**Critères d'acceptation :**
- L'API accepte PDF, PNG, JPG (max 20 Mo)
- Le service OCR extrait les 9 paramètres du document
- Si l'OCR réussit partiellement, les champs disponibles sont stockés et `prediction_possible: false` est retourné
- Le texte brut OCR est conservé pour audit
- En cas d'indisponibilité d'OCR.space, le fallback Claude Vision prend le relais automatiquement

**Route :** `POST /ingest/ocr-and-predict`

---

## US-03 — Consulter mes prélèvements

**En tant que** client,  
**je veux** accéder à la liste de mes prélèvements passés avec leurs résultats,  
**afin de** suivre l'historique de qualité de l'eau de ma collectivité.

**Critères d'acceptation :**
- La liste est paginée (20 par page par défaut, max 100)
- Filtres disponibles : `date_from`, `date_to`
- Chaque entrée affiche : date, lieu, source, résultat potabilité, probabilité
- Un client ne peut accéder qu'à ses propres prélèvements (isolation stricte)

**Route :** `GET /me/prelevements`

---

## US-04 — Accéder à mes données personnelles (RGPD)

**En tant que** client,  
**je veux** consulter toutes les données personnelles stockées me concernant,  
**afin d'** exercer mon droit d'accès conformément à l'article 15 du RGPD.

**Critères d'acceptation :**
- Retourne : données d'identification, nombre de prélèvements, historique des 50 derniers accès
- Les IPs affichées sont pseudonymisées (dernier octet masqué)
- Les règles de conservation et les droits disponibles sont explicitement listés

**Route :** `GET /me/rgpd`

---

## US-05 — Demander la suppression de mon compte (RGPD)

**En tant que** client,  
**je veux** pouvoir demander l'effacement de mes données personnelles,  
**afin d'** exercer mon droit à l'oubli conformément à l'article 17 du RGPD.

**Critères d'acceptation :**
- L'action nécessite une confirmation explicite (`{"confirmer": true}`)
- Après suppression : denomination et adresse sont anonymisées, clé API révoquée, compte désactivé
- Les prélèvements sont conservés sous forme anonymisée (obligations légales traçabilité eau)
- L'action est irréversible et tracée dans l'audit log

**Route :** `DELETE /me/rgpd`

---

## US-06 — Créer et gérer des comptes clients

**En tant qu'** expert (analyste ou exploit),  
**je veux** créer des comptes pour les nouvelles collectivités et générer leurs clés API,  
**afin de** les onboarder sur la plateforme.

**Critères d'acceptation :**
- Création : `id_client` (identifiant métier unique), `denomination`, `adresse`
- La clé API est générée séparément et retournée **une seule fois** dans la réponse
- La clé n'est jamais stockée en clair (SHA-256)
- Un expert peut régénérer une clé (invalide l'ancienne immédiatement)
- Un client peut être désactivé/réactivé via `PUT /admin/clients/<id>`

**Routes :** `POST /admin/clients`, `POST /admin/clients/<id>/apikey`, `PUT /admin/clients/<id>`

---

## US-07 — Consulter le dashboard qualité global

**En tant qu'** analyste qualité,  
**je veux** avoir une vue agrégée de la qualité de l'eau sur l'ensemble des collectivités,  
**afin de** détecter des tendances et alerter si nécessaire.

**Critères d'acceptation :**
- KPIs : total prélèvements, taux de potabilité global, clients actifs, total prédictions
- Moyennes des 5 paramètres principaux (ph, turbidité, conductivité, chloramines, dureté)
- Répartition par source d'ingestion (manual vs ocr)
- Liste des 15 prélèvements les plus récents

**Route :** `GET /analyste/dashboard`

---

## US-08 — Filtrer les prélèvements par client et date

**En tant qu'** analyste qualité,  
**je veux** filtrer l'ensemble des prélèvements par collectivité, source, et période,  
**afin d'** isoler les données pertinentes pour une investigation.

**Critères d'acceptation :**
- Filtres disponibles : `client_id` (id_client métier), `source` (manual/ocr), `date_from`, `date_to`
- Résultats paginés avec total
- Chaque prélèvement inclut le texte OCR brut si disponible
- Accessible depuis l'interface web (onglet Prélèvements)

**Route :** `GET /analyste/prelevements`

---

## US-09 — Superviser les métriques de la plateforme

**En tant que** responsable d'exploitation,  
**je veux** consulter les indicateurs de performance de l'API,  
**afin de** détecter les dégradations et planifier la capacité.

**Critères d'acceptation :**
- Métriques par route : volume, taux d'erreur, p50/p95/moyenne de temps de réponse
- Vue globale : clients total/actifs, prélèvements, taux potabilité
- Accessible uniquement au rôle `exploit`

**Route :** `GET /exploitation/metrics`

---

## US-10 — Auditer les accès à la plateforme

**En tant que** responsable d'exploitation,  
**je veux** consulter le journal d'accès de la plateforme,  
**afin de** détecter des comportements anormaux et répondre aux obligations RGPD de traçabilité.

**Critères d'acceptation :**
- Chaque accès (client ou expert) est enregistré : acteur, action, IP pseudonymisée, statut HTTP, horodatage
- Filtres disponibles : `actor_type`, `actor_id`, `action`
- Journal paginé (max 200 entrées par page)
- Conservation : 12 mois glissants, purge automatique nocturne

**Route :** `GET /exploitation/audit`

---

*User Stories Waterflow 2 — B3 IA 2025*
