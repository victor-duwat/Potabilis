"""
setup_waterflow.py — Script de configuration complète de Waterflow 2.
Lance depuis waterflow/ :  python setup_waterflow.py

Étapes :
  1. Pré-traitement de water_potability.csv  →  water_potability_clean.csv
  2. Entraînement XGBoost                    →  model_artifacts/
  3. Enregistrement MLflow (SQLite local)    →  mlflow_water.db + modèle v1
"""

import os
import sys
import json
import joblib
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# 0. Répertoire de travail = dossier du script
# ─────────────────────────────────────────────
os.chdir(os.path.dirname(os.path.abspath(__file__)))
SEED = 42
np.random.seed(SEED)

# ═══════════════════════════════════════════════════════
# ÉTAPE 1 — Pré-traitement
# ═══════════════════════════════════════════════════════
print("\n" + "═"*60)
print("  ÉTAPE 1 — Pré-traitement du dataset")
print("═"*60)

from scipy.stats.mstats import winsorize

df = pd.read_csv("water_potability.csv")
print(f"  Chargé : {df.shape[0]} lignes × {df.shape[1]} colonnes")
print(f"  Valeurs manquantes : ph={df['ph'].isna().sum()}, "
      f"Sulfate={df['Sulfate'].isna().sum()}, "
      f"Trihalomethanes={df['Trihalomethanes'].isna().sum()}")

df_clean = df.copy()
for col in ["ph", "Sulfate", "Trihalomethanes"]:
    medians = df_clean.groupby("Potability")[col].transform("median")
    global_median = df_clean[col].median()
    df_clean[col] = df_clean[col].fillna(medians).fillna(global_median)

features = [c for c in df_clean.columns if c != "Potability"]
df_clean[features] = df_clean[features].apply(
    lambda col: pd.Series(winsorize(col, limits=[0.01, 0.01]), index=col.index)
)

df_clean.to_csv("water_potability_clean.csv", index=False)
print(f"  ✓ water_potability_clean.csv sauvegardé ({df_clean.shape[0]} lignes, 0 valeurs manquantes)")

# ═══════════════════════════════════════════════════════
# ÉTAPE 2 — Entraînement XGBoost
# ═══════════════════════════════════════════════════════
print("\n" + "═"*60)
print("  ÉTAPE 2 — Entraînement XGBoost")
print("═"*60)

from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score,
    precision_score, recall_score, average_precision_score,
)
from imblearn.over_sampling import SMOTE
import xgboost as xgb

X = df_clean[features]
y = df_clean["Potability"]

X_train, X_val, y_train, y_val = train_test_split(
    X, y, test_size=0.20, stratify=y, random_state=SEED
)

scaler     = RobustScaler()
X_train_sc = scaler.fit_transform(X_train)
X_val_sc   = scaler.transform(X_val)

smote = SMOTE(random_state=SEED)
X_train_res, y_train_res = smote.fit_resample(X_train_sc, y_train)
print(f"  Train après SMOTE : {X_train_res.shape[0]} échantillons (équilibrés)")

params = dict(
    n_estimators=500, max_depth=6, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
    gamma=0.1, reg_alpha=0.1, reg_lambda=1.0,
    eval_metric="logloss", random_state=SEED, n_jobs=-1,
)

model = xgb.XGBClassifier(**params)
model.fit(
    X_train_res, y_train_res,
    eval_set=[(X_train_res, y_train_res), (X_val_sc, y_val)],
    verbose=False,
)
print(f"  ✓ Entraînement terminé ({params['n_estimators']} arbres)")

y_pred      = model.predict(X_val_sc)
y_pred_prob = model.predict_proba(X_val_sc)[:, 1]

metrics = {
    "Accuracy" : accuracy_score(y_val, y_pred),
    "F1-Score" : f1_score(y_val, y_pred),
    "Précision": precision_score(y_val, y_pred),
    "Rappel"   : recall_score(y_val, y_pred),
    "ROC-AUC"  : roc_auc_score(y_val, y_pred_prob),
    "PR-AUC"   : average_precision_score(y_val, y_pred_prob),
}
print(f"  Accuracy={metrics['Accuracy']:.4f}  F1={metrics['F1-Score']:.4f}  ROC-AUC={metrics['ROC-AUC']:.4f}")

