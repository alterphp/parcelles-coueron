// Lancer avec : node --test tests/parcels.test.mjs tests/dvf-plu.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { pointOnSurface, pointInRing, centroid } from "../js/parcels.js";
import { indexDvf, salesForParcel, pricePerM2, describeMutation, nearbySales, medianPricePerM2 } from "../js/dvf.js";
import { describeZone, parseGpuDate, buildability } from "../js/plu.js";

test("point intérieur d'une parcelle en U (centroïde hors parcelle)", () => {
  // U ouvert vers le haut : le centroïde tombe dans le vide central
  const u = [[0, 0], [3, 0], [3, 3], [2, 3], [2, 1], [1, 1], [1, 3], [0, 3], [0, 0]];
  const g = { type: "Polygon", coordinates: [u] };
  assert.equal(pointInRing(centroid(g), u), false);
  const p = pointOnSurface(g);
  assert.equal(pointInRing(p, u), true, `point ${p}`);
});

test("point intérieur = centroïde pour une parcelle convexe", () => {
  const sq = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]];
  assert.deepEqual(pointOnSurface({ type: "Polygon", coordinates: [sq] }), [1, 1]);
});

const dvf = indexDvf({
  meta: { periode: ["2021-03-01", "2026-06-30"] },
  mutations: [
    { id: "a", d: "2024-05-02", n: "Vente", v: 330000, p: ["P1"], l: [["Maison", 110, 5], ["Dépendance", null, 0]], t: 812, lat: 47.2100, lon: -1.7300 },
    { id: "b", d: "2021-09-10", n: "Vente", v: 250000, p: ["P1"], l: [["Maison", 110, 5]], t: 812, lat: 47.2100, lon: -1.7300 },
    { id: "c", d: "2025-01-15", n: "Vente terrain à bâtir", v: 90000, p: ["P2", "P3"], l: [], t: 1050, lat: 47.2110, lon: -1.7300 },
    { id: "d", d: "2023-11-20", n: "Vente", v: 300000, p: ["P4"], l: [["Maison", 100, 4]], t: 500, lat: 47.2120, lon: -1.7300 },
    { id: "e", d: "2022-02-02", n: "Vente", v: 280000, p: ["P5"], l: [["Maison", 140, 6]], t: 700, lat: 47.2105, lon: -1.7310 },
    { id: "f", d: "2025-06-01", n: "Vente", v: 400000, p: ["P6"], l: [["Maison", 120, 5]], t: 900, lat: 47.2500, lon: -1.7300 },
  ],
});

test("historique d'une parcelle, du plus récent au plus ancien", () => {
  assert.deepEqual(salesForParcel(dvf, "P1").map((m) => m.id), ["a", "b"]);
  assert.deepEqual(salesForParcel(dvf, "P3").map((m) => m.id), ["c"]);
  assert.deepEqual(salesForParcel(dvf, "inconnue"), []);
  assert.deepEqual(salesForParcel(null, "P1"), []);
});

test("prix au m² seulement pour un logement unique de surface connue", () => {
  assert.equal(pricePerM2(dvf.mutations[0]), 3000);
  assert.equal(pricePerM2(dvf.mutations[2]), null);
  assert.equal(describeMutation(dvf.mutations[0]), "Maison 110 m² · 5 p. · terrain 812 m²");
  assert.equal(describeMutation(dvf.mutations[2]).replace(/\s/g, " "), "Terrain · terrain 1 050 m² · 2 parcelles");
});

test("ventes de maisons voisines dans le rayon, hors parcelle courante", () => {
  const near = nearbySales(dvf, [-1.7300, 47.2100], { radius: 300, exclude: "P1" });
  assert.deepEqual(near.map((x) => x.m.id), ["d", "e"]); // c = terrain, f = trop loin
  assert.equal(near[0].dist, 223);
  assert.equal(medianPricePerM2(near), null); // moins de 3 valeurs
  const all = nearbySales(dvf, [-1.7300, 47.2100], { radius: 300 });
  assert.equal(medianPricePerM2(all), 2637); // 2000, 2273, 3000, 3000 → (2273 + 3000) / 2
});

test("description d'une zone PLUm", () => {
  const z = describeZone({ libelle: "UMd1", libelong: "Zone urbaine mixte diffuse", typezone: "U",
                           datappro: "20190405", urlfic: "https://example.org/reglement.pdf", partition: "DU_244400404" });
  assert.equal(z.code, "UMd1");
  assert.equal(z.typeLabel, "Zone urbaine");
  assert.equal(z.level, "ok");
  assert.equal(z.approved.getFullYear(), 2019);
  assert.equal(z.reglementUrl, "https://example.org/reglement.pdf");
  assert.equal(describeZone({ typezone: "N", urlfic: "reglement.pdf" }).reglementUrl, null);
  assert.equal(buildability("A").level, "bad");
  assert.equal(parseGpuDate("2019-04-05").getMonth(), 3);
  assert.equal(parseGpuDate("n/a"), null);
});
