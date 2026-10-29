#!/usr/bin/env python3
"""Prépare data/dvf-<INSEE>.json à partir des DVF géolocalisées (Etalab, data.gouv.fr).

Usage : python3 scripts/fetch_dvf.py [code_insee]      (défaut : 44047, Couëron)

Le fichier produit contient une entrée par mutation (vente) de la commune, avec les
parcelles concernées. La page web l'indexe par parcelle pour afficher l'historique des
ventes et les ventes voisines.

Sources essayées, par ordre :
  1. fichiers par commune et par année  : geo-dvf/latest/csv/<an>/communes/<dep>/<insee>.csv
  2. fichiers par département et année   : geo-dvf/latest/csv/<an>/departements/<dep>.csv.gz
  3. ressources annuelles du jeu de données sur data.gouv.fr (full.csv.gz), filtrées à la volée
data.gouv.fr réorganise ces fichiers : si les trois échouent, téléchargez le fichier annuel
à la main et passez-le avec --fichier (plusieurs fois possible).

Python 3.8+, bibliothèque standard uniquement.
"""
import argparse
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = "https://files.data.gouv.fr/geo-dvf/latest/csv"
DATASET_API = "https://www.data.gouv.fr/api/1/datasets/demandes-de-valeurs-foncieres-geolocalisees/"
UA = {"User-Agent": "parcelles-coueron/0.1 (script de préparation DVF)"}


# ---------------------------------------------------------------- téléchargement

def open_url(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300)


def read_rows(stream, gz):
    """Lit un CSV DVF (éventuellement gzip) ligne à ligne, sans tout charger en mémoire."""
    raw = gzip.GzipFile(fileobj=stream) if gz else stream
    yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))


def rows_for_year(year, insee):
    dep = insee[:3] if insee.startswith("97") else insee[:2]
    candidates = [
        (f"{BASE}/{year}/communes/{dep}/{insee}.csv", False),
        (f"{BASE}/{year}/departements/{dep}.csv.gz", True),
    ]
    for url, gz in candidates:
        try:
            with open_url(url) as resp:
                print(f"  {year} : {url}")
                yield from (r for r in read_rows(resp, gz) if r.get("code_commune") == insee)
                return
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"  {year} : {url} → HTTP {e.code}", file=sys.stderr)
        except urllib.error.URLError as e:
            print(f"  {year} : {url} → {e.reason}", file=sys.stderr)


def rows_from_dataset(insee):
    """Dernier recours : ressources annuelles « full.csv.gz » listées par l'API data.gouv.fr."""
    try:
        with open_url(DATASET_API) as resp:
            meta = json.load(resp)
    except Exception as e:  # noqa: BLE001
        print(f"  API data.gouv.fr indisponible : {e}", file=sys.stderr)
        return
    for res in meta.get("resources", []):
        url = res.get("url") or ""
        if url.endswith(".csv.gz") and re.search(r"20\d\d", res.get("title", "") + url):
            print(f"  ressource : {res.get('title')} ({url})")
            try:
                with open_url(url) as resp:
                    yield from (r for r in read_rows(resp, True) if r.get("code_commune") == insee)
            except Exception as e:  # noqa: BLE001
                print(f"    échec : {e}", file=sys.stderr)


def rows_from_files(paths, insee):
    for path in paths:
        print(f"  fichier local : {path}")
        with open(path, "rb") as fh:
            yield from (r for r in read_rows(fh, path.endswith(".gz")) if r.get("code_commune") == insee)


# ---------------------------------------------------------------- agrégation

def _num(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _int(value):
    n = _num(value)
    return int(n) if n is not None else None


def aggregate(rows):
    """Regroupe les lignes DVF (une par local × parcelle) en mutations.

    Retourne une liste de dicts compacts :
      id, d (date), n (nature), v (valeur foncière €), a (adresse), lat, lon,
      p (parcelles), l (locaux : [type, surface bâtie m², pièces]), t (surface terrain m²)
    """
    muts = {}
    for r in rows:
        mid = r.get("id_mutation")
        if not mid:
            continue
        m = muts.get(mid)
        if m is None:
            num = (r.get("adresse_numero") or "").strip()
            voie = (r.get("adresse_nom_voie") or "").strip()
            m = muts[mid] = {
                "id": mid,
                "d": r.get("date_mutation", ""),
                "n": r.get("nature_mutation", ""),
                "v": _num(r.get("valeur_fonciere")),
                "a": f"{num} {voie}".strip(),
                "lat": _num(r.get("latitude")),
                "lon": _num(r.get("longitude")),
                "p": [], "l": [], "t": 0,
                "_locaux": set(), "_terrains": set(),
            }
        pid = r.get("id_parcelle") or ""
        if pid and pid not in m["p"]:
            m["p"].append(pid)
        if m["lat"] is None:
            m["lat"], m["lon"] = _num(r.get("latitude")), _num(r.get("longitude"))

        type_local = (r.get("type_local") or "").strip()
        if type_local:
            key = (pid, r.get("numero_disposition"), type_local, r.get("surface_reelle_bati"),
                   r.get("nombre_pieces_principales"), r.get("lot1_numero"))
            if key not in m["_locaux"]:
                m["_locaux"].add(key)
                m["l"].append([type_local, _int(r.get("surface_reelle_bati")),
                               _int(r.get("nombre_pieces_principales"))])

        terrain = _int(r.get("surface_terrain"))
        if terrain:
            key = (pid, r.get("nature_culture"), terrain)
            if key not in m["_terrains"]:
                m["_terrains"].add(key)
                m["t"] += terrain

    out = []
    for m in muts.values():
        del m["_locaux"], m["_terrains"]
        out.append(m)
    out.sort(key=lambda m: m["d"], reverse=True)
    return out


# ---------------------------------------------------------------- programme

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("insee", nargs="?", default="44047")
    ap.add_argument("--annees", type=int, default=7, help="nombre d'années à remonter (défaut 7)")
    ap.add_argument("--fichier", action="append", default=[],
                    help="CSV DVF géolocalisé déjà téléchargé (.csv ou .csv.gz) ; répétable")
    ap.add_argument("--sortie", default=None, help="chemin du JSON produit")
    args = ap.parse_args(argv)

    insee = args.insee
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = args.sortie or os.path.join(root, "data", f"dvf-{insee}.json")

    print(f"DVF pour la commune {insee}")
    if args.fichier:
        rows = list(rows_from_files(args.fichier, insee))
    else:
        this_year = dt.date.today().year
        rows = []
        for year in range(this_year, this_year - args.annees, -1):
            rows.extend(rows_for_year(year, insee))
        if not rows:
            print("  aucun fichier par année trouvé, essai via l'API data.gouv.fr…")
            rows = list(rows_from_dataset(insee))

    if not rows:
        print("Aucune donnée DVF récupérée. Téléchargez un fichier annuel sur\n"
              "https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres-geolocalisees\n"
              "puis relancez avec --fichier <chemin>.", file=sys.stderr)
        return 1

    mutations = aggregate(rows)
    dates = sorted(m["d"] for m in mutations if m["d"])
    payload = {
        "meta": {
            "commune": insee,
            "source": "DVF géolocalisées (Etalab / DGFiP)",
            "genere_le": dt.date.today().isoformat(),
            "periode": [dates[0], dates[-1]] if dates else None,
            "mutations": len(mutations),
        },
        "mutations": mutations,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"OK → {out_path} ({len(mutations)} ventes, {payload['meta']['periode']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
