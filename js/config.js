// Configuration du projet : c'est le seul fichier à modifier pour changer de commune ou de sources.

const INSEE = "44047"; // Couëron
const DEPT = INSEE.slice(0, 2); // ⚠ Corse (2A/2B) et DOM (971…) : adapter le code département.

export const CONFIG = {
  commune: {
    insee: INSEE,
    nom: "Couëron",
    centre: [47.2155, -1.7255], // [lat, lon]
    zoom: 14,
  },

  // Sources essayées dans l'ordre : copie locale (scripts/fetch-data.sh), puis cadastre Etalab en ligne.
  dataSources: [
    `data/cadastre-${INSEE}-parcelles.json.gz`,
    `https://cadastre.data.gouv.fr/data/etalab-cadastre/latest/geojson/communes/${DEPT}/${INSEE}/cadastre-${INSEE}-parcelles.json.gz`,
  ],

  defaultFilter: { min: 400, max: 600 },
  presets: [[300, 600], [600, 1000], [1000, 2000], [2000, null]],
  // Repères ronds au centre des parcelles éligibles, visibles jusqu'à ce niveau de zoom inclus
  // (au-delà, les contours suffisent). Rayon en pixels.
  markers: { maxZoom: 17, radius: 6 },

  listLimit: 500, // lignes affichées dans la liste (toutes restent sur la carte et dans l'export)

  // Ventes immobilières : fichier préparé par `python3 scripts/fetch_dvf.py`.
  dvf: {
    url: `data/dvf-${INSEE}.json`,
    nearby: { radius: 300, types: ["Maison"] }, // ventes voisines : toutes listées dans le panneau (zone défilante)
  },

  // Adresse de la parcelle : géocodage inverse de la Géoplateforme IGN (BAN), sans clé.
  // Au-delà de maxDistance mètres du centre de la parcelle, aucune adresse n'est affichée.
  address: { api: "https://data.geopf.fr/geocodage", maxDistance: 100 },

  // Zonage PLUm : API Carto, module Géoportail de l'Urbanisme (IGN), sans clé.
  plu: { api: "https://apicarto.ign.fr/api/gpu" },
};
