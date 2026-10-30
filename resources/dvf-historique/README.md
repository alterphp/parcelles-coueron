# DVF historique – Loire-Atlantique (2014-2023)

Ventes immobilières déclarées en Loire-Atlantique (département 44), du 2 janvier 2014 au
31 décembre 2023 : 826 215 lignes, 221 communes.

Ces années ne sont plus publiées par la DGFiP sur data.gouv.fr (fenêtre glissante de cinq ans) :
cette copie est donc à conserver, elle ne peut pas être retéléchargée depuis la source officielle.

## Contenu du dossier

| Fichier | Versionné | Rôle |
|---|---|---|
| `dvf-44047.zip` (168 Ko) | oui | Couëron seule. Lu par `scripts/fetch_dvf.py` au déploiement. |
| `dvf-44.zip` (13 Mo) | **non** (`.gitignore`) | Les 221 communes du département : copie d'archivage locale. |

Chaque zip contient `<INSEE>.txt` (un fichier par commune, `44047.txt` pour Couëron, `44109.txt`
pour Nantes) et un `meta.json`. Les zips sont compressés pour ne pas exposer adresses et prix en
clair dans un dépôt public ; `dvf-44.zip` n'est pas versionné, car il couvre toutes les communes.

## Date couverte

`meta.json` garde la trace de la date jusqu'à laquelle l'historique est complet :

```json
{ "periode": ["2014-01-03", "2023-12-29"], "couvert_jusqu_au": "2023-12-31", ... }
```

- `periode` : première et dernière vente présentes (pour Couëron, la dernière est du 29 décembre 2023 ;
  pour tout le département, du 31 décembre 2023).
- `couvert_jusqu_au` : **31 décembre 2023**. C'est la limite que lit `scripts/fetch_dvf.py` : l'API
  DVF n'est interrogée que pour les ventes du **1er janvier 2024** et après, et ses ventes antérieures
  sont écartées pour ne pas les compter deux fois.

Pour étendre l'historique à une nouvelle année, régénérer les zips avec le fichier de cette année
(voir « Régénérer »), `couvert_jusqu_au` avance de lui-même.

## Utilisation par la page

La page ne lit pas ce dossier. `python3 scripts/fetch_dvf.py` (lancé par le workflow Pages) :

1. lit `dvf-44047.zip` et convertit les lignes au schéma des DVF géolocalisées
   (`scripts/dvf_historique.py`), puis les agrège comme celles de l'API ;
2. demande à l'API les ventes depuis le lendemain de `couvert_jusqu_au` ;
3. écrit un seul `data/dvf-44047.json` (non versionné), créé à chaque déploiement.

`meta.historique.jusqu_au` du JSON produit rappelle la date de l'archive.

