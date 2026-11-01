#!/usr/bin/env python3
"""Télécharge les DVF nationaux de data.cquest.org et en archive un département, par commune.

Usage : python3 scripts/fetch_dvf_historique.py [--departement 44] [--commune INSEE]… [--sortie DOSSIER]
                                                [--travail DOSSIER] [--couvert-jusqu-au AAAA-MM-JJ]
        (défaut : département 44, Loire-Atlantique ; sortie resources/dvf-historique/)

Enchaîne les trois étapes de la régénération décrite dans resources/dvf-historique/README.md :
  1. télécharge, dans l'archive https://data.cquest.org/dgfip_dvf/, le fichier national de chaque année
     listé dans LIVRAISONS (≈ 3 Go) ;
  2. dézippe ceux qui sont livrés en .zip ;
  3. appelle scripts/split_dvf_historique.py, qui garde les lignes du département et produit
     dvf-<département>.zip (et dvf-<INSEE>.zip pour chaque --commune) dans le dossier de sortie.
Les options --departement, --commune, --sortie et --couvert-jusqu-au lui sont transmises telles quelles.

Les fichiers téléchargés vont dans un dossier temporaire, supprimé à la fin. Avec --travail DOSSIER, ils y
sont conservés : un téléchargement interrompu reprend où il s'était arrêté, et un fichier déjà complet
n'est pas retéléchargé. Prévoir ≈ 3,5 Go de disque libre.

Pour ajouter une plage d'années (une nouvelle livraison de l'archive), ajouter une ligne à LIVRAISONS, puis au
tableau « Origine » du README. Chaque livraison remplace la précédente et complète les années déjà publiées :
une année n'est lue que dans une seule ligne, et les plages doivent se suivre sans trou.

Python 3.8+, bibliothèque standard uniquement.
"""
import argparse
import collections
import contextlib
import datetime as dt
import http.client
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

import split_dvf_historique as split

BASE = "https://data.cquest.org/dgfip_dvf"
UA = {"User-Agent": "parcelles-coueron/0.1 (script de préparation DVF)"}
ESSAIS = 3
BLOC = 1 << 20

# Une ligne par plage d'années : dossier de la livraison (AAAAMM) sur data.cquest.org, première et dernière
# année qu'on y lit, modèle du nom de fichier ({annee} est remplacé ; « .zip » : fichier à dézipper).
Livraison = collections.namedtuple("Livraison", "dossier de a fichier")
LIVRAISONS = [
    Livraison("201904", 2014, 2017, "valeursfoncieres-{annee}.txt"),
    Livraison("202204", 2018, 2020, "valeursfoncieres-{annee}.txt"),  # 2018 de 201904 : incomplète
    Livraison("202504", 2021, 2023, "valeursfoncieres-{annee}.txt.zip"),
]


def plan(livraisons):
    """[(année, livraison, nom du fichier)] dans l'ordre chronologique ; refuse les années en double ou manquantes."""
    annees = {}
    for liv in livraisons:
        if liv.a < liv.de:
            raise SystemExit(f"Livraison {liv.dossier} : plage d'années vide ({liv.de} – {liv.a}).")
        for annee in range(liv.de, liv.a + 1):
            if annee in annees:
                raise SystemExit(f"L'année {annee} figure dans deux livraisons ({annees[annee][0].dossier} et "
                                 f"{liv.dossier}) : ses ventes seraient comptées deux fois.")
            annees[annee] = (liv, liv.fichier.format(annee=annee))
    manquantes = [a for a in range(min(annees), max(annees) + 1) if a not in annees]
    if manquantes:
        raise SystemExit(f"Années sans livraison : {', '.join(map(str, manquantes))}. "
                         "Les plages doivent se suivre, l'historique est supposé continu.")
    return [(annee, liv, nom) for annee, (liv, nom) in sorted(annees.items())]


def url(liv, nom):
    return f"{BASE}/{liv.dossier}/{nom}"


