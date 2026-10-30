"""Lecture de l'archive DVF historique d'une commune (resources/dvf-historique/dvf-<INSEE>.zip).

L'archive est produite par split_dvf_historique.py : <INSEE>.txt au format DGFiP brut et meta.json.
Ce module convertit ses lignes au schéma des DVF géolocalisées (les clés lues par aggregate() de
fetch_dvf.py), pour que l'historique et les ventes récentes de l'API passent par le même traitement.

Ce que le format DGFiP brut n'a pas, et comment il est reconstitué :
  - id_mutation : absent. Les lignes d'une vente se suivent dans le fichier : une vente est une suite
    de lignes consécutives de même date, nature et valeur foncière. Deux ventes distinctes qui se
    suivent avec les mêmes date, nature et prix sont donc confondues (rare : 25 cas non contigus sur
    5 065 couples à Couëron, tous des ventes différentes). L'identifiant « AAAA-H<n> » est propre à
    l'archive ; le « H » le distingue de ceux de l'API.
  - id_parcelle : INSEE (5) + préfixe de section (3) + section (2) + numéro de plan (4).
  - latitude, longitude : absentes, laissées vides.
  - adresse : type de voie + libellé de la voie, tels que saisis (abrégés, parfois tronqués).
"""
import json
import zipfile
from collections import Counter

# Colonnes du fichier DGFiP lues ici (le reste est ignoré).
COLONNES = ("No disposition", "Date mutation", "Nature mutation", "Valeur fonciere", "No voie", "B/T/Q",
            "Type de voie", "Voie", "Code departement", "Code commune", "Prefixe de section", "Section",
            "No plan", "1er lot", "Type local", "Surface reelle bati", "Nombre pieces principales",
            "Nature culture", "Surface terrain")


def charger(chemin, insee):
    """Lit l'archive : retourne (meta.json, lignes au schéma géolocalisé) de la commune."""
    with zipfile.ZipFile(chemin) as zf:
        meta = json.loads(zf.read("meta.json").decode("utf-8"))
        texte = zf.read(f"{insee}.txt").decode("utf-8")
    return meta, convertir(texte, insee)


def convertir(texte, insee):
    """Lignes DVF brutes (texte entier avec en-tête) → liste de dicts au schéma géolocalisé."""
    lignes = texte.split("\n")
    entete = lignes[0].rstrip("\r").split("|")
    col = {nom: i for i, nom in enumerate(entete)}
    absentes = [nom for nom in COLONNES if nom not in col]
    if absentes:
        raise ValueError(f"colonnes absentes de l'archive DVF historique : {', '.join(absentes)}")
    dep = insee[:3] if insee.startswith("97") else insee[:2]

    out, vente, precedente = [], Counter(), None
    for ligne in lignes[1:]:
        c = ligne.rstrip("\r").split("|")
        if len(c) != len(entete):
            continue  # ligne vide de fin de fichier
        v = {nom: c[col[nom]].strip() for nom in COLONNES}
        if dep + v["Code commune"].zfill(5 - len(dep)) != insee:
            continue
        jour, mois, annee = v["Date mutation"][:2], v["Date mutation"][3:5], v["Date mutation"][6:]
        if len(v["Date mutation"]) != 10 or not (jour + mois + annee).isdigit():
            raise ValueError(f"date de mutation illisible : {v['Date mutation']!r}")
        date = f"{annee}-{mois}-{jour}"

        cle = (date, v["Nature mutation"], v["Valeur fonciere"])
        if cle != precedente:
            vente[annee] += 1
            precedente = cle
        parcelle = ""
        if v["Section"] and v["No plan"]:
            parcelle = f"{insee}{v['Prefixe de section'].zfill(3)}{v['Section'].zfill(2)}{v['No plan'].zfill(4)}"
        out.append({
            "id_mutation": f"{annee}-H{vente[annee]}",
            "date_mutation": date,
            "numero_disposition": v["No disposition"],
            "nature_mutation": v["Nature mutation"],
            "valeur_fonciere": v["Valeur fonciere"],
            "adresse_numero": f"{v['No voie']} {v['B/T/Q']}".strip(),
            "adresse_nom_voie": f"{v['Type de voie']} {v['Voie']}".strip(),
            "code_commune": insee,
            "id_parcelle": parcelle,
            "lot1_numero": v["1er lot"],
            "type_local": v["Type local"],
            "surface_reelle_bati": v["Surface reelle bati"],
            "nombre_pieces_principales": v["Nombre pieces principales"],
            "nature_culture": v["Nature culture"],
            "surface_terrain": v["Surface terrain"],
            "longitude": "",
            "latitude": "",
        })
    return out
