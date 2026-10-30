"""Tests du découpage des DVF historiques par commune. Lancer : python3 -m unittest discover -s tests"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import split_dvf_historique as split  # noqa: E402

HEADER = "Reference document|Date mutation|Valeur fonciere|Code departement|Code commune|Commune"
ROWS_2016 = [
    "|08/01/2016|40000,00|44|047|COUËRON",
    "|11/01/2016|1677,00|01|430|VARAMBON",  # autre département : ignoré
    "|15/03/2016|250000,00|44|109|NANTES",
    "|20/03/2016|90000,00|44|047|COUËRON",
]
ROWS_2017 = [
    "|02/02/2017|310000,00|44|047|COUËRON",
    "|03/02/2017|120000,00|49|007|ANGERS",  # autre département : ignoré
    "|04/02/2017|5000,00|44|003|ANCENIS-SAINT-GEREON",
]


class SplitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "sortie")

    def write_source(self, name, rows, header=HEADER):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(("\n".join([header] + rows) + "\n").encode("utf-8"))
        return path

    def run_split(self, paths, departement="44"):
        with contextlib.redirect_stdout(io.StringIO()):
            return split.split(paths, departement, self.out)

    def lines(self, insee):
        with open(os.path.join(self.out, f"{insee}.txt"), "rb") as fh:
            return fh.read().decode("utf-8").splitlines()

    def test_un_fichier_par_commune_du_departement(self):
        stats = self.run_split([self.write_source("2016.txt", ROWS_2016)])
        self.assertEqual(sorted(os.listdir(self.out)), ["44047.txt", "44109.txt"])
        self.assertEqual({k: v["lignes"] for k, v in stats.items()}, {"44047": 2, "44109": 1})
        self.assertEqual(self.lines("44109"), [HEADER, ROWS_2016[2]])

    def test_periode_des_ventes_par_commune(self):
        stats = self.run_split([self.write_source("2016.txt", ROWS_2016), self.write_source("2017.txt", ROWS_2017)])
        self.assertEqual((stats["44047"]["du"], stats["44047"]["au"]), ("2016-01-08", "2017-02-02"))
        self.assertEqual((stats["44109"]["du"], stats["44109"]["au"]), ("2016-03-15", "2016-03-15"))

    def test_date_illisible_refusee(self):
        with self.assertRaises(SystemExit):
            self.run_split([self.write_source("x.txt", ["|2016-01-08|1,00|44|047|X"])])

    def test_lignes_recopiees_sans_transformation_dans_l_ordre_des_fichiers(self):
        paths = [self.write_source("2016.txt", ROWS_2016), self.write_source("2017.txt", ROWS_2017)]
        self.run_split(paths)
        self.assertEqual(self.lines("44047"), [HEADER, ROWS_2016[0], ROWS_2016[3], ROWS_2017[0]])
        self.assertEqual(self.lines("44003"), [HEADER, ROWS_2017[2]])
        self.assertFalse(any("VARAMBON" in l or "ANGERS" in l for n in os.listdir(self.out)
                             for l in self.lines(n[:-4])))

    def test_relancer_remplace_les_fichiers_sans_doublon(self):
        paths = [self.write_source("2016.txt", ROWS_2016)]
        self.run_split(paths)
        self.run_split(paths)
        self.assertEqual(self.lines("44047"), [HEADER, ROWS_2016[0], ROWS_2016[3]])

    def test_entete_different_refuse(self):
        paths = [self.write_source("2016.txt", ROWS_2016),
                 self.write_source("2017.txt", ROWS_2017, header=HEADER + "|Colonne en plus")]
        with self.assertRaises(SystemExit):
            self.run_split(paths)

    def test_colonne_renommee_acceptee_entete_du_premier_fichier_conserve(self):
        renomme = HEADER.replace("Reference document", "Code service CH")
        paths = [self.write_source("2016.txt", ROWS_2016, header=renomme),
                 self.write_source("2017.txt", ROWS_2017, header=HEADER.replace("Reference document",
                                                                              "Identifiant de document"))]
        self.run_split(paths)
        self.assertEqual(self.lines("44047"), [renomme, ROWS_2016[0], ROWS_2016[3], ROWS_2017[0]])

    def test_colonne_absente_refusee(self):
        with self.assertRaises(SystemExit):
            self.run_split([self.write_source("x.txt", ["a|b|c"], header="a|b|c")])

    def test_departement_sans_ligne(self):
        self.assertEqual(len(self.run_split([self.write_source("2016.txt", ROWS_2016)], "85")), 0)

    def run_main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return split.main([*args, "--sortie", self.out])

    def zip_content(self, nom):
        with zipfile.ZipFile(os.path.join(self.out, nom)) as zf:
            return {n: zf.read(n).decode("utf-8") for n in zf.namelist()}, json.loads(zf.read("meta.json"))

    def test_zips_du_departement_et_de_la_commune(self):
        paths = [self.write_source("2016.txt", ROWS_2016), self.write_source("2017.txt", ROWS_2017)]
        self.assertEqual(self.run_main(*paths, "--commune", "44047"), 0)
        self.assertEqual(sorted(os.listdir(self.out)), ["dvf-44.zip", "dvf-44047.zip"])   # pas de .txt en vrac

        dep, meta_dep = self.zip_content("dvf-44.zip")
        self.assertEqual(sorted(dep), ["44003.txt", "44047.txt", "44109.txt", "meta.json"])
        self.assertEqual(dep["44109.txt"].splitlines(), [HEADER, ROWS_2016[2]])
        self.assertEqual((meta_dep["communes"], meta_dep["lignes"]), (3, 5))
        self.assertEqual(meta_dep["periode"], ["2016-01-08", "2017-02-04"])

        com, meta = self.zip_content("dvf-44047.zip")
        self.assertEqual(sorted(com), ["44047.txt", "meta.json"])
        self.assertEqual(com["44047.txt"].splitlines(), [HEADER, ROWS_2016[0], ROWS_2016[3], ROWS_2017[0]])
        self.assertEqual((meta["departement"], meta["communes"], meta["lignes"]), ("44", 1, 3))
        self.assertEqual(meta["periode"], ["2016-01-08", "2017-02-02"])
        self.assertEqual(meta["fichiers_sources"], ["2016.txt", "2017.txt"])

    def test_couvert_jusqu_au_defaut_fin_de_l_annee_de_la_derniere_vente(self):
        self.assertEqual(self.run_main(self.write_source("2016.txt", ROWS_2016), "--commune", "44047"), 0)
        self.assertEqual(self.zip_content("dvf-44047.zip")[1]["couvert_jusqu_au"], "2016-12-31")

    def test_couvert_jusqu_au_impose(self):
        path = self.write_source("2016.txt", ROWS_2016)
        self.assertEqual(self.run_main(path, "--commune", "44047", "--couvert-jusqu-au", "2016-06-30"), 0)
        self.assertEqual(self.zip_content("dvf-44047.zip")[1]["couvert_jusqu_au"], "2016-06-30")

    def test_commune_absente_refusee(self):
        self.assertEqual(self.run_main(self.write_source("2016.txt", ROWS_2016), "--commune", "44999"), 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "dvf-44999.zip")))

    def test_code_insee(self):
        self.assertEqual(split.code_insee("44", "47"), "44047")
        self.assertEqual(split.code_insee("44", "047"), "44047")
        self.assertEqual(split.code_insee("971", "1"), "97101")


if __name__ == "__main__":
    unittest.main()
