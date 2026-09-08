/*
 * FIT Editor
 * Copyright (C) 2026 K. Hochkirch
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import { ChartStack, formatDuration } from './chart.js';
import { initGarmin } from './garmin.js';

const COLORS = ['#4ea1ff', '#3ddc84', '#ffb454', '#ff6b6b', '#c792ea',
                '#59d3d3', '#f778ba', '#a4c639', '#e3b341', '#7ee787'];

/* factor and label applied to the SI values delivered by the server */
const UNIT_SYSTEMS = {
  metric: { speed: [3.6, 'km/h'], distance: [0.001, 'km'] },
  nautical: { speed: [1.9438445, 'kn'], distance: [1 / 1852, 'nm'] },
};

const BASEMAPS = {
  street: {
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    options: { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' },
  },
  satellite: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    options: { maxZoom: 19, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics' },
  },
  topo: {
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    options: { maxZoom: 17, attribution: '&copy; OpenTopoMap, &copy; OpenStreetMap contributors' },
  },
};

const el = (id) => document.getElementById(id);
const state = {
  data: null,
  path: null,
  series: [],
  markers: [],
  lat: [],
  lon: [],
  cursor: 0,
  units: localStorage.getItem('fitedit.units') || 'metric',
  basemap: localStorage.getItem('fitedit.basemap') || 'street',
};

const stack = new ChartStack(el('charts'));
let map, tileLayer, fullTrack, selTrack, hoverMarker, startMarker, endMarker, markerLayer;
let playTimer = null;
let placing = false;
let markerSeq = 1;

function unit(kind) {
  return kind ? UNIT_SYSTEMS[state.units][kind] || null : null;
}

function convert(value, kind) {
  const u = unit(kind);
  return value === null || value === undefined ? null : (u ? value * u[0] : value);
}

function unitLabel(kind, fallback = '') {
  const u = unit(kind);
  return u ? u[1] : fallback;
}

function buildSeries() {
  state.series = state.data.series.map((s, i) => {
    const u = unit(s.kind);
    return {
      ...s,
      color: COLORS[i % COLORS.length],
      units: u ? u[1] : s.units,
      values: u ? s.values.map((v) => (v === null || v === undefined ? null : v * u[0])) : s.values,
    };
  });
  return state.series;
}

/* ---------------- map ---------------- */
function initMap() {
  map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([52, 13], 12);
  setBasemap(state.basemap);
  fullTrack = L.polyline([], { color: '#5a6572', weight: 3, opacity: 0.9 }).addTo(map);
  selTrack = L.polyline([], { color: '#4ea1ff', weight: 4 }).addTo(map);
  hoverMarker = L.circleMarker([0, 0], {
    radius: 6, color: '#fff', weight: 2, fillColor: '#4ea1ff', fillOpacity: 1,
  });
  startMarker = L.circleMarker([0, 0], {
    radius: 6, color: '#0d1117', weight: 2, fillColor: '#3ddc84', fillOpacity: 1,
  });
  endMarker = L.circleMarker([0, 0], {
    radius: 6, color: '#0d1117', weight: 2, fillColor: '#ff6b6b', fillOpacity: 1,
  });
  markerLayer = L.layerGroup().addTo(map);

  map.on('click', (e) => {
    if (placing) addMarker(e.latlng.lat, e.latlng.lng);
  });

  map.on('mousemove', (e) => {
    const index = nearestIndex(e.latlng.lat, e.latlng.lng);
    if (index === null) return;
    stack.setCursor(index);
    showHover(index, e.originalEvent);
  });
  map.on('mouseout', () => hideTooltip());
}

function setBasemap(name) {
  const spec = BASEMAPS[name] || BASEMAPS.street;
  const next = L.tileLayer(spec.url, spec.options);
  next.addTo(map);
  if (tileLayer) map.removeLayer(tileLayer);
  tileLayer = next;
  if (fullTrack) fullTrack.bringToFront();
  if (selTrack) selTrack.bringToFront();
  state.basemap = name;
  localStorage.setItem('fitedit.basemap', name);
}

function nearestIndex(lat, lon) {
  let best = null, bestDist = Infinity;
  const cos = Math.cos((lat * Math.PI) / 180);
  for (let i = 0; i < state.lat.length; i++) {
    if (state.lat[i] === undefined) continue;
    const dy = state.lat[i] - lat;
    const dx = (state.lon[i] - lon) * cos;
    const d = dx * dx + dy * dy;
    if (d < bestDist) { bestDist = d; best = i; }
  }
  return best;
}

function drawTrack() {
  const points = state.data.track.map((p) => [p.lat, p.lon]);
  fullTrack.setLatLngs(points);
  if (points.length) {
    map.fitBounds(fullTrack.getBounds(), { padding: [20, 20] });
  } else {
    const fixes = endpointFixes();
    if (fixes.length) map.fitBounds(L.latLngBounds(fixes).pad(1.5));
  }
  updateSelection();
}

/** Start/end fix of the session, the only position a dive computer stores. */
function endpointFixes() {
  const pos = state.data.positions || {};
  return [pos.start, pos.end].filter(Boolean).map((p) => [p.lat, p.lon]);
}

function updateSelection() {
  const [c0, c1] = stack.crop;
  const points = state.data.track
    .filter((p) => p.i >= c0 && p.i <= c1)
    .map((p) => [p.lat, p.lon]);
  selTrack.setLatLngs(points);
  const marks = points.length ? [points[0], points[points.length - 1]] : endpointFixes();
  if (marks.length) {
    startMarker.setLatLng(marks[0]).addTo(map);
    endMarker.setLatLng(marks[marks.length - 1]).addTo(map);
  } else {
    map.removeLayer(startMarker);
    map.removeLayer(endMarker);
  }
}

/* ---------------- markers ---------------- */
const SYMBOLS = {
  'buoy-red': { label: 'Buoy red', color: '#e2483c', shape: 'buoy' },
  'buoy-green': { label: 'Buoy green', color: '#2ecc71', shape: 'buoy' },
  'buoy-yellow': { label: 'Buoy yellow', color: '#f1c40f', shape: 'buoy' },
  'buoy-orange': { label: 'Buoy orange', color: '#e67e22', shape: 'buoy' },
  'buoy-blue': { label: 'Buoy blue', color: '#4ea1ff', shape: 'buoy' },
  'flag-blue': { label: 'Flag blue', color: '#4ea1ff', shape: 'flag' },
  'flag-white': { label: 'Flag white', color: '#f2f5fa', shape: 'flag' },
  'pin': { label: 'Pin', color: '#c792ea', shape: 'pin' },
  'anchor': { label: 'Anchor', color: '#9aa7b8', shape: 'anchor' },
};
const DEFAULT_SYMBOL = 'buoy-red';

const SHAPES = {
  buoy: (c) => `<polygon points="11,2 18,21 4,21" fill="${c}" stroke="#0d1117" stroke-width="1.5"/>`
    + `<rect x="3" y="21" width="16" height="3" rx="1.5" fill="#0d1117"/>`,
  flag: (c) => `<line x1="4" y1="2" x2="4" y2="24" stroke="#0d1117" stroke-width="2.5"/>`
    + `<polygon points="5,3 19,8 5,13" fill="${c}" stroke="#0d1117" stroke-width="1"/>`,
  pin: (c) => `<path d="M11 24 C11 24 3 14 3 9 A8 8 0 1 1 19 9 C19 14 11 24 11 24 Z"`
    + ` fill="${c}" stroke="#0d1117" stroke-width="1.5"/><circle cx="11" cy="9" r="3" fill="#0d1117"/>`,
  anchor: (c) => `<circle cx="11" cy="4" r="2.5" fill="none" stroke="${c}" stroke-width="2"/>`
    + `<line x1="11" y1="6" x2="11" y2="22" stroke="${c}" stroke-width="2"/>`
    + `<line x1="5" y1="10" x2="17" y2="10" stroke="${c}" stroke-width="2"/>`
    + `<path d="M4 16 C4 22 11 23 11 23 C11 23 18 22 18 16" fill="none" stroke="${c}" stroke-width="2"/>`,
};

function markerIcon(symbol) {
  const spec = SYMBOLS[symbol] || SYMBOLS[DEFAULT_SYMBOL];
  return L.divIcon({
    className: 'marker-icon',
    html: `<svg width="22" height="26" viewBox="0 0 22 26">${SHAPES[spec.shape](spec.color)}</svg>`,
    iconSize: [22, 26],
    iconAnchor: [11, 24],
    tooltipAnchor: [0, -20],
  });
}

function symbolOptions(selected) {
  return Object.entries(SYMBOLS).map(([key, spec]) =>
    `<option value="${key}"${key === selected ? ' selected' : ''}>${esc(spec.label)}</option>`).join('');
}

let markerFile = null;
let markerSaveTimer = null;

function readJson(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}

function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function markerPayload() {
  return state.markers.map(({ name, symbol, lat, lon }) => ({ name, symbol, lat, lon }));
}

function postMarkers(file) {
  return api(`/api/markers?file=${encodeURIComponent(file)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ markers: markerPayload() }),
  });
}

/** Autosave to the companion file of the loaded activity. */
function saveMarkers() {
  if (!markerFile) return;
  clearTimeout(markerSaveTimer);
  markerSaveTimer = setTimeout(() => {
    postMarkers(markerFile).catch((err) => toast(err.message, true));
  }, 400);
}

function setMarkerFile(name) {
  markerFile = name;
  el('markerFile').textContent = name ? `\u2194 ${name}` : '';
  el('markerFile').title = name ? `Markers are stored in ${name}` : '';
}

function setMarkers(list) {
  markerLayer.clearLayers();
  state.markers = (list || []).map((m, i) => ({
    id: markerSeq++,
    name: String(m.name || `M${i + 1}`),
    symbol: SYMBOLS[m.symbol] ? m.symbol : DEFAULT_SYMBOL,
    lat: Number(m.lat),
    lon: Number(m.lon),
  })).filter((m) => Number.isFinite(m.lat) && Number.isFinite(m.lon));
  state.markers.forEach((m) => attachMarker(m));
  renderMarkers();
}

async function loadMarkers() {
  setMarkerFile(state.path.replace(/\.fit$/i, '') + '.markers.json');
  try {
    const result = await api(`/api/markers?file=${encodeURIComponent(markerFile)}`);
    setMarkers(result.markers);
  } catch (err) {
    setMarkers([]);
    toast(err.message, true);
  }
}

async function saveMarkersAs() {
  const name = prompt('Save markers to file:', markerFile || 'markers.json');
  if (!name) return;
  try {
    const result = await postMarkers(name);
    setMarkerFile(result.file);
    toast(`Saved ${result.count} marker(s) to <b>${esc(result.file)}</b>. `
      + `<a href="/api/download?path=${encodeURIComponent(result.file)}">download</a>`);
  } catch (err) {
    toast(err.message, true);
  }
}

function loadMarkersFrom(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const parsed = JSON.parse(reader.result);
      const list = Array.isArray(parsed) ? parsed : parsed.markers;
      if (!Array.isArray(list)) throw new Error('no marker list in the file');
      setMarkers(list);
      saveMarkers();
      toast(`Loaded ${state.markers.length} marker(s) from ${esc(file.name)}`
        + (markerFile ? ` \u2014 now stored in <b>${esc(markerFile)}</b>.` : '.'));
    } catch (err) {
      toast(`Could not read markers: ${err.message}`, true);
    }
  };
  reader.readAsText(file);
}

function attachMarker(m) {
  m.layer = L.marker([m.lat, m.lon], { draggable: true, icon: markerIcon(m.symbol) })
    .bindTooltip(m.name, { direction: 'top' })
    .addTo(markerLayer);
  m.layer.on('drag', () => {
    const p = m.layer.getLatLng();
    m.lat = p.lat;
    m.lon = p.lng;
    const row = el('markerList').querySelector(`[data-id="${m.id}"]`);
    if (row) {
      row.querySelector('.lat').value = m.lat.toFixed(6);
      row.querySelector('.lon').value = m.lon.toFixed(6);
    }
  });
  m.layer.on('dragend', saveMarkers);
}

function nextMarkerName() {
  const used = new Set(state.markers.map((m) => m.name));
  let n = state.markers.length + 1;
  while (used.has(`M${n}`)) n++;
  return `M${n}`;
}

function addMarker(lat, lon, name) {
  const m = {
    id: markerSeq++,
    name: name || nextMarkerName(),
    symbol: el('markerSymbol').value,
    lat,
    lon,
  };
  state.markers.push(m);
  attachMarker(m);
  renderMarkers();
  saveMarkers();
}

function removeMarker(m) {
  markerLayer.removeLayer(m.layer);
  state.markers.splice(state.markers.indexOf(m), 1);
  renderMarkers();
  saveMarkers();
}

function renderMarkers() {
  const list = el('markerList');
  list.innerHTML = '';
  if (!state.markers.length) {
    list.innerHTML = '<span class="hint">No markers yet \u2013 use "place on map" or "+ at cursor".</span>';
    return;
  }
  for (const m of state.markers) {
    const row = document.createElement('div');
    row.className = 'marker-row';
    row.dataset.id = m.id;
    row.innerHTML = '<input class="name" title="Name">'
      + `<select class="sym" title="Symbol">${symbolOptions(m.symbol)}</select>`
      + '<input class="coord lat" type="number" step="0.000001" min="-90" max="90" title="Latitude">'
      + '<input class="coord lon" type="number" step="0.000001" min="-180" max="180" title="Longitude">'
      + '<button class="mini go" title="Centre the map here">\u25ce</button>'
      + '<button class="mini del" title="Delete marker">\u00d7</button>';

    const name = row.querySelector('.name');
    const lat = row.querySelector('.lat');
    const lon = row.querySelector('.lon');
    name.value = m.name;
    lat.value = m.lat.toFixed(6);
    lon.value = m.lon.toFixed(6);

    row.querySelector('.sym').addEventListener('change', (e) => {
      m.symbol = e.target.value;
      m.layer.setIcon(markerIcon(m.symbol));
      saveMarkers();
    });

    name.addEventListener('change', () => {
      m.name = name.value.trim() || m.name;
      name.value = m.name;
      m.layer.setTooltipContent(m.name);
      saveMarkers();
    });
    const applyCoords = () => {
      const newLat = Number(lat.value);
      const newLon = Number(lon.value);
      if (!Number.isFinite(newLat) || Math.abs(newLat) > 90
        || !Number.isFinite(newLon) || Math.abs(newLon) > 180) {
        lat.value = m.lat.toFixed(6);
        lon.value = m.lon.toFixed(6);
        return toast('Latitude must be within \u00b190\u00b0 and longitude within \u00b1180\u00b0.', true);
      }
      m.lat = newLat;
      m.lon = newLon;
      m.layer.setLatLng([newLat, newLon]);
      saveMarkers();
    };
    lat.addEventListener('change', applyCoords);
    lon.addEventListener('change', applyCoords);
    row.querySelector('.go').addEventListener('click', () =>
      map.setView([m.lat, m.lon], Math.max(map.getZoom(), 15)));
    row.querySelector('.del').addEventListener('click', () => removeMarker(m));
    list.append(row);
  }
}

function setPlacing(on) {
  placing = on;
  el('placeMode').classList.toggle('active', on);
  map.getContainer().style.cursor = on ? 'crosshair' : '';
}

/* ---------------- field visibility ---------------- */
const hiddenFields = {
  cursor: new Set(readJson('fitedit.hidden.cursor', [])),
  summary: new Set(readJson('fitedit.hidden.summary', [])),
};
const chooserOpen = { cursor: false, summary: false };

function chooserHtml(panel, names) {
  if (!chooserOpen[panel]) return '';
  return '<div class="field-chooser">' + names.map((n) =>
    `<label><input type="checkbox" data-panel="${panel}" data-name="${esc(n)}"`
    + `${hiddenFields[panel].has(n) ? '' : ' checked'}>${esc(n)}</label>`).join('')
    + '</div>';
}

/* ---------------- panel layout ---------------- */
const collapsedPanels = new Set(readJson('fitedit.collapsed', []));
const panelHeights = readJson('fitedit.heights', {});
let heightTimer = null;

function initPanels() {
  const boxes = [...document.querySelectorAll('.panel, #map')];
  boxes.forEach((box) => {
    if (panelHeights[box.id]) box.style.height = `${panelHeights[box.id]}px`;
    box.classList.toggle('collapsed', collapsedPanels.has(box.id));
  });
  const observer = new ResizeObserver((entries) => {
    if (entries.some((entry) => entry.target.id === 'map')) map.invalidateSize();
    snapshotHeights();
  });
  boxes.forEach((box) => observer.observe(box));
  // the native resize grip emits no event, so also capture the end of a drag
  window.addEventListener('pointerup', snapshotHeights);
}

function snapshotHeights() {
  document.querySelectorAll('.panel, #map').forEach((box) => {
    if (box.style.height) panelHeights[box.id] = parseInt(box.style.height, 10);
  });
  clearTimeout(heightTimer);
  heightTimer = setTimeout(() =>
    localStorage.setItem('fitedit.heights', JSON.stringify(panelHeights)), 300);
}

document.addEventListener('click', (e) => {
  const button = e.target.closest('[data-collapse]');
  if (!button) return;
  const box = el(button.dataset.collapse);
  if (box.classList.toggle('collapsed')) collapsedPanels.add(box.id);
  else collapsedPanels.delete(box.id);
  localStorage.setItem('fitedit.collapsed', JSON.stringify([...collapsedPanels]));
});

/* ---------------- cursor ---------------- */
function formatValue(value) {
  const abs = Math.abs(value);
  return abs >= 100 ? value.toFixed(0) : abs >= 1 ? value.toFixed(2) : value.toFixed(3);
}

function valueRows(index) {
  const rows = state.series.map((s) => {
    const value = s.values[index];
    if (value === null || value === undefined || hiddenFields.cursor.has(s.name)) return '';
    return `<tr><td class="k">${esc(s.name)}</td>`
      + `<td class="v">${formatValue(value)} ${esc(s.units)}</td></tr>`;
  }).join('');
  const lat = state.lat[index], lon = state.lon[index];
  const pos = lat === undefined || hiddenFields.cursor.has('position') ? '' :
    `<tr><td class="k">position</td><td class="v">${lat.toFixed(5)}, ${lon.toFixed(5)}</td></tr>`;
  return rows + pos;
}

function cursorFieldNames() {
  return [...state.series.map((s) => s.name), 'position'];
}

function showHover(index, event) {
  const times = state.data.times;
  if (index === null || index >= times.length) return;
  state.cursor = index;
  el('cursor').value = index;

  const time = times[index];
  const clock = new Date(time * 1000).toLocaleString();
  const elapsed = `+${formatDuration(time - times[0])}`;
  el('cursorTime').textContent = `${clock}  \u00b7  ${elapsed}`;
  el('cursorBody').innerHTML = chooserHtml('cursor', cursorFieldNames())
    + `<table class="values">${valueRows(index)}</table>`;

  const lat = state.lat[index], lon = state.lon[index];
  if (lat !== undefined) hoverMarker.setLatLng([lat, lon]).addTo(map);

  const tip = el('tooltip');
  if (!event) return hideTooltip();
  tip.innerHTML = `<div class="t-head">${clock} &middot; ${elapsed}</div>`
    + `<table>${valueRows(index)}</table>`;
  tip.hidden = false;
  const x = Math.min(event.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
  const y = Math.min(event.clientY + 14, window.innerHeight - tip.offsetHeight - 8);
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}

function hideTooltip() {
  el('tooltip').hidden = true;
}

function togglePlay() {
  if (playTimer) {
    clearInterval(playTimer);
    playTimer = null;
    el('play').innerHTML = '&#9654;';
    return;
  }
  const [c0, c1] = stack.crop;
  if (state.cursor < c0 || state.cursor >= c1) stack.setCursor(c0);
  const step = Math.max(1, Math.round((c1 - c0) / 900));
  el('play').innerHTML = '&#10073;&#10073;';
  playTimer = setInterval(() => {
    const next = state.cursor + step;
    if (next >= c1) { stack.setCursor(c1); showHover(c1, null); return togglePlay(); }
    stack.setCursor(next);
    showHover(next, null);
  }, 40);
}

/* ---------------- ui ---------------- */
function buildSeriesList() {
  const list = el('seriesList');
  list.innerHTML = '';
  state.series.forEach((s) => {
    const label = document.createElement('label');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = stack.visible.has(s.name);
    box.addEventListener('change', () => stack.setVisible(s.name, box.checked));
    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = s.color;
    label.append(box, swatch, document.createTextNode(s.name));
    list.append(label);
  });
}

function fmtValue(value, digits = 1) {
  return value === null || value === undefined ? '\u2013' : Number(value).toFixed(digits);
}

function renderSummary() {
  const d = state.data;
  const s = d.sessions[0] || {};
  const speedUnit = unitLabel('speed');
  const distUnit = unitLabel('distance');
  const dist = (value) => (value ? `${convert(value, 'distance').toFixed(2)} ${distUnit}` : '\u2013');
  const speed = (value) => (value ? convert(value, 'speed').toFixed(2) : '\u2013');
  const rows = [
    ['File', `${d.name} (${(d.size / 1024).toFixed(0)} KiB)`],
    ['Sport', s.sport_name || '\u2013'],
    ['Type', d.profileName || '\u2013'],
    ['Start', d.times.length ? new Date(d.times[0] * 1000).toLocaleString() : '\u2013'],
    ['End', d.times.length ? new Date(d.times[d.times.length - 1] * 1000).toLocaleString() : '\u2013'],
    ['Records', d.recordCount],
    ['Elapsed', s.total_elapsed_time ? formatDuration(s.total_elapsed_time) : '\u2013'],
    ['Timer', s.total_timer_time ? formatDuration(s.total_timer_time) : '\u2013'],
    ['Distance', dist(s.total_distance)],
    ['Avg / max speed', `${speed(s.enhanced_avg_speed ?? s.avg_speed)} / `
      + `${speed(s.enhanced_max_speed ?? s.max_speed)} ${speedUnit}`],
    ['Ascent / descent', `${fmtValue(s.total_ascent, 0)} / ${fmtValue(s.total_descent, 0)} m`],
    ['Avg / max HR', `${fmtValue(s.avg_heart_rate, 0)} / ${fmtValue(s.max_heart_rate, 0)} bpm`],
    ['Laps', d.laps.length],
  ];

  const dive = d.dive || {};
  const num = (value, digits = 1) => Number(value).toFixed(digits);
  if (dive.max_depth != null) {
    rows.push(['Max / avg depth',
      `${num(dive.max_depth)} / ${num(dive.avg_depth ?? 0)} m`]);
  }
  if (dive.bottom_time) rows.push(['Bottom time', formatDuration(dive.bottom_time)]);
  if (dive.dive_number) rows.push(['Dive number', dive.dive_number]);
  if (dive.surface_interval) {
    rows.push(['Surface interval', formatDuration(dive.surface_interval)]);
  }
  if (dive.tank_start_pressure != null) {
    rows.push(['Tank start / end',
      `${num(dive.tank_start_pressure, 0)} / ${num(dive.tank_end_pressure ?? 0, 0)} bar`]);
  }
  if (dive.avg_rmv != null) rows.push(['Avg RMV', `${num(dive.avg_rmv)} L/min`]);
  if (dive.oxygen_content != null) {
    rows.push(['Gas O\u2082 / He',
      `${dive.oxygen_content} / ${dive.helium_content ?? 0} %`]);
  }
  if (dive.end_cns != null) rows.push(['CNS start / end', `${dive.start_cns ?? 0} / ${dive.end_cns} %`]);
  if (!d.track.length && (d.positions || {}).start) {
    rows.push(['Position', `${d.positions.start.lat.toFixed(5)}, ${d.positions.start.lon.toFixed(5)}`]);
  }
  el('summaryBody').innerHTML = chooserHtml('summary', rows.map(([k]) => k))
    + '<div class="name-row">'
    + '<label for="activityName">Name</label>'
    + `<input id="activityName" maxlength="64"`
    + ` placeholder="activity name" value="${esc(d.activityName || '')}">`
    + '<button id="renameBtn" class="mini">save</button></div>'
    + '<dl class="kv">'
    + rows.filter(([k]) => !hiddenFields.summary.has(k))
      .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')
    + '</dl>';
  el('renameBtn').addEventListener('click', () => saveActivityName());
  el('activityName').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') saveActivityName();
  });
}

async function saveActivityName() {
  const name = el('activityName').value.trim();
  try {
    const result = await api('/api/rename', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: state.path, name }),
    });
    state.data.activityName = result.name;
    await refreshFiles(state.path);
    toast(result.name
      ? `Activity name set to <b>${esc(result.name)}</b>.`
      : 'Activity name cleared.');
  } catch (err) {
    toast(err.message, true);
  }
}

function renderCrop() {
  const [c0, c1] = stack.crop;
  const times = state.data.times;
  el('startTime').value = `${new Date(times[c0] * 1000).toLocaleString()}  (+${formatDuration(times[c0] - times[0])})`;
  el('endTime').value = `${new Date(times[c1] * 1000).toLocaleString()}  (+${formatDuration(times[c1] - times[0])})`;
  const kept = c1 - c0 + 1;
  el('selectionInfo').textContent =
    `${formatDuration(times[c1] - times[c0])} selected \u2014 ${kept} of ${times.length} records`
    + ` (trim ${c0} at the start, ${times.length - 1 - c1} at the end)`;
  updateSelection();
}

function toast(message, isError = false) {
  const box = el('toast');
  box.innerHTML = message;
  box.className = `toast${isError ? ' error' : ''}`;
  box.hidden = false;
  clearTimeout(box._timer);
  box._timer = setTimeout(() => { box.hidden = true; }, 9000);
}

/* ---------------- data ---------------- */
async function api(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({ error: response.statusText }));
  if (!response.ok) throw new Error(payload.error || 'request failed');
  return payload;
}

function fileStamp(unix) {
  const d = new Date(unix * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} `
    + `${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function refreshFiles(select) {
  const { files } = await api('/api/files');
  const box = el('fileSelect');
  box.innerHTML = files.map((f) => {
    const parts = [fileStamp(f.start || f.modified), f.type || '\u2013'];
    if (f.activity) parts.push(f.activity);
    parts.push(f.name);
    return `<option value="${esc(f.name)}">${esc(parts.join(' - '))}</option>`;
  }).join('');
  if (select && files.some((f) => f.name === select)) box.value = select;
  return files;
}

async function loadFile(name) {
  if (!name) return;
  toast(`Loading ${name}\u2026`);
  const data = await api(`/api/load?path=${encodeURIComponent(name)}`);
  if (!data.times.length) throw new Error('no record messages with timestamps');
  state.data = data;
  state.path = data.path;
  state.lat = new Array(data.times.length);
  state.lon = new Array(data.times.length);
  data.track.forEach((p) => { state.lat[p.i] = p.lat; state.lon[p.i] = p.lon; });

  stack.setData(data.times, buildSeries());
  el('cursor').max = data.times.length - 1;
  el('cursor').value = 0;
  buildSeriesList();
  renderSummary();
  drawTrack();
  renderCrop();
  await loadMarkers();
  showHover(0, null);
  el('toast').hidden = true;
}

async function saveCropped() {
  const [c0, c1] = stack.crop;
  const times = state.data.times;
  const suggestion = state.path.replace(/\.fit$/i, '') + '_cropped.fit';
  const name = prompt('Save cropped activity as:', suggestion);
  if (!name) return;
  el('save').disabled = true;
  try {
    const report = await api('/api/crop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: state.path, start: times[c0], end: times[c1], output: name }),
    });
    await refreshFiles(state.path);
    toast(`Saved <b>${report.path}</b> \u2014 ${report.records} records, `
      + `${formatDuration(report.elapsed)}, `
      + `${convert(report.distance, 'distance').toFixed(2)} ${unitLabel('distance')}, `
      + `${report.droppedMessages} messages removed. `
      + `<a href="/api/download?path=${encodeURIComponent(report.path)}">download</a>`);
  } catch (err) {
    toast(err.message, true);
  } finally {
    el('save').disabled = false;
  }
}

/* ---------------- wiring ---------------- */
stack.on('hover', (index, event) => {
  if (index === null) hideTooltip(); else showHover(index, event);
});
stack.on('crop', () => renderCrop());

el('fileSelect').addEventListener('change', (e) => loadFile(e.target.value).catch((err) => toast(err.message, true)));
el('reload').addEventListener('click', () => refreshFiles(state.path).catch((err) => toast(err.message, true)));
el('clockMode').addEventListener('change', (e) => stack.setXMode(e.target.checked ? 'clock' : 'elapsed'));
el('basemap').addEventListener('change', (e) => setBasemap(e.target.value));
el('units').addEventListener('change', (e) => {
  state.units = e.target.value;
  localStorage.setItem('fitedit.units', state.units);
  if (!state.data) return;
  stack.setSeries(buildSeries());
  buildSeriesList();
  renderSummary();
  showHover(state.cursor, null);
});
el('cursor').addEventListener('input', (e) => {
  const index = Number(e.target.value);
  stack.setCursor(index);
  showHover(index, null);
});
el('play').addEventListener('click', () => togglePlay());
el('placeMode').addEventListener('click', () => setPlacing(!placing));
el('addMarker').addEventListener('click', () => {
  const lat = state.lat[state.cursor];
  if (lat === undefined) return toast('The current cursor position has no GPS fix.', true);
  addMarker(lat, state.lon[state.cursor]);
});
el('saveMarkersAs').addEventListener('click', () => saveMarkersAs());
el('loadMarkers').addEventListener('click', () => el('markerFileInput').click());
el('markerFileInput').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (file) loadMarkersFrom(file);
  e.target.value = '';
});

document.addEventListener('click', (e) => {
  const button = e.target.closest('[data-fields]');
  if (!button) return;
  const panel = button.dataset.fields;
  chooserOpen[panel] = !chooserOpen[panel];
  if (panel === 'cursor') showHover(state.cursor, null); else renderSummary();
});

document.addEventListener('change', (e) => {
  const box = e.target.closest('.field-chooser input');
  if (!box) return;
  const { panel, name } = box.dataset;
  if (box.checked) hiddenFields[panel].delete(name); else hiddenFields[panel].add(name);
  localStorage.setItem(`fitedit.hidden.${panel}`, JSON.stringify([...hiddenFields[panel]]));
  if (panel === 'cursor') showHover(state.cursor, null); else renderSummary();
});

el('resetCrop').addEventListener('click', () => {
  stack.setCrop(0, state.data.times.length - 1);
  stack.resetView();
});
el('save').addEventListener('click', () => saveCropped());

document.querySelectorAll('[data-set]').forEach((button) => {
  button.addEventListener('click', () => {
    if (stack.hover === null) return toast('Move the mouse over a plot first.', true);
    const [c0, c1] = stack.crop;
    if (button.dataset.set === 'start') stack.setCrop(Math.min(stack.hover, c1 - 1), c1);
    else stack.setCrop(c0, Math.max(stack.hover, c0 + 1));
  });
});

el('fileInput').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const result = await api(`/api/upload?name=${encodeURIComponent(file.name)}`,
      { method: 'POST', body: file });
    await refreshFiles(result.path);
    await loadFile(result.path);
  } catch (err) {
    toast(err.message, true);
  }
  e.target.value = '';
});

initMap();
initPanels();
el('units').value = state.units;
el('basemap').value = state.basemap;
el('markerSymbol').innerHTML = symbolOptions(localStorage.getItem('fitedit.symbol') || DEFAULT_SYMBOL);
el('markerSymbol').addEventListener('change', (e) =>
  localStorage.setItem('fitedit.symbol', e.target.value));

initGarmin({
  api,
  toast,
  esc,
  formatDuration,
  formatDistance: (metres) =>
    `${convert(metres, 'distance').toFixed(2)} ${unitLabel('distance')}`,
  onDownloaded: async (files) => {
    await refreshFiles(files[0]);
    await loadFile(files[0]);
  },
});

refreshFiles()
  .then((files) => files.length && loadFile(files[0].name))
  .catch((err) => toast(err.message, true));
