"""Tests du script de préparation DVF. Lancer : python3 -m unittest discover -s tests"""
import gzip
import json
import os
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
