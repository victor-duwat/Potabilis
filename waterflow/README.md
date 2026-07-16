# Potabilis — Plateforme MLOps Qualité de l'Eau

Plateforme de classification de la potabilité de l'eau destinée aux collectivités territoriales.
Exposée via une **API Flask unique** portant trois modules : données, prédiction ML et ingestion OCR.

---

## Architecture

```
.github/workflows/ci.yml        # CI/CD GitHub Actions (à la racine du dépôt)
waterflow/
├── app.py / auth.py / routes.py / predict_service.py   # Implémentations cœur
├── api/                        # Package applicatif (ré-exporte le cœur)
│   ├── app.py                  # Factory Flask + Swagger + Prometheus + rate limiting
│   ├── models/db.py            # Modèles SQLAlchemy (RGPD)
│   ├── middleware/auth.py      # Auth clé API (clients) + Bearer (experts)
│   ├── routes/routes.py        # Toutes les routes API
│   └── services/
│       ├── ocr_service.py      # OCR.space (primaire) + Claude Vision (fallback)
│       └── predict_service.py  # XGBoost via MLflow
├── templates/index.html        # Interface web (SPA Tailwind) clients + experts
├── scripts/init_db.py          # Initialisation DB + données de test
├── tests/
│   ├── conftest.py             # Config partagée (tokens experts, env de test)
│   ├── test_api.py             # Tests intégration complets (Potabilis)
│   ├── test_e2e.py             # Test bout en bout : OCR → prédiction
│   ├── test_unitaires.py       # Tests unitaires (modèle)
│   ├── test_fonctionnels.py    # Tests fonctionnels (routes)
│   ├── test_non_regression.py  # Tests de non-régression
│   └── test_bug_e5.py          # Test de détection du bug E5 (probabilité inversée)
├── docs/                       # MCD, architecture, user stories, RGPD, incidents, sources E1
├── monitoring/                 # Config Prometheus + dashboards Grafana provisionnés
├── samples/                    # Fiches labo anonymisées (exemples OCR)
├── model_artifacts/            # Modèle XGBoost + scaler
├── swagger.yaml                # Documentation OpenAPI — accessible sur /apidocs
├── main.py                     # Point d'entrée (serveur Flask / Gunicorn)
├── Dockerfile
├── docker-compose.yml          # API + Prometheus + Grafana
├── requirements.txt
└── .env.example
```

---

## Prérequis

- Python 3.11+
- Docker & Docker Compose (pour le déploiement conteneurisé)
- Au moins une clé OCR : `OCR_SPACE_API_KEY` ou `ANTHROPIC_API_KEY`

---

## Installation et lancement

### Mode local

```bash
# 1. Cloner le dépôt
git clone <url-du-repo>
cd waterflow

# 2. Créer l'environnement virtuel
python -m venv .venv
source .venv/bin/activate   # Windows : .venv\Scripts\activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env : renseigner OCR_SPACE_API_KEY et/ou ANTHROPIC_API_KEY
# Configurer EXPERT_TOKENS : login:token:role,login2:token2:role2

# 5. Initialiser la base de données avec des données de test
python scripts/init_db.py

# 6. Lancer le serveur
python main.py
# → http://localhost:8080
# → Documentation Swagger : http://localhost:8080/apidocs
```

### Mode Docker

```bash
# 1. Variables d'environnement
cp .env.example .env
# Éditer .env

# 2. Lancer via Docker Compose
docker compose up -d

# 3. Initialiser la base de données
docker compose exec waterflow2 python scripts/init_db.py

# Logs
docker compose logs -f waterflow2
```

---

## Lancer les tests

```bash
# Tous les tests
pytest tests/ -v

# Avec couverture
pytest tests/ -v --cov=api

# Test bout en bout uniquement
pytest tests/test_e2e.py -v

# Tests d'intégration Potabilis
pytest tests/test_api.py -v
```

---

## Routes API

Documentation interactive complète : **`/apidocs`** (Swagger UI)

| Méthode | Route                              | Auth               | Description                       |
|---------|------------------------------------|--------------------|-----------------------------------|
| GET     | /health                            | public             | État du service                   |
| GET     | /me                                | X-API-Key          | Profil client                     |
| GET     | /me/prelevements                   | X-API-Key          | Mes prélèvements (paginés)        |
| GET     | /me/prelevements/`<id>`            | X-API-Key          | Détail d'un prélèvement           |
| GET     | /me/resultats                      | X-API-Key          | Mes prédictions                   |
| GET     | /me/rgpd                           | X-API-Key          | Données personnelles (RGPD)       |
| DELETE  | /me/rgpd                           | X-API-Key          | Droit à l'effacement              |
| POST    | /ingest/manual                     | X-API-Key          | Déposer mesures JSON + prédiction |
| POST    | /ingest/ocr                        | X-API-Key          | Déposer fiche labo (OCR seul)     |
| POST    | /ingest/ocr-and-predict            | X-API-Key          | OCR + prédiction (pipeline)       |
| GET     | /admin/clients                     | Bearer (tout expert) | Lister les clients              |
| POST    | /admin/clients                     | Bearer (tout expert) | Créer un client                 |
| GET     | /admin/clients/`<id>`              | Bearer (tout expert) | Détail client                   |
| PUT     | /admin/clients/`<id>`              | Bearer (tout expert) | Modifier client                 |
| POST    | /admin/clients/`<id>`/apikey       | Bearer (tout expert) | Générer/régénérer clé API       |
| GET     | /analyste/prelevements             | Bearer (analyste+) | Tous les prélèvements             |
| GET     | /analyste/prelevements/`<id>`      | Bearer (analyste+) | Détail complet (+ OCR brut)      |
| GET     | /analyste/dashboard                | Bearer (analyste+) | KPIs agrégés                     |
| GET     | /exploitation/metrics              | Bearer (exploit)   | Métriques système                 |
| GET     | /exploitation/audit                | Bearer (exploit)   | Journal d'accès RGPD              |

