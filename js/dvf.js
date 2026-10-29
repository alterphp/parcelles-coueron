// Ventes immobilières DVF : chargement du fichier préparé par scripts/fetch_dvf.py,
// index par parcelle et recherche des ventes voisines. Fonctions pures sauf loadDvf().
import { distanceMeters } from "./parcels.js";

/** Charge data/dvf-<insee>.json ; renvoie null si le fichier n'a pas été préparé. */
export async function loadDvf(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return indexDvf(await res.json());
  } catch {
    return null;
  }
}

/** Construit { meta, mutations, byParcel: Map<id_parcelle, mutation[]> }. */
export function indexDvf(json) {
  const mutations = json.mutations || [];
  const byParcel = new Map();
  for (const m of mutations) {
    for (const pid of m.p || []) {
      if (!byParcel.has(pid)) byParcel.set(pid, []);
      byParcel.get(pid).push(m);
    }
  }
  for (const list of byParcel.values()) list.sort((a, b) => b.d.localeCompare(a.d));
  return { meta: json.meta || {}, mutations, byParcel };
}

export function salesForParcel(index, parcelId) {
  return index?.byParcel.get(parcelId) || [];
}

/** Locaux principaux d'une mutation (hors dépendances). */
export function mainLocals(m) {
  return (m.l || []).filter(([type]) => type === "Maison" || type === "Appartement");
}

/**
 * Prix au m² bâti, seulement quand la vente porte sur un seul logement de surface connue
 * (sinon la valeur foncière couvre plusieurs biens et le ratio n'a pas de sens).
 * Il inclut la valeur du terrain : c'est un indicateur, pas une estimation.
 */
export function pricePerM2(m) {
  const locals = mainLocals(m);
  if (!m.v || locals.length !== 1 || !locals[0][1]) return null;
  return Math.round(m.v / locals[0][1]);
}

/** Résumé lisible du bien vendu : « Maison 110 m² · 5 p. · terrain 812 m² ». */
export function describeMutation(m) {
  const parts = [];
  const locals = mainLocals(m);
  if (locals.length === 1) {
    const [type, surf, rooms] = locals[0];
    parts.push(surf ? `${type} ${surf} m²` : type);
    if (rooms) parts.push(`${rooms} p.`);
  } else if (locals.length > 1) {
    parts.push(`${locals.length} logements`);
  } else if (!(m.l || []).length) {
    parts.push("Terrain");
  } else {
    parts.push((m.l[0] || [])[0] || "Bien");
  }
  if (m.t) parts.push(`terrain ${m.t.toLocaleString("fr-FR")} m²`);
  if ((m.p || []).length > 1) parts.push(`${m.p.length} parcelles`);
  return parts.join(" · ");
}

/**
 * Ventes voisines d'un point [lon, lat] : par défaut les maisons, dans un rayon donné,
 * hors parcelle courante, les plus récentes d'abord.
 */
export function nearbySales(index, point, { radius = 300, types = ["Maison"], exclude = "", limit = 6 } = {}) {
  if (!index) return [];
  const out = [];
  for (const m of index.mutations) {
    if (m.lat == null || m.lon == null || (m.p || []).includes(exclude)) continue;
    if (types.length && !mainLocals(m).some(([t]) => types.includes(t))) continue;
    const dist = distanceMeters(point, [m.lon, m.lat]);
    if (dist <= radius) out.push({ m, dist: Math.round(dist) });
  }
  out.sort((a, b) => b.m.d.localeCompare(a.m.d) || a.dist - b.dist);
  return out.slice(0, limit);
}

/** Médiane du prix au m² des ventes fournies (null si moins de 3 valeurs). */
export function medianPricePerM2(sales) {
  const values = sales.map(({ m }) => pricePerM2(m)).filter((v) => v != null).sort((a, b) => a - b);
  if (values.length < 3) return null;
  const mid = Math.floor(values.length / 2);
  return values.length % 2 ? values[mid] : Math.round((values[mid - 1] + values[mid]) / 2);
}