def taille_distante(adresse):
    req = urllib.request.Request(adresse, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            taille = r.headers.get("Content-Length")
    except urllib.error.URLError as e:
        raise SystemExit(f"{adresse} : {e}. Vérifier la ligne correspondante de LIVRAISONS.")
    if taille is None:
        raise SystemExit(f"{adresse} : le serveur n'indique pas la taille du fichier.")
    return int(taille)


def copier(adresse, part, total):
    """Ajoute à `part` la suite du fichier distant (ou le recommence si le serveur ignore la reprise)."""
    debut = os.path.getsize(part) if os.path.exists(part) else 0
    if debut >= total:
        debut = 0
    headers = dict(UA, Range=f"bytes={debut}-") if debut else UA
    with urllib.request.urlopen(urllib.request.Request(adresse, headers=headers), timeout=60) as r:
        repris = debut and r.status == 206
        fait = debut if repris else 0
        with open(part, "ab" if repris else "wb") as out:
            while True:
                bloc = r.read(BLOC)
                if not bloc:
                    return
                out.write(bloc)
                fait += len(bloc)
                if sys.stdout.isatty():
                    print(f"\r    {fait * 100 // total} %", end="", flush=True)


def telecharger(adresse, dest):
    """Télécharge `adresse` dans `dest`, en reprenant `dest.part` s'il existe ; ne fait rien si `dest` est complet."""
    total = taille_distante(adresse)
    if os.path.exists(dest) and os.path.getsize(dest) == total:
        print(f"  {os.path.basename(dest)} : déjà téléchargé")
        return
    print(f"  {os.path.basename(dest)} : téléchargement de {total / 1e6:.0f} Mo")
    part = dest + ".part"
    essais = 0
    while not (os.path.exists(part) and os.path.getsize(part) == total):
        if essais == ESSAIS:
            raise SystemExit(f"{adresse} : téléchargement incomplet, à relancer (avec --travail pour le reprendre).")
        essais += 1
        try:
            copier(adresse, part, total)
        except (OSError, http.client.HTTPException) as e:
            print(f"\n    interrompu ({e}), essai {essais}/{ESSAIS}", file=sys.stderr)
    if sys.stdout.isatty():
        print()
    os.replace(part, dest)


def dezipper(archive, dest):
    """Écrit dans `dest` l'unique .txt de `archive`. Le nom du membre n'est jamais utilisé comme chemin."""
    with zipfile.ZipFile(archive) as zf:
        txt = [i for i in zf.infolist() if i.filename.lower().endswith(".txt")]
        if len(txt) != 1:
            raise SystemExit(f"{archive} : un seul .txt attendu, trouvé {[i.filename for i in txt]}.")
        print(f"  {os.path.basename(dest)} : extrait de {os.path.basename(archive)} ({txt[0].file_size / 1e6:.0f} Mo)")
        with zf.open(txt[0]) as src, open(dest + ".part", "wb") as out:
            shutil.copyfileobj(src, out, BLOC)
    os.replace(dest + ".part", dest)


def preparer(travail, livraisons):
    """Télécharge (et dézippe) le fichier de chaque année dans `travail`. Retourne les .txt dans l'ordre."""
    fichiers = []
    for _, liv, nom in plan(livraisons):
        dossier = os.path.join(travail, liv.dossier)
        os.makedirs(dossier, exist_ok=True)
        local = os.path.join(dossier, nom)
        telecharger(url(liv, nom), local)
        if nom.endswith(".zip"):
            txt = local[:-len(".zip")]
            if not os.path.exists(txt):
                dezipper(local, txt)
            local = txt
        fichiers.append(local)
    return fichiers


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--departement", default=split.DEPARTEMENT, help=f"code du département (défaut {split.DEPARTEMENT})")
    ap.add_argument("--commune", action="append", default=[], metavar="INSEE",
                    help="produit aussi dvf-<INSEE>.zip pour cette commune (répétable)")
    ap.add_argument("--sortie", default=split.SORTIE, help="dossier des zips produits")
    ap.add_argument("--travail", metavar="DOSSIER",
                    help="dossier où garder les fichiers téléchargés (reprise possible) ; défaut : dossier temporaire")
    ap.add_argument("--couvert-jusqu-au", type=dt.date.fromisoformat, default=None, metavar="AAAA-MM-JJ",
                    help="voir split_dvf_historique.py")
    args = ap.parse_args(argv)

    with contextlib.ExitStack() as stack:
        travail = args.travail or stack.enter_context(tempfile.TemporaryDirectory(prefix="dvf-historique-"))
        os.makedirs(travail, exist_ok=True)
        print(f"Téléchargement dans {travail}")
        fichiers = preparer(travail, LIVRAISONS)
        cmd = fichiers + ["--departement", args.departement, "--sortie", args.sortie]
        for commune in args.commune:
            cmd += ["--commune", commune]
        if args.couvert_jusqu_au:
            cmd += ["--couvert-jusqu-au", args.couvert_jusqu_au.isoformat()]
        return split.main(cmd)


if __name__ == "__main__":
    sys.exit(main())
