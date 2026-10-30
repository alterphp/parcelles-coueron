#!/usr/bin/env python3
"""Prépare data/dvf-<INSEE>.json à partir des DVF géolocalisées (Etalab, data.gouv.fr).

Usage : python3 scripts/fetch_dvf.py [code_insee] [--depuis AAAA-MM-JJ]
        (défaut : 44047, Couëron ; ventes depuis le 1er janvier 2014)

Le fichier produit contient une entrée par mutation (vente) de la commune, avec les
parcelles concernées. La page web l'indexe par parcelle pour afficher l'historique des
ventes et les ventes voisines.

Historique : si resources/dvf-historique/dvf-<INSEE>.zip existe (voir split_dvf_historique.py), les
ventes jusqu'à la date « couvert_jusqu_au » de son meta.json en proviennent (DVF DGFiP archivées,
sans coordonnées) et les sources ci-dessous ne sont interrogées que pour les ventes postérieures.
--sans-historique l'ignore.

Sources de l'API, par ordre de priorité (les id_mutation changent d'une livraison à l'autre : une période
n'est lue que dans une seule source, sinon les ventes seraient comptées deux fois) :
  1. ressources full-<an>[-s1|-s2].csv.gz du jeu de données data.gouv.fr (API) : fichiers nationaux de
     50 à 140 Mo filtrés à la volée sur la commune. C'est la livraison la plus récente : ventes tardives
     et identifiants de parcelles à jour par rapport au cadastre actuel.
  2. pour les périodes que 1. ne couvre pas (ou dont le téléchargement a échoué) : fichier par commune
     puis par département, geo-dvf/latest/csv/<an>/communes/<dep>/<insee>.csv et .../departements/<dep>.csv.gz
     (petits, rapides ; chemin annoncé comme archive, supprimé fin 2026 ; couvre encore janvier-juin 2021)
  3. en dernier recours, si rien n'a été trouvé : ressources dont le nom n'est pas reconnu
     (par exemple le fichier unique multi-années)
data.gouv.fr réorganise ces fichiers : si tout échoue, téléchargez le fichier annuel à la main
et passez-le avec --fichier (plusieurs fois possible).

DVF n'est publié que pour les dernières années (depuis janvier 2021 à ce jour) : les années
sans donnée, avant comme après l'historique, sont signalées et ignorées.

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

import dvf_historique

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORIQUE = os.path.join(ROOT, "resources", "dvf-historique")  # dvf-<INSEE>.zip
BASE = "https://files.data.gouv.fr/geo-dvf/latest/csv"
DATASET_API = "https://www.data.gouv.fr/api/1/datasets/demandes-de-valeurs-foncieres-geolocalisees/"
DEPUIS = "2014-01-01"  # début de la période demandée par défaut
RESOURCE_RE = re.compile(r"full-(\d{4})(?:-s([12]))?\.csv\.gz$")
UA = {"User-Agent": "parcelles-coueron/0.1 (script de préparation DVF)"}


# ---------------------------------------------------------------- téléchargement

def open_url(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300)


def read_rows(stream, gz):
    """Lit un CSV DVF (éventuellement gzip) ligne à ligne, sans tout charger en mémoire."""
    raw = gzip.GzipFile(fileobj=stream) if gz else stream
    yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))


def rows_for_year(year, insee):
    """Lignes DVF de la commune pour l'année, ou None si aucun fichier n'est publié."""
    dep = insee[:3] if insee.startswith("97") else insee[:2]
    candidates = [
        (f"{BASE}/{year}/communes/{dep}/{insee}.csv", False),
        (f"{BASE}/{year}/departements/{dep}.csv.gz", True),
    ]
    for url, gz in candidates:
        try:
            with open_url(url) as resp:
                print(f"  {year} : {url}")
                return [r for r in read_rows(resp, gz) if r.get("code_commune") == insee]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"  {year} : {url} → HTTP {e.code}", file=sys.stderr)
        except urllib.error.URLError as e:
            print(f"  {year} : {url} → {e.reason}", file=sys.stderr)
    return None


def dataset_resources():
    """Ressources CSV du jeu de données (API data.gouv.fr) : liste de (période, titre, url).

    La période (début, fin) en dates ISO est déduite du nom « full-AAAA[-s1|-s2].csv.gz » ;
    elle vaut None pour un fichier qui ne suit pas ce nommage (fichier unique multi-années…).
    """
    try:
        with open_url(DATASET_API) as resp:
            meta = json.load(resp)
    except Exception as e:  # noqa: BLE001
        print(f"  API data.gouv.fr indisponible : {e}", file=sys.stderr)
        return []
    out = []
    for res in meta.get("resources", []):
        url = res.get("url") or ""
        if not url.endswith(".csv.gz"):
            continue
        m = RESOURCE_RE.search(url)
        period = None
        if m:
            year, half = m.group(1), m.group(2)
            period = (f"{year}-07-01" if half == "2" else f"{year}-01-01",
                      f"{year}-06-30" if half == "1" else f"{year}-12-31")
        out.append((period, res.get("title", ""), url))
    return out


def rows_from_resource(url, insee):
    """Lignes de la commune dans une ressource nationale (lue en flux), ou None en cas d'échec."""
    try:
        with open_url(url) as resp:
            return [r for r in read_rows(resp, True) if r.get("code_commune") == insee]
    except Exception as e:  # noqa: BLE001
        print(f"    échec : {e}", file=sys.stderr)
        return None


def rows_from_file(path, insee):
    print(f"  fichier local : {path}")
    with open(path, "rb") as fh:
        return [r for r in read_rows(fh, path.endswith(".gz")) if r.get("code_commune") == insee]


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


