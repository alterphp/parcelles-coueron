// Aperçu au niveau de la rue : Panoramax (sans clé) et Google Street View (clé optionnelle).
import { distanceMeters, bearing } from "./parcels.js";

/**
 * Cherche la photo Panoramax la plus proche d'un point (API STAC /api/search).
 * `place_position` attend « lon,lat ». La distance est revérifiée côté client.
 * @returns {Promise<null | {id, img, date, position:[lon,lat], distance, heading, viewerUrl}>}
 */
export async function findPanoramax([lon, lat], { api, viewer, radius }, signal) {
  const url = `${api}/api/search?place_position=${lon},${lat}&place_distance=0-${radius}&limit=5`;
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`Panoramax HTTP ${res.status}`);
  const json = await res.json();

  const items = (json.features || [])
    .filter((f) => f.geometry?.coordinates)
    .map((f) => ({ f, d: distanceMeters([lon, lat], f.geometry.coordinates) }))
    .filter((x) => x.d <= radius * 1.5)
    .sort((a, b) => a.d - b.d);
  if (!items.length) return null;

  const { f, d } = items[0];
  const a = f.assets || {};
  const position = f.geometry.coordinates;
  return {
    id: f.id,
    img: a.sd?.href || a.thumb?.href || a.hd?.href || null,
    date: f.properties?.datetime || null,
    position,
    distance: Math.round(d),
    heading: Math.round(bearing(position, [lon, lat])), // direction photo → parcelle
    viewerUrl: `${viewer}/#focus=pic&pic=${encodeURIComponent(f.id)}&map=19/${position[1]}/${position[0]}`,
  };
}

/** URL d'intégration Google Street View (Maps Embed API, clé requise). */
export function googleEmbedUrl(key, [lon, lat]) {
  return `https://www.google.com/maps/embed/v1/streetview?key=${encodeURIComponent(key)}` +
    `&location=${lat},${lon}&fov=80&pitch=0`;
}

/** Lien universel Google Maps qui ouvre Street View au plus près du point (aucune clé). */
export function googleLinkUrl([lon, lat]) {
  return `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${lat},${lon}`;
}
