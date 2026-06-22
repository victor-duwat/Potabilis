# Modèle Conceptuel de Données — Waterflow 2

## MCD (Entités et associations)

```
┌─────────────────────┐       ┌──────────────────────┐
│       CLIENT        │       │     PRELEVEMENT       │
├─────────────────────┤ 1   N ├──────────────────────┤
│ id (UUID, PK)       │───────│ id (UUID, PK)         │
│ id_client (unique)  │       │ client_id (FK)        │
│ denomination        │       │ date_prelevement      │
│ adresse             │       │ lieu                  │
│ api_key_hash        │       │ source (manual/ocr)   │
│ api_key_hint        │       │ fichier_nom           │
│ actif (bool)        │       │ ocr_raw_text          │
│ created_at          │       │ ocr_warnings (JSON)   │
│ created_by          │       │ observations          │
│ rgpd_consent        │       │ created_at            │
│ rgpd_consent_at     │       └──────────────────────┘
│ anonymised_at       │                  │
└─────────────────────┘                  │ 1
                                         │
                            ┌────────────┴──────────────┐
                            │                           │
                     1      ▼ 0..1                0..1  ▼
           ┌───────────────────────┐   ┌───────────────────────┐
           │        MESURE         │   │      PREDICTION       │
           ├───────────────────────┤   ├───────────────────────┤
           │ id (UUID, PK)         │   │ id (UUID, PK)         │
           │ prelevement_id (FK)   │   │ prelevement_id (FK)   │
           │ ph (float)            │   │ potable (0/1)         │
           │ hardness (float)      │   │ probability (float)   │
           │ solids (float)        │   │ model_version (str)   │
           │ chloramines (float)   │   │ created_at            │
           │ sulfate (float)       │   └───────────────────────┘
           │ conductivity (float)  │
           │ organic_carbon (float)│   ┌───────────────────────┐
           │ trihalomethanes(float)│   │      AUDIT_LOG        │
           │ turbidity (float)     │   ├───────────────────────┤
           │ created_at            │   │ id (UUID, PK)         │
           └───────────────────────┘   │ actor_type            │
                                       │ actor_id              │
                                       │ actor_role            │
           ┌───────────────────────┐   │ ip_address (pseudo.)  │
           │   REQUEST_METRIC      │   │ action                │
           ├───────────────────────┤   │ resource_id           │
           │ id (UUID, PK)         │   │ status_code           │
           │ route                 │   │ detail                │
           │ method                │   │ timestamp             │
           │ status_code           │   └───────────────────────┘
           │ duration_ms           │
           │ actor_type            │
           │ actor_hint            │
           │ timestamp             │
           └───────────────────────┘
```

---

## MPD — Modèle Physique de Données

### Table `clients`
| Colonne | Type | Contraintes |
|---|---|---|
| id | VARCHAR(36) | PK, UUID |
| id_client | VARCHAR(50) | UNIQUE NOT NULL |
| denomination | VARCHAR(200) | NOT NULL |
| adresse | TEXT | |
| api_key_hash | VARCHAR(64) | nullable (SHA-256) |
| api_key_hint | VARCHAR(10) | nullable |
| key_generated_at | DATETIME | |
| actif | BOOLEAN | DEFAULT true |
| created_at | DATETIME | DEFAULT now() |
| created_by | VARCHAR(100) | login expert |
| rgpd_consent | BOOLEAN | DEFAULT false |
| rgpd_consent_at | DATETIME | |
| anonymised_at | DATETIME | nullable |

### Table `prelevements`
| Colonne | Type | Contraintes |
|---|---|---|
| id | VARCHAR(36) | PK, UUID |
| client_id | VARCHAR(36) | FK → clients.id |
| date_prelevement | DATETIME | nullable |
| lieu | VARCHAR(300) | nullable |
| source | ENUM | 'manual', 'ocr' |
| fichier_nom | VARCHAR(500) | nullable |
| fichier_type | VARCHAR(100) | nullable |
| ocr_raw_text | TEXT | nullable |
| ocr_warnings | TEXT | JSON array |
| observations | TEXT | nullable |
| created_at | DATETIME | DEFAULT now() |

### Table `mesures`
| Colonne | Type | Contraintes |
|---|---|---|
| id | VARCHAR(36) | PK, UUID |
| prelevement_id | VARCHAR(36) | FK → prelevements.id, UNIQUE |
| ph | FLOAT | nullable |
| hardness | FLOAT | nullable |
| solids | FLOAT | nullable |
| chloramines | FLOAT | nullable |
| sulfate | FLOAT | nullable |
| conductivity | FLOAT | nullable |
| organic_carbon | FLOAT | nullable |
| trihalomethanes | FLOAT | nullable |
| turbidity | FLOAT | nullable |
| created_at | DATETIME | DEFAULT now() |

### Table `predictions`
| Colonne | Type | Contraintes |
|---|---|---|
| id | VARCHAR(36) | PK, UUID |
| prelevement_id | VARCHAR(36) | FK → prelevements.id |
| potable | INTEGER | 0 ou 1 |
| probability | FLOAT | |
| model_version | VARCHAR(200) | URI MLflow |
| created_at | DATETIME | DEFAULT now() |

### Table `audit_logs`
| Colonne | Type | Contraintes |
|---|---|---|
| id | VARCHAR(36) | PK, UUID |
| actor_type | VARCHAR(20) | 'client' ou 'expert' |
| actor_id | VARCHAR(100) | id_client ou login |
| actor_role | VARCHAR(20) | 'client', 'analyste', 'exploit' |
| ip_address | VARCHAR(50) | pseudonymisée (*.xxx) |
| action | VARCHAR(100) | ex. 'client_ingest_manual' |
| resource_id | VARCHAR(36) | UUID prélèvement ou client |
| status_code | INTEGER | code HTTP |
| detail | TEXT | informations complémentaires |
| timestamp | DATETIME | DEFAULT now() |

### Table `request_metrics`
| Colonne | Type | Contraintes |
|---|---|---|
| id | VARCHAR(36) | PK, UUID |
| route | VARCHAR(200) | chemin HTTP |
| method | VARCHAR(10) | GET, POST, etc. |
| status_code | INTEGER | |
| duration_ms | FLOAT | temps de traitement |
| actor_type | VARCHAR(20) | nullable |
| actor_hint | VARCHAR(20) | hint clé ou login |
| timestamp | DATETIME | DEFAULT now() |

---

## Cardinalités

- `CLIENT` (1,1) → (0,N) `PRELEVEMENT` : un client peut avoir zéro ou plusieurs prélèvements
- `PRELEVEMENT` (1,1) → (0,1) `MESURE` : chaque prélèvement a au plus une fiche de mesures
- `PRELEVEMENT` (1,1) → (0,N) `PREDICTION` : un prélèvement peut avoir plusieurs prédictions (historique)
- `AUDIT_LOG` et `REQUEST_METRIC` sont indépendantes (pas de FK directe pour éviter les contraintes lors des purges)

---

*MCD Waterflow 2 — B3 IA 2025*
