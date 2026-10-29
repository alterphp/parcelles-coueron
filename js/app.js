// Point d'entrée : chargement des données, filtres, carte, liste et panneau d'aperçu rue.
/* global L */
import { CONFIG } from "./config.js";
import * as P from "./parcels.js";
import { createBaseLayers, createCadastreLayer } from "./layers.js";
import { findPanoramax, googleEmbedUrl, googleLinkUrl } from "./streetview.js";
import * as DVF from "./dvf.js";
import { fetchPluZones, describeZone, gpuMapUrl } from "./plu.js";

const $ = (id) => document.getElementById(id);
const fmt = (n) => Number(n).toLocaleString("fr-FR");
const euros = (n) => Number(n).toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const longDate = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
const monthYear = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const state = {
  all: [],            // toutes les parcelles normalisées
  matches: [],        // parcelles éligibles, triées
  byId: new Map(),
  selected: null,
  streetAbort: null,  // AbortController de la requête Panoramax en cours
  pluAbort: null,     // AbortController de la requête PLUm en cours
  dvf: undefined,     // index DVF : undefined = en cours de chargement, null = indisponible
};

/* ------------------------------------------------------------------ Carte */

const map = L.map("map", { preferCanvas: true }).setView(CONFIG.commune.centre, CONFIG.commune.zoom);
const bases = createBaseLayers();
bases["Satellite IGN (orthophoto)"].addTo(map);
const cadastre = createCadastreLayer().addTo(map);

const featureToParcel = new WeakMap();
const eligibleLayer = L.geoJSON(null, {
  style: () => ({ color: token("--match"), weight: 1.5, fillColor: token("--match"), fillOpacity: 0.3 }),
  onEachFeature: (feature, layer) => {
    const p = featureToParcel.get(feature);
    layer.bindTooltip(`${P.label(p)} · ${fmt(p.surface)} m²`, { sticky: true, className: "parcel-tip" });
    layer.on("click", () => select(p, { fit: false }));
  },
}).addTo(map);

const selectedLayer = L.geoJSON(null, {
  interactive: false,
  style: () => ({ color: token("--select"), weight: 3, fill: false }),
}).addTo(map);

const viewpointLayer = L.layerGroup().addTo(map);

// Contour de la zone PLUm contenant la parcelle sélectionnée (non cliquable).
const pluLayer = L.geoJSON(null, {
  interactive: false,
  style: () => ({ color: token("--plu"), weight: 2.5, dashArray: "8 6", fill: true, fillColor: token("--plu"), fillOpacity: 0.06 }),
}).addTo(map);

// Ventes DVF voisines de la parcelle sélectionnée.
const salesLayer = L.layerGroup().addTo(map);

// Marqueurs des parcelles éligibles : un rond au centre de chaque parcelle, pour les repérer
// quand la carte est dézoomée. Pane dédié au-dessus des contours ; en SVG pour que les clics
// hors des ronds atteignent les parcelles en dessous. Masqués au-delà de CONFIG.markers.maxZoom.
const markerPane = map.createPane("parcelMarkers");
markerPane.style.zIndex = 450;
markerPane.style.pointerEvents = "none";
const markerRenderer = L.svg({ pane: "parcelMarkers" });
const markerLayer = L.layerGroup().addTo(map);

function syncMarkerVisibility() {
  markerPane.style.display = map.getZoom() <= CONFIG.markers.maxZoom ? "" : "none";
}
map.on("zoomend", syncMarkerVisibility);
syncMarkerVisibility();

L.control.layers(bases, {
  "Plan cadastral IGN": cadastre,
  "Parcelles éligibles": eligibleLayer,
  [`Marqueurs (zoom ≤ ${CONFIG.markers.maxZoom})`]: markerLayer,
  "Point de vue de la photo": viewpointLayer,
  "Zone PLUm de la parcelle": pluLayer,
  "Ventes voisines (DVF)": salesLayer,
}, { collapsed: window.matchMedia("(max-width: 900px)").matches }).addTo(map);
L.control.scale({ imperial: false }).addTo(map);

