// Lancer avec : node --test tests/address.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { pickAddress, addressLine, addressNote, fetchAddress } from "../js/address.js";

// Réponse réelle (raccourcie) du géocodage inverse de la Géoplateforme
const reply = (props) => ({ type: "FeatureCollection", features: [{ type: "Feature", properties: props }] });
const REAL = { label: "1 Impasse Morville-Babin 44220 Couëron", name: "1 Impasse Morville-Babin", postcode: "44220", city: "Couëron", type: "housenumber", distance: 13 };

test("adresse extraite d'une réponse de l'API", () => {
  const a = pickAddress(reply(REAL), 100);
  assert.deepEqual(a, { street: "1 Impasse Morville-Babin", city: "44220 Couëron", distance: 13 });
  assert.equal(addressLine(a), "1 Impasse Morville-Babin, 44220 Couëron");
});

test("aucun résultat, résultat sans nom ou trop éloigné → null", () => {
  assert.equal(pickAddress({ features: [] }, 100), null);
  assert.equal(pickAddress({}, 100), null);
  assert.equal(pickAddress(null, 100), null);
  assert.equal(pickAddress(reply({ ...REAL, name: "" }), 100), null);
  assert.equal(pickAddress(reply({ ...REAL, distance: 101 }), 100), null);
  assert.equal(pickAddress(reply({ ...REAL, distance: 100 }), 100).distance, 100);   // borne incluse
});

test("distance absente : adresse conservée, sans mention de proximité", () => {
  const a = pickAddress(reply({ ...REAL, distance: undefined }), 100);
  assert.equal(a.distance, null);
  assert.equal(addressNote(a), "");
});

test("mention « adresse la plus proche » seulement si elle est un peu loin", () => {
  assert.equal(addressNote({ distance: 13 }), "");
  assert.equal(addressNote({ distance: 30 }), "");
  assert.equal(addressNote({ distance: 45 }), "adresse la plus proche, à 45 m");
});

test("requête : coordonnées, index adresse, numéros seulement ; erreur HTTP levée", async () => {
  const seen = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url) => { seen.push(url); return { ok: true, json: async () => reply(REAL) }; };
  try {
    const a = await fetchAddress([-1.7375, 47.2208], { api: "https://x/geocodage", maxDistance: 100 });
    assert.equal(a.street, "1 Impasse Morville-Babin");
    assert.equal(seen[0], "https://x/geocodage/reverse?lon=-1.7375&lat=47.2208&index=address&type=housenumber&limit=1");
    globalThis.fetch = async () => ({ ok: false, status: 503 });
    await assert.rejects(fetchAddress([0, 0], { api: "https://x", maxDistance: 100 }), /HTTP 503/);
  } finally {
    globalThis.fetch = realFetch;
  }
});
