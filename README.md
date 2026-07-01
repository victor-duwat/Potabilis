# Waterflow 2 — Plateforme MLOps de qualité de l'eau

[![CI/CD](https://github.com/victor-duwat/waterflow2/actions/workflows/ci.yml/badge.svg)](https://github.com/victor-duwat/waterflow2/actions/workflows/ci.yml)

> Projet chef-d'œuvre — Titre RNCP 37827 « Développeur en Intelligence Artificielle ».
> Plateforme de classification de la **potabilité de l'eau** pour des collectivités territoriales :
> une **API Flask unique** à trois modules (Données, Prédiction ML, Ingestion OCR), une base
> relationnelle conforme **RGPD**, une interface web experts, et une supervision **Prometheus/Grafana**.

---

## Contexte

Une collectivité dépose des mesures physico-chimiques d'un prélèvement d'eau — soit en JSON,
soit en envoyant une **photo / PDF de fiche de laboratoire** (OCR) — et reçoit une prédiction
*potable / non potable* issue d'un modèle **XGBoost** versionné sous **MLflow**. Les analystes et
le responsable d'exploitation disposent d'une interface web (dashboards, filtres, audit, métriques).

## Architecture

```
Client / Analyste / Exploitation
              │  (X-API-Key  ou  Authorization: Bearer)
              ▼
      ┌──────────────────────────────┐
      │   API Flask unique (modules)  │
      │  ── Données   (prélèvements)  │──► Base relationnelle (SQLAlchemy, RGPD)
      │  ── Prédiction (XGBoost)      │──► MLflow (registre + versions du modèle)
      │  ── OCR (OCR.space + fallback)│──► Claude Vision (secours)
      └──────────────────────────────┘
              │  /metrics
              ▼
      Prometheus ──► Grafana (dashboards)  +  Alertmanager (alertes)
```

## Structure du dépôt

```
.
├── .github/workflows/ci.yml     # CI GitHub Actions (lint ruff + pytest)
├── README.md                    # ce fichier
└── waterflow/                   # le projet
    ├── app.py / auth.py / routes.py / predict_service.py / ocr_service.py / db.py
    ├── api/                     # package applicatif (factory, routes, services, modèles)
    ├── templates/index.html     # interface web (SPA) clients + experts
    ├── scripts/                 # init_db.py, register_model.py
    ├── model_artifacts/         # modèle XGBoost entraîné + RobustScaler (versionnés)
    ├── monitoring/              # prometheus.yml, alert.rules.yml, alertmanager.yml, dashboards Grafana
    ├── tests/                   # suite pytest (unitaires, fonctionnels, non-régression, e2e, bug)
    ├── docs/                    # architecture, MCD, user stories, RGPD, incident, Agile, maquettes…
    ├── Dockerfile / docker-compose.yml / .env.example
    └── requirements.txt
```

## Démarrage rapide

### Option A — Docker (recommandé, tout-en-un)

```bash
git clone https://github.com/victor-duwat/waterflow2.git
cd waterflow2/waterflow
cp .env.example .env          # renseigner EXPERT_TOKENS (et clés OCR si besoin)
docker compose up -d --build  # API + Prometheus + Grafana + Alertmanager
```

| Service | URL |
|---|---|
| Application | http://localhost:8080 |
| Documentation API (Swagger) | http://localhost:8080/apidocs |
| Prometheus (métriques + alertes) | http://localhost:9090 |
| Grafana (dashboards) | http://localhost:3000 — `admin` / `waterflow` |
| Alertmanager | http://localhost:9093 |

> Au premier démarrage, le conteneur **enregistre automatiquement** le modèle dans MLflow
> (`scripts/register_model.py`) puis lance l'API — comptez ~15 s avant l'état *healthy*.

### Option B — Local (développement)

```bash
cd waterflow
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python setup_waterflow.py     # (1re fois) entraîne + enregistre le modèle dans MLflow
python scripts/init_db.py     # crée la base + données de test (affiche les clés API)
python main.py                # http://localhost:8080
```

## Comptes et clés de test

Les **experts** sont définis dans `.env` via `EXPERT_TOKENS` (format `login:token:role`) :

| Rôle | Login | Accès |
|---|---|---|
| `analyste` | alice | dashboards, prélèvements, gestion clients |
| `exploit` | bob | tout analyste + métriques + audit |

Les **clients** obtiennent une clé API générée par un expert
(`POST /admin/clients` puis `POST /admin/clients/<id>/apikey`).

## Tests

```bash
cd waterflow
pytest tests/ test_api.py -q          # suite complète
pytest tests/ --cov=api               # avec couverture
```

## Monitoring & alertes

- L'API expose ses métriques au format Prometheus sur **`/metrics`**.
- **5 règles d'alerte à seuils** (`monitoring/alert.rules.yml`) : taux d'erreur 5xx, latence p95,
  échecs d'authentification, API injoignable, échecs OCR — routées par **Alertmanager** (Slack/e-mail).
- Dashboard **Grafana** provisionné automatiquement.

## Sécurité & RGPD

- Clés API **hachées SHA-256** (jamais stockées en clair), transmises par header `X-API-Key`.
- **Cloisonnement** : un client n'accède qu'à ses propres données.
- IP **pseudonymisées** dans les logs, **journal d'audit** immuable, purge automatique (12 mois).
- Droit à l'effacement via `DELETE /me/rgpd`. Recommandations **OWASP** appliquées.

## Documentation détaillée (`waterflow/docs/`)

| Document | Contenu |
|---|---|
| `architecture.md` | Schéma technique, composants, flux de données |
| `mcd.md` | Modèle de données (MCD / MPD, méthode Merise) |
| `user_stories.md` | User stories + critères d'acceptation + accessibilité (WCAG/RGAA) |
| `gestion_agile.md` | Kanban, backlog MoSCoW, sprints, rituels |
| `maquettes.md` | Wireframes + mini cahier des charges UI |
| `rgpd.md` | Gestion des données personnelles et des journaux d'accès |
| `incident.md` / `bug_e5.md` | Scénarios d'incident et résolution |
| `sources_donnees.md` | Tableau des sources de données (E1) |

## Compétences RNCP couvertes (chef-d'œuvre E3 / E4 / E5)

| Comp. | Où | Comp. | Où |
|---|---|---|---|
| C9 API modèle | `routes.py` + auth | C15 architecture | `docs/architecture.md` |
| C10 intégration + renouvellement clé | UI + `/apikey` | C16 Agile | `docs/gestion_agile.md` |
| C11 monitoring modèle | MLflow | C17 composants/UI | `templates/index.html` + `docs/maquettes.md` |
| C12 tests | `tests/` | C18 tests CI | `.github/workflows/ci.yml` |
| C13 CI | GitHub Actions | C19 livraison | Docker Compose |
| C14 besoin/US | `docs/user_stories.md` | C20 / C21 monitoring & bug | `monitoring/` + `docs/bug_e5.md` |

## Limites connues

- CORS non configuré (à activer pour un frontend séparé).
- Authentification expert par token statique (pas de rotation automatique).
- Alerting Slack en configuration de démonstration (webhook à renseigner en production).

---

*Waterflow 2 — Victor Duwat · B3 Développeur IA · RNCP 37827*
