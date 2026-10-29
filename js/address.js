// Adresse d'une parcelle. Le cadastre n'en porte pas : on interroge le géocodage inverse de la
// Géoplateforme IGN (Base Adresse Nationale, sans clé) au point intérieur de la parcelle et on
// retient l'adresse numérotée la plus proche.

/** Adresse numérotée la plus proche de [lon, lat], ou null s'il n'y en a pas à `maxDistance` mètres. */
export async function fetchAddress([lon, lat], { api, maxDistance }, signal) {
  const res = await fetch(`${api}/reverse?lon=${lon}&lat=${lat}&index=address&type=housenumber&limit=1`, { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return pickAddress(await res.json(), maxDistance);
}

/** Premier résultat de l'API → { street, city, distance } ; null si aucun résultat ou trop éloigné. */
export function pickAddress(json, maxDistance = Infinity) {
  const p = json?.features?.[0]?.properties;
  if (!p?.name) return null;
  const distance = Number.isFinite(Number(p.distance)) ? Math.round(Number(p.distance)) : null;
  if (distance != null && distance > maxDistance) return null;
  return { street: p.name, city: [p.postcode, p.city].filter(Boolean).join(" "), distance };
}

/** « 1 Impasse Morville-Babin, 44220 Couëron » */
export const addressLine = (a) => [a.street, a.city].filter(Boolean).join(", ");

/** Mention à afficher quand l'adresse est un peu loin du centre de la parcelle : ce peut être celle d'une voisine. */
export function addressNote(a, nearby = 30) {
  return a.distance != null && a.distance > nearby ? `adresse la plus proche, à ${a.distance} m` : "";
}