**Les ventes de l'archive n'ont pas de coordonnées** (le fichier DGFiP n'en contient pas) : elles
apparaissent dans l'historique de leur parcelle, mais pas dans les ventes voisines, sur la carte ni
dans le prix médian, qui ne portent que sur 2024 et après. La page l'indique.

## Validation

Les DVF géolocalisées d'Etalab (`geo-dvf`) sont encore en ligne pour 2021 à 2023, ce qui permet de
vérifier la conversion de l'archive pour Couëron : **1 479 ventes sur 1 480 sont identiques** (date,
valeur, parcelles, maisons, surface de terrain). L'écart est celui décrit plus haut : deux
appartements vendus le même jour au même prix (79 000 €, 22/09/2022, boulevard des Martyrs de la
Résistance), regroupés en une seule vente. 95 % des parcelles de l'archive existent encore dans le
cadastre actuel (99,7 % pour les ventes de l'API) ; les autres ont été divisées ou renumérotées depuis
la vente, et la page les affiche grisées.

## Origine

Fichiers nationaux « Demandes de valeurs foncières » de la DGFiP, tels qu'archivés par
[data.cquest.org/dgfip_dvf](http://data.cquest.org/dgfip_dvf/), un dossier par livraison. Chaque
livraison remplace la précédente et ajoute des ventes tardives aux années déjà publiées : chaque année
est lue dans **une seule** livraison.

| Années | Livraison | Fichiers |
|---|---|---|
| 2014 – 2017 | `201904` (avril 2019) | `valeursfoncieres-AAAA.txt` |
| 2018 – 2020 | `202204` (avril 2022) | `valeursfoncieres-AAAA.txt` |
| 2021 – 2023 | `202504` (avril 2025) | `valeursfoncieres-AAAA.txt.zip` (contient `ValeursFoncieres-AAAA.txt`) |

L'année 2018 de la livraison `201904` est incomplète (fichier national d'environ 30 % plus petit que
dans `202204`) : elle n'est pas utilisée. Pour 2015 à 2017, les fichiers nationaux de `201904`
diffèrent de moins de 1 % en taille de ceux des livraisons suivantes ; quelques ventes tardives
peuvent donc manquer pour ces années.

| Année | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 |
|---|---|---|---|---|---|---|---|---|---|---|
| Lignes | 62 173 | 63 787 | 71 981 | 86 379 | 83 014 | 90 797 | 82 758 | 104 004 | 100 624 | 80 698 |

## Format des `.txt`

Format DGFiP conservé tel quel, voir la notice descriptive du fichier DVF : texte UTF-8, séparateur
`|`, virgule décimale, dates `JJ/MM/AAAA`, 43 colonnes. En-tête sur la première ligne de chaque
fichier, puis les lignes de 2014 à 2023 dans l'ordre chronologique des fichiers sources. Une ligne
correspond à une disposition × une parcelle × un local : une vente porte souvent plusieurs lignes.
Il n'existe pas d'identifiant de vente : les sept premières colonnes (« Reference document »,
« Articles CGI ») sont vides sur toutes les lignes, et « No disposition », qui vient ensuite,
ne distingue pas deux ventes. `scripts/dvf_historique.py` regroupe les lignes consécutives de même
date, nature et valeur foncière (deux ventes distinctes qui se suivent avec les mêmes trois valeurs
seraient confondues ; c'est rare).

À savoir :

- **Le code commune n'est pas complété par des zéros** dans les données (`47` et non `047`, pour
  Couëron). Le code INSEE d'une ligne est `44` + « Code commune » sur 3 chiffres.
- La première colonne, vide sur toutes les lignes, s'appelle « Code service CH » dans l'en-tête
  (livraisons jusqu'en 2020) ; la DGFiP l'a renommée « Identifiant de document » dans les fichiers 2021+.
  L'en-tête conservé est celui du premier fichier (« Code service CH »).
- La « Valeur fonciere » est celle de la vente entière, répétée sur chaque ligne de la vente.
- Les adresses sont celles saisies par la DGFiP : type de voie abrégé (« RUE », « BD », « IMP »…),
  libellé parfois tronqué.
- DVF ne couvre que les ventes (ni donations ni successions) et exclut l'Alsace, la Moselle et Mayotte.

## Communes fusionnées

Les fichiers sont rangés par le code de commune présent dans les données. Il y a 207 communes
actuelles et **14 anciens codes**, de communes depuis fusionnées. Leurs ventes sont absentes du fichier
de la commune qui les a absorbées ; pour une série continue, il faut réunir les deux fichiers.

| Code | Commune (nom DVF) | Années présentes |
|---|---|---|
| 44004 | ANETZ | 2014 – 2016 |
| 44008 | BARBECHAT | 2014 – 2016 |
| 44011 | BELLIGNE | 2014 – 2016 |
| 44017 | BONNOEUVRE | 2014 – 2018 |
| 44034 | LA CHAPELLE ST SAUVEUR | 2014 – 2016 |
| 44040 | CHEMERE | 2014 – 2016 |
| 44059 | FRESNAY-EN-RETZ | 2014 – 2015 |
| 44060 | FRESNE-SUR-LOIRE (LE) | 2014 – 2022 |
| 44093 | MAUMUSSON | 2014 – 2018 |
| 44147 | ROUXIERE (LA) | 2014 – 2016 |
| 44160 | SAINT-GEREON | 2014 – 2018 |
| 44181 | SAINT-MEME-LE-TENU | 2014 – 2016 |
| 44191 | SAINT-SULPICE-DES-LANDES | 2014 – 2018 |
| 44219 | VRITZ | 2014 – 2018 |

## Réutilisation

Ces données relèvent des [conditions générales d'utilisation de la DGFiP](http://data.cquest.org/dgfip_dvf/conditions-generales-dutilisation-20201016.pdf) :
leur réutilisation ne doit permettre ni la ré-identification des personnes, même indirecte, ni
l'indexation des données par les moteurs de recherche externes. Les fichiers contiennent adresses,
parcelles et prix. Mesures prises : archives compressées et zip du département hors du dépôt.

## Régénérer

```sh
# télécharger les fichiers (≈ 3 Go) dans un dossier de travail, décompresser les .zip de 202504, puis :
python3 scripts/split_dvf_historique.py \
  201904/valeursfoncieres-201{4,5,6,7}.txt 202204/valeursfoncieres-20{18,19,20}.txt \
  202504/ValeursFoncieres-202{1,2,3}.txt --commune 44047
```

Produit `dvf-44.zip` et `dvf-44047.zip` ici. Le script prend quelques minutes, la compression des
107 Mo en étant l'essentiel ; il accepte `--departement`, `--sortie`, `--commune` (répétable) et `--couvert-jusqu-au`.
