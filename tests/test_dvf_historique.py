"""Tests de la lecture de l'archive DVF historique et de sa fusion avec l'API.
Lancer : python3 -m unittest discover -s tests"""
import contextlib
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import dvf_historique  # noqa: E402
import fetch_dvf  # noqa: E402

DEFAUT = {
    "No disposition": "000001", "Date mutation": "12/06/2023", "Nature mutation": "Vente",
    "Valeur fonciere": "325000,00", "No voie": "12", "B/T/Q": "", "Type de voie": "RUE", "Voie": "DES LILAS",
    "Code departement": "44", "Code commune": "47", "Prefixe de section": "", "Section": "AB", "No plan": "12",
    "1er lot": "", "Type local": "Maison", "Surface reelle bati": "110", "Nombre pieces principales": "5",
    "Nature culture": "S", "Surface terrain": "812",
}


def brut(*lignes, colonnes=dvf_historique.COLONNES):
    """Texte DGFiP brut : en-tête puis une ligne par dict (valeurs par défaut = DEFAUT)."""
    out = ["|".join(colonnes)]
    out += ["|".join({**DEFAUT, **ligne}[c] for c in colonnes) for ligne in lignes]
    return "\n".join(out) + "\n"


def ecrire_archive(dossier, texte, insee="44047", couvert="2023-12-31"):
    chemin = os.path.join(dossier, f"dvf-{insee}.zip")
    with zipfile.ZipFile(chemin, "w") as zf:
        zf.writestr("meta.json", json.dumps({"couvert_jusqu_au": couvert, "periode": ["2014-01-03", "2023-12-29"]}))
        zf.writestr(f"{insee}.txt", texte)
    return chemin


class ConvertirTest(unittest.TestCase):
    def test_schema_geolocalise(self):
        (r,) = dvf_historique.convertir(brut({}), "44047")
        self.assertEqual(r["id_parcelle"], "44047000AB0012")
        self.assertEqual(r["date_mutation"], "2023-06-12")
        self.assertEqual((r["adresse_numero"], r["adresse_nom_voie"]), ("12", "RUE DES LILAS"))
        self.assertEqual((r["type_local"], r["surface_reelle_bati"], r["surface_terrain"]), ("Maison", "110", "812"))
        self.assertEqual((r["longitude"], r["latitude"]), ("", ""))             # pas de coordonnées dans la source

    def test_parcelle_section_d_une_lettre_prefixe_et_numero_sur_quatre_chiffres(self):
        (r,) = dvf_historique.convertir(brut({"Section": "A", "No plan": "7", "Prefixe de section": "12"}), "44047")
        self.assertEqual(r["id_parcelle"], "44047012" + "0A" + "0007")

    def test_lignes_consecutives_de_meme_date_nature_valeur_forment_une_vente(self):
        texte = brut({"No plan": "1"}, {"No plan": "2", "Type local": ""},                  # même vente
                     {"No plan": "3", "Valeur fonciere": "90000,00"},                        # autre valeur
                     {"No plan": "4"},                                                      # retour à la 1re clé, non contigu
                     {"No plan": "5", "Date mutation": "03/01/2024"})
        ids = [r["id_mutation"] for r in dvf_historique.convertir(texte, "44047")]
        self.assertEqual(ids, ["2023-H1", "2023-H1", "2023-H2", "2023-H3", "2024-H1"])

    def test_adresse_avec_indice_de_repetition_et_valeur_absente(self):
        (r,) = dvf_historique.convertir(brut({"B/T/Q": "B", "Valeur fonciere": "", "Type de voie": ""}), "44047")
        self.assertEqual((r["adresse_numero"], r["adresse_nom_voie"]), ("12 B", "DES LILAS"))
        self.assertEqual(r["valeur_fonciere"], "")

    def test_autre_commune_ignoree(self):
        rows = dvf_historique.convertir(brut({}, {"Code commune": "109"}), "44047")
        self.assertEqual(len(rows), 1)

    def test_code_commune_complete_a_trois_chiffres(self):
        self.assertEqual(len(dvf_historique.convertir(brut({"Code commune": "047"}), "44047")), 1)

    def test_colonne_absente(self):
        with self.assertRaises(ValueError):
            dvf_historique.convertir(brut({}, colonnes=dvf_historique.COLONNES[:-1]), "44047")

    def test_date_illisible(self):
        with self.assertRaises(ValueError):
            dvf_historique.convertir(brut({"Date mutation": "2023-06-12"}), "44047")


def api_sale(mid, date, valeur, parcelle):
    return {"id_mutation": mid, "date_mutation": date, "nature_mutation": "Vente", "valeur_fonciere": valeur,
            "code_commune": "44047", "id_parcelle": parcelle, "type_local": "Maison",
            "surface_reelle_bati": "90", "nombre_pieces_principales": "4",
            "adresse_numero": "3", "adresse_nom_voie": "RUE NEUVE", "longitude": "-1.73", "latitude": "47.21"}


