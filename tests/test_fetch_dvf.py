"""Tests du script de préparation DVF. Lancer : python3 -m unittest discover -s tests"""
import datetime as dt
import gzip
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fetch_dvf  # noqa: E402

HEADER = ("id_mutation,date_mutation,numero_disposition,nature_mutation,valeur_fonciere,adresse_numero,"
          "adresse_nom_voie,code_commune,id_parcelle,lot1_numero,type_local,surface_reelle_bati,"
          "nombre_pieces_principales,nature_culture,surface_terrain,longitude,latitude")
ROWS = [
    # Vente d'une maison + dépendance sur une parcelle (terrain répété sur les 2 lignes)
    "2023-1,2023-06-12,000001,Vente,325000,12,RUE DES LILAS,44047,44047000AB0012,,Maison,110,5,sols,812,-1.73,47.21",
    "2023-1,2023-06-12,000001,Vente,325000,12,RUE DES LILAS,44047,44047000AB0012,,Dépendance,,0,sols,812,-1.73,47.21",
    # Terrain nu sur deux parcelles
    "2022-7,2022-02-01,000001,Vente terrain à bâtir,90000,,LA GRANDE VILLE,44047,44047000ZD0004,,,,,terrains a bâtir,600,-1.74,47.22",
    "2022-7,2022-02-01,000001,Vente terrain à bâtir,90000,,LA GRANDE VILLE,44047,44047000ZD0005,,,,,terrains a bâtir,450,-1.74,47.22",
    # Autre commune : doit être ignorée
    "2023-9,2023-01-01,000001,Vente,1,,X,44109,44109000AA0001,,Maison,50,2,,100,-1.5,47.2",
]


def write_csv(path, gz):
    data = (HEADER + "\n" + "\n".join(ROWS) + "\n").encode("utf-8")
    with (gzip.open(path, "wb") if gz else open(path, "wb")) as fh:
        fh.write(data)


class AggregateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def run_script(self, gz):
        src = os.path.join(self.tmp, "dvf.csv.gz" if gz else "dvf.csv")
        out = os.path.join(self.tmp, "out.json")
        write_csv(src, gz)
        self.assertEqual(fetch_dvf.main(["44047", "--fichier", src, "--sortie", out]), 0)
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)

    def test_regroupement(self):
        data = self.run_script(gz=True)
        muts = {m["id"]: m for m in data["mutations"]}
        self.assertEqual(set(muts), {"2023-1", "2022-7"})          # autre commune exclue
        self.assertEqual(data["mutations"][0]["id"], "2023-1")      # plus récente d'abord

        maison = muts["2023-1"]
        self.assertEqual(maison["v"], 325000)
        self.assertEqual(maison["a"], "12 RUE DES LILAS")
        self.assertEqual(maison["p"], ["44047000AB0012"])
        self.assertEqual(maison["l"], [["Maison", 110, 5], ["Dépendance", None, 0]])
        self.assertEqual(maison["t"], 812)                          # terrain compté une fois

        terrain = muts["2022-7"]
        self.assertEqual(terrain["p"], ["44047000ZD0004", "44047000ZD0005"])
        self.assertEqual(terrain["l"], [])
        self.assertEqual(terrain["t"], 1050)
        self.assertEqual(data["meta"]["periode"], ["2022-02-01", "2023-06-12"])

    def test_csv_non_compresse(self):
        self.assertEqual(self.run_script(gz=False)["meta"]["mutations"], 2)

    def test_depuis_ecarte_les_ventes_anterieures(self):
        src = os.path.join(self.tmp, "dvf.csv")
        out = os.path.join(self.tmp, "out.json")
        write_csv(src, gz=False)
        self.assertEqual(fetch_dvf.main(["44047", "--fichier", src, "--sortie", out, "--depuis", "2023-01-01"]), 0)
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual([m["id"] for m in data["mutations"]], ["2023-1"])   # la vente de 2022 est écartée
        self.assertEqual(data["meta"]["periode"], ["2023-06-12", "2023-06-12"])