print("  Validation croisée 5-fold (peut prendre ~30s)...")
cv_scores = cross_val_score(
    xgb.XGBClassifier(**params), X_train_res, y_train_res,
    cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED),
    scoring="roc_auc", n_jobs=-1,
)
print(f"  CV ROC-AUC = {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

# Sauvegarde des artefacts
os.makedirs("model_artifacts", exist_ok=True)
model.save_model("model_artifacts/xgboost_model.json")
joblib.dump(scaler, "model_artifacts/robust_scaler.pkl")
np.save("model_artifacts/X_val_sc.npy", X_val_sc)
np.save("model_artifacts/y_val.npy", y_val.values)
np.save("model_artifacts/y_pred.npy", y_pred)
np.save("model_artifacts/y_pred_prob.npy", y_pred_prob)
np.save("model_artifacts/cv_scores.npy", cv_scores)

metadata = {
    "features"       : list(features),
    "params"         : {k: str(v) for k, v in params.items()},
    "metrics"        : {k: round(float(v), 6) for k, v in metrics.items()},
    "cv_mean"        : round(float(cv_scores.mean()), 6),
    "cv_std"         : round(float(cv_scores.std()), 6),
    "n_train_raw"    : len(X_train),
    "n_train_smote"  : len(X_train_res),
    "n_val"          : len(X_val),
}
with open("model_artifacts/metadata.json", "w") as f:
    json.dump(metadata, f, indent=2)

evals = model.evals_result()
with open("model_artifacts/evals_result.json", "w") as f:
    json.dump(evals, f)

print("  ✓ model_artifacts/ créé (modèle, scaler, métadonnées)")

# ═══════════════════════════════════════════════════════
# ÉTAPE 3 — Enregistrement dans MLflow (SQLite local)
# ═══════════════════════════════════════════════════════
print("\n" + "═"*60)
print("  ÉTAPE 3 — Enregistrement MLflow")
print("═"*60)

import mlflow
import mlflow.xgboost
from mlflow import MlflowClient

MLFLOW_DB    = "sqlite:///mlflow_water.db"
ARTIFACT_DIR = "./mlflow_artifacts"
EXP_NAME     = "experiment_water_quality"
MODEL_NAME   = "WaterQualityXGBoost"

os.makedirs(ARTIFACT_DIR, exist_ok=True)
mlflow.set_tracking_uri(MLFLOW_DB)
print(f"  Tracking URI : {MLFLOW_DB}")

client = MlflowClient(tracking_uri=MLFLOW_DB)

experiment = client.get_experiment_by_name(EXP_NAME)
if experiment is None:
    experiment_id = client.create_experiment(
        name=EXP_NAME, artifact_location=ARTIFACT_DIR
    )
    print(f"  Expérience créée : {EXP_NAME}")
else:
    experiment_id = experiment.experiment_id
    print(f"  Expérience existante : {EXP_NAME} (id={experiment_id})")

mlflow.set_experiment(EXP_NAME)

RUN_NAME = "XGBoost_SMOTE_RobustScaler_v1"
existing = client.search_runs(
    experiment_ids=[experiment_id],
    filter_string=f"tags.mlflow.runName = '{RUN_NAME}' and attributes.status = 'FINISHED'",
    max_results=1,
)
if existing:
    count = len(client.search_runs(experiment_ids=[experiment_id]))
    RUN_NAME = f"{RUN_NAME}_run{count + 1}"
    print(f"  Run existant détecté → nouveau nom : {RUN_NAME}")

with mlflow.start_run(experiment_id=experiment_id, run_name=RUN_NAME) as run:
    run_id = run.info.run_id

    mlflow.set_tags({
        "model_type" : "XGBoostClassifier",
        "dataset"    : "water_potability.csv",
        "resampling" : "SMOTE",
        "scaler"     : "RobustScaler",
        "task"       : "binary_classification",
    })

    mlflow.log_params({k: str(v) for k, v in params.items()})
    mlflow.log_params({
        "n_train_raw"   : metadata["n_train_raw"],
        "n_train_smote" : metadata["n_train_smote"],
        "n_val"         : metadata["n_val"],
    })

    mlflow.log_metrics({
        "val_accuracy"  : metrics["Accuracy"],
        "val_f1"        : metrics["F1-Score"],
        "val_precision" : metrics["Précision"],
        "val_recall"    : metrics["Rappel"],
        "val_roc_auc"   : metrics["ROC-AUC"],
        "val_pr_auc"    : metrics["PR-AUC"],
        "cv_roc_auc_mean": float(cv_scores.mean()),
        "cv_roc_auc_std" : float(cv_scores.std()),
    })

    mlflow.xgboost.log_model(
        model,
        artifact_path=         "xgboost_model",
        registered_model_name= MODEL_NAME,
        input_example=         pd.DataFrame(X_val_sc[:3], columns=features),
    )

    print(f"  ✓ Run '{RUN_NAME}' enregistré (ID: {run_id[:20]}...)")
    print(f"  ✓ Modèle enregistré : {MODEL_NAME} v1")

# Alias champion
try:
    versions = client.search_model_versions(f"name='{MODEL_NAME}'")
    if versions:
        client.set_registered_model_alias(MODEL_NAME, "champion", versions[0].version)
        print(f"  ✓ Alias 'champion' → {MODEL_NAME} v{versions[0].version}")
except Exception:
    pass

# ═══════════════════════════════════════════════════════
print("\n" + "═"*60)
print("  SETUP TERMINÉ !")
print("═"*60)
print()
print("  Fichiers créés :")
print("    ✓ water_potability_clean.csv")
print("    ✓ model_artifacts/  (xgboost_model.json, robust_scaler.pkl, ...)")
print("    ✓ mlflow_water.db   (registry MLflow)")
print()
print("  Étapes suivantes :")
print("    1. python scripts/init_db.py      (noter les clés API affichées)")
print("    2. python main.py                 (serveur sur http://localhost:8080)")
print()
