# Sources de données — Waterflow 2

## Tableau récapitulatif des 5 sources

| # | Source | Provenance | Format | Technologie | Volume | Champs utilisés |
|---|---|---|---|---|---|---|
| 1 | **Dataset Kaggle** | Water Potability Dataset (Kaggle / UCI) | CSV | pandas, numpy | 3 276 échantillons × 10 colonnes | ph, Hardness, Solids, Chloramines, Sulfate, Conductivity, Organic_carbon, Trihalomethanes, Turbidity, Potability |
| 2 | **API OCR.space** | OCR.space (service cloud) | JSON (REST) | requests (HTTP multipart) | ~25 000 req/mois (tier gratuit) | ParsedText, IsErroredOnProcessing, ErrorMessage, ParsedResults |
| 3 | **Base de données relationnelle** | SQLite local / PostgreSQL (prod) | SQL | SQLAlchemy 2.0 ORM | 6 tables, volumétrie variable | clients, prelevements, mesures, predictions, audit_logs, request_metrics |
| 4 | **Saisie manuelle JSON** | Collectivités (clients API) | JSON (POST body) | Flask REST API | 1 mesure / requête | ph, Hardness, Solids, Chloramines, Sulfate, Conductivity, Organic_carbon, Trihalomethanes, Turbidity |
| 5 | **Fiches de laboratoire (PDF/image)** | Laboratoires d'analyse d'eau | PDF, PNG, JPG | PyMuPDF (fitz), OCR.space, Claude Vision | 1 fichier / prélèvement, max 20 Mo | Date prélèvement, lieu, 9 paramètres physico-chimiques, observations |

---

## Détail par source

### Source 1 — Dataset Kaggle (CSV)

**Rôle dans le projet :** entraînement et évaluation du modèle XGBoost.

```python
import pandas as pd
df = pd.read_csv("water_potability.csv")   # 3 276 lignes, 10 colonnes
df_clean = df.dropna()                      # → water_potability_clean.csv
```

**Traitement :**
- Nettoyage des valeurs manquantes (imputation par médiane ou suppression)
- Normalisation via `RobustScaler` (résistant aux outliers)
- Split 80/20 entraînement/validation avec `train_test_split`

**Volume :** 3 276 échantillons → 2 386 après nettoyage NaN

---

### Source 2 — API OCR.space (REST)

**Rôle dans le projet :** extraction automatique des mesures depuis les fiches PDF/image des laboratoires.

```python
import requests

response = requests.post(
    "https://api.ocr.space/parse/image",
    files={"file": (filename, file_bytes, mime_type)},
    data={
        "apikey": OCR_SPACE_API_KEY,
        "language": "fre",
        "isOverlayRequired": False,
        "OCREngine": 2,
    },
    timeout=30,
)
result = response.json()
parsed_text = result["ParsedResults"][0]["ParsedText"]
```

**Fallback :** si OCR.space est indisponible (timeout ou erreur HTTP), basculement automatique vers **Claude Vision (Anthropic)**.

**Données extraites :** texte brut → parsing regex pour extraire les 9 paramètres physico-chimiques.

---

### Source 3 — Base de données relationnelle (SQL)

**Rôle dans le projet :** persistance de toutes les données opérationnelles.

**Requête exemple — agrégation (JOIN + GROUP BY) :**
```sql
SELECT c.id_client, c.denomination,
       COUNT(p.id) AS nb_prelevements,
       AVG(pr.probability) AS prob_moyenne,
       SUM(CASE WHEN pr.potable = 1 THEN 1 ELSE 0 END) AS potables
FROM clients c
LEFT JOIN prelevements p ON p.client_id = c.id
LEFT JOIN predictions pr ON pr.prelevement_id = p.id
WHERE c.actif = 1
GROUP BY c.id_client, c.denomination
ORDER BY nb_prelevements DESC;
```

**Requête exemple — audit RGPD :**
```sql
SELECT actor_id, action, COUNT(*) AS nb, MAX(timestamp) AS dernier_acces
FROM audit_logs
WHERE timestamp > datetime('now', '-12 months')
GROUP BY actor_id, action
ORDER BY nb DESC;
```

**Tables :** 6 tables, volumétrie dépendante du nombre de collectivités clientes.

---

### Source 4 — Saisie manuelle JSON (API REST)

**Rôle dans le projet :** ingestion directe des mesures par les agents terrain des collectivités.

```json
POST /ingest/manual
Content-Type: application/json
X-API-Key: <clé>

{
  "ph": 7.2,
  "Hardness": 198.4,
  "Solids": 18630.0,
  "Chloramines": 7.1,
  "Sulfate": 333.0,
  "Conductivity": 432.0,
  "Organic_carbon": 14.2,
  "Trihalomethanes": 62.8,
  "Turbidity": 4.0
}
```

**Validation :** tous les 9 paramètres sont requis, de type numérique. Erreur 400 si manquant ou non-numérique.

---

### Source 5 — Fiches de laboratoire (PDF / image)

**Rôle dans le projet :** automatisation du traitement des comptes-rendus d'analyse des laboratoires accrédités.

**Flux :**
```
Fiche PDF/PNG/JPG
    ↓
[PyMuPDF] Conversion PDF → image si nécessaire
    ↓
[OCR.space API] Extraction du texte brut
    ↓ (fallback)
[Claude Vision] Extraction avec prompt structuré
    ↓
[Regex / parsing] Extraction des 9 paramètres
    ↓
Stockage prélèvement + mesures en base
```

**Fichiers d'exemple :** `samples/fiche_labo_exemple_1.txt` (complet) et `samples/fiche_labo_exemple_2_partiel.txt` (partiel).

---

## Concaténation / JOIN entre sources

**Pipeline principal :**
```
[CSV Kaggle] → Entraînement XGBoost → [Modèle MLflow]
                                              ↓
[Source 4 ou 5] → API /ingest → [DB Source 3] → run_prediction() → [Prédiction]
```

**JOIN opérationnel (dashboard analyste) :**
```
clients JOIN prelevements JOIN mesures JOIN predictions
→ KPIs, moyennes, taux de potabilité par client
```

---

*Document sources de données — Waterflow 2 B3 IA 2025*