const legend = L.control({ position: "bottomright" });
legend.onAdd = () => {
  const div = L.DomUtil.create("div", "legend");
  div.innerHTML = '<span><i class="l-match"></i>Parcelle éligible</span>' +
                  '<span><i class="l-marker"></i>Repère de parcelle éligible</span>' +
                  '<span><i class="l-select"></i>Parcelle sélectionnée</span>' +
                  '<span><i class="l-photo"></i>Position de la photo</span>' +
                  '<span><i class="l-plu"></i>Zone PLUm</span>' +
                  '<span><i class="l-sale"></i>Vente voisine (DVF)</span>';
  return div;
};
legend.addTo(map);

/* -------------------------------------------------------------- Données */

async function parseBuffer(buffer) {
  const bytes = new Uint8Array(buffer, 0, 2);
  let text;
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
    // Fichier .gz brut (le serveur n'a pas décompressé à la volée)
    const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
    text = await new Response(stream).text();
  } else {
    text = new TextDecoder().decode(buffer);
  }
  return JSON.parse(text);
}

async function loadData() {
  const errors = [];
  for (const src of CONFIG.dataSources) {
    try {
      setStatus("Chargement du cadastre…");
      const res = await fetch(src);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      ingest(await parseBuffer(await res.arrayBuffer()));
      return;
    } catch (e) {
      errors.push(`${src} → ${e.message}`);
      console.warn("Source indisponible :", src, e);
    }
  }
  setStatus('<span class="err">Le cadastre n\'a pas pu être chargé.</span>', true);
  const link = $("fallbackLink");
  link.href = CONFIG.dataSources[CONFIG.dataSources.length - 1];
  $("fallback").hidden = false;
  console.error(errors.join("\n"));
}

$("file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  setStatus("Lecture du fichier…");
  try {
    ingest(await parseBuffer(await file.arrayBuffer()));
    $("fallback").hidden = true;
  } catch (err) {
    setStatus(`<span class="err">Fichier illisible : ${err.message}</span>`, true);
  }
});

function ingest(geojson) {
  state.all = P.loadParcels(geojson);
  state.byId = new Map(state.all.map((p) => [p.id, p]));
  state.all.forEach((p) => featureToParcel.set(p.feature, p));

  const sel = $("section");
  for (const s of P.listSections(state.all)) sel.add(new Option(s, s));

  // Cadrage sur l'emprise de la commune. Sans animation : Leaflet ignore tout zoom demandé
  // pendant une animation, ce qui empêcherait le zoom sur une parcelle passée dans l'URL.
  const pts = state.all.filter((p) => p.center).map((p) => [p.center[1], p.center[0]]);
  if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [20, 20], animate: false });

  const wanted = P.parseHash(location.hash).parcel; // lu avant que apply() ne réécrive le hash
  readHash();
  apply();
  if (wanted && state.byId.has(wanted)) select(state.byId.get(wanted));
}

/* ------------------------------------------------------------- Filtres */

function readFilter() {
  const num = (id) => ($(id).value === "" ? NaN : Number($(id).value));
  return { min: num("min"), max: num("max"), section: $("section").value };
}

function readHash() {
  const h = P.parseHash(location.hash);
  const hasFilter = h.min !== undefined || h.max !== undefined;
  $("min").value = hasFilter ? h.min ?? "" : CONFIG.defaultFilter.min;
  $("max").value = hasFilter ? h.max ?? "" : CONFIG.defaultFilter.max;
  $("section").value = h.section;
}

function writeHash() {
  const f = readFilter();
  history.replaceState(null, "", P.buildHash({ ...f, parcel: state.selected?.id }));
}

