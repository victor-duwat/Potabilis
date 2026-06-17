# Rapport de conformité — Waterflow 2 vs. spécification B3IA 2025

> Analyse réalisée le 2026-06-21 par lecture complète du dépôt et du PDF de spécification.

---

## Résumé exécutif

Le projet répond à la grande majorité des exigences fonctionnelles et techniques du cahier des charges. L'API unique Flask portant les trois modules (données, prédiction, OCR) est opérationnelle, la base de données est conforme RGPD, la documentation Swagger est en place, et l'interface web permet aux clients comme aux experts d'utiliser la plateforme sans passer par l'API brute.

**Estimation de couverture globale : ~78 %**

Quatre points bloquants sont à corriger avant la soutenance :

1. `ci.yml` est à la racine, pas dans `.github/workflows/` → la CI GitHub Actions ne se déclenche jamais.
2. `docs/` est dans `.gitignore` → les cinq fichiers de documentation requis sont absents du dépôt partagé.
3. `tests/test_fonctionnels.py` et `tests/test_non_regression.py` testent l'ancienne route `/predict` (supprimée) → ils échouent à l'exécution.
4. L'interface web n'expose pas les filtres (par client, date, source, résultat) requis sur la vue analyste.

---

## Analyse détaillée par section

---

### 1. Analyse du besoin et spécifications

| Exigence | Statut | Commentaire |
|---|---|---|
| Contexte métier formalisé | ✅ | `docs/architecture.md`, README |
| Profils utilisateur définis | ✅ | `docs/user_stories.md` — 10 US avec critères d'acceptation |
| Architecture technique proposée | ✅ | Diagramme ASCII dans `docs/architecture.md`, table des composants |
| Veille comparative OCR | ✅ | Tableau 5 solutions dans `ocr_service.py` (OCR.space retenu + justification) |

---

### 2. Modélisation et base de données

| Exigence | Statut | Commentaire |
|---|---|---|
| MCD incluant clients, prélèvements, logs d'accès | ✅ | `docs/mcd.md` complet avec MPD et cardinalités |
| Implémentation SQL avec scripts de création | ✅ | `db.py` — SQLAlchemy 2.0, 6 tables : `clients`, `prelevements`, `mesures`, `predictions`, `audit_logs`, `request_metrics` |
| Script d'import / initialisation | ✅ | `scripts/init_db.py` — seed 3 clients + 5 prélèvements, flags `--init-only` et `--reset` |
| Base PostgreSQL / MariaDB (recommandée) | ⚠️ | SQLite utilisé en dev et en prod Docker. `DATABASE_URL` accepte PostgreSQL mais `docker-compose.yml` n'inclut pas de service PostgreSQL. À noter comme limite connue en soutenance. |

---

### 3. API Data et authentification

| Exigence | Statut | Commentaire |
|---|---|---|
| POST /admin/clients (admin) | ✅ | Avec validation métier complète |
| GET /admin/clients (admin) | ✅ | + GET par ID, PUT modification |
| POST /ingest/manual (client + clé) — dépôt mesures | ✅ | Équivalent à `/api/measurements` du spec |
| GET /me/prelevements (client + clé) — liste filtrée | ✅ | Paginé, filtre date_from/date_to |
| GET /analyste/prelevements (expert) — vue globale | ✅ | Filtrés par client_id, source, dates |
| Validation des schémas et types | ✅ | Gestion ValueError dans `routes.py`, 400 si manquant |
| Contrôle d'accès par clé API | ✅ | `auth.py` — hash SHA-256, pas de stockage en clair |
| Génération et régénération de clé API | ✅ | `POST /admin/clients/<id>/apikey` — `secrets.token_urlsafe(32)` |
| Documentation OpenAPI / Swagger | ✅ | `swagger.yaml` + flasgger → `/apidocs` |

---

### 4. API Model (prédiction)

| Exigence | Statut | Commentaire |
|---|---|---|
| Réutilisation du modèle XGBoost MLflow | ✅ | `predict_service.py` — `mlflow.xgboost.load_model` |
| Route de prédiction avec métadonnées (version modèle) | ⚠️ | La prédiction est intégrée à `/ingest/manual` et `/ingest/ocr-and-predict`. Pas de route dédiée `POST /api/predict`. Fonctionnellement correct mais le spec suggère une route isolée. |
| Suivi de version MLflow | ✅ | `MLFLOW_URI=models:/WaterQualityXGBoost/1`, version retournée dans la réponse |
| Tests unitaires + intégration pipeline prédiction | ✅ | `tests/test_unitaires.py` — validation, scaling, prédiction, dataset |

---

### 5. API OCR

