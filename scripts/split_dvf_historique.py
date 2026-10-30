#!/usr/bin/env python3
"""Archive les fichiers DVF nationaux « valeursfoncieres-AAAA.txt » d'un département, par commune.

Usage : python3 scripts/split_dvf_historique.py FICHIER [FICHIER…] [--departement 44] [--sortie DOSSIER]
                                                [--commune INSEE]… [--couvert-jusqu-au AAAA-MM-JJ]
        (défaut : département 44, Loire-Atlantique ; sortie resources/dvf-historique/)

Les fichiers DGFiP des anciennes années ne sont plus publiés sur data.gouv.fr (fenêtre glissante de
cinq ans). Les livraisons successives restent disponibles dans l'archive http://data.cquest.org/dgfip_dvf/
(un dossier par livraison, AAAAMM) : ce script extrait les lignes d'un département, les range par
commune (<INSEE>.txt) et produit, dans le dossier de sortie :
  - dvf-<département>.zip : une archive de toutes les communes du département (copie d'archivage) ;
  - dvf-<INSEE>.zip pour chaque --commune : l'archive que lit scripts/fetch_dvf.py (via dvf_historique.py).
Chaque zip contient les <INSEE>.txt et un meta.json (période des ventes, date couverte, sources).

Le format source est conservé tel quel : texte UTF-8, séparateur « | », virgule décimale, dates
JJ/MM/AAAA, une ligne par (disposition × parcelle × local). Chaque fichier de commune reprend l'en-tête
du premier fichier source, puis les lignes de tous les fichiers passés en argument, dans l'ordre des
arguments. Les en-têtes doivent être identiques, au renommage près de la première colonne (vide).

Chaque livraison remplace la précédente et ajoute des ventes tardives aux années déjà publiées : une
année ne doit être lue que dans une seule livraison (sinon ses ventes seraient comptées deux fois).
Les fichiers dézippés sont à passer un par un, un par année, dans l'ordre chronologique.

meta.json garde la trace de la date jusqu'à laquelle l'historique est complet (« couvert_jusqu_au ») :
fetch_dvf.py n'interroge l'API que pour les ventes postérieures. Par défaut, c'est le 31 décembre de
l'année de la vente la plus récente (les fichiers sont des millésimes annuels) ; --couvert-jusqu-au
la fixe autrement, par exemple si le dernier fichier est un semestre.

Python 3.8+, bibliothèque standard uniquement.
"""
import argparse
import collections
import datetime as dt
import json
import os
import sys
import tempfile
import zipfile

DEPARTEMENT = "44"
SORTIE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "resources", "dvf-historique")
SEP = b"|"
COL_DEPARTEMENT, COL_COMMUNE, COL_DATE = b"Code departement", b"Code commune", b"Date mutation"
# Colonne renommée par la DGFiP sans changer de place : la première, vide sur toutes les lignes,
# s'appelle « Code service CH » jusqu'aux fichiers 2020 et « Identifiant de document » depuis 2021.
RENOMMEES = {b"Identifiant de document": b"Code service CH"}


def colonnes(header):
    """Noms des colonnes de la ligne d'en-tête, les colonnes renommées ramenées à leur ancien nom."""
    return [RENOMMEES.get(c, c) for c in header.rstrip(b"\r\n").split(SEP)]


def indices(header):
    """Positions des colonnes utiles dans la ligne d'en-tête (octets)."""
    cols = header.rstrip(b"\r\n").split(SEP)
    try:
        return tuple(cols.index(c) for c in (COL_DEPARTEMENT, COL_COMMUNE, COL_DATE))
    except ValueError as e:
        raise SystemExit(f"En-tête inattendu, colonne introuvable ({e}) : {header[:120]!r}")


def code_insee(departement, commune):
    """« 44 » + « 47 » ou « 047 » → « 44047 » (commune sur 3 chiffres, 2 en outre-mer)."""
    return departement + commune.zfill(5 - len(departement))


def iso(date):
    """b'08/01/2016' → '2016-01-08'."""
    if len(date) != 10 or date[2:3] != b"/" or date[5:6] != b"/":
        raise SystemExit(f"Date de mutation inattendue (JJ/MM/AAAA attendu) : {date!r}")
    return (date[6:] + b"-" + date[3:5] + b"-" + date[:2]).decode()


