"""
scripts/scrape_communes.py — Extraction de VRAIES données de qualité de l'eau
potable de communes françaises, depuis le portail national officiel Hub'Eau
(Ministère de la Santé / ARS — https://hubeau.eaufrance.fr).

Compétence E1/C1 : automatiser l'extraction depuis une source web réelle.
On ne conserve QUE les paramètres réellement mesurés (pas de valeur inventée) ;
les champs absents d'une commune restent vides.

Sortie : data/communes_eau.csv
Option : --load-db  -> insère aussi les communes (clients) et leurs analyses
                       (prélèvements + mesures réelles + conclusion ARS) dans la base.

Usage :
    python scripts/scrape_communes.py
    python scripts/scrape_communes.py --load-db
"""

import os
import sys
import csv
import argparse
import unicodedata
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HUBEAU = "https://hubeau.eaufrance.fr/api/v1/qualite_eau_potable/resultats_dis"

# Communes réelles (code INSEE, nom, adresse mairie)
COMMUNES = [
    ("06088", "Nice",               "Place Pierre Gautier, 06300 Nice"),
    ("13055", "Marseille",          "Quai du Port, 13002 Marseille"),
    ("13001", "Aix-en-Provence",    "Place de l'Hôtel de Ville, 13100 Aix-en-Provence"),
    ("83137", "Toulon",             "Avenue de la République, 83000 Toulon"),
    ("84007", "Avignon",            "Place de l'Horloge, 84000 Avignon"),
    ("06029", "Cannes",             "Place Bernard Cornut-Gentille, 06400 Cannes"),
    ("05061", "Gap",                "3 Rue Colonel Roux, 05000 Gap"),
    ("83061", "Fréjus",             "Place Formigé, 83600 Fréjus"),
    ("13103", "Salon-de-Provence",  "Place de l'Hôtel de Ville, 13300 Salon-de-Provence"),
    ("13004", "Arles",              "Place de la République, 13200 Arles"),
    ("04070", "Digne-les-Bains",    "1 Boulevard Gassendi, 04000 Digne-les-Bains"),
    ("83069", "Hyères",             "Avenue Joseph Clotis, 83400 Hyères"),
]

# Mapping : feature du modèle -> motif(s) recherché(s) dans le libellé (normalisé) du paramètre
FEATURE_PATTERNS = {
    "ph":              [lambda x: x == "ph"],
    "Conductivity":    [lambda x: "conductivit" in x],
    "Turbidity":       [lambda x: "turbidit" in x],
    "Sulfate":         [lambda x: "sulfate" in x],
    "Hardness":        [lambda x: "duret" in x or "hydrotim" in x],
    "Organic_carbon":  [lambda x: "carbone organique" in x],
    "Trihalomethanes": [lambda x: "trihalomethane" in x, lambda x: "chloroforme" in x],
    "Chloramines":     [lambda x: "chloramine" in x, lambda x: "chlore total" in x],
    "Solids":          [lambda x: "residu sec" in x or "matieres dissoutes" in x],
}
FEATURES = list(FEATURE_PATTERNS.keys())


