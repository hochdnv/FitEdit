/* Lightweight canvas chart stack with shared x-axis, hover crosshair and
   draggable crop handles. No external dependencies. */

const AXIS_LEFT = 56;
const AXIS_RIGHT = 12;
const AXIS_TOP = 8;
const AXIS_BOTTOM = 18;

function niceStep(range, target) {
  if (!isFinite(range) || range <= 0) return 1;
  const raw = range / target;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1;
  return step * mag;
}

export class ChartStack {
  constructor(container) {
    this.container = container;
    this.times = [];
    this.series = [];
    this.visible = new Set();
    this.view = [0, 0];
    this.crop = [0, 0];
    this.hover = null;
    this.xMode = 'elapsed';
    this.charts = [];
    this.listeners = { hover: [], crop: [], view: [] };
    this._drag = null;
    this._raf = null;
    window.addEventListener('resize', () => this.render());
  }

  on(event, cb) { this.listeners[event].push(cb); return this; }
  _emit(event, ...args) { this.listeners[event].forEach((cb) => cb(...args)); }

  setData(times, series) {
    this.times = times;
    this.series = series;
    this.visible = new Set(series.slice(0, 4).map((s) => s.name));
    this.view = [0, Math.max(0, times.length - 1)];
    this.crop = [0, Math.max(0, times.length - 1)];
    this.hover = null;
    this.build();
  }

  setVisible(name, on) {
    if (on) this.visible.add(name); else this.visible.delete(name);
    this.build();
  }

  /** Replace the series (e.g. after a unit change) keeping view and selection. */
  setSeries(series) {
    this.series = series;
    this.build();
  }

  setCursor(index) {
    this.hover = this._clampIndex(Math.round(index));
    this.render();
  }

  setXMode(mode) { this.xMode = mode; this.render(); }

  setCrop(a, b) {
    const n = this.times.length - 1;
    const lo = Math.round(Math.min(a, b));
    const hi = Math.round(Math.max(a, b));
    this.crop = [Math.max(0, lo), Math.min(n, hi)];
    this._emit('crop', this.crop);
    this.render();
  }

  resetView() {
    this.view = [0, Math.max(0, this.times.length - 1)];
    this.render();
  }

  build() {
    this.container.innerHTML = '';
    this.charts = [];
    const shown = this.series.filter((s) => this.visible.has(s.name));
    if (!shown.length) {
      this.container.innerHTML = '<p class="empty">Select at least one data series to plot.</p>';
      return;
    }
    for (const s of shown) {
      const row = document.createElement('div');
      row.className = 'chart-row';
      const label = document.createElement('div');
      label.className = 'chart-title';
      label.textContent = s.units ? `${s.name} (${s.units})` : s.name;
      const canvas = document.createElement('canvas');
      row.append(label, canvas);
      this.container.append(row);
      this.charts.push({ series: s, canvas, ctx: canvas.getContext('2d') });
      this._bind(canvas);
    }
    this.render();
  }

