// Lancer avec : node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ringArea, geometryArea, centroid, distanceMeters, bearing, normalizeParcel, findParcelAt,
  filterParcels, sortParcels, listSections, toCSV, parseHash, buildHash, label,
} from "../js/parcels.js";

// Carré d'environ 20 m × 20 m à Couëron (1° lat ≈ 111 320 m ; 1° lon ≈ 75 590 m à 47,2°N)
const LAT = 47.2155, LON = -1.7255;
const dLat = 20 / 111320, dLon = 20 / (111320 * Math.cos(LAT * Math.PI / 180));
const square = [[LON, LAT], [LON + dLon, LAT], [LON + dLon, LAT + dLat], [LON, LAT + dLat], [LON, LAT]];

const feat = (props, ring = square) => ({ type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: [ring] } });

test("aire d'un carré de 20 m ≈ 400 m²", () => {
  assert.ok(Math.abs(ringArea(square) - 400) < 4, `obtenu ${ringArea(square)}`);
});

test("un trou est déduit de l'aire", () => {
  const hole = square.map(([x, y]) => [LON + (x - LON) / 2 + dLon / 4, LAT + (y - LAT) / 2 + dLat / 4]);
  const a = geometryArea({ type: "Polygon", coordinates: [square, hole] });
  assert.ok(Math.abs(a - 300) < 4, `obtenu ${a}`);
});

test("centroïde au centre du carré", () => {
  const [x, y] = centroid({ type: "Polygon", coordinates: [square] });
  assert.ok(Math.abs(x - (LON + dLon / 2)) < 1e-9 && Math.abs(y - (LAT + dLat / 2)) < 1e-9);
});

test("distance et cap", () => {
  assert.ok(Math.abs(distanceMeters([LON, LAT], [LON, LAT + dLat]) - 20) < 0.2);
  assert.ok(Math.abs(bearing([LON, LAT], [LON, LAT + dLat]) - 0) < 0.5);
  assert.ok(Math.abs(bearing([LON, LAT], [LON + dLon, LAT]) - 90) < 0.5);
});

test("contenance cadastrale prioritaire, sinon surface estimée", () => {
  const a = normalizeParcel(feat({ id: "44047000AB0012", section: "AB", numero: "0012", contenance: 812 }));
  assert.equal(a.surface, 812); assert.equal(a.estimated, false); assert.equal(label(a), "AB 12");
  const b = normalizeParcel(feat({ id: "44047000AB0013", section: "AB", numero: "0013" }));
  assert.equal(b.estimated, true); assert.ok(Math.abs(b.surface - 400) <= 4);
});

test("parcelle sous un point : voisine, trou, multi-polygone, hors parcelle", () => {
  const shift = (dx) => square.map(([x, y]) => [x + dx * dLon, y]);
  const hole = square.map(([x, y]) => [LON + (x - LON) / 2 + dLon / 4, LAT + (y - LAT) / 2 + dLat / 4]);
  const A = normalizeParcel(feat({ id: "A" }));
  const B = normalizeParcel(feat({ id: "B" }, shift(1)));
  const C = normalizeParcel({ type: "Feature", properties: { id: "C" },
    geometry: { type: "Polygon", coordinates: [shift(3), hole.map(([x, y]) => [x + 3 * dLon, y])] } });
  const D = normalizeParcel({ type: "Feature", properties: { id: "D" },
    geometry: { type: "MultiPolygon", coordinates: [[shift(5)], [shift(7)]] } });
  const all = [A, B, C, D];
  const at = (dx, dy = 0.5) => findParcelAt(all, [LON + dx * dLon, LAT + dy * dLat])?.id ?? null;

  assert.equal(at(0.5), "A");
  assert.equal(at(1.5), "B");   // la voisine, pas la première de la liste
  assert.equal(at(3.1), "C");   // dans la parcelle, hors du trou
  assert.equal(at(3.5), null);  // dans le trou
  assert.equal(at(5.5), "D");
  assert.equal(at(7.5), "D");   // second polygone du MultiPolygon
  assert.equal(at(6.5), null);  // entre les deux polygones
  assert.equal(at(0.5, 2), null); // hors de toute parcelle
});

const parcels = [
  { id: "1", section: "AB", numero: "1", surface: 300 },
  { id: "2", section: "AB", numero: "2", surface: 600 },
  { id: "3", section: "ZK", numero: "3", surface: 1000 },
  { id: "4", section: "B", numero: "4", surface: 2500 },
];

test("filtre bornes incluses, max vide = sans limite, section", () => {
  assert.deepEqual(filterParcels(parcels, { min: 600, max: 1000 }).map((p) => p.id), ["2", "3"]);
  assert.deepEqual(filterParcels(parcels, { min: 1000, max: NaN }).map((p) => p.id), ["3", "4"]);
  assert.deepEqual(filterParcels(parcels, { min: 0, max: Infinity, section: "AB" }).map((p) => p.id), ["1", "2"]);
});

test("tri et sections", () => {
  assert.deepEqual(sortParcels(parcels, "desc").map((p) => p.id), ["4", "3", "2", "1"]);
  assert.deepEqual(sortParcels(parcels, "asc").map((p) => p.id), ["1", "2", "3", "4"]);
  assert.deepEqual(listSections(parcels), ["AB", "B", "ZK"]);
});

test("CSV et hash", () => {
  const csv = toCSV([{ ...parcels[0], estimated: false, center: [LON, LAT] }]);
  assert.match(csv, /^﻿reference;section/);
  assert.match(csv, /1;AB;1;300;non;47\.215500;-1\.725500/);
  const h = buildHash({ min: 400, max: NaN, section: "AB", parcel: "44047000AB0012" });
  assert.deepEqual(parseHash(h), { min: 400, max: undefined, section: "AB", parcel: "44047000AB0012" });
});