def _norm(s: str) -> str:
    """minuscule + sans accents, pour comparer les libellés."""
    s = (s or "").lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def fetch_commune(code_insee: str) -> dict:
    """Récupère les dernières analyses réelles d'une commune et en extrait
    la valeur la plus récente pour chaque paramètre mappé."""
    r = requests.get(HUBEAU, params={
        "code_commune": code_insee, "size": 500, "sort": "desc",
    }, timeout=45)
    r.raise_for_status()
    data = r.json().get("data", [])

    values = {}          # feature -> (valeur, date)
    conclusion = None
    date_analyse = None
    for row in data:
        label = _norm(row.get("libelle_parametre"))
        val = row.get("resultat_numerique")
        date = row.get("date_prelevement")
        if conclusion is None and row.get("conclusion_conformite_prelevement"):
            conclusion = row["conclusion_conformite_prelevement"]
            date_analyse = date
        if val is None:
            continue
        for feat, patterns in FEATURE_PATTERNS.items():
            if feat in values:
                continue  # déjà la valeur la plus récente (données triées desc)
            for match in patterns:
                if match(label):
                    values[feat] = (val, date)
                    break
    return {"values": values, "conclusion": conclusion, "date": date_analyse,
            "n_analyses": len(data)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--load-db", action="store_true",
                    help="insère aussi les communes et analyses réelles dans la base")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(root, "data")
    os.makedirs(out_dir, exist_ok=True)
    out_csv = os.path.join(out_dir, "communes_eau.csv")

    rows = []
    print("Extraction Hub'Eau (donnees reelles) :")
    for code, nom, adresse in COMMUNES:
        try:
            res = fetch_commune(code)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {nom} ({code}) : echec ({exc})")
            continue
        v = res["values"]
        potable = None
        if res["conclusion"]:
            c = _norm(res["conclusion"])
            potable = 1 if ("conforme" in c and "non conforme" not in c) else 0
        row = {"code_insee": code, "commune": nom, "date_analyse": res["date"],
               "conclusion_ars": res["conclusion"], "potable_ars": potable}
        for feat in FEATURES:
            row[feat] = v.get(feat, (None,))[0]
        rows.append((row, adresse))
        dispo = [f for f in FEATURES if v.get(f)]
        etat = "conforme" if potable == 1 else ("non conforme" if potable == 0 else "n/c")
        print(f"  + {nom:20s} : {len(dispo)} parametres reels {dispo} | ARS: {etat}")

    cols = ["code_insee", "commune", "date_analyse", "conclusion_ars", "potable_ars"] + FEATURES
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for row, _ in rows:
            writer.writerow(row)
    print(f"\n[OK] {len(rows)} communes ecrites dans {out_csv}")

    if args.load_db:
        load_into_db(rows)


def load_into_db(rows):
    import secrets
    from datetime import timezone
    from db import (init_db, SessionLocal, Client, Prelevement, Mesure,
                    Prediction, IngestionSource)

    def utcnow():
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def parse_dt(s):
        if not s:
            return utcnow()
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return utcnow()

    init_db()
    db = SessionLocal()
    n_clients = 0
    n_prev = 0
    for row, adresse in rows:
        id_client = f"INSEE-{row['code_insee']}"
        if db.query(Client).filter_by(id_client=id_client).first():
            continue
        client = Client(id_client=id_client, denomination=f"Commune de {row['commune']}",
                        adresse=adresse, actif=True, created_by="scrape_communes",
                        rgpd_consent=True, rgpd_consent_at=utcnow())
        client.set_api_key(secrets.token_urlsafe(32))
        db.add(client)
        db.flush()
        n_clients += 1

        dt = parse_dt(row["date_analyse"])
        prev = Prelevement(client_id=client.id, date_prelevement=dt, created_at=dt,
                           lieu=f"Reseau public - {row['commune']}",
                           source=IngestionSource.MANUAL,
                           observations=row["conclusion_ars"], ocr_warnings="[]")
        db.add(prev)
        db.flush()
        n_prev += 1

        db.add(Mesure(
            prelevement_id=prev.id,
            ph=row["ph"], hardness=row["Hardness"], solids=row["Solids"],
            chloramines=row["Chloramines"], sulfate=row["Sulfate"],
            conductivity=row["Conductivity"], organic_carbon=row["Organic_carbon"],
            trihalomethanes=row["Trihalomethanes"], turbidity=row["Turbidity"],
        ))
        if row["potable_ars"] is not None:
            # Conclusion officielle binaire (pas une probabilité de modèle) :
            # 1.0 = conforme, 0.0 = non conforme. Source explicitée dans model_version.
            db.add(Prediction(prelevement_id=prev.id, potable=row["potable_ars"],
                              probability=float(row["potable_ars"]),
                              model_version="Conclusion sanitaire ARS (donnee reelle)",
                              created_at=dt))
        db.commit()
    db.close()
    print(f"[OK] Base : {n_clients} communes (clients) et {n_prev} analyses reelles inserees.")


if __name__ == "__main__":
    main()
