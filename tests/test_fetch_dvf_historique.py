"""Tests du téléchargement des DVF historiques. Lancer : python3 -m unittest discover -s tests"""
import contextlib
import http.server
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fetch_dvf_historique as fetch  # noqa: E402

L = fetch.Livraison
HEADER = "Reference document|Date mutation|Valeur fonciere|Code departement|Code commune|Commune"
ROWS = {
    2016: ["|08/01/2016|40000,00|44|047|COUËRON", "|11/01/2016|1677,00|01|430|VARAMBON"],
    2017: ["|02/02/2017|310000,00|44|047|COUËRON", "|04/02/2017|5000,00|44|109|NANTES"],
}


class PlanTest(unittest.TestCase):
    def test_table_du_depot_continue_et_chronologique(self):
        annees = [a for a, _, _ in fetch.plan(fetch.LIVRAISONS)]
        self.assertEqual(annees, list(range(annees[0], annees[-1] + 1)))

    def test_nouvelle_plage_ajoutee_a_la_table(self):
        liv = fetch.LIVRAISONS + [L("202604", 2024, 2025, "valeursfoncieres-{annee}.txt.zip")]
        plan = fetch.plan(liv)
        self.assertEqual([a for a, _, _ in plan][-2:], [2024, 2025])
        self.assertEqual(plan[-1][2], "valeursfoncieres-2025.txt.zip")
        self.assertEqual(fetch.url(plan[-1][1], plan[-1][2]),
                         "https://data.cquest.org/dgfip_dvf/202604/valeursfoncieres-2025.txt.zip")

    def test_ordre_des_lignes_indifferent(self):
        liv = [L("b", 2018, 2019, "{annee}.txt"), L("a", 2016, 2017, "{annee}.txt")]
        self.assertEqual([a for a, _, _ in fetch.plan(liv)], [2016, 2017, 2018, 2019])

    def test_annee_en_double_refusee(self):
        with self.assertRaisesRegex(SystemExit, "2017"):
            fetch.plan([L("a", 2016, 2017, "{annee}.txt"), L("b", 2017, 2018, "{annee}.txt")])

    def test_trou_refuse(self):
        with self.assertRaisesRegex(SystemExit, "2018"):
            fetch.plan([L("a", 2016, 2017, "{annee}.txt"), L("b", 2019, 2020, "{annee}.txt")])

    def test_plage_vide_refusee(self):
        with self.assertRaises(SystemExit):
            fetch.plan([L("a", 2018, 2016, "{annee}.txt")])


class Handler(http.server.BaseHTTPRequestHandler):
    """Sert `server.fichiers` ({chemin: octets}) ; honore Range sauf si `server.ignore_range`."""

    def log_message(self, format, *args):
        pass

    def do_HEAD(self):
        self.repondre(head=True)

    def do_GET(self):
        self.repondre(head=False)

    def repondre(self, head):
        data = self.server.fichiers.get(self.path)
        if data is None:
            self.send_error(404)
            return
        debut = 0
        m = re.match(r"bytes=(\d+)-", self.headers.get("Range", ""))
        if m and not self.server.ignore_range:
            debut = int(m.group(1))
        self.send_response(206 if debut else 200)
        self.send_header("Content-Length", str(len(data) - debut))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        if not head:
            self.server.demandes.append((self.path, debut))
            self.wfile.write(data[debut:])