function apply() {
  if (!state.all.length) return;
  const f = readFilter();
  state.matches = P.sortParcels(P.filterParcels(state.all, f), $("sort").value);

  eligibleLayer.clearLayers();
  eligibleLayer.addData(state.matches.map((p) => p.feature));
  renderMarkers();

  const range = Number.isFinite(f.max)
    ? `entre ${fmt(f.min || 0)} et ${fmt(f.max)} m²`
    : `de ${fmt(f.min || 0)} m² ou plus`;
  const where = f.section ? ` en section ${f.section}` : "";
  setStatus(`<b>${fmt(state.matches.length)}</b> parcelles ${range}${where} sur ${fmt(state.all.length)}`, true);
  $("export").disabled = state.matches.length === 0;

  renderPresets();
  renderList();
  writeHash();
}

function renderMarkers() {
  markerLayer.clearLayers();
  const style = {
    renderer: markerRenderer,
    radius: CONFIG.markers.radius,
    color: token("--panel"), weight: 1.5,
    fillColor: token("--match"), fillOpacity: 0.95,
  };
  for (const p of state.matches) {
    if (!p.center) continue;
    L.circleMarker([p.center[1], p.center[0]], style)
      .bindTooltip(`${P.label(p)} · ${fmt(p.surface)} m²`, { className: "parcel-tip" })
      .on("click", () => select(p))
      .addTo(markerLayer);
  }
}

function renderPresets() {
  const box = $("presets");
  const f = readFilter();
  box.innerHTML = "";
  for (const [lo, hi] of CONFIG.presets) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = hi == null ? `≥ ${fmt(lo)}` : `${fmt(lo)}–${fmt(hi)}`;
    const active = f.min === lo && (hi == null ? !Number.isFinite(f.max) : f.max === hi);
    b.setAttribute("aria-pressed", String(active));
    b.addEventListener("click", () => {
      $("min").value = lo;
      $("max").value = hi ?? "";
      apply();
    });
    box.append(b);
  }
}

function renderList() {
  const ol = $("list");
  const frag = document.createDocumentFragment();
  for (const p of state.matches.slice(0, CONFIG.listLimit)) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.id = p.id;
    if (state.selected === p) b.setAttribute("aria-current", "true");
    b.innerHTML = `<span>${P.label(p)}</span><span class="surf">${fmt(p.surface)} m²` +
                  `${p.estimated ? '<span class="est" title="Surface calculée sur la géométrie">est.</span>' : ""}</span>`;
    b.addEventListener("click", () => select(p));
    li.append(b);
    frag.append(li);
  }
  if (state.matches.length > CONFIG.listLimit) {
    const li = document.createElement("li");
    li.className = "more";
    li.textContent = `… et ${fmt(state.matches.length - CONFIG.listLimit)} autres sur la carte. Affinez le filtre pour les lister.`;
    frag.append(li);
  }
  ol.replaceChildren(frag);
}

function setStatus(html, isHtml = false) {
  if (isHtml) $("status").innerHTML = html;
  else $("status").textContent = html;
}

let debounce;
["min", "max"].forEach((id) => $(id).addEventListener("input", () => {
  clearTimeout(debounce);
  debounce = setTimeout(apply, 250);
}));
$("section").addEventListener("change", apply);
$("sort").addEventListener("change", apply);
$("filters").addEventListener("submit", (e) => { e.preventDefault(); apply(); });