def sale(mid, date, valeur="100000", parcelle="44047000AB0001"):
    """Ligne DVF minimale (dict) comme produite par csv.DictReader."""
    return {"id_mutation": mid, "date_mutation": date, "nature_mutation": "Vente", "valeur_fonciere": valeur,
            "code_commune": "44047", "id_parcelle": parcelle, "type_local": "Maison",
            "surface_reelle_bati": "100", "nombre_pieces_principales": "4",
            "longitude": "-1.73", "latitude": "47.21"}


API_25 = (("2025-01-01", "2025-12-31"), "DVF 2025", "https://x/full-2025.csv.gz")
API_26 = (("2026-01-01", "2026-06-30"), "DVF 2026 (1er semestre)", "https://x/full-2026-s1.csv.gz")
API_21S2 = (("2021-07-01", "2021-12-31"), "DVF 2021 (2nd semestre)", "https://x/full-2021-s2.csv.gz")
API_22_24 = [((f"{y}-01-01", f"{y}-12-31"), f"DVF {y}", f"https://x/full-{y}.csv.gz") for y in (2022, 2023, 2024)]
API_UNIQUE = (None, "DVF juillet 2021 - juin 2026 - fichier unique", "https://x/dvf.csv.gz")


class CollectTest(unittest.TestCase):
    """Choix des sources : réseau simulé, aucune connexion."""

    def collect(self, legacy, resources, depuis="2014-01-01", from_api=None):
        """legacy : {année: lignes}, les autres années n'ont pas de fichier. Retourne (lots, manquantes, urls lues)."""
        asked_years, downloaded = [], []

        def rows_for_year(year, insee):
            asked_years.append(year)
            return legacy.get(year)

        def rows_from_resource(url, insee):
            downloaded.append(url)
            return (from_api or {}).get(url, [])

        with mock.patch.object(fetch_dvf, "rows_for_year", rows_for_year), \
             mock.patch.object(fetch_dvf, "dataset_resources", lambda: resources), \
             mock.patch.object(fetch_dvf, "rows_from_resource", rows_from_resource):
            batches, missing = fetch_dvf.collect("44047", dt.date.fromisoformat(depuis))
        return batches, missing, downloaded, asked_years

    def test_par_defaut_depuis_le_1er_janvier_2014(self):
        _, _, _, asked = self.collect({}, [])
        self.assertEqual(asked, list(range(dt.date.today().year, 2013, -1)))
        self.assertEqual(asked[-1], 2014)                                    # 2014 demandée, pas 2013

    def test_depuis_choisit_la_premiere_annee_demandee(self):
        self.assertEqual(self.collect({}, [], depuis="2020-06-01")[3][-1], 2020)

    def test_api_prioritaire_ancien_chemin_pour_le_reste(self):
        legacy = {y: [sale(f"{y}-5", f"{y}-03-01")] for y in range(2021, 2026)}
        resources = [API_21S2, *API_22_24, API_25, API_26]
        _, missing, downloaded, asked = self.collect(legacy, resources)
        self.assertEqual(sorted(downloaded), sorted(r[2] for r in resources))
        # Fichiers par commune : seulement 2026 (2nd semestre), 2021 (1er semestre) et avant. 2022-2025 : inutiles.
        self.assertEqual(asked, [2026, 2021, *range(2020, 2013, -1)])
        self.assertEqual(missing, list(range(2020, 2013, -1)))                # 2014-2020 : nulle part

    def test_ventes_deja_lues_dans_l_api_ne_sont_pas_reprises(self):
        """Janvier-juin 2021 vient de l'ancien chemin ; son second semestre est déjà dans l'API."""
        legacy = {2021: [sale("2021-1", "2021-03-01", "100000", "AB1"), sale("2021-2", "2021-09-01", "200000", "AB2")]}
        api = {API_21S2[2]: [sale("x", "2021-09-01", "200000", "AB9")]}   # même vente, parcelle mise à jour
        batches, _, _, _ = self.collect(legacy, [API_21S2], from_api=api)
        dates = sorted(r["date_mutation"] for b in batches for r in b)
        self.assertEqual(dates, ["2021-03-01", "2021-09-01"])             # une seule vente de septembre : celle de l'API
        self.assertEqual([r["id_parcelle"] for b in batches for r in b if r["date_mutation"] == "2021-09-01"], ["AB9"])

    def test_ancien_chemin_reprend_si_une_ressource_api_echoue(self):
        legacy = {2025: [sale("2025-5", "2025-03-01")]}
        batches, missing, _, asked = self.collect(legacy, [API_25], from_api={API_25[2]: None})   # téléchargement raté
        self.assertIn(2025, asked)                                        # l'année n'est pas considérée couverte
        self.assertEqual(batches, [legacy[2025]])
        self.assertNotIn(2025, missing)

    def test_api_seule_quand_l_ancien_chemin_a_disparu(self):
        api = {API_21S2[2]: [sale("2021-1", "2021-09-01")], API_25[2]: [sale("2025-1", "2025-02-01")],
               API_26[2]: [sale("2026-1", "2026-02-01")]}
        _, missing, downloaded, _ = self.collect({}, [API_21S2, API_25, API_26], from_api=api)
        self.assertEqual(sorted(downloaded), sorted([API_21S2[2], API_25[2], API_26[2]]))
        self.assertNotIn(2025, missing)
        self.assertNotIn(2026, missing)
        self.assertIn(2024, missing)                                         # pas de ressource 2024 dans ce scénario

    def test_ressources_anterieures_a_depuis_ignorees(self):
        _, _, downloaded, _ = self.collect({}, [API_21S2, API_25, API_26], depuis="2025-07-01")
        self.assertEqual(sorted(downloaded), sorted([API_25[2], API_26[2]]))  # 2021 trop ancienne

    def test_fichier_unique_en_dernier_recours_seulement(self):
        unique = {API_UNIQUE[2]: [sale("u-1", "2023-04-01")]}
        _, _, downloaded, _ = self.collect({}, [API_25, API_UNIQUE], from_api=unique)
        self.assertIn(API_UNIQUE[2], downloaded)                             # 2025 vide → repli sur le fichier unique
        legacy = {2025: [sale("2025-5", "2025-03-01")]}
        _, _, downloaded, _ = self.collect(legacy, [API_UNIQUE], from_api=unique)
        self.assertEqual(downloaded, [])                                     # des données existent : pas de repli

    def test_ids_identiques_dans_deux_sources_ne_fusionnent_pas(self):
        """Les id_mutation sont des compteurs propres à chaque livraison : deux ventes distinctes
        portant le même id dans deux fichiers doivent rester deux ventes."""
        batches = [[sale("2025-1", "2025-03-01", "100000", "44047000AB0001")],
                   [sale("2025-1", "2026-02-01", "250000", "44047000ZD0009")]]
        with mock.patch.object(fetch_dvf, "collect", lambda insee, depuis: (batches, [])):
            out = os.path.join(tempfile.mkdtemp(), "out.json")
            self.assertEqual(fetch_dvf.main(["44047", "--sortie", out]), 0)
        with open(out, encoding="utf-8") as fh:
            muts = json.load(fh)["mutations"]
        self.assertEqual([(m["d"], m["v"]) for m in muts], [("2026-02-01", 250000), ("2025-03-01", 100000)])

    def test_nommage_des_ressources_de_l_api(self):
        meta = {"resources": [
            {"title": "DVF 2021 (2nd semestre)", "url": "https://s/2026/full-2021-s2.csv.gz"},
            {"title": "DVF 2022", "url": "https://s/2026/full-2022.csv.gz"},
            {"title": "DVF 2026 (1er semestre)", "url": "https://s/2026/full-2026-s1.csv.gz"},
            {"title": "DVF juillet 2021 - juin 2026 - fichier unique", "url": "https://s/2026/dvf.csv.gz"},
            {"title": "Documentation", "url": "https://s/notice.pdf"},
        ]}
        with mock.patch.object(fetch_dvf, "open_url", lambda url: io.BytesIO(json.dumps(meta).encode())):
            res = fetch_dvf.dataset_resources()
        self.assertEqual([r[0] for r in res], [("2021-07-01", "2021-12-31"), ("2022-01-01", "2022-12-31"),
                                               ("2026-01-01", "2026-06-30"), None])   # le PDF est ignoré

    def test_span(self):
        self.assertEqual(fetch_dvf.span([2020, 2019, 2017, 2014, 2015]), "2014–2015, 2017, 2019–2020")


if __name__ == "__main__":
    unittest.main()