| Exigence | Statut | Commentaire |
|---|---|---|
| Intégration OCR.space | ✅ | `ocr_service.py` — requête multipart/form-data, parse JSON, extraction des 9 features |
| Fallback si OCR.space indisponible | ✅ | Claude Vision (Anthropic) avec prompt d'extraction structurée |
| Route POST /ingest/ocr (OCR seul) | ✅ | Stocke le prélèvement même si mesures incomplètes |
| Route POST /ingest/ocr-and-predict (pipeline complet) | ✅ | OCR → prélèvement → prédiction, avec `prediction_possible: false` si mesures insuffisantes |
| Documentation des erreurs (timeout, champs manquants) | ✅ | Codes 503 (OCR indisponible), 400 (fichier invalide), warnings dans la réponse |
| Fichiers exemples pour l'OCR | ✅ | `samples/fiche_labo_exemple_1.txt` (complet) et `fiche_labo_exemple_2_partiel.txt` (partiel) |

---

### 6. Interface web expert

| Exigence | Statut | Commentaire |
|---|---|---|
| Consulter tous les prélèvements | ✅ | Onglet "Prélèvements" de la vue expert |
| Filtrer par client, provenance, date, résultat | ❌ | Les endpoints API ont les filtres (`client_id`, `source`, `date_from`, `date_to`) mais l'interface web ne les expose pas. Contrôles de filtre absents du HTML. |
| Indicateurs clés (KPI) | ✅ | Dashboard : total prélèvements, taux potabilité, clients actifs, moyennes physico-chimiques |
| Vue des journaux d'accès (exploit) | ⚠️ | L'endpoint `GET /exploitation/audit` existe et fonctionne, mais n'est pas accessible depuis l'interface web. La vue exploit n'a pas d'onglet "Audit". |
| Gestion des clients (création, clé API) | ✅ | Onglet "Clients" avec formulaire de création et bouton "Nouvelle clé" |

---

### 7. Tests, CI/CD, monitoring, incidents

#### Tests

| Exigence | Statut | Commentaire |
|---|---|---|
| Tests unitaires (validation, scaling, prédiction) | ✅ | `tests/test_unitaires.py` — 27 tests, 4 classes |
| Tests d'intégration API | ⚠️ | `tests/test_fonctionnels.py` et `tests/test_non_regression.py` testent les routes `/predict` et `/health` de l'ancienne architecture. Ces routes et attributs globaux (`flask_app.model`, `flask_app.FEATURES`) n'existent plus dans le `app.py` actuel → **ces tests échouent**. |
| Test bout en bout (OCR → prélèvement → prédiction) | ✅ | `tests/test_e2e.py` — 10 tests avec mocks OCR et ML |
| Jeux de données de test | ✅ | `conftest.py` + `water_potability.csv` / `water_potability_clean.csv` |

#### CI/CD

| Exigence | Statut | Commentaire |
|---|---|---|
| CI exécutant les tests à chaque push | ❌ | `ci.yml` est à la **racine** du dépôt. GitHub Actions lit uniquement `.github/workflows/*.yml`. Le fichier n'est jamais déclenché. |
| Build image Docker dans la CI | ✅ | Pipeline défini dans `ci.yml` (build + push vers GHCR) |
| Déploiement continu (bonus) | ✅ | Job `deploy` via SSH dans `ci.yml` |

#### Conteneurisation

| Exigence | Statut | Commentaire |
|---|---|---|
| Dockerfile API | ✅ | Python 3.11-slim, utilisateur non-root, healthcheck |
| docker-compose.yml | ✅ | Volume persistant, restart policy, healthcheck |
| `.env.example` | ✅ | Présent à la racine |
| Instructions de lancement | ✅ | README — mode local et mode Docker |

#### Monitoring

| Exigence | Statut | Commentaire |
|---|---|---|
| Journalisation des requêtes (client, route, status, durée) | ✅ | Table `request_metrics` + décorateur `@timed` |
| Journal d'accès RGPD (audit_logs) | ✅ | Toutes les routes écrivent dans `audit_logs` |
| Métriques exposées | ✅ | `GET /exploitation/metrics` — p50, p95, taux d'erreur par route |
| Prometheus / Grafana | ➖ | Optionnel selon le spec — non implémenté, noté dans README |

#### Incidents

| Exigence | Statut | Commentaire |
|---|---|---|
| Scénario d'incident documenté | ✅ | `docs/incident.md` — OCR.space indisponible : détection, diagnostic, correction, versionnement |

---

### 8. RGPD et gouvernance des accès

