# Scénario d'incident — Waterflow 2

## Incident référence : INC-2025-001

**Titre :** Indisponibilité du service OCR.space — dégradation du pipeline d'ingestion OCR  
**Date :** 2025-11-14 09h17 UTC  
**Durée :** 47 minutes (09h17 → 10h04)  
**Sévérité :** Moyenne (service dégradé, pas d'interruption totale)  
**Statut :** Résolu

---

## 1. Détection

**09h17** — Une alerte automatique est déclenchée lorsque 3 requêtes successives vers `POST /ingest/ocr-and-predict` retournent `503 Service Unavailable`.

Les métriques visibles sur `GET /exploitation/metrics` montrent :
```
POST /ingest/ocr-and-predict  →  error_rate: 1.00  (100 % d'erreurs)
POST /ingest/ocr              →  error_rate: 1.00
```

**Extrait du log applicatif :**
```
[ERROR] ocr_service — OCR.space timeout après 30s (tentative 1/2)
[ERROR] ocr_service — OCR.space timeout après 30s (tentative 2/2)
[WARNING] ocr_service — OCR.space indisponible, basculement vers Claude Vision
[INFO] ocr_service — Fallback Claude Vision activé
```

---

## 2. Diagnostic

**09h22** — Le responsable exploitation consulte le journal d'audit via `GET /exploitation/audit?action=client_ingest_ocr` et identifie 12 échecs depuis 09h15.

**09h25** — Vérification du statut OCR.space : page de statut externe confirme une panne de l'API européenne.

**09h28** — Vérification que le fallback Claude Vision fonctionne :
```bash
curl -X POST /ingest/ocr-and-predict \
  -H "X-API-Key: <clé>" \
  -F "file=@fiche_test.pdf"
# → 201 Created (extraction réussie via Claude Vision)
```

**Conclusion :** le mécanisme de fallback fonctionne. L'impact est limité à une légère augmentation de latence (Claude Vision : ~8s vs OCR.space : ~2s).

---

## 3. Impact

| Métrique | Valeur |
|---|---|
| Durée de la panne OCR.space | 47 minutes |
| Requêtes OCR en erreur (sans fallback) | 0 (fallback actif) |
| Requêtes OCR servies par Claude Vision | 23 |
| Clients impactés (dégradation latence) | 4 |
| Prélèvements perdus | 0 |

Le service n'a pas été interrompu grâce au fallback automatique. L'impact utilisateur s'est limité à des temps de réponse plus longs (~6s supplémentaires).

---

## 4. Résolution

**10h04** — OCR.space rétablit son service. Le système rebascule automatiquement (pas d'action manuelle requise — la logique de sélection du service OCR tente OCR.space en premier à chaque requête).

**10h10** — Vérification des métriques : `error_rate` revenu à 0 sur les routes `/ingest/ocr*`.

---

## 5. Actions correctives

### Immédiat (fait)
- ✅ Le fallback Claude Vision a fonctionné sans intervention manuelle
- ✅ Toutes les fiches déposées pendant l'incident ont été traitées correctement

### Court terme (à implémenter)
- [ ] Ajouter une alerte proactive (`error_rate > 0.5` sur routes OCR pendant > 2 min) vers Slack/email
- [ ] Exposer le statut du service OCR actif dans `GET /health` (`ocr_backend: "ocr.space" | "claude-vision"`)
- [ ] Documenter la procédure de basculement manuel dans le runbook

### Moyen terme
- [ ] Implémenter un circuit-breaker sur OCR.space (éviter d'attendre le timeout à chaque requête pendant une panne prolongée)
- [ ] Ajouter un troisième fournisseur OCR de secours (ex. Google Document AI)

---

## 6. Leçons tirées

1. **Le fallback automatique fonctionne** — aucun prélèvement n'a été perdu
2. **La détection est manuelle** — il a fallu que le responsable d'exploitation consulte les métriques ; une alerte automatique aurait réduit le temps de réaction de 5 minutes à < 1 minute
3. **La latence fallback est acceptable** — 8s est perceptible mais pas bloquant pour les cas d'usage réels (upload de fiche labo)

---

## 7. Traçabilité

- Incidents loggés dans `audit_logs` avec `action = 'client_ingest_ocr'` et `status_code = 503`
- Métriques conservées dans `request_metrics` (90 jours)
- Ce document versionné dans `docs/incident.md`

---

*Post-mortem INC-2025-001 — Waterflow 2 B3 IA 2025*
