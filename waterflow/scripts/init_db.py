"""
scripts/init_db.py — Initialise la base de données et injecte des données de test.

Usage :
    python scripts/init_db.py            # init + seed (défaut)
    python scripts/init_db.py --init-only  # tables seulement, sans données
    python scripts/init_db.py --reset    # supprime et recrée tout (DANGEREUX en prod)

Clients créés :
    CLIENT-001 / Mairie de Marseille        → clé affichée en sortie
    CLIENT-002 / Syndicat des Eaux du Var   → clé affichée en sortie
    CLIENT-003 / Commune de Nice (inactif)  → clé affichée en sortie
"""

import sys
import os
import secrets
import argparse
from datetime import datetime, timezone, timedelta

# Ajoute la racine du projet au chemin Python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import (
    init_db, SessionLocal, Base, engine,
    Client, Prelevement, Mesure, Prediction, IngestionSource
)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def reset_db():
    print("⚠️  Suppression de toutes les tables...")
    Base.metadata.drop_all(bind=engine)
    print("✓  Tables supprimées.")


def create_tables():
    init_db()
    print("✓  Tables créées (ou déjà existantes).")


def seed(db):
    # ── Clients ────────────────────────────────────────────────────────────────

    clients_data = [
        {
            "id_client":    "CLIENT-001",
            "denomination": "Mairie de Marseille",
            "adresse":      "2 Quai du Port, 13002 Marseille",
            "actif":        True,
        },
        {
            "id_client":    "CLIENT-002",
            "denomination": "Syndicat des Eaux du Var",
            "adresse":      "45 Avenue de la République, 83000 Toulon",
            "actif":        True,
        },
        {
            "id_client":    "CLIENT-003",
            "denomination": "Commune de Nice",
            "adresse":      "5 Rue de l'Hôtel de Ville, 06000 Nice",
            "actif":        False,
        },
    ]

    created_clients = []
    print("\n── Clients ─────────────────────────────────────────────────────────")
    for data in clients_data:
        existing = db.query(Client).filter_by(id_client=data["id_client"]).first()
        if existing:
            print(f"  ⚠  {data['id_client']} déjà présent — ignoré.")
            created_clients.append((existing, None))
            continue

        client = Client(
            id_client=data["id_client"],
            denomination=data["denomination"],
            adresse=data["adresse"],
            actif=data["actif"],
            rgpd_consent=True,
            rgpd_consent_at=utcnow(),
        )
        raw_key = secrets.token_urlsafe(32)
        client.set_api_key(raw_key)
        db.add(client)
        db.flush()
        created_clients.append((client, raw_key))
        status = "actif" if data["actif"] else "inactif"
        print(f"  ✓  {data['id_client']} ({status})")
        print(f"     Clé API : {raw_key}")

    db.commit()

    # ── Prélèvements + Mesures ─────────────────────────────────────────────────

    samples = [
        # CLIENT-001 — 3 prélèvements
        {
            "client_idx": 0,
            "date": utcnow() - timedelta(days=30),
            "lieu": "Station de pompage Nord",
            "source": IngestionSource.MANUAL,
            "mesures": {
                "ph": 7.2, "hardness": 182.5, "solids": 18630.0,
                "chloramines": 8.1, "sulfate": 310.0, "conductivity": 415.0,
                "organic_carbon": 14.2, "trihalomethanes": 66.4, "turbidity": 3.8,
            },
        },
        {
            "client_idx": 0,
            "date": utcnow() - timedelta(days=15),
            "lieu": "Réservoir Sud",
            "source": IngestionSource.OCR,
            "mesures": {
                "ph": 6.8, "hardness": 204.3, "solids": 22450.0,
                "chloramines": 7.5, "sulfate": 285.0, "conductivity": 390.0,
                "organic_carbon": 11.8, "trihalomethanes": 75.2, "turbidity": 4.1,
            },
        },
        {
            "client_idx": 0,
            "date": utcnow() - timedelta(days=2),
            "lieu": "Puits privé Est",
            "source": IngestionSource.MANUAL,
            "mesures": {
                "ph": 8.1, "hardness": 155.0, "solids": 14200.0,
                "chloramines": 9.2, "sulfate": 330.0, "conductivity": 445.0,
                "organic_carbon": 16.0, "trihalomethanes": 58.0, "turbidity": 2.9,
            },
        },
        # CLIENT-002 — 2 prélèvements
        {
            "client_idx": 1,
            "date": utcnow() - timedelta(days=20),
            "lieu": "Source de la Foux",
            "source": IngestionSource.MANUAL,
            "mesures": {
                "ph": 7.5, "hardness": 196.0, "solids": 19800.0,
                "chloramines": 6.8, "sulfate": 270.0, "conductivity": 402.0,
                "organic_carbon": 13.5, "trihalomethanes": 70.1, "turbidity": 3.5,
            },
        },
        {
            "client_idx": 1,
            "date": utcnow() - timedelta(days=5),
            "lieu": "Forage municipal",
            "source": IngestionSource.OCR,
            "mesures": {
                "ph": 5.1, "hardness": 320.0, "solids": 45000.0,
                "chloramines": 12.5, "sulfate": 480.0, "conductivity": 680.0,
                "organic_carbon": 28.0, "trihalomethanes": 120.0, "turbidity": 9.2,
            },
        },
    ]

    print("\n── Prélèvements ─────────────────────────────────────────────────────")
    for s in samples:
        client_obj, _ = created_clients[s["client_idx"]]
        if client_obj is None:
            continue

        existing = db.query(Prelevement).filter_by(
            client_id=client_obj.id,
            date_prelevement=s["date"],
            lieu=s["lieu"],
        ).first()
        if existing:
            print(f"  ⚠  Prélèvement '{s['lieu']}' déjà présent — ignoré.")
            continue

        prev = Prelevement(
            client_id=client_obj.id,
            date_prelevement=s["date"],
            lieu=s["lieu"],
            source=s["source"],
        )
        db.add(prev)
        db.flush()

        m = s["mesures"]
        mesure = Mesure(
            prelevement_id=prev.id,
            ph=m["ph"], hardness=m["hardness"], solids=m["solids"],
            chloramines=m["chloramines"], sulfate=m["sulfate"],
            conductivity=m["conductivity"], organic_carbon=m["organic_carbon"],
            trihalomethanes=m["trihalomethanes"], turbidity=m["turbidity"],
        )
        db.add(mesure)
        db.flush()

        # Prédiction simulée (sans charger le modèle ML)
        is_potable = 1 if m["ph"] > 6.5 and m["turbidity"] < 5.0 and m["chloramines"] < 10.0 else 0
        pred = Prediction(
            prelevement_id=prev.id,
            potable=is_potable,
            probability=0.78 if is_potable else 0.22,
            model_version="seed/heuristic",
        )
        db.add(pred)

        label = "Potable" if is_potable else "Non potable"
        print(f"  ✓  {client_obj.id_client} — {s['lieu']} ({s['source'].value}) → {label}")

    db.commit()


def main():
    parser = argparse.ArgumentParser(description="Initialise la base Waterflow 2")
    parser.add_argument("--init-only", action="store_true",
                        help="Crée les tables sans insérer de données")
    parser.add_argument("--reset", action="store_true",
                        help="Supprime et recrée toutes les tables (DANGEREUX)")
    args = parser.parse_args()

    print("═" * 60)
    print("  Waterflow 2 — Initialisation base de données")
    print("═" * 60)

    if args.reset:
        confirm = input("⚠️  Supprimer toutes les données ? (oui/non) : ").strip().lower()
        if confirm != "oui":
            print("Annulé.")
            sys.exit(0)
        reset_db()

    create_tables()

    if not args.init_only:
        db = SessionLocal()
        try:
            seed(db)
        finally:
            db.close()

    print("\n═" * 60)
    print("  Terminé.")
    print("═" * 60)


if __name__ == "__main__":
    main()