def split(paths, departement, sortie):
    """Écrit <sortie>/<INSEE>.txt pour chaque commune du département.

    Retourne {INSEE: {"lignes": n, "du": date ISO de la première vente, "au": date de la dernière}}.
    Lit en binaire, ligne par ligne : seules les premières colonnes sont examinées, les lignes
    retenues sont recopiées sans transformation.
    """
    os.makedirs(sortie, exist_ok=True)
    dep = departement.encode()
    with open(paths[0], "rb") as fh:
        header = fh.readline().rstrip(b"\r\n") + b"\n"
    i_dep, i_com, i_date = indices(header)
    last = max(i_dep, i_com, i_date)
    outputs, stats = {}, {}
    try:
        for path in paths:
            with open(path, "rb") as fh:
                if colonnes(fh.readline()) != colonnes(header):
                    raise SystemExit(f"{path} : en-tête différent de celui de {paths[0]}, "
                                     "les colonnes ne sont pas comparables.")
                read, kept, years = 0, 0, collections.Counter()
                for line in fh:
                    read += 1
                    cols = line.split(SEP, last + 1)
                    if len(cols) <= last or cols[i_dep] != dep:
                        continue
                    insee = code_insee(departement, cols[i_com].decode())
                    date = iso(cols[i_date])
                    out = outputs.get(insee)
                    if out is None:
                        out = outputs[insee] = open(os.path.join(sortie, f"{insee}.txt"), "wb")
                        out.write(header)
                        stats[insee] = {"lignes": 0, "du": date, "au": date}
                    out.write(line if line.endswith(b"\n") else line + b"\n")
                    st = stats[insee]
                    st["lignes"] += 1
                    if date < st["du"]:
                        st["du"] = date
                    if date > st["au"]:
                        st["au"] = date
                    kept += 1
                    years[date[:4]] += 1
            detail = ", ".join(f"{y} : {n}" for y, n in sorted(years.items()))
            print(f"  {os.path.basename(path)} : {kept} lignes retenues sur {read} ({detail or 'aucune'})")
    finally:
        for out in outputs.values():
            out.close()
    return stats


def archiver(chemin, dossier, insees, stats, departement, sources, couvert_jusqu_au):
    """Écrit le zip `chemin` : meta.json puis les <INSEE>.txt demandés (lus dans `dossier`)."""
    meta = {
        "departement": departement,
        "communes": len(insees),
        "lignes": sum(stats[i]["lignes"] for i in insees),
        "periode": [min(stats[i]["du"] for i in insees), max(stats[i]["au"] for i in insees)],
        "couvert_jusqu_au": couvert_jusqu_au,
        "fichiers_sources": sources,
        "genere_le": dt.date.today().isoformat(),
    }
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        for insee in sorted(insees):
            zf.write(os.path.join(dossier, f"{insee}.txt"), f"{insee}.txt")
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fichiers", nargs="+", metavar="FICHIER", help="valeursfoncieres-AAAA.txt (dans l'ordre voulu)")
    ap.add_argument("--departement", default=DEPARTEMENT, help=f"code du département (défaut {DEPARTEMENT})")
    ap.add_argument("--sortie", default=SORTIE, help="dossier des zips produits")
    ap.add_argument("--commune", action="append", default=[], metavar="INSEE",
                    help="produit aussi dvf-<INSEE>.zip pour cette commune (répétable)")
    ap.add_argument("--couvert-jusqu-au", type=dt.date.fromisoformat, default=None, metavar="AAAA-MM-JJ",
                    help="date jusqu'à laquelle l'historique est complet (défaut : 31 décembre de l'année "
                         "de la vente la plus récente)")
    args = ap.parse_args(argv)

    print(f"Département {args.departement} → {args.sortie}")
    os.makedirs(args.sortie, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stats = split(args.fichiers, args.departement, tmp)
        if not stats:
            print(f"Aucune ligne du département {args.departement} dans ces fichiers.", file=sys.stderr)
            return 1
        inconnues = [c for c in args.commune if c not in stats]
        if inconnues:
            print(f"Commune absente des fichiers : {', '.join(inconnues)}", file=sys.stderr)
            return 1

        derniere = max(st["au"] for st in stats.values())
        couvert = (args.couvert_jusqu_au or dt.date(int(derniere[:4]), 12, 31)).isoformat()
        sources = [os.path.basename(p) for p in args.fichiers]
        demandes = [(f"dvf-{args.departement}.zip", list(stats))] + \
                   [(f"dvf-{c}.zip", [c]) for c in args.commune]
        for nom, insees in demandes:
            meta = archiver(os.path.join(args.sortie, nom), tmp, insees, stats, args.departement, sources, couvert)
            print(f"  {nom} : {meta['communes']} commune(s), {meta['lignes']} lignes, "
                  f"ventes du {meta['periode'][0]} au {meta['periode'][1]}, couvert jusqu'au {couvert}")
    print(f"OK : {len(stats)} communes, {sum(st['lignes'] for st in stats.values())} lignes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
