# Politique de protection des données — Waterflow 2

## 1. Responsable du traitement

**Waterflow 2** — plateforme d'analyse de potabilité de l'eau  
Contact DPO : dpo@waterflow.example.com

---

## 2. Classification des données traitées

| Catégorie | Données | Base légale | Finalité |
|---|---|---|---|
| Identification client | `id_client`, `denomination`, `adresse` | Contrat (art. 6.1.b RGPD) | Authentification et facturation |
| Données de mesure | Paramètres physico-chimiques (ph, turbidité, etc.) | Contrat | Service de prédiction de potabilité |
| Données techniques | IP pseudonymisée, action, route, statut HTTP | Intérêt légitime (art. 6.1.f) | Sécurité, audit, débogage |
| Métriques de performance | Route, durée, code HTTP, hint de clé | Intérêt légitime | Supervision de la plateforme |

**Données NON collectées** : aucune donnée de santé, biométrique, ou directement identifiante sur les personnes physiques. Les clients sont des collectivités (personnes morales).

---

## 3. Durées de conservation

| Type de données | Durée | Justification | Purge |
|---|---|---|---|
| Prélèvements et mesures | Durée de vie du compte actif | Traçabilité réglementaire eau potable (Code de la santé) | À la demande (`DELETE /me/rgpd`) |
| Journaux d'accès (`audit_logs`) | **12 mois glissants** | Détection d'intrusion, audit CNIL | Automatique par cron mensuel |
| Métriques de performance | **90 jours** puis agrégation anonyme | Supervision opérationnelle | Agrégation automatique |
| Hash de clé API | Durée de vie du compte | Authentification | Révoqué à la rotation ou à l'effacement |
| Données anonymisées | Illimitée | Statistiques agrégées, pas de réidentification possible | N/A |

---

## 4. Droits des personnes concernées

Les collectivités clientes peuvent exercer leurs droits via l'API :

| Droit | Endpoint | Description |
|---|---|---|
| Accès (art. 15) | `GET /me/rgpd` | Retourne toutes les données, l'historique des accès et les règles de conservation |
| Effacement (art. 17) | `DELETE /me/rgpd` avec `{"confirmer": true}` | Anonymise le compte : denomination → `[ANONYMISÉ-xxx]`, clé API révoquée |
| Portabilité (art. 20) | `GET /me/prelevements` | Tous les prélèvements au format JSON |
| Rectification (art. 16) | Via administrateur | Modification de denomination/adresse par `PUT /admin/clients/<id>` |

---

## 5. Sécurité des données (art. 32 RGPD)

### Clé API
- Générée avec `secrets.token_urlsafe(32)` — CSPRNG, 256 bits d'entropie
- Stockée uniquement sous forme de hash SHA-256 (`api_key_hash`)
- Transmise exclusivement dans le header HTTP `X-API-Key` (jamais en URL)
- Seul le hint (4 premiers caractères) est conservé pour identification
- Rotation via `POST /admin/clients/<id>/apikey` — ancienne clé invalidée immédiatement

### Tokens experts
- Configurés dans `EXPERT_TOKENS` (variable d'environnement)
- Stockés en mémoire sous forme de hash SHA-256, jamais en clair
- Transmis via `Authorization: Bearer <token>`

### IP address
- Pseudonymisation systématique : dernier octet masqué (`1.2.3.xxx`)
- Jamais stockée en clair dans les logs

### Ce qui n'est jamais loggé
- La clé API elle-même
- Le body complet des requêtes
- Les données personnelles brutes

---

## 6. Procédure de compromission de clé API

1. **Révoquer** : `POST /admin/clients/<id>/apikey` invalide l'ancienne clé et génère une nouvelle
2. **Notifier** : la nouvelle clé est retournée une seule fois dans la réponse
3. **Tracer** : l'action est automatiquement loggée dans `audit_logs`

Une clé compromise est neutralisée en moins d'une minute, sans redéploiement.

---

## 7. Sous-traitants

| Service | Finalité | Localisation |
|---|---|---|
| OCR.space (optionnel) | Extraction de texte des fiches PDF | UE |
| Anthropic Claude (fallback OCR) | Extraction de texte via vision IA | USA — clause contractuelle standard |

Les sous-traitants OCR ne traitent pas de données personnelles directes (seules des images de fiches techniques sont envoyées).

---

*Document mis à jour le 2026-06-25 — Waterflow 2 B3 IA*
