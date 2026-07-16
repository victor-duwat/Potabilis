# Architecture technique — Waterflow 2

## Contexte métier

Waterflow 2 est une plateforme MLOps destinée aux collectivités territoriales pour analyser la potabilité de l'eau. Elle automatise la collecte de mesures physico-chimiques (saisie manuelle ou OCR de fiches de laboratoire), applique un modèle XGBoost entraîné sur le dataset *Water Potability* (Kaggle), et expose les résultats via une API REST sécurisée.

---

## Composants principaux

```
waterflow/
├── api/
│   ├── app.py                  # Factory Flask (create_app)
│   ├── models/db.py            # 6 tables SQLAlchemy
│   ├── middleware/auth.py      # Auth clé API + Bearer expert
│   ├── routes/routes.py        # Toutes les routes (Blueprint)
│   └── services/
│       ├── ocr_service.py      # OCR.space + fallback Claude Vision
│       └── predict_service.py  # XGBoost via MLflow
├── templates/index.html        # Interface web SPA (Tailwind)
├── scripts/init_db.py          # Seed base de données
├── model_artifacts/            # Modèle XGBoost + RobustScaler
├── mlflow_artifacts/           # Registry MLflow local
├── Dockerfile
├── docker-compose.yml
└── .github/workflows/ci.yml    # CI GitHub Actions
```

---

## Diagramme de flux

```
Client HTTP
    │
    ▼
[Flask API :8080]
    │
    ├─ Auth ──────────────────► [SQLite / PostgreSQL]
    │   ├─ X-API-Key (clients)       clients, prelevements,
    │   └─ Bearer (experts)          mesures, predictions,
    │                                audit_logs, request_metrics
    ├─ POST /ingest/manual
    │   └─► predict_service ──► [MLflow XGBoost v1]
    │
    ├─ POST /ingest/ocr*
    │   ├─► ocr_service ──────► [OCR.space API]
    │   │                            └─ fallback: [Claude Vision]
    │   └─► predict_service ──► [MLflow XGBoost v1]
    │
    └─ GET /analyste/dashboard
        └─► [SQLAlchemy ORM]
```

---

## Choix techniques

| Composant | Choix | Justification |
|---|---|---|
| Framework API | Flask 3 + Blueprint | Léger, modulaire, maturité OCR/ML ecosystem |
| ORM | SQLAlchemy 2.0 | Portabilité SQLite ↔ PostgreSQL |
| Base de données | SQLite (dev/prod) | Déploiement simplifié sans service externe |
| ML tracking | MLflow | Versionnement modèle, reproductibilité |
| Modèle | XGBoost (sklearn API) | Précision 67 % AUC 0.68 sur dataset équilibré |
| Scaler | RobustScaler | Résistant aux outliers (mesures eau) |
| OCR primaire | OCR.space | API REST, support PDF+image, gratuit jusqu'à 25k/mois |
| OCR fallback | Claude Vision (Anthropic) | Fiabilité en cas d'indisponibilité OCR.space |
| Rate limiting | Flask-Limiter | Protection contre les abus |
| Conteneurisation | Docker + Compose | Déploiement reproductible |
| CI/CD | GitHub Actions | Tests + build image Docker + déploiement SSH |

---

## Authentification et périmètres

```
MONDE 1 — CLIENTS (collectivités)
  Transport : X-API-Key header
  Périmètre : uniquement leurs propres données
  Décorateur : @require_client_key

MONDE 2 — EXPERTS
  Transport : Authorization: Bearer <token>
  Rôle analyste : dashboards, tous prélèvements, gestion clients
  Rôle exploit  : métriques système, audit RGPD + tout analyste
  Décorateur : @require_expert(role=...)
```

### Sécurité de l'API — positionnement face à l'OWASP Top 10

L'API expose un modèle de ML à des clients externes : les risques du
[Top 10 OWASP](https://owasp.org/www-project-top-ten/) s'y appliquent. Mesures en
place, rapportées aux catégories concernées :

| Risque OWASP | Mesure dans Waterflow 2 |
|---|---|
| A01 — Broken Access Control | Deux périmètres étanches (clients / experts), rôles vérifiés serveur (`@require_expert(role=...)`) et reflétés dans l'UI : un client ne voit que ses prélèvements, un analyste n'accède pas à l'audit. |
| A02 — Cryptographic Failures | Aucun secret en clair : les tokens experts sont comparés via leur empreinte SHA-256 (`auth.py`), jamais stockés bruts. |
| A03 — Injection | Accès BDD exclusivement via l'ORM SQLAlchemy : requêtes paramétrées, pas de SQL concaténé. |
| A05 — Security Misconfiguration | Secrets hors du code (`.env`, gitignoré) ; l'image Docker n'embarque aucune clé. |
| A07 — Identification & Authentication Failures | Renouvellement des accès prévu : `POST /admin/clients/<id>/apikey` régénère la clé d'un client (révocation immédiate de l'ancienne). |
| A09 — Security Logging & Monitoring Failures | Logs JSON structurés sur chaque échec d'auth + alerte `PicAuthEchouees` (Prometheus) : plus d'un échec/s pendant 2 min déclenche une notification. |

Les autres catégories (A04, A06, A08, A10) sont suivies mais sans mesure dédiée : le
périmètre du projet (API interne, pas de dépendance exotique, pas de désérialisation
d'objets) ne les expose pas directement.

---

## Base de données — 6 tables

| Table | Description |
|---|---|
| `clients` | Collectivités : id_client, denomination, api_key_hash |
| `prelevements` | Échantillons : date, lieu, source (manual/ocr), OCR brut |
| `mesures` | 9 paramètres physico-chimiques (FK prelevement) |
| `predictions` | Résultat XGBoost : potable, probabilité, version modèle |
| `audit_logs` | Journal RGPD immuable : acteur, action, IP pseudonymisée |
| `request_metrics` | Monitoring : route, durée, statut HTTP |

---

## Modèle ML

- **Dataset** : Water Potability (Kaggle) — 3 276 échantillons, 9 features
- **Pipeline** : nettoyage NaN → RobustScaler → XGBoost (max_depth=5, n_estimators=300)
- **Métriques** : Accuracy 67 %, F1 0.55, AUC-ROC 0.68
- **Tracking** : MLflow (sqlite:///mlflow_water.db), modèle `WaterQualityXGBoost/1`
- **Features** : ph, Hardness, Solids, Chloramines, Sulfate, Conductivity, Organic_carbon, Trihalomethanes, Turbidity

---

*Architecture Waterflow 2 — B3 IA 2025*
