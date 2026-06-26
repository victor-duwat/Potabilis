# Scénario de bug E5 — INC-2025-002

## Résumé

| Champ | Valeur |
|---|---|
| **Référence** | INC-2025-002 |
| **Date introduction** | 2025-12-03 |
| **Date détection** | 2025-12-03 (CI GitHub Actions) |
| **Date correction** | 2025-12-03 (même journée) |
| **Sévérité** | Haute (résultats erronés affichés aux clients) |
| **Composant** | `predict_service.py` — fonction `run_prediction()` |

---

## 1. Description du bug

### Cause racine
Lors d'un refactoring de `predict_service.py`, l'index d'extraction de la probabilité a été modifié par erreur :

```python
# AVANT (correct)
probability = float(_model.predict_proba(values_scaled)[0][1])  # P(potable=1)

# APRÈS (bug) ← commit buggy
probability = float(_model.predict_proba(values_scaled)[0][0])  # P(non-potable=0) ← FAUX
```

`predict_proba()` retourne une matrice `[[P(classe=0), P(classe=1)]]`. L'index `[0][1]` donne la probabilité de potabilité. L'index `[0][0]` donne celle de non-potabilité.

### Symptôme observable
Un client soumet un échantillon d'eau saine. Le modèle le classe `potable = 1`, mais la probabilité affichée est `18 %` au lieu de `82 %` — induisant une confusion majeure sur la fiabilité du résultat.

```json
// Avec le bug
{ "potable": 1, "label": "Potable", "probability": 0.18 }

// Attendu
{ "potable": 1, "label": "Potable", "probability": 0.82 }
```

---

## 2. Détection par la CI

Le test `tests/test_bug_e5.py::TestBugProbabiliteInversee::test_probabilite_correspond_a_classe_positive` a échoué à la CI immédiatement après le push :

```
FAILED tests/test_bug_e5.py::TestBugProbabiliteInversee::test_probabilite_correspond_a_classe_positive
AssertionError: Bug détecté : probabilité 0.1300 < 0.5 pour un échantillon classifié potable.
Vérifier predict_service.py ligne predict_proba()[0][1] vs [0][0].
```

**Pipeline CI GitHub Actions :** le job `test` a échoué en 47 secondes — aucun déploiement n'a été déclenché (le job `build` a `needs: test`).

---

## 3. Correction

```python
# predict_service.py — ligne corrigée
probability = float(_model.predict_proba(values_scaled)[0][1])  # P(potable=1) ← restauré
```

**Commit de correction :**
```
fix(predict): restaurer l'index [0][1] dans predict_proba()

Régression introduite dans INC-2025-002 :
predict_proba()[0][0] retournait P(non-potable) au lieu de P(potable).
Détecté par test_bug_e5.py::test_probabilite_correspond_a_classe_positive.

Fixes INC-2025-002
```

---

## 4. Déploiement via CI

Après correction et push :
1. ✅ `ruff check` — lint OK
2. ✅ `pytest tests/` — tous les tests passent, dont `test_bug_e5.py`
3. ✅ `docker build` — image construite
4. ✅ `docker push ghcr.io/...` — image publiée
5. ✅ SSH deploy — `docker compose up -d` sur le serveur de prod
6. ✅ Health check post-déploiement — `curl /health` → 200 OK

Durée totale CI → déploiement : **4 min 23 s**

---

## 5. Mesures préventives

- **Test ajouté** : `tests/test_bug_e5.py` — 3 tests qui vérifient la cohérence probabilité/prédiction
- **Règle invariante documentée** : `potable=1 ↔ probability >= 0.5`
- **Code review** : toute modification de `predict_service.py` requiert une relecture de l'index `predict_proba`

---

## Reproduire le bug pour la démo

```bash
# 1. Introduire le bug
sed -i 's/predict_proba(values_scaled)\[0\]\[1\]/predict_proba(values_scaled)[0][0]/' waterflow/predict_service.py

# 2. Lancer les tests → doit échouer
pytest waterflow/tests/test_bug_e5.py -v
# FAILED tests/test_bug_e5.py::TestBugProbabiliteInversee::test_probabilite_correspond_a_classe_positive

# 3. Corriger
sed -i 's/predict_proba(values_scaled)\[0\]\[0\]/predict_proba(values_scaled)[0][1]/' waterflow/predict_service.py

# 4. Relancer → doit passer
pytest waterflow/tests/test_bug_e5.py -v
# PASSED (3 tests)
```

---

*Post-mortem INC-2025-002 — Waterflow 2 B3 IA 2025*
