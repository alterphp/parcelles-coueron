// Logique métier pure (aucune dépendance au DOM ni à Leaflet) : testable sous Node.

const EARTH_RADIUS = 6378137;
const RAD = Math.PI / 180;

/** Aire d'un anneau [lon, lat] en m² (approximation sphérique, suffisante à l'échelle d'une parcelle). */
export function ringArea(ring) {
  let a = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[i + 1];
    a += (x2 - x1) * RAD * (2 + Math.sin(y1 * RAD) + Math.sin(y2 * RAD));
  }
  return Math.abs((a * EARTH_RADIUS * EARTH_RADIUS) / 2);
}

function polygonsOf(geometry) {
  if (!geometry) return [];
  if (geometry.type === "Polygon") return [geometry.coordinates];
  if (geometry.type === "MultiPolygon") return geometry.coordinates;
  return [];
}

/** Aire d'un Polygon / MultiPolygon GeoJSON en m² (trous déduits). */
export function geometryArea(geometry) {
  return polygonsOf(geometry).reduce(
    (sum, poly) => sum + ringArea(poly[0]) - poly.slice(1).reduce((h, r) => h + ringArea(r), 0),
    0
  );
}

/** Centroïde [lon, lat] du plus grand polygone (centre de gravité de l'anneau extérieur). */
export function centroid(geometry) {
  const polys = polygonsOf(geometry);
  if (!polys.length) return null;
  const outer = polys.map((p) => p[0]).sort((a, b) => ringArea(b) - ringArea(a))[0];
  // Calcul relatif au premier sommet pour éviter la perte de précision sur des coordonnées absolues.
  const [ox, oy] = outer[0];
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < outer.length - 1; i++) {
    const x1 = outer[i][0] - ox, y1 = outer[i][1] - oy;
    const x2 = outer[i + 1][0] - ox, y2 = outer[i + 1][1] - oy;
    const f = x1 * y2 - x2 * y1;
    a += f; cx += (x1 + x2) * f; cy += (y1 + y2) * f;
  }
  if (Math.abs(a) < 1e-18) {
    const xs = outer.map((p) => p[0]), ys = outer.map((p) => p[1]);
    return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
  }
  return [ox + cx / (3 * a), oy + cy / (3 * a)];
}