---

## Authentification

### Clients (collectivités)
```
X-API-Key: <clé_générée_par_la_plateforme>
```
La clé est transmise **uniquement** via le header `X-API-Key` — jamais en paramètre
d'URL (une clé dans l'URL est journalisée par les proxies et l'historique navigateur).

### Experts (analystes / exploitation)
```
Authorization: Bearer <token>
```
Les tokens sont configurés via la variable d'environnement `EXPERT_TOKENS` :
```
EXPERT_TOKENS=alice:token-alice:analyste,bob:token-bob:exploit
```
Rôles : `analyste` (dashboards, prélèvements) | `exploit` (métriques, audit + tout analyste)

---

## Variables d'environnement

| Variable            | Obligatoire | Défaut                              | Description                         |
|---------------------|-------------|-------------------------------------|-------------------------------------|
| `DATABASE_URL`      | non         | `sqlite:///waterflow2.db`           | URL SQLAlchemy (SQLite ou PostgreSQL) |
| `MLFLOW_URI`        | non         | `models:/WaterQualityXGBoost/1`     | URI du modèle MLflow                |
| `MLFLOW_TRACKING_URI` | non       | `sqlite:///mlflow_water.db`         | Backend MLflow                      |
| `SCALER_PATH`       | non         | `model_artifacts/robust_scaler.pkl` | Chemin vers le RobustScaler         |
| `OCR_SPACE_API_KEY` | non*        | `""`                                | Clé API OCR.space                   |
| `ANTHROPIC_API_KEY` | non*        | `""`                                | Clé Claude Vision (fallback OCR)    |
| `EXPERT_TOKENS`     | **oui**     | —                                   | `login:token:role,...`              |
| `MAX_UPLOAD_MB`     | non         | `20`                                | Taille max upload OCR (Mo)          |
| `PORT`              | non         | `8080`                              | Port d'écoute                       |
| `FLASK_ENV`         | non         | `production`                        | `development` pour le mode debug    |

\* Au moins une des deux clés OCR est requise pour les routes `/ingest/ocr*`.

---

## Comptes et clés de test

Après `python scripts/init_db.py`, deux clients sont créés (clés affichées en sortie) :

| ID client    | Dénomination                 | Statut  |
|--------------|------------------------------|---------|
| CLIENT-001   | Mairie de Marseille          | actif   |
| CLIENT-002   | Syndicat des Eaux du Var     | actif   |
| CLIENT-003   | Commune de Nice              | inactif |

Les tokens experts sont définis dans `.env` via `EXPERT_TOKENS`.

---

## Fiches labo exemples (OCR)

Le dossier `samples/` contient deux fiches anonymisées :

| Fichier                          | Description                                 |
|----------------------------------|---------------------------------------------|
| `fiche_labo_exemple_1.txt`       | Fiche complète → `prediction_possible=true` |
| `fiche_labo_exemple_2_partiel.txt` | Fiche partielle → `prediction_possible=false` |

---

## Conformité RGPD

- Clés API hashées SHA-256 (jamais stockées en clair)
- IPs pseudonymisées dans les logs (dernier octet masqué)
- Table `audit_logs` immuable — journal de tous les accès
- Droit à l'effacement via `DELETE /me/rgpd`
- Conservation des logs : 12 mois glissants
- Clé API transmise uniquement via header `X-API-Key` (jamais en URL)
- Documentation complète : `docs/rgpd.md`

---

## Supervision (Prometheus / Grafana)

Le monitoring est intégré au `docker compose` :

- L'API expose les métriques au format Prometheus sur **`/metrics`** (via `prometheus_flask_exporter`).
- **Prometheus** (port 9090) scrape l'API toutes les 10 s.
- **Grafana** (port 3000, `admin` / `waterflow`) charge automatiquement la source de
  données et le dashboard `Potabilis — Monitoring API` (taux d'erreur, latences p50/p95,
  volume par statut HTTP, latence des routes d'ingestion).

```bash
docker compose up -d        # API + Prometheus + Grafana
# Grafana : http://localhost:3000   (dashboard provisionné automatiquement)
```

---

## Limites connues et pistes d'amélioration

- CORS non configuré (à activer si un frontend séparé consomme l'API)
- La clé API est unique par client (pas de rotation multiple simultanée)
- Authentification expert par token statique (pas de rotation automatique)
- Alerting Grafana non configuré (dashboards en lecture seule pour l'instant)