class Serveur(http.server.ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.fichiers, self.ignore_range, self.demandes = {}, False, []


class ServeurTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.server = Serveur()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        old = fetch.BASE
        fetch.BASE = self.base
        self.addCleanup(setattr, fetch, "BASE", old)

    def quiet(self, f, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return f(*args)


class TelechargerTest(ServeurTest):
    DATA = bytes(range(256)) * 40

    def setUp(self):
        super().setUp()
        self.server.fichiers["/f.bin"] = self.DATA
        self.dest = os.path.join(self.tmp, "f.bin")

    def lu(self):
        with open(self.dest, "rb") as fh:
            return fh.read()

    def test_telechargement_complet(self):
        self.quiet(fetch.telecharger, self.base + "/f.bin", self.dest)
        self.assertEqual(self.lu(), self.DATA)
        self.assertFalse(os.path.exists(self.dest + ".part"))

    def test_reprise_apres_interruption(self):
        with open(self.dest + ".part", "wb") as fh:
            fh.write(self.DATA[:1000])
        self.quiet(fetch.telecharger, self.base + "/f.bin", self.dest)
        self.assertEqual(self.lu(), self.DATA)
        self.assertEqual(self.server.demandes, [("/f.bin", 1000)])

    def test_serveur_sans_reprise_recommence(self):
        self.server.ignore_range = True
        with open(self.dest + ".part", "wb") as fh:
            fh.write(self.DATA[:1000])
        self.quiet(fetch.telecharger, self.base + "/f.bin", self.dest)
        self.assertEqual(self.lu(), self.DATA)

    def test_fichier_deja_complet_pas_retelecharge(self):
        with open(self.dest, "wb") as fh:
            fh.write(self.DATA)
        self.quiet(fetch.telecharger, self.base + "/f.bin", self.dest)
        self.assertEqual(self.server.demandes, [])

    def test_part_deja_complet_pas_retelecharge(self):
        with open(self.dest + ".part", "wb") as fh:
            fh.write(self.DATA)
        self.quiet(fetch.telecharger, self.base + "/f.bin", self.dest)
        self.assertEqual(self.lu(), self.DATA)
        self.assertEqual(self.server.demandes, [])

    def test_fichier_inexistant(self):
        with self.assertRaisesRegex(SystemExit, "404.*LIVRAISONS"):
            self.quiet(fetch.telecharger, self.base + "/absent", self.dest)


class DezipperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def zip(self, *membres):
        path = os.path.join(self.tmp, "a.zip")
        with zipfile.ZipFile(path, "w") as zf:
            for nom, data in membres:
                zf.writestr(nom, data)
        return path

    def test_extrait_l_unique_txt_sous_le_nom_demande(self):
        dest = os.path.join(self.tmp, "valeursfoncieres-2021.txt")
        with contextlib.redirect_stdout(io.StringIO()):
            fetch.dezipper(self.zip(("../ValeursFoncieres-2021.txt", b"abc")), dest)
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), b"abc")
        self.assertEqual(sorted(os.listdir(self.tmp)), ["a.zip", "valeursfoncieres-2021.txt"])

    def test_refuse_plusieurs_txt(self):
        with self.assertRaises(SystemExit):
            fetch.dezipper(self.zip(("a.txt", b"1"), ("b.txt", b"2")), os.path.join(self.tmp, "x.txt"))


class MainTest(ServeurTest):
    """De bout en bout : télécharge un .txt et un .txt.zip locaux, puis archive le département."""

    def setUp(self):
        super().setUp()
        txt = lambda annee: ("\n".join([HEADER] + ROWS[annee]) + "\n").encode("utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("ValeursFoncieres-2017.txt", txt(2017))
        self.server.fichiers = {"/201904/v-2016.txt": txt(2016), "/202504/v-2017.txt.zip": buf.getvalue()}
        old = fetch.LIVRAISONS
        fetch.LIVRAISONS = [L("201904", 2016, 2016, "v-{annee}.txt"), L("202504", 2017, 2017, "v-{annee}.txt.zip")]
        self.addCleanup(setattr, fetch, "LIVRAISONS", old)
        self.sortie = os.path.join(self.tmp, "sortie")

    def test_archive_du_departement_et_de_la_commune(self):
        code = self.quiet(fetch.main, ["--sortie", self.sortie, "--commune", "44047"])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(self.sortie)), ["dvf-44.zip", "dvf-44047.zip"])
        with zipfile.ZipFile(os.path.join(self.sortie, "dvf-44.zip")) as zf:
            self.assertEqual(sorted(zf.namelist()), ["44047.txt", "44109.txt", "meta.json"])
            meta = json.loads(zf.read("meta.json"))
            self.assertEqual(zf.read("44047.txt").decode().splitlines(), [HEADER, ROWS[2016][0], ROWS[2017][0]])
        self.assertEqual(meta["periode"], ["2016-01-08", "2017-02-04"])
        self.assertEqual(meta["fichiers_sources"], ["v-2016.txt", "v-2017.txt"])

    def test_travail_conserve_les_fichiers(self):
        travail = os.path.join(self.tmp, "travail")
        self.quiet(fetch.main, ["--sortie", self.sortie, "--travail", travail])
        self.assertEqual(sorted(os.listdir(os.path.join(travail, "202504"))), ["v-2017.txt", "v-2017.txt.zip"])
        self.server.demandes.clear()
        self.quiet(fetch.main, ["--sortie", self.sortie, "--travail", travail])
        self.assertEqual(self.server.demandes, [])


if __name__ == "__main__":
    unittest.main()