/** Le point [lon, lat] est-il dans l'anneau (lancer de rayon) ? */
export function pointInRing([x, y], ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function pointInPolygon(pt, poly) {
  return pointInRing(pt, poly[0]) && !poly.slice(1).some((hole) => pointInRing(pt, hole));
}

/**
 * Point garanti à l'intérieur de la parcelle : le centroïde s'il y tombe, sinon le milieu
 * du plus large segment intérieur sur l'horizontale du centroïde (parcelles en L, en U…).
 * Sert de repère sur la carte et de point d'interrogation du PLUm.
 */
export function pointOnSurface(geometry) {
  const c = centroid(geometry);
  const polys = polygonsOf(geometry);
  if (!c || !polys.length) return c;
  const main = polys.slice().sort((a, b) => ringArea(b[0]) - ringArea(a[0]))[0];
  if (pointInPolygon(c, main)) return c;

  const ys = main[0].map((p) => p[1]);
  const y = c[1] > Math.min(...ys) && c[1] < Math.max(...ys) ? c[1] : (Math.min(...ys) + Math.max(...ys)) / 2;
  const xs = [];
  for (const ring of main) {
    for (let i = 0; i < ring.length - 1; i++) {
      const [x1, y1] = ring[i], [x2, y2] = ring[i + 1];
      if ((y1 > y) !== (y2 > y)) xs.push(x1 + ((y - y1) * (x2 - x1)) / (y2 - y1));
    }
  }
  xs.sort((a, b) => a - b);
  let best = null;
  for (let i = 0; i + 1 < xs.length; i += 2) {
    if (!best || xs[i + 1] - xs[i] > best[1] - best[0]) best = [xs[i], xs[i + 1]];
  }
  return best ? [(best[0] + best[1]) / 2, y] : c;
}

/** Distance en mètres entre deux points [lon, lat] (haversine). */
export function distanceMeters([lon1, lat1], [lon2, lat2]) {
  const dLat = (lat2 - lat1) * RAD, dLon = (lon2 - lon1) * RAD;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS * Math.asin(Math.sqrt(h));
}

/** Cap en degrés (0 = nord, sens horaire) de `from` vers `to`, points [lon, lat]. */
export function bearing([lon1, lat1], [lon2, lat2]) {
  const y = Math.sin((lon2 - lon1) * RAD) * Math.cos(lat2 * RAD);
  const x = Math.cos(lat1 * RAD) * Math.sin(lat2 * RAD) -
            Math.sin(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.cos((lon2 - lon1) * RAD);
  return (Math.atan2(y, x) / RAD + 360) % 360;
}

/**
 * Transforme une feature Etalab « parcelles » en objet métier.
 * Propriétés Etalab : id (14 car.), commune, prefixe, section, numero, contenance (m²)…
 * Si la contenance est absente, la surface est calculée sur la géométrie et marquée `estimated`.
 */
export function normalizeParcel(feature) {
  const p = feature.properties || {};
  const contenance = Number(p.contenance);
  const hasContenance = Number.isFinite(contenance) && contenance > 0;
  return {
    id: String(p.id || ""),
    section: String(p.section || ""),
    numero: String(p.numero || ""),
    surface: hasContenance ? contenance : Math.round(geometryArea(feature.geometry)),
    estimated: !hasContenance,
    center: pointOnSurface(feature.geometry), // toujours à l'intérieur de la parcelle
    feature,
  };
}

export function loadParcels(geojson) {
  return (geojson.features || []).filter((f) => f.geometry).map(normalizeParcel);
}

/** Filtre { min, max, section } — bornes incluses, max vide = pas de limite. */
export function filterParcels(parcels, { min = 0, max = Infinity, section = "" } = {}) {
  const lo = Number.isFinite(min) ? min : 0;
  const hi = Number.isFinite(max) ? max : Infinity;
  return parcels.filter((p) => p.surface >= lo && p.surface <= hi && (!section || p.section === section));
}

export function sortParcels(list, mode = "desc") {
  const out = list.slice();
  if (mode === "asc") out.sort((a, b) => a.surface - b.surface);
  else if (mode === "ref") out.sort((a, b) => a.id.localeCompare(b.id));
  else out.sort((a, b) => b.surface - a.surface);
  return out;
}

export function listSections(parcels) {
  return [...new Set(parcels.map((p) => p.section))].sort((a, b) => a.localeCompare(b, "fr", { numeric: true }));
}

/** Libellé lisible : « AB 123 ». */
export const label = (p) => `${p.section} ${Number(p.numero) || p.numero}`;

/** Export CSV (séparateur « ; » et BOM pour Excel FR). */
export function toCSV(list) {
  const rows = [["reference", "section", "numero", "surface_m2", "surface_estimee", "latitude", "longitude"]];
  for (const p of list) {
    rows.push([p.id, p.section, Number(p.numero) || p.numero, p.surface, p.estimated ? "oui" : "non",
      p.center ? p.center[1].toFixed(6) : "", p.center ? p.center[0].toFixed(6) : ""]);
  }
  return "﻿" + rows.map((r) => r.join(";")).join("\n");
}

/** Lecture / écriture de l'état dans le hash d'URL (#min=400&max=1000&section=AB&p=44047000AB0123). */
export function parseHash(hash) {
  const q = new URLSearchParams(String(hash).replace(/^#/, ""));
  const num = (k) => (q.has(k) && q.get(k) !== "" ? Number(q.get(k)) : undefined);
  return { min: num("min"), max: num("max"), section: q.get("section") || "", parcel: q.get("p") || "" };
}

export function buildHash({ min, max, section, parcel }) {
  const q = new URLSearchParams();
  if (Number.isFinite(min)) q.set("min", min);
  if (Number.isFinite(max)) q.set("max", max);
  if (section) q.set("section", section);
  if (parcel) q.set("p", parcel);
  return "#" + q.toString();
}