$("export").addEventListener("click", () => {
  const blob = new Blob([P.toCSV(state.matches)], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  const f = readFilter();
  a.href = URL.createObjectURL(blob);
  a.download = `parcelles-${CONFIG.commune.nom.toLowerCase()}-${f.min || 0}-${Number.isFinite(f.max) ? f.max : "plus"}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

/* ---------------------------------------------------------- Sélection */

function select(p, { fit = true } = {}) {
  state.selected = p;
  selectedLayer.clearLayers().addData(p.feature);

  document.body.classList.add("has-street");
  $("street").hidden = false;
  map.invalidateSize();
  if (fit) {
    map.fitBounds(selectedLayer.getBounds(), { maxZoom: 19, padding: [60, 60] });
    // Sur mobile, la carte est au-dessus de la liste : la ramener à l'écran.
    if (window.matchMedia("(max-width: 900px)").matches) {
      document.getElementById("map").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  document.querySelectorAll('.list button[aria-current="true"]').forEach((b) => b.removeAttribute("aria-current"));
  const row = document.querySelector(`.list button[data-id="${CSS.escape(p.id)}"]`);
  if (row) { row.setAttribute("aria-current", "true"); row.scrollIntoView({ block: "nearest" }); }

  $("streetTitle").textContent = `Parcelle ${P.label(p)}`;
  $("streetMeta").textContent = `${fmt(p.surface)} m²${p.estimated ? " (estimée)" : ""} · réf. ${p.id}`;
  renderLinks(p);
  loadPanoramax(p);
  renderGoogle(p);
  loadPlu(p);
  renderDvf(p);
  writeHash();
}

function closeStreet() {
  state.selected = null;
  state.streetAbort?.abort();
  state.pluAbort?.abort();
  selectedLayer.clearLayers();
  viewpointLayer.clearLayers();
  pluLayer.clearLayers();
  salesLayer.clearLayers();
  $("street").hidden = true;
  document.body.classList.remove("has-street");
  $("paneGsv").replaceChildren();
  map.invalidateSize();
  document.querySelectorAll('.list button[aria-current="true"]').forEach((b) => b.removeAttribute("aria-current"));
  writeHash();
}
$("closeStreet").addEventListener("click", closeStreet);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.selected) closeStreet(); });

function renderLinks(p) {
  const [lon, lat] = p.center;
  const geoportail = `https://www.geoportail.gouv.fr/carte?c=${lon},${lat}&z=19` +
    "&l0=ORTHOIMAGERY.ORTHOPHOTOS::GEOPORTAIL:OGC:WMTS(1)" +
    "&l1=CADASTRALPARCELS.PARCELLAIRE_EXPRESS::GEOPORTAIL:OGC:WMTS(1)&permalink=yes";
  const links = [
    ["Géoportail", geoportail],
    ["Google Maps", `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`],
    ["Street View", googleLinkUrl(p.center)],
  ];
  $("streetLinks").replaceChildren(...links.map(([text, href]) => {
    const a = document.createElement("a");
    a.href = href; a.target = "_blank"; a.rel = "noopener"; a.textContent = `${text} ↗`;
    return a;
  }));
}

/* ---------------------------------------------------------- Urbanisme (PLUm) */

async function loadPlu(p) {
  const body = $("pluBody");
  state.pluAbort?.abort();
  const ctrl = new AbortController();
  state.pluAbort = ctrl;
  pluLayer.clearLayers();
  body.innerHTML = '<p class="muted">Interrogation du Géoportail de l\'Urbanisme…</p>';
  const mapLink = `<p><a href="${gpuMapUrl(p.center)}" target="_blank" rel="noopener">Voir sur le Géoportail de l'Urbanisme ↗</a></p>`;

  try {
    const features = await fetchPluZones(p.center, CONFIG.plu, ctrl.signal);
    if (ctrl.signal.aborted) return;
    if (!features.length) {
      body.innerHTML = "<p>Aucun zonage trouvé à cet endroit.</p>" + mapLink;
      return;
    }
    const html = features.map((f) => {
      const z = describeZone(f.properties);
      const approved = z.approved ? ` · approuvé le ${z.approved.toLocaleDateString("fr-FR")}` : "";
      return `<div class="zone">
          <span class="zone__code">${esc(z.code)}</span>
          <div class="zone__text">
            <b>${esc(z.name || z.typeLabel)}</b>
            <span class="muted">${esc(z.typeLabel)}${approved}</span>
            <span class="pill pill--${z.level}">${esc(z.text)}</span>
            ${z.reglementUrl ? `<a href="${esc(z.reglementUrl)}" target="_blank" rel="noopener">Règlement de la zone ↗</a>` : ""}
          </div>
        </div>`;
    }).join("");
    body.innerHTML = html + mapLink;
    pluLayer.addData(features.filter((f) => f.geometry));
  } catch (e) {
    if (e.name === "AbortError") return;
    body.innerHTML = `<p>Le Géoportail de l'Urbanisme ne répond pas (${esc(e.message)}).</p>` + mapLink;
  }
}

/* ---------------------------------------------------------- Ventes (DVF) */

function saleHtml(m, extra = "") {
  const ppm = DVF.pricePerM2(m);
  const nature = m.n && m.n !== "Vente" ? ` · ${esc(m.n)}` : "";
  return `<li class="sale">
      <div class="sale__head"><span>${longDate(m.d)}${nature}</span><b>${m.v ? euros(m.v) : "montant non publié"}</b></div>
      <div class="sale__desc">${esc(DVF.describeMutation(m))}${ppm ? ` · <span class="nowrap">${fmt(ppm)} €/m² bâti</span>` : ""}</div>
      ${extra}
    </li>`;
}

function renderDvf(p) {
  const body = $("dvfBody");
  salesLayer.clearLayers();
  if (state.dvf === undefined) {
    body.innerHTML = '<p class="muted">Chargement des ventes…</p>';
    return;
  }
  if (state.dvf === null) {
    body.innerHTML = `<p>Les données de ventes ne sont pas installées.</p>
      <p class="muted">Lancez <code>python3 scripts/fetch_dvf.py</code> pour les préparer, ou consultez
      <a href="https://explore.data.gouv.fr/fr/immobilier" target="_blank" rel="noopener">l'explorateur DVF ↗</a>.</p>`;
    return;
  }

  const period = state.dvf.meta.periode;
  const since = period ? monthYear(period[0]) : "";
  const until = period ? monthYear(period[1]) : "";
  const own = DVF.salesForParcel(state.dvf, p.id);
  let html = `<p class="muted">Ventes publiées de ${since} à ${until}.</p>`;
  html += own.length
    ? `<h4>Sur cette parcelle</h4><ul class="sales">${own.map((m) => saleHtml(m)).join("")}</ul>`
    : "<p>Aucune vente enregistrée sur cette parcelle sur la période.</p>";

  const { radius, types, limit } = CONFIG.dvf.nearby;
  const near = DVF.nearbySales(state.dvf, p.center, { radius, types, limit: 500, exclude: p.id });
  const median = DVF.medianPricePerM2(near);
  html += `<h4>${types.join(" et ")}s vendues à moins de ${radius} m</h4>`;
  if (near.length) {
    html += `<p>${near.length} vente${near.length > 1 ? "s" : ""}` +
            (median ? ` · prix médian <b>${fmt(median)} €/m²</b> bâti (terrain inclus)` : "") + "</p>";
    html += `<ul class="sales">${near.slice(0, limit).map(({ m, dist }) =>
      saleHtml(m, `<div class="sale__where muted">${esc(m.a || "Adresse non publiée")} · à ${dist} m</div>`)).join("")}</ul>`;
    for (const { m } of near) {
      L.circleMarker([m.lat, m.lon], {
        radius: 5, color: token("--panel"), weight: 1.5, fillColor: token("--dvf"), fillOpacity: 0.95,
      }).bindTooltip(`${longDate(m.d)} · ${m.v ? euros(m.v) : "?"}<br>${esc(DVF.describeMutation(m))}`)
        .addTo(salesLayer);
    }
  } else {
    html += "<p>Aucune vente comparable dans ce rayon.</p>";
  }
  body.innerHTML = html;
}

/* ---------------------------------------------------------- Aperçu rue */

async function loadPanoramax(p) {
  const pane = $("panePnx");
  state.streetAbort?.abort();
  const ctrl = new AbortController();
  state.streetAbort = ctrl;
  viewpointLayer.clearLayers();
  pane.innerHTML = '<div class="skeleton"></div><p class="muted">Recherche de la photo de rue la plus proche…</p>';

  try {
    const photo = await findPanoramax(p.center, CONFIG.streetView.panoramax, ctrl.signal);
    if (ctrl.signal.aborted) return;
    if (!photo) {
      pane.innerHTML = `<p>Aucune photo Panoramax à moins de ${CONFIG.streetView.panoramax.radius} m de cette parcelle.</p>` +
                       '<p class="muted">Essayez l\'onglet Google Street View.</p>';
      return;
    }
    const date = photo.date
      ? new Date(photo.date).toLocaleDateString("fr-FR", { month: "long", year: "numeric" })
      : "date inconnue";
    pane.innerHTML = "";
    if (photo.img) {
      const a = document.createElement("a");
      a.href = photo.viewerUrl; a.target = "_blank"; a.rel = "noopener";
      const img = document.createElement("img");
      img.className = "shot"; img.src = photo.img; img.loading = "lazy";
      img.alt = `Vue de la rue près de la parcelle ${P.label(p)}`;
      a.append(img);
      pane.append(a);
    }
    const info = document.createElement("p");
    info.innerHTML = `Photo prise à <b>${photo.distance} m</b> de la parcelle, ${date}.`;
    const open = document.createElement("p");
    open.innerHTML = `<a href="${photo.viewerUrl}" target="_blank" rel="noopener">Ouvrir la vue immersive Panoramax ↗</a>`;
    pane.append(info, open);

    // Point de vue sur la carte : position de la photo et ligne vers la parcelle
    const from = [photo.position[1], photo.position[0]];
    const to = [p.center[1], p.center[0]];
    L.polyline([from, to], { color: token("--select"), weight: 2, dashArray: "4 4", interactive: false }).addTo(viewpointLayer);
    L.circleMarker(from, { radius: 6, color: token("--select"), weight: 2, fillColor: token("--panel"), fillOpacity: 1 })
      .bindTooltip("Position de la photo")
      .addTo(viewpointLayer);
  } catch (e) {
    if (e.name === "AbortError") return;
    pane.innerHTML = `<p>Le service Panoramax ne répond pas (${e.message}).</p>`;
  }
}

function renderGoogle(p) {
  const pane = $("paneGsv");
  const key = CONFIG.streetView.googleEmbedApiKey;
  if (key) {
    // L'iframe n'est créée que si l'onglet est visible, pour ne pas consommer de quota inutilement.
    pane.dataset.src = googleEmbedUrl(key, p.center);
    if (!pane.hidden) mountGoogleFrame();
    else pane.replaceChildren();
  } else {
    delete pane.dataset.src;
    pane.innerHTML =
      `<p>Ouvrez Google Street View au plus près de la parcelle :</p>
       <p><a class="btn btn--primary" href="${googleLinkUrl(p.center)}" target="_blank" rel="noopener">Voir dans Street View ↗</a></p>
       <p class="muted">Pour afficher Street View directement ici, ajoutez une clé « Maps Embed API » dans <code>js/config.js</code>.</p>`;
  }
}

function mountGoogleFrame() {
  const pane = $("paneGsv");
  if (!pane.dataset.src || pane.querySelector("iframe")?.src === pane.dataset.src) return;
  const frame = document.createElement("iframe");
  frame.className = "gsv";
  frame.src = pane.dataset.src;
  frame.loading = "lazy";
  frame.allowFullscreen = true;
  frame.referrerPolicy = "no-referrer-when-downgrade";
  frame.title = "Google Street View";
  pane.replaceChildren(frame);
}

/* --------------------------------------------------------------- Onglets */

const tabs = [["tabPnx", "panePnx"], ["tabGsv", "paneGsv"]];
for (const [tabId, paneId] of tabs) {
  $(tabId).addEventListener("click", () => {
    for (const [t, pn] of tabs) {
      $(t).setAttribute("aria-selected", String(t === tabId));
      $(pn).hidden = pn !== paneId;
    }
    if (paneId === "paneGsv") mountGoogleFrame();
  });
}

/* ---------------------------------------------------------------- Démarrage */

window.addEventListener("hashchange", () => { if (state.all.length) { readHash(); apply(); } });
loadData();
DVF.loadDvf(CONFIG.dvf.url).then((index) => {
  state.dvf = index;
  if (state.selected) renderDvf(state.selected);
});
