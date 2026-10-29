// Fonds de carte et couches raster (Leaflet).
/* global L */

const IGN_WMTS = "https://data.geopf.fr/wmts";

/**
 * Couche tuilée du Géoplateforme IGN (WMTS, projection Web Mercator « PM »).
 * `maxZoom` = `maxNativeZoom` : pas de sur-agrandissement des tuiles au-delà du dernier niveau servi.
 */
function ignLayer(layer, { style = "normal", format = "image/png", maxNativeZoom = 19, maxZoom = maxNativeZoom, ...opts } = {}) {
  const url = `${IGN_WMTS}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0` +
    `&LAYER=${layer}&STYLE=${encodeURIComponent(style)}&TILEMATRIXSET=PM` +
    `&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=${encodeURIComponent(format)}`;
  return L.tileLayer(url, {
    maxZoom, maxNativeZoom,
    attribution: '© <a href="https://geoservices.ign.fr/" target="_blank" rel="noopener">IGN</a>',
    ...opts,
  });
}

/**
 * Fonds de carte. Le `maxZoom` de chacun est le dernier niveau où il affiche quelque chose autour de la
 * commune (vérifié sur Couëron) : au-delà, les tuiles IGN répondent 404, Esri sert une tuile « donnée
 * indisponible » et OSM une erreur. La carte limite son zoom à celui du fond actif (voir app.js).
 */
export function createBaseLayers() {
  return {
    "Satellite IGN (orthophoto)": ignLayer("ORTHOIMAGERY.ORTHOPHOTOS", { format: "image/jpeg", maxNativeZoom: 19 }),
    "Satellite Esri": L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 19, attribution: "Tiles © Esri — Esri, Maxar, Earthstar Geographics" }
    ),
    "Plan IGN": ignLayer("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", { maxNativeZoom: 19 }),
    "OpenStreetMap": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
    }),
  };
}

/** Plan cadastral IGN (Parcellaire Express) : limites, numéros de parcelles et bâti, fond transparent. */
export function createCadastreLayer() {
  return ignLayer("CADASTRALPARCELS.PARCELLAIRE_EXPRESS", {
    style: "PCI vecteur", maxNativeZoom: 19, opacity: 0.9, zIndex: 5,
  });
}