  render() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => { this._raf = null; this._draw(); });
  }

  /* ---------- geometry ---------- */
  _plotWidth(canvas) { return canvas.clientWidth - AXIS_LEFT - AXIS_RIGHT; }

  xOf(canvas, index) {
    const [v0, v1] = this.view;
    const span = Math.max(1e-9, v1 - v0);
    return AXIS_LEFT + ((index - v0) / span) * this._plotWidth(canvas);
  }

  indexAt(canvas, px) {
    const [v0, v1] = this.view;
    const frac = (px - AXIS_LEFT) / Math.max(1, this._plotWidth(canvas));
    return v0 + frac * (v1 - v0);
  }

  /* ---------- drawing ---------- */
  _draw() {
    for (const chart of this.charts) this._drawChart(chart);
  }

  _drawChart(chart) {
    const { canvas, ctx, series } = chart;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr; canvas.height = h * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const plotW = w - AXIS_LEFT - AXIS_RIGHT;
    const plotH = h - AXIS_TOP - AXIS_BOTTOM;
    const [v0, v1] = this.view;
    const i0 = Math.max(0, Math.floor(v0));
    const i1 = Math.min(series.values.length - 1, Math.ceil(v1));

    let min = Infinity, max = -Infinity;
    for (let i = i0; i <= i1; i++) {
      const value = series.values[i];
      if (value === null || value === undefined) continue;
      if (value < min) min = value;
      if (value > max) max = value;
    }
    if (min === Infinity) { min = 0; max = 1; }
    if (min === max) { min -= 1; max += 1; }
    const pad = (max - min) * 0.08;
    min -= pad; max += pad;
    const yOf = (value) => AXIS_TOP + plotH - ((value - min) / (max - min)) * plotH;

    ctx.fillStyle = '#12161d';
    ctx.fillRect(AXIS_LEFT, AXIS_TOP, plotW, plotH);

    // area outside of the crop selection
    const cx0 = this.xOf(canvas, this.crop[0]);
    const cx1 = this.xOf(canvas, this.crop[1]);
    ctx.fillStyle = 'rgba(0,0,0,0.55)';
    if (cx0 > AXIS_LEFT) ctx.fillRect(AXIS_LEFT, AXIS_TOP, Math.min(cx0, AXIS_LEFT + plotW) - AXIS_LEFT, plotH);
    if (cx1 < AXIS_LEFT + plotW) ctx.fillRect(Math.max(cx1, AXIS_LEFT), AXIS_TOP, AXIS_LEFT + plotW - Math.max(cx1, AXIS_LEFT), plotH);

    // y grid + labels
    const step = niceStep(max - min, 3);
    ctx.strokeStyle = '#232a35';
    ctx.fillStyle = '#8a94a6';
    ctx.font = '11px system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let value = Math.ceil(min / step) * step; value <= max; value += step) {
      const y = yOf(value);
      ctx.beginPath();
      ctx.moveTo(AXIS_LEFT, y); ctx.lineTo(AXIS_LEFT + plotW, y);
      ctx.stroke();
      ctx.fillText(this._fmtNum(value, step), AXIS_LEFT - 6, y);
    }

    this._drawXAxis(ctx, canvas, w, h, plotW, plotH);

    // series line
    ctx.save();
    ctx.beginPath();
    ctx.rect(AXIS_LEFT, AXIS_TOP, plotW, plotH);
    ctx.clip();
    ctx.strokeStyle = series.color || '#4ea1ff';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    let pen = false;
    const stride = Math.max(1, Math.floor((i1 - i0) / (plotW * 2)) || 1);
    for (let i = i0; i <= i1; i += stride) {
      const value = series.values[i];
      if (value === null || value === undefined) { pen = false; continue; }
      const x = this.xOf(canvas, i);
      const y = yOf(value);
      if (pen) ctx.lineTo(x, y); else { ctx.moveTo(x, y); pen = true; }
    }
    ctx.stroke();
    ctx.restore();

    // crop handles
    for (const [idx, edge] of [[this.crop[0], 'start'], [this.crop[1], 'end']]) {
      const x = this.xOf(canvas, idx);
      if (x < AXIS_LEFT - 4 || x > AXIS_LEFT + plotW + 4) continue;
      ctx.strokeStyle = edge === 'start' ? '#3ddc84' : '#ff6b6b';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, AXIS_TOP); ctx.lineTo(x, AXIS_TOP + plotH);
      ctx.stroke();
      ctx.fillStyle = ctx.strokeStyle;
      ctx.fillRect(x - 3, AXIS_TOP, 6, 8);
    }

    // hover crosshair
    if (this.hover !== null) {
      const x = this.xOf(canvas, this.hover);
      if (x >= AXIS_LEFT && x <= AXIS_LEFT + plotW) {
        ctx.strokeStyle = '#e6edf7';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x, AXIS_TOP); ctx.lineTo(x, AXIS_TOP + plotH);
        ctx.stroke();
        ctx.setLineDash([]);
        const value = series.values[this.hover];
        if (value !== null && value !== undefined) {
          ctx.fillStyle = series.color || '#4ea1ff';
          ctx.beginPath();
          ctx.arc(x, yOf(value), 3, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    ctx.strokeStyle = '#2b3442';
    ctx.lineWidth = 1;
    ctx.strokeRect(AXIS_LEFT + 0.5, AXIS_TOP + 0.5, plotW - 1, plotH - 1);
  }

  _drawXAxis(ctx, canvas, w, h, plotW, plotH) {
    if (!this.times.length) return;
    const [v0, v1] = this.view;
    const t0 = this.times[Math.max(0, Math.round(v0))];
    const t1 = this.times[Math.min(this.times.length - 1, Math.round(v1))];
    const spanSec = Math.max(1, t1 - t0);
    const step = this._timeStep(spanSec);
    const base = this.xMode === 'clock' ? t0 : t0 - this.times[0];
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#8a94a6';
    ctx.strokeStyle = '#232a35';
    const first = Math.ceil((this.xMode === 'clock' ? t0 : base) / step) * step;
    for (let t = first; t <= (this.xMode === 'clock' ? t1 : base + spanSec); t += step) {
      const abs = this.xMode === 'clock' ? t : this.times[0] + t;
      const index = this._indexForTime(abs);
      const x = this.xOf(canvas, index);
      if (x < AXIS_LEFT || x > AXIS_LEFT + plotW) continue;
      ctx.beginPath();
      ctx.moveTo(x, AXIS_TOP); ctx.lineTo(x, AXIS_TOP + plotH);
      ctx.stroke();
      const text = this.xMode === 'clock'
        ? new Date(abs * 1000).toLocaleTimeString()
        : formatDuration(abs - this.times[0]);
      ctx.fillText(text, x, AXIS_TOP + plotH + 3);
    }
  }

  _timeStep(spanSec) {
    const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400];
    for (const s of steps) if (spanSec / s <= 8) return s;
    return 86400;
  }

  _indexForTime(t) {
    const times = this.times;
    let lo = 0, hi = times.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (times[mid] < t) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  _fmtNum(value, step) {
    const decimals = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
    return value.toFixed(decimals);
  }

  /* ---------- interaction ---------- */
  _bind(canvas) {
    canvas.addEventListener('mousemove', (e) => {
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      if (this._drag) {
        const index = this._clampIndex(this.indexAt(canvas, px));
        if (this._drag.kind === 'start') this.setCrop(Math.min(index, this.crop[1] - 1), this.crop[1]);
        else if (this._drag.kind === 'end') this.setCrop(this.crop[0], Math.max(index, this.crop[0] + 1));
        else {
          const delta = this._drag.startIndex - this.indexAt(canvas, px);
          this._panTo(this._drag.view[0] + delta, this._drag.view[1] + delta);
        }
        return;
      }
      canvas.style.cursor = this._handleAt(canvas, px) ? 'ew-resize' : 'crosshair';
      const index = Math.round(this._clampIndex(this.indexAt(canvas, px)));
      this.hover = index;
      this._emit('hover', index, e);
      this.render();
    });
    canvas.addEventListener('mouseleave', () => {
      if (this._drag) return;
      this._emit('hover', this.hover, null);
      this.render();
    });
    canvas.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const handle = this._handleAt(canvas, px);
      this._drag = handle
        ? { kind: handle }
        : { kind: 'pan', startIndex: this.indexAt(canvas, px), view: [...this.view] };
      e.preventDefault();
    });
    window.addEventListener('mouseup', () => { this._drag = null; });
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const anchor = this._clampIndex(this.indexAt(canvas, e.clientX - rect.left));
      const factor = e.deltaY > 0 ? 1.25 : 0.8;
      const [v0, v1] = this.view;
      this._panTo(anchor - (anchor - v0) * factor, anchor + (v1 - anchor) * factor);
    }, { passive: false });
    canvas.addEventListener('dblclick', () => this.resetView());
  }

  _panTo(a, b) {
    const n = this.times.length - 1;
    let span = Math.min(Math.max(b - a, 5), n);
    let v0 = a, v1 = a + span;
    if (v0 < 0) { v0 = 0; v1 = span; }
    if (v1 > n) { v1 = n; v0 = n - span; }
    this.view = [Math.max(0, v0), Math.min(n, v1)];
    this._emit('view', this.view);
    this.render();
  }

  _handleAt(canvas, px) {
    if (Math.abs(px - this.xOf(canvas, this.crop[0])) <= 5) return 'start';
    if (Math.abs(px - this.xOf(canvas, this.crop[1])) <= 5) return 'end';
    return null;
  }

  _clampIndex(index) {
    return Math.max(0, Math.min(this.times.length - 1, index));
  }
}

export function formatDuration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
           : `${m}:${String(sec).padStart(2, '0')}`;
}