| Exigence | Statut | Commentaire |
|---|---|---|
| Séparation stricte des périmètres | ✅ | `require_client_key` filtre par `client_id` — impossible de voir les données d'un autre client |
| Minimisation des données personnelles | ✅ | ID client + dénomination + adresse seulement |
| Clé API jamais stockée en clair | ✅ | SHA-256 dans `api_key_hash`, seul le hint (8 derniers chars) est lisible |
| IP pseudonymisée dans les logs | ✅ | `_pseudo_ip()` masque le dernier octet IPv4 |
| Journaux d'accès | ✅ | Rétention documentée à 12 mois dans `docs/rgpd.md` |
| Droit d'accès aux données (art. 15) | ✅ | `GET /me/rgpd` |
| Droit à l'effacement (art. 17) | ✅ | `DELETE /me/rgpd` — anonymisation irréversible avec confirmation |
| Documentation RGPD | ✅ | `docs/rgpd.md` — classification des données, rétention, droits |

---

### 9. Livrables du dépôt GitHub

| Livrable | Statut | Commentaire |
|---|---|---|
| Code source API complet | ✅ | |
| Interface web expert | ✅ | `templates/index.html` |
| Scripts d'initialisation DB | ✅ | `scripts/init_db.py` |
| Fichiers de configuration | ✅ | `requirements.txt`, `.env.example`, `docker-compose.yml` |
| Historique Git régulier et attribuable | ❌ | Les commits récents sont : "ajout tout", "ajout monitoring", "add api key", "add test". Messages non descriptifs, nombreux changements en un seul commit. |
| Dossier `docs/` dans le dépôt | ❌ | `docs/` est listé dans `.gitignore`. Les 5 fichiers de documentation requis (architecture, MCD, user stories, RGPD, incident) **n'apparaissent pas dans le dépôt distant**. |
| `README.md` complet | ✅ | Architecture, prérequis, installation, routes, auth, variables, comptes test, limites |

---

## Tableau de synthèse

| Section | Couverture | Points critiques |
|---|---|---|
| 1. Spécifications | ✅ 95 % | — |
| 2. Base de données | ✅ 90 % | SQLite au lieu de PostgreSQL |
| 3. API Data | ✅ 95 % | — |
| 4. API Model | ⚠️ 80 % | Pas de route /predict dédiée |
| 5. API OCR | ✅ 95 % | — |
| 6. Interface web | ⚠️ 65 % | Filtres absents, vue audit manquante |
| 7. Tests | ⚠️ 60 % | test_fonctionnels + test_non_regression cassés |
| 7. CI/CD | ❌ 40 % | ci.yml au mauvais endroit |
| 7. Docker | ✅ 90 % | — |
| 7. Monitoring | ✅ 90 % | Prometheus optionnel absent |
| 7. Incident | ✅ 100 % | — |
| 8. RGPD | ✅ 95 % | — |
| 9. Livrables repo | ❌ 55 % | docs/ gitignorés, commits non descriptifs |

---

## Actions prioritaires avant soutenance

### Critiques (bloquants pour l'évaluation)

1. **Déplacer `ci.yml` → `.github/workflows/ci.yml`**
   Le fichier CI ne sera jamais exécuté tant qu'il est à la racine.

2. **Retirer `docs/` du `.gitignore`**
   Ajouter et committer les 5 fichiers `docs/*.md`. C'est un livrable explicitement demandé.

3. **Corriger ou remplacer `tests/test_fonctionnels.py` et `tests/test_non_regression.py`**
   Ces fichiers testent l'ancienne architecture (`/predict`, `flask_app.model`). Ils doivent être réécrits pour cibler les nouvelles routes ou supprimés au profit de `tests/test_e2e.py` et `test_api.py`.

4. **Ajouter les filtres dans l'interface web analyste**
   L'endpoint `GET /analyste/prelevements` accepte `client_id`, `source`, `date_from`, `date_to`. L'interface doit exposer ces contrôles.

### Importants (impact sur la note)

5. **Rendre la vue "Audit" accessible dans l'UI exploit**
   `GET /exploitation/audit` existe — ajouter un onglet dédié dans la vue expert rôle `exploit`.

6. **Améliorer l'historique Git**
   Décomposer les futurs commits par fonctionnalité avec des messages explicites (`feat:`, `fix:`, `docs:`...).

7. **Documenter la limite SQLite et la marche à suivre PostgreSQL**
   Ajouter dans le README comment switcher `DATABASE_URL` vers PostgreSQL et ajouter un service dans `docker-compose.yml` si nécessaire.

### Mineurs (bonus ou non-bloquants)

8. Ajouter un `README` dans `samples/` expliquant le format des fiches labo.
9. Exposer `GET /analyste/clients/<id>/prelevements` dans l'UI (dropdown client dans la vue prélèvements).
10. Ajouter un badge CI/CD dans le README pointant vers les GitHub Actions (une fois le fichier déplacé).
