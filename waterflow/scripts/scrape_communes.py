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

# Communes réelles (code INSEE, nom, adresse mairie). Un code sans données
# disponibles sur Hub'Eau est automatiquement ignoré (voir main()).
COMMUNES = [
    # ── PACA / Sud-Est ──
    ("06088", "Nice",               "Place Pierre Gautier, 06300 Nice"),
    ("13055", "Marseille",          "Quai du Port, 13002 Marseille"),
    ("13001", "Aix-en-Provence",    "Place de l'Hôtel de Ville, 13100 Aix-en-Provence"),
    ("83137", "Toulon",             "Avenue de la République, 83000 Toulon"),
    ("84007", "Avignon",            "Place de l'Horloge, 84000 Avignon"),
    ("06029", "Cannes",             "Place Bernard Cornut-Gentille, 06400 Cannes"),
    ("83061", "Fréjus",             "Place Formigé, 83600 Fréjus"),
    ("13103", "Salon-de-Provence",  "Place de l'Hôtel de Ville, 13300 Salon-de-Provence"),
    ("13004", "Arles",              "Place de la République, 13200 Arles"),
    ("04070", "Digne-les-Bains",    "1 Boulevard Gassendi, 04000 Digne-les-Bains"),
    ("83069", "Hyères",             "Avenue Joseph Clotis, 83400 Hyères"),
    ("06004", "Antibes",            "Place de l'Hôtel de Ville, 06600 Antibes"),
    # ── Grandes métropoles ──
    ("75056", "Paris",              "Place de l'Hôtel de Ville, 75004 Paris"),
    ("69123", "Lyon",               "Place de la Comédie, 69001 Lyon"),
    ("31555", "Toulouse",           "Place du Capitole, 31000 Toulouse"),
    ("44109", "Nantes",             "2 Rue de l'Hôtel de Ville, 44000 Nantes"),
    ("34172", "Montpellier",        "1 Place Georges Frêche, 34000 Montpellier"),
    ("67482", "Strasbourg",         "9 Rue Brûlée, 67000 Strasbourg"),
    ("33063", "Bordeaux",           "Place Pey Berland, 33000 Bordeaux"),
    ("59350", "Lille",              "Place Augustin Laurent, 59000 Lille"),
    ("35238", "Rennes",             "Place de la Mairie, 35000 Rennes"),
    ("51454", "Reims",              "9 Place de l'Hôtel de Ville, 51100 Reims"),
    ("42218", "Saint-Étienne",      "Place de l'Hôtel de Ville, 42000 Saint-Étienne"),
    ("38185", "Grenoble",           "11 Boulevard Jean Pain, 38000 Grenoble"),
    ("21231", "Dijon",              "Place de la Libération, 21000 Dijon"),
    ("49007", "Angers",             "Boulevard de la Résistance, 49000 Angers"),
    ("30189", "Nîmes",              "Place de l'Hôtel de Ville, 30000 Nîmes"),
    ("63113", "Clermont-Ferrand",   "10 Rue Philippe Marcombes, 63000 Clermont-Ferrand"),
    ("72181", "Le Mans",            "Place Saint-Pierre, 72000 Le Mans"),
    ("29019", "Brest",              "2 Rue Frézier, 29200 Brest"),
    ("37261", "Tours",              "1-3 Rue des Minimes, 37000 Tours"),
    ("80021", "Amiens",             "Place de l'Hôtel de Ville, 80000 Amiens"),
    ("87085", "Limoges",            "Place Léon Betoulle, 87000 Limoges"),
    ("66136", "Perpignan",          "Place de la Loge, 66000 Perpignan"),
    ("25056", "Besançon",           "2 Rue Mégevand, 25000 Besançon"),
    ("57463", "Metz",               "1 Place d'Armes, 57000 Metz"),
    ("45234", "Orléans",            "Place de l'Étape, 45000 Orléans"),
    ("76540", "Rouen",              "Place du Général de Gaulle, 76000 Rouen"),
    ("68224", "Mulhouse",           "2 Rue Pierre et Marie Curie, 68100 Mulhouse"),
    ("14118", "Caen",               "Esplanade Jean-Marie Louvel, 14000 Caen"),
    ("54395", "Nancy",              "Place Stanislas, 54000 Nancy"),
    ("86194", "Poitiers",           "15 Place du Maréchal Leclerc, 86000 Poitiers"),
    ("64445", "Pau",                "Place Royale, 64000 Pau"),
    ("68066", "Colmar",             "1 Rue de la Mairie, 68000 Colmar"),
    ("29232", "Quimper",            "44 Place Saint-Corentin, 29000 Quimper"),
    ("56121", "Lorient",            "Place Yves Le Coz, 56100 Lorient"),
    ("73065", "Chambéry",           "Place de l'Hôtel de Ville, 73000 Chambéry"),
    ("26362", "Valence",            "1 Place de la Liberté, 26000 Valence"),
    ("64102", "Bayonne",            "1 Avenue du Maréchal Leclerc, 64100 Bayonne"),
    ("87154", "Saint-Junien",       "Place Auguste Roche, 87200 Saint-Junien"),
    ("17300", "La Rochelle",        "Place de l'Hôtel de Ville, 17000 La Rochelle"),
    # ── Île-de-France / grande couronne ──
    ("92050", "Nanterre",           "Hôtel de Ville, 92000 Nanterre"),
    ("94028", "Créteil",            "Hôtel de Ville, 94000 Créteil"),
    ("93048", "Montreuil",          "Hôtel de Ville, 93100 Montreuil"),
    ("95018", "Argenteuil",         "Hôtel de Ville, 95100 Argenteuil"),
    ("92012", "Boulogne-Billancourt","Hôtel de Ville, 92100 Boulogne-Billancourt"),
    ("78646", "Versailles",         "Hôtel de Ville, 78000 Versailles"),
    ("77288", "Melun",              "Hôtel de Ville, 77000 Melun"),
    ("91228", "Évry-Courcouronnes", "Hôtel de Ville, 91000 Évry-Courcouronnes"),
    # ── Hauts-de-France / Grand Est / Normandie ──
    ("59183", "Dunkerque",          "Hôtel de Ville, 59140 Dunkerque"),
    ("59606", "Valenciennes",       "Hôtel de Ville, 59300 Valenciennes"),
    ("62193", "Calais",             "Hôtel de Ville, 62100 Calais"),
    ("62041", "Arras",              "Hôtel de Ville, 62000 Arras"),
    ("10387", "Troyes",             "Hôtel de Ville, 10000 Troyes"),
    ("88160", "Épinal",             "Hôtel de Ville, 88000 Épinal"),
    ("27229", "Évreux",             "Hôtel de Ville, 27000 Évreux"),
    ("50129", "Cherbourg-en-Cotentin","Hôtel de Ville, 50100 Cherbourg-en-Cotentin"),
    ("76217", "Dieppe",             "Hôtel de Ville, 76200 Dieppe"),
    # ── Ouest / Bretagne / Pays de la Loire ──
    ("44184", "Saint-Nazaire",      "Hôtel de Ville, 44600 Saint-Nazaire"),
    ("49099", "Cholet",             "Hôtel de Ville, 49300 Cholet"),
    ("85191", "La Roche-sur-Yon",   "Hôtel de Ville, 85000 La Roche-sur-Yon"),
    ("53130", "Laval",              "Hôtel de Ville, 53000 Laval"),
    ("56260", "Vannes",             "Hôtel de Ville, 56000 Vannes"),
    ("22278", "Saint-Brieuc",       "Hôtel de Ville, 22000 Saint-Brieuc"),
    ("35288", "Saint-Malo",         "Hôtel de Ville, 35400 Saint-Malo"),
    # ── Centre / Bourgogne-Franche-Comté ──
    ("41018", "Blois",              "Hôtel de Ville, 41000 Blois"),
    ("18033", "Bourges",            "Hôtel de Ville, 18000 Bourges"),
    ("36044", "Châteauroux",        "Hôtel de Ville, 36000 Châteauroux"),
    ("28085", "Chartres",           "Hôtel de Ville, 28000 Chartres"),
    ("71076", "Chalon-sur-Saône",   "Hôtel de Ville, 71100 Chalon-sur-Saône"),
    ("90010", "Belfort",            "Hôtel de Ville, 90000 Belfort"),
    ("89024", "Auxerre",            "Hôtel de Ville, 89000 Auxerre"),
    # ── Nouvelle-Aquitaine / Occitanie ──
    ("79191", "Niort",              "Hôtel de Ville, 79000 Niort"),
    ("16015", "Angoulême",          "Hôtel de Ville, 16000 Angoulême"),
    ("24322", "Périgueux",          "Hôtel de Ville, 24000 Périgueux"),
    ("47001", "Agen",               "Hôtel de Ville, 47000 Agen"),
    ("81004", "Albi",               "Hôtel de Ville, 81000 Albi"),
    ("65440", "Tarbes",             "Hôtel de Ville, 65000 Tarbes"),
    ("34032", "Béziers",            "Hôtel de Ville, 34500 Béziers"),
    ("11262", "Narbonne",           "Hôtel de Ville, 11100 Narbonne"),
    ("11069", "Carcassonne",        "Hôtel de Ville, 11000 Carcassonne"),
    ("34301", "Sète",               "Hôtel de Ville, 34200 Sète"),
    # ── Auvergne-Rhône-Alpes / Sud-Est ──
    ("69266", "Villeurbanne",       "Hôtel de Ville, 69100 Villeurbanne"),
    ("42187", "Roanne",             "Hôtel de Ville, 42300 Roanne"),
    ("01053", "Bourg-en-Bresse",    "Hôtel de Ville, 01000 Bourg-en-Bresse"),
    ("74012", "Annemasse",          "Hôtel de Ville, 74100 Annemasse"),
    ("84087", "Orange",             "Hôtel de Ville, 84100 Orange"),
    ("13005", "Aubagne",            "Hôtel de Ville, 13400 Aubagne"),
    ("13056", "Martigues",          "Hôtel de Ville, 13500 Martigues"),
    ("83126", "La Seyne-sur-Mer",   "Hôtel de Ville, 83500 La Seyne-sur-Mer"),
    ("04112", "Manosque",           "Hôtel de Ville, 04100 Manosque"),
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
        dispo = [f for f in FEATURES if v.get(f)]
        if not dispo:
            # Aucune donnée réelle disponible (code INSEE sans mesures) -> on ignore
            print(f"  - {nom:20s} : aucune donnee disponible sur Hub'Eau, ignoree")
            continue
        row = {"code_insee": code, "commune": nom, "date_analyse": res["date"],
               "conclusion_ars": res["conclusion"], "potable_ars": potable}
        for feat in FEATURES:
            row[feat] = v.get(feat, (None,))[0]
        rows.append((row, adresse))
        etat = "conforme" if potable == 1 else ("non conforme" if potable == 0 else "n/c")
        print(f"  + {nom:20s} : {len(dispo)} parametres reels | ARS: {etat}")

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
