# Gestion de projet Agile — Waterflow 2 (compétence C16)

> Méthode de conduite du projet, backlog priorisé, découpage en sprints, tableau kanban
> et rituels. Adaptée à un contexte **mono-développeur** (agilité « Kanban + itérations courtes »).

---

## 1. Méthode retenue et justification

**Kanban avec itérations d'une semaine** (hybride Scrum/Kanban), piloté via **GitHub Projects**.

| Élément Scrum classique | Adaptation solo Waterflow 2 |
|---|---|
| Sprint (2 semaines) | **Itération d'1 semaine** (cadence rapide, feedback formateur) |
| Product backlog | **Backlog des user stories** priorisées (US-01 → US-10) |
| Sprint backlog | Colonne **To Do** du board, alimentée en début d'itération |
| Daily stand-up | **Point quotidien écrit** (note d'avancement dans le journal de bord) |
| Sprint review | **Démo de fin d'itération** (à soi / au formateur) |
| Rétrospective | **Rétro écrite** en fin d'itération (ce qui a marché / à améliorer) |
| Rôles (PO, SM, Dev) | Cumulés par le développeur ; le **formateur joue le PO** (priorise, valide) |

**Outils de pilotage :** GitHub Projects (board kanban + backlog), Issues GitHub (une par US), milestones (= sprints), et le graphe d'activité Git comme **burndown** de fait.

---

## 2. Tableau Kanban (état type en cours de projet)

```
┌───────────────┬────────────────┬────────────────┬───────────────┐
│  BACKLOG      │  TO DO (sprint)│  IN PROGRESS   │  DONE         │
├───────────────┼────────────────┼────────────────┼───────────────┤
│ US-09 métriq. │ US-05 RGPD del │ US-07 dashboard│ US-01 ingest  │
│ US-10 audit   │ US-06 admin    │                │ US-02 OCR     │
│ US-08 filtres │                │                │ US-03 liste   │
│               │                │                │ US-04 RGPD get│
└───────────────┴────────────────┴────────────────┴───────────────┘
        WIP limit : max 1 carte "In Progress" à la fois (focus).
```

- **Règle WIP** (Work In Progress) : une seule carte « In Progress » → on finit avant d'en tirer une nouvelle.
- Chaque carte = 1 user story = 1 Issue GitHub, liée aux commits par `#numéro`.

---

## 3. Backlog priorisé (MoSCoW)

| Priorité | User stories | Justification |
|---|---|---|
| **Must have** | US-01, US-02, US-03, US-06 | Cœur métier : ingérer (manuel + OCR), consulter, gérer les clients/clés |
| **Should have** | US-04, US-05, US-07, US-09 | RGPD (droits d'accès/effacement), dashboards analyste & exploitation |
| **Could have** | US-08, US-10 | Filtres avancés, journal d'audit détaillé |
| **Won't have (v1)** | Rejeu de prédiction multi-versions, front de monitoring dédié | Hors périmètre du socle simplifié (options du sujet) |

---

## 4. Découpage en sprints (itérations d'1 semaine)

| Sprint | Objectif (incrément livrable) | User stories | Definition of Done |
|---|---|---|---|
| **S1 — Socle données & auth** | Base RGPD + auth clé API + admin clients | US-06 | Tables créées, clé API hachée, tests auth verts |
| **S2 — Prédiction** | Ingestion manuelle + modèle MLflow | US-01, US-03 | `/ingest/manual` renvoie une prédiction, tests verts |
| **S3 — OCR** | Pipeline OCR + fallback | US-02 | Fiche PDF → mesures → prédiction, test e2e vert |
| **S4 — Experts & RGPD** | Dashboards + droits RGPD | US-04, US-05, US-07 | Dashboard analyste OK, DELETE /me/rgpd OK |
| **S5 — Exploitation & durcissement** | Métriques, audit, monitoring, CI/CD | US-08, US-09, US-10 | CI verte, Prometheus/Grafana up, incident documenté |

**Definition of Done (transverse) :** code committé + testé (pytest vert) + relu + CI verte + documenté.

---

## 5. Rituels (adaptés solo)

- **Planification d'itération** (lundi, 15 min) : tirer les US prioritaires du backlog vers *To Do*.
- **Point quotidien** (5 min, écrit) : « fait hier / prévu aujourd'hui / blocages ».
- **Revue de fin d'itération** (vendredi) : démo de l'incrément + mise à jour du board.
- **Rétrospective** (vendredi, 10 min) : 1 chose à garder, 1 à améliorer.

---

## 6. Suivi de l'avancement (burndown)

Le **graphe d'activité Git** (commits réguliers étalés sur les sprints) et l'**historique des Issues fermées**
tiennent lieu de burndown chart : la vélocité se lit dans le nombre d'US passées en *Done* par itération.

> Preuve à montrer en soutenance : capture du **board GitHub Projects**, du **backlog priorisé**,
> et de l'**historique des commits/Issues** par sprint.

---

*Gestion Agile — Waterflow 2 · B3 IA 2025*
