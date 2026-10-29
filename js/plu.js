// Zonage du PLUm (Plan Local d'Urbanisme métropolitain de Nantes Métropole)
// via l'API Carto « Géoportail de l'Urbanisme » de l'IGN.

/** Libellés des types de zone du standard CNIG. */
export const TYPEZONE = {
  U: "Zone urbaine",
  AUc: "Zone à urbaniser (ouverte)",
  AUs: "Zone à urbaniser (fermée)",
  AU: "Zone à urbaniser",
  A: "Zone agricole",
  N: "Zone naturelle et forestière",
};

/** Constructibilité indicative selon le type de zone (le règlement fait foi). */
export function buildability(typezone) {
  if (typezone === "U" || typezone === "AUc") return { level: "ok", text: "Constructible selon le règlement de zone" };
  if (typezone === "AUs" || typezone === "AU") return { level: "warn", text: "Urbanisation future, soumise à évolution du PLUm" };
  if (typezone === "A" || typezone === "N") return { level: "bad", text: "Construction neuve très limitée" };
  return { level: "unknown", text: "Consulter le règlement" };
}

/** « 20190405 » ou « 2019-04-05 » → Date, sinon null. */
export function parseGpuDate(value) {
  const s = String(value || "").replace(/-/g, "");
  if (!/^\d{8}$/.test(s)) return null;
  const d = new Date(`${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T00:00:00`);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Normalise les propriétés d'une zone renvoyée par l'API. */
export function describeZone(props = {}) {
  const typezone = props.typezone || "";
  const url = String(props.urlfic || "");
  return {
    code: props.libelle || "?",
    name: props.libelong || "",
    typezone,
    typeLabel: TYPEZONE[typezone] || typezone || "Type inconnu",
    approved: parseGpuDate(props.datappro || props.datvalid),
    reglementUrl: /^https?:\/\//.test(url) ? url : null,
    partition: props.partition || "",
    ...buildability(typezone),
  };
}

/**
 * Zones d'urbanisme au point [lon, lat]. Renvoie les features GeoJSON (avec géométrie).
 * L'API accepte une géométrie GeoJSON dans le paramètre `geom`.
 */
export async function fetchPluZones([lon, lat], { api }, signal) {
  const geom = encodeURIComponent(JSON.stringify({ type: "Point", coordinates: [lon, lat] }));
  const res = await fetch(`${api}/zone-urba?geom=${geom}`, { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();
  return (json.features || []).filter((f) => f.properties);
}

/** Lien vers la carte du Géoportail de l'Urbanisme centrée sur le point. */
export function gpuMapUrl([lon, lat]) {
  return `https://www.geoportail-urbanisme.gouv.fr/map/#tile=1&lon=${lon}&lat=${lat}&zoom=18`;
}