class FusionTest(unittest.TestCase):
    """fetch_dvf.main : historique jusqu'à la date couverte, API seulement après. Réseau simulé."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "out.json")
        patcher = mock.patch.object(fetch_dvf, "HISTORIQUE", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        ecrire_archive(self.tmp, brut(
            {"Date mutation": "10/03/2014", "No plan": "1", "Valeur fonciere": "150000,00"},
            {"Date mutation": "29/12/2023", "No plan": "2", "Valeur fonciere": "400000,00"}))

    def run_main(self, *args, api=None):
        """Retourne (JSON produit, première date demandée à collect())."""
        demandes = []

        def collect(insee, depuis):
            demandes.append(depuis)
            return [api] if api else [], []

        with mock.patch.object(fetch_dvf, "collect", collect), contextlib.redirect_stdout(io.StringIO()):
            code = fetch_dvf.main(["44047", "--sortie", self.out, *args])
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as fh:
            return json.load(fh), demandes

    def test_l_api_n_est_interrogee_qu_apres_la_date_couverte(self):
        data, demandes = self.run_main(api=[api_sale("2024-9", "2024-02-05", "310000", "44047000AB0003")])
        self.assertEqual(demandes, [dt.date(2024, 1, 1)])
        self.assertEqual([m["d"] for m in data["mutations"]], ["2024-02-05", "2023-12-29", "2014-03-10"])
        self.assertEqual(data["meta"]["periode"], ["2014-03-10", "2024-02-05"])
        self.assertEqual(data["meta"]["mutations"], 3)

    def test_trace_de_l_historique_dans_meta(self):
        data, _ = self.run_main(api=[api_sale("2024-9", "2024-02-05", "310000", "44047000AB0003")])
        self.assertEqual(data["meta"]["historique"]["jusqu_au"], "2023-12-31")
        self.assertEqual(data["meta"]["historique"]["mutations"], 2)
        self.assertEqual(data["meta"]["geolocalisees_depuis"], "2024-01-01")

    def test_ventes_historiques_sans_coordonnees_ventes_api_avec(self):
        data, _ = self.run_main(api=[api_sale("2024-9", "2024-02-05", "310000", "44047000AB0003")])
        par_date = {m["d"]: m for m in data["mutations"]}
        self.assertEqual((par_date["2023-12-29"]["lat"], par_date["2023-12-29"]["lon"]), (None, None))
        self.assertEqual(par_date["2023-12-29"]["p"], ["44047000AB0002"])
        self.assertEqual(par_date["2023-12-29"]["v"], 400000)
        self.assertEqual(par_date["2024-02-05"]["lat"], 47.21)

    def test_ventes_de_l_api_anterieures_a_la_date_couverte_sont_ecartees(self):
        """Un fichier annuel déborde sur la période de l'historique : ses ventes de 2023 feraient doublon."""
        api = [api_sale("2023-1", "2023-12-29", "400000", "44047000AB0002"),
               api_sale("2024-9", "2024-02-05", "310000", "44047000AB0003")]
        data, _ = self.run_main(api=api)
        self.assertEqual([m["d"] for m in data["mutations"]], ["2024-02-05", "2023-12-29", "2014-03-10"])

    def test_depuis_dans_l_historique(self):
        data, demandes = self.run_main("--depuis", "2023-06-01",
                                       api=[api_sale("2024-9", "2024-02-05", "310000", "44047000AB0003")])
        self.assertEqual(demandes, [dt.date(2024, 1, 1)])
        self.assertEqual([m["d"] for m in data["mutations"]], ["2024-02-05", "2023-12-29"])   # 2014 écartée

    def test_depuis_posterieur_a_l_historique_ne_lit_pas_l_archive(self):
        data, demandes = self.run_main("--depuis", "2024-02-01",
                                       api=[api_sale("2024-9", "2024-02-05", "310000", "44047000AB0003")])
        self.assertEqual(demandes, [dt.date(2024, 2, 1)])
        self.assertEqual([m["d"] for m in data["mutations"]], ["2024-02-05"])
        self.assertNotIn("historique", data["meta"])

    def test_sans_historique(self):
        data, demandes = self.run_main("--sans-historique",
                                       api=[api_sale("2024-9", "2024-02-05", "310000", "44047000AB0003")])
        self.assertEqual(demandes, [dt.date(2014, 1, 1)])
        self.assertEqual([m["d"] for m in data["mutations"]], ["2024-02-05"])
        self.assertNotIn("historique", data["meta"])
        self.assertNotIn("geolocalisees_depuis", data["meta"])

    def test_commune_sans_archive(self):
        os.remove(os.path.join(self.tmp, "dvf-44047.zip"))
        data, demandes = self.run_main(api=[api_sale("2024-9", "2024-02-05", "310000", "44047000AB0003")])
        self.assertEqual(demandes, [dt.date(2014, 1, 1)])
        self.assertNotIn("historique", data["meta"])

    def test_api_vide_est_une_erreur_meme_avec_historique(self):
        """Sans ventes récentes, on n'écrit pas un fichier amputé : le workflow garde la version publiée."""
        with mock.patch.object(fetch_dvf, "collect", lambda insee, depuis: ([], [])), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetch_dvf.main(["44047", "--sortie", self.out]), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_fichier_local_filtre_comme_l_api(self):
        src = os.path.join(self.tmp, "dvf.csv")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("id_mutation,date_mutation,nature_mutation,valeur_fonciere,code_commune,id_parcelle\n"
                     "x-1,2023-06-12,Vente,1,44047,44047000AB0009\n"
                     "x-2,2024-03-01,Vente,2,44047,44047000AB0008\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fetch_dvf.main(["44047", "--fichier", src, "--sortie", self.out]), 0)
        with open(self.out, encoding="utf-8") as fh:
            dates = [m["d"] for m in json.load(fh)["mutations"]]
        self.assertEqual(dates, ["2024-03-01", "2023-12-29", "2014-03-10"])        # la vente de juin 2023 du fichier est écartée


if __name__ == "__main__":
    unittest.main()