# ---------------------------------------------------------------- collecte

def span(years):
    """[2020, 2019, 2017] → « 2017, 2019–2020 »."""
    runs = []
    for y in sorted(years):
        if runs and y == runs[-1][1] + 1:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in runs)


def collect(insee, depuis):
    """Récupère les lignes DVF de la commune depuis `depuis` (voir la docstring du module).

    Retourne (lots, années sans donnée) : un lot de lignes par fichier source, à agréger séparément
    car les id_mutation ne sont pas comparables d'un fichier à l'autre.
    """
    since = depuis.isoformat()
    years = range(dt.date.today().year, depuis.year - 1, -1)
    resources = dataset_resources()
    batches, covered, got = [], [], set()

    for period, title, url in resources:
        if period is None or period[1] < since:
            continue
        print(f"  ressource : {title} ({url})")
        rows = rows_from_resource(url, insee)
        if rows is not None:
            batches.append(rows)
            covered.append(period)
            got.add(int(period[0][:4]))

    def has_period(start, end):
        return any(p[0] <= start and end <= p[1] for p in covered)

    for year in years:
        if has_period(f"{year}-01-01", f"{year}-06-30") and has_period(f"{year}-07-01", f"{year}-12-31"):
            continue  # année entièrement couverte par l'API
        rows = rows_for_year(year, insee)
        if rows is not None:
            # Les ventes d'une période déjà lue dans l'API ne sont pas reprises : doublons sinon.
            batches.append([r for r in rows
                            if not any(p[0] <= r.get("date_mutation", "") <= p[1] for p in covered)])
            got.add(year)

    if not any(batches):
        for period, title, url in resources:
            if period is None:
                print(f"  ressource : {title} ({url})")
                rows = rows_from_resource(url, insee)
                if rows is not None:
                    batches.append(rows)
        got.update(int(r["date_mutation"][:4]) for b in batches for r in b if r.get("date_mutation"))

    return batches, [y for y in years if y not in got]


# ---------------------------------------------------------------- historique

def historique(insee, depuis):
    """Ventes de l'archive resources/dvf-historique/dvf-<INSEE>.zip, à partir de `depuis`.

    Retourne (meta.json de l'archive, lignes au schéma géolocalisé, première date à demander à l'API) :
    le lendemain de « couvert_jusqu_au ». Sans archive, ou si `depuis` lui est postérieur,
    retourne (None, [], depuis).
    """
    chemin = os.path.join(HISTORIQUE, f"dvf-{insee}.zip")
    if not os.path.exists(chemin):
        return None, [], depuis
    meta, rows = dvf_historique.charger(chemin, insee)
    jusqu_au = dt.date.fromisoformat(meta["couvert_jusqu_au"])
    if depuis > jusqu_au:
        return None, [], depuis
    debut, fin = depuis.isoformat(), jusqu_au.isoformat()
    rows = [r for r in rows if debut <= r["date_mutation"] <= fin]
    api_depuis = jusqu_au + dt.timedelta(days=1)
    print(f"  historique : {chemin} (ventes jusqu'au {fin}, {len(rows)} lignes) ; "
          f"l'API n'est interrogée qu'à partir du {api_depuis}")
    return meta, rows, api_depuis


# ---------------------------------------------------------------- programme

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("insee", nargs="?", default="44047")
    ap.add_argument("--depuis", type=dt.date.fromisoformat, default=dt.date.fromisoformat(DEPUIS),
                    metavar="AAAA-MM-JJ", help=f"date de la plus ancienne vente conservée (défaut {DEPUIS})")
    ap.add_argument("--fichier", action="append", default=[],
                    help="CSV DVF géolocalisé déjà téléchargé (.csv ou .csv.gz) ; répétable")
    ap.add_argument("--sans-historique", action="store_true",
                    help="ignore l'archive resources/dvf-historique : toutes les ventes viennent de l'API")
    ap.add_argument("--sortie", default=None, help="chemin du JSON produit")
    args = ap.parse_args(argv)

    insee = args.insee
    out_path = args.sortie or os.path.join(ROOT, "data", f"dvf-{insee}.json")

    print(f"DVF pour la commune {insee}")
    hist_meta, hist_rows, depuis = (None, [], args.depuis) if args.sans_historique \
        else historique(insee, args.depuis)
    if args.fichier:
        batches, missing = [rows_from_file(path, insee) for path in args.fichier], []
    else:
        batches, missing = collect(insee, depuis)
    if missing:
        print(f"  Pas de donnée DVF publiée pour {span(missing)} (DVF ne couvre que les dernières années).")

    # Les fichiers annuels débordent parfois de la date demandée.
    since = depuis.isoformat()
    batches = [[r for r in b if (r.get("date_mutation") or since) >= since] for b in batches]

    if not any(batches):
        print(f"Aucune donnée DVF récupérée à partir du {since}. Téléchargez un fichier annuel sur\n"
              "https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres-geolocalisees\n"
              "puis relancez avec --fichier <chemin>.", file=sys.stderr)
        return 1

    anciennes = aggregate(hist_rows)
    mutations = sorted(anciennes + [m for b in batches for m in aggregate(b)], key=lambda m: m["d"], reverse=True)
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
    if hist_meta:
        payload["meta"]["historique"] = {
            "source": "DVF DGFiP archivées (resources/dvf-historique), sans coordonnées",
            "jusqu_au": hist_meta["couvert_jusqu_au"],
            "mutations": len(anciennes),
        }
        payload["meta"]["geolocalisees_depuis"] = since
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"OK → {out_path} ({len(mutations)} ventes, {payload['meta']['periode']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
