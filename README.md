# Parcelles de Couëron

Page web cartographique qui affiche les parcelles cadastrales de Couëron (INSEE 44047) répondant à un critère de surface, avec :

- **fonds de carte** : satellite IGN (orthophoto), satellite Esri, Plan IGN, OpenStreetMap ; le zoom est limité au zoom maximal du fond actif (19 pour tous aujourd'hui, au-delà les tuiles n'existent plus) ;
- **couche cadastrale** IGN (Parcellaire Express : limites, numéros, bâti) superposable à n'importe quel fond, désactivée par défaut ; une fois activée, un clic sur n'importe quelle parcelle de la commune (éligible ou non) la sélectionne et ouvre son panneau de détails ;
- **parcelles éligibles** en surbrillance, filtrées par surface min/max et section cadastrale ;
- **repères ronds** au centre de chaque parcelle éligible pour les localiser dézoomé, masqués au-delà du zoom 17 (réglable dans `config.js`, `markers`) ;
- **adresse** de la parcelle sélectionnée (adresse numérotée la plus proche, à 100 m au plus), dans le panneau de détails et dans l'infobulle fixe posée sur la parcelle ;
- **aperçu de rue** de la parcelle sélectionnée : photo Panoramax la plus proche (avec sa position sur la carte) et Google Street View (intégré si une clé est configurée, sinon lien) ;
- **urbanisme** de la parcelle sélectionnée : zone du PLUm de Nantes Métropole (code, libellé, type, date d'approbation, constructibilité indicative, lien vers le règlement) et contour de la zone sur la carte ;
- **ventes DVF** : historique des ventes de la parcelle, ventes de maisons à moins de 300 m (avec prix médian au m² et repères sur la carte) ;
- liste triable, export CSV, et URL partageable (`#min=600&max=1000&section=AB&p=44047000AB0006`).

Aucune étape de build : HTML, CSS et JavaScript (modules ES) servis tels quels. Seule dépendance : Leaflet 1.9.4 via cdnjs.

## Démarrer

```sh
./scripts/fetch-data.sh        # copie locale du cadastre dans data/ (recommandé)
python3 scripts/fetch_dvf.py   # ventes DVF de la commune → data/dvf-44047.json
python3 -m http.server 8084    # les modules ES exigent un serveur HTTP (pas file://)
# → http://localhost:8084
```

Sans copie locale, la page télécharge le cadastre directement depuis cadastre.data.gouv.fr. Si les deux échouent, elle propose de charger le fichier à la main. Sans fichier DVF, le bloc « Ventes » indique la commande à lancer ; le reste de la page fonctionne.

Tests (sans dépendance) :

```sh
node --test tests/parcels.test.mjs tests/dvf-plu.test.mjs tests/address.test.mjs   # logique de la page (Node ≥ 18)
python3 -m unittest discover -s tests                        # script de préparation DVF
```

## Structure

```
index.html            Structure de la page (barre de filtres, carte, panneau d'aperçu rue)
css/style.css         Styles, thème clair/sombre, mise en page mobile
js/config.js          ⚙ Commune, sources de données, plages prédéfinies, clés — seul fichier à adapter
js/parcels.js         Logique pure : surfaces, centroïdes, filtre, tri, CSV, état d'URL (testée)
js/layers.js          Fonds de carte et couche cadastrale (WMTS Géoplateforme IGN, Esri, OSM)
js/streetview.js      Recherche Panoramax (API STAC) et URLs Google Street View
js/plu.js             Zonage PLUm via l'API Carto GPU, libellés et constructibilité indicative
js/dvf.js             Index des ventes DVF par parcelle, ventes voisines, prix au m² (testé)
js/app.js             Chargement des données, rendu carte/liste, sélection, panneau de la parcelle
scripts/fetch-data.sh Téléchargement du cadastre Etalab pour une commune
scripts/fetch_dvf.py  Préparation des ventes DVF d'une commune (Python, bibliothèque standard)
scripts/dvf_historique.py        Lecture de l'archive DVF 2014-2023 d'une commune (schéma des DVF géolocalisées)
scripts/split_dvf_historique.py  Archive les DVF nationaux (2014-2023) d'un département, un fichier par commune
tests/                Tests unitaires (node:test et unittest)
data/                 Cadastre et DVF préparés localement (non versionnés)
resources/dvf-historique/  Archive zip DVF 2014-2023 de Couëron, lue par fetch_dvf.py (voir son README)
.github/workflows/    Publication sur GitHub Pages avec mise à jour mensuelle des données
```

## Données et services

| Usage | Source | Clé |
|---|---|---|
| Parcelles (géométrie + contenance) | [Cadastre Etalab](https://cadastre.data.gouv.fr/datasets/cadastre-etalab), GeoJSON par commune | non |
| Orthophoto, Plan IGN, plan cadastral | [Géoplateforme IGN](https://geoservices.ign.fr/) — WMTS `data.geopf.fr` | non |
| Satellite alternatif | Esri World Imagery | non (usage raisonnable) |
| Adresse de la parcelle | [Géocodage inverse de la Géoplateforme IGN](https://geoservices.ign.fr/documentation/services/services-geoplateforme/geocodage) (Base Adresse Nationale) — `data.geopf.fr/geocodage/reverse` | non |
| Photos de rue | [Panoramax](https://panoramax.fr/) — `api.panoramax.xyz/api/search` | non |
| Zonage PLUm | [API Carto, module Géoportail de l'Urbanisme](https://apicarto.ign.fr/) — `api/gpu/zone-urba?geom=…` | non |
| Ventes immobilières | [DVF géolocalisées](https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres-geolocalisees) (Etalab / DGFiP), préparées par `scripts/fetch_dvf.py` | non |
| Street View intégré | Google [Maps Embed API](https://developers.google.com/maps/documentation/embed/embedding-map), mode `streetview` | **oui** |

**Surface utilisée** : la *contenance* cadastrale (surface fiscale, en m²). Quand elle manque, la surface est calculée sur la géométrie et signalée « est. » dans la liste et « estimée » dans le panneau. Ce n'est ni la surface habitable ni forcément l'emprise d'une propriété, qui peut regrouper plusieurs parcelles.

### Lire les ventes DVF

- DVF couvre les **ventes** (pas les donations ni successions), mises à jour deux fois par an. Relancez `scripts/fetch_dvf.py` après chaque mise à jour.
- Le script demande les ventes **depuis le 1er janvier 2014** (`--depuis AAAA-MM-JJ` pour changer la date), mais Etalab / la DGFiP ne publient que les 5 dernières années environ : à ce jour, rien avant janvier 2021. Les années sans donnée sont signalées et ignorées ; la période réellement couverte figure dans `meta.periode` du fichier produit.
- **Historique 2014-2023.** Les ventes jusqu'au 31/12/2023 viennent de l'archive `resources/dvf-historique/dvf-<INSEE>.zip` (fichiers DGFiP archivés, Couëron seule est versionnée) ; l'API n'est interrogée que pour les ventes **à partir du 1er janvier 2024** (date lue dans le `meta.json` de l'archive et rappelée dans `meta.historique.jusqu_au`). Le JSON `data/dvf-44047.json` est recréé à chaque déploiement, il n'est pas versionné. Ces ventes anciennes **n'ont pas de coordonnées** : elles figurent dans l'historique de leur parcelle mais pas dans les ventes voisines ni dans le prix médian, ce que la page indique. `--sans-historique` ignore l'archive.
- Le **prix au m²** n'est affiché que pour une vente d'un seul logement de surface connue. Il divise le prix total par la surface bâtie : la valeur du terrain y est incluse. C'est un repère de comparaison, pas une estimation.
- Sources, par priorité : les **ressources annuelles ou semestrielles de data.gouv.fr** (livraison la plus récente : ventes tardives, parcelles à jour par rapport au cadastre actuel ; fichiers nationaux de 50 à 140 Mo, soit environ 3 minutes), puis, pour les périodes qu'elles ne couvrent pas (janvier-juin 2021), les fichiers par commune ou par département de l'ancien chemin `geo-dvf/latest`, annoncé comme supprimé fin 2026. Une période n'est lue que dans une seule source : les identifiants de vente changent d'une livraison à l'autre. Si tout échoue, téléchargez un fichier annuel à la main et passez-le avec `--fichier chemin.csv.gz`.

### Lire le zonage PLUm

- La zone est celle qui contient un point situé **à l'intérieur** de la parcelle. Une grande parcelle peut être à cheval sur deux zones : vérifiez sur le Géoportail de l'Urbanisme (lien dans le panneau).
- La mention de constructibilité est déduite du type de zone (U, AU, A, N). **Seul le règlement de la zone fait foi** (hauteurs, emprise, reculs, servitudes, OAP…).

### Activer Google Street View intégré

1. Dans Google Cloud Console, activez **Maps Embed API** et créez une clé.
2. Restreignez-la par référent HTTP au domaine du site.
3. Renseignez `streetView.googleEmbedApiKey` dans `js/config.js`.

L'iframe n'est chargée que lorsque l'onglet Google est ouvert. Sans clé, l'onglet propose un lien qui ouvre Street View dans un nouvel onglet.

## Publier sur GitHub Pages

Le workflow `.github/workflows/pages.yml` lance les tests, retélécharge le cadastre et les ventes DVF, puis publie le site. Il tourne à chaque push sur `main`, le 2 de chaque mois, et à la demande.

1. Créez un dépôt sur GitHub (par exemple `parcelles-coueron`) et poussez-y le projet :
   ```sh
   git init && git add . && git commit -m "Carte des parcelles"
   git branch -M main
   git remote add origin https://github.com/<votre-compte>/parcelles-coueron.git
   git push -u origin main
   ```
2. Dans le dépôt : **Settings → Pages → Build and deployment → Source : GitHub Actions**.
3. Onglet **Actions** → « Publier la carte » → **Run workflow** (ou attendez le premier push).
4. La carte est en ligne à `https://<votre-compte>.github.io/parcelles-coueron/`.

À savoir :

- **Dépôt public** requis pour Pages avec un compte gratuit (privé possible avec GitHub Pro). Le site publié est toujours public, même depuis un dépôt privé.
- **Données non versionnées** : elles sont reconstruites à chaque publication. Si une source ne répond pas, le workflow réutilise la version déjà en ligne et le signale par un avertissement dans le journal de l'Action.
- **Mise en veille** : GitHub désactive les tâches planifiées d'un dépôt public après 60 jours sans activité, et prévient par e-mail. Il suffit de la réactiver dans l'onglet Actions, ou de pousser un commit.
- **Clé Google** : `js/config.js` est publié tel quel. Si vous y mettez une clé Maps Embed API, restreignez-la au référent `https://<votre-compte>.github.io/*` dans Google Cloud Console.
- La date de la dernière publication des données est visible à `…/data-version.txt`.

## Adapter à une autre commune

Dans `js/config.js`, changez `INSEE`, `commune.nom` et `commune.centre`, puis lancez `./scripts/fetch-data.sh <INSEE>` et `python3 scripts/fetch_dvf.py <INSEE>`. Sur GitHub, changez aussi `INSEE` dans `.github/workflows/pages.yml`. Pour la Corse (2A/2B) et les DOM (971…), corrigez le calcul du code département.

## Points à vérifier en conditions réelles

Les tests ont été faits avec un jeu de parcelles fictif et des services simulés ; les points suivants n'ont pas pu être contrôlés contre les vrais serveurs :

- **CORS de cadastre.data.gouv.fr** : si le téléchargement direct échoue dans le navigateur, utilisez la copie locale (`scripts/fetch-data.sh`) — c'est de toute façon recommandé en production.
- **Format du lien Panoramax** (`#focus=pic&pic=<id>&map=19/lat/lon`) et noms des images (`assets.sd`, `thumb`, `hd`) : à confirmer sur une parcelle réelle.
- **Style de la couche cadastrale** (`PCI vecteur`) : si les tuiles ne s'affichent pas, consulter le GetCapabilities WMTS de `data.geopf.fr` pour le nom exact du style.
- **API Carto GPU** : appel GET avec `geom` et noms des champs (`libelle`, `libelong`, `typezone`, `datappro`, `urlfic`) ; lien vers la carte du Géoportail de l'Urbanisme.
- **Emplacements des fichiers DVF** : voir « Lire les ventes DVF ».
- **Volume** : environ 15 à 20 000 parcelles attendues pour Couëron ; le rendu Canvas de Leaflet le supporte, mais au-delà (agglomération entière), passer à des tuiles vectorielles (MapLibre GL + PMTiles).

## Pistes d'évolution

- Croiser avec le **bâti** (Etalab `batiments`) pour ne garder que les parcelles construites ou calculer l'emprise bâtie.
- Afficher les **prescriptions et servitudes** du PLUm (API Carto : `prescription-surf`, `assiette-sup-s`) : espaces boisés classés, zones inondables (PPRI Loire), etc.
- Filtrer les parcelles par **type de zone PLUm** (n'afficher que les zones U).
- Regrouper les parcelles contiguës d'un même compte de propriété (donnée non publique : nécessite les fichiers fonciers).


## Données DVF

Les données facilement trouvables correspondent aux 5 dernières années (glissantes). Cependant des archives des données précédemment publiées sont disponibles (ex: http://data.cquest.org/dgfip_dvf/202504/).
