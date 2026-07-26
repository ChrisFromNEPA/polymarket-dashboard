// Hand-rolled SVG charts. No dependencies, no CDN, no build step.
// Everything uses viewBox so it scales with its container.
const Charts = (() => {

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Equity line chart ────────────────────────────────────
  // points: [{ t: iso, v: number }], baseline: starting capital
  function lineChart(points, opts) {
    opts = opts || {};
    const W = 720, H = 240, P = { t: 16, r: 16, b: 28, l: 56 };
    if (!points || points.length === 0) return '';

    const vals = points.map(p => p.v).filter(v => typeof v === 'number' && !isNaN(v));
    if (vals.length === 0) return '';

    let min = Math.min.apply(null, vals);
    let max = Math.max.apply(null, vals);
    if (opts.baseline !== undefined) {
      min = Math.min(min, opts.baseline);
      max = Math.max(max, opts.baseline);
    }
    // Pad the range so a flat line doesn't sit on the axis
    const pad = (max - min) * 0.1 || Math.abs(max) * 0.02 || 1;
    min -= pad; max += pad;

    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const x = i => P.l + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw);
    const y = v => P.t + ih - ((v - min) / (max - min || 1)) * ih;

    let d = '';
    points.forEach((p, i) => {
      if (typeof p.v !== 'number' || isNaN(p.v)) return;
      d += (d === '' ? 'M' : 'L') + x(i).toFixed(1) + ' ' + y(p.v).toFixed(1) + ' ';
    });

    // Horizontal gridlines + y labels
    let grid = '';
    for (let g = 0; g <= 4; g++) {
      const v = min + (g / 4) * (max - min);
      const yy = y(v).toFixed(1);
      grid += '<line class="grid" x1="' + P.l + '" y1="' + yy + '" x2="' + (W - P.r) + '" y2="' + yy + '"/>';
      grid += '<text class="axis" x="' + (P.l - 8) + '" y="' + yy + '" text-anchor="end" dominant-baseline="middle">' +
        (opts.money ? '$' + Math.round(v).toLocaleString('en-US') : v.toFixed(2)) + '</text>';
    }

    let base = '';
    if (opts.baseline !== undefined) {
      const by = y(opts.baseline).toFixed(1);
      base = '<line class="baseline" x1="' + P.l + '" y1="' + by + '" x2="' + (W - P.r) + '" y2="' + by + '"/>';
    }

    // First/last time labels
    let xlab = '';
    if (points.length > 1) {
      const f = points[0].t ? String(points[0].t).slice(5, 10) : '';
      const l = points[points.length - 1].t ? String(points[points.length - 1].t).slice(5, 10) : '';
      xlab = '<text class="axis" x="' + P.l + '" y="' + (H - 8) + '">' + esc(f) + '</text>' +
        '<text class="axis" x="' + (W - P.r) + '" y="' + (H - 8) + '" text-anchor="end">' + esc(l) + '</text>';
    }

    return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
      'aria-label="' + esc(opts.ariaLabel || 'Line chart') + '">' +
      grid + base +
      '<path class="line" d="' + d.trim() + '"/>' +
      xlab + '</svg>';
  }

  // ── Reliability diagram ──────────────────────────────────
  // bins: [{ p_lo, p_hi, n, predicted, realized }]
  // Marker AREA encodes bin count, so sparse buckets visibly look sparse —
  // otherwise a bucket holding 2 forecasts reads as confidently as one holding 200.
  function reliability(bins) {
    const S = 320, P = { t: 14, r: 14, b: 36, l: 44 };
    const iw = S - P.l - P.r, ih = S - P.t - P.b;
    const x = p => P.l + p * iw;
    const y = p => P.t + ih - p * ih;

    let grid = '';
    for (let g = 0; g <= 5; g++) {
      const v = g / 5;
      grid += '<line class="grid" x1="' + x(0) + '" y1="' + y(v) + '" x2="' + x(1) + '" y2="' + y(v) + '"/>';
      grid += '<line class="grid" x1="' + x(v) + '" y1="' + y(0) + '" x2="' + x(v) + '" y2="' + y(1) + '"/>';
      grid += '<text class="axis" x="' + (P.l - 6) + '" y="' + y(v) + '" text-anchor="end" dominant-baseline="middle">' + (v * 100).toFixed(0) + '</text>';
      grid += '<text class="axis" x="' + x(v) + '" y="' + (S - P.b + 16) + '" text-anchor="middle">' + (v * 100).toFixed(0) + '</text>';
    }

    const diagonal = '<line class="diagonal" x1="' + x(0) + '" y1="' + y(0) + '" x2="' + x(1) + '" y2="' + y(1) + '"/>';

    let pts = '', path = '';
    if (bins && bins.length) {
      const maxN = Math.max.apply(null, bins.map(b => b.n || 0)) || 1;
      const ordered = bins.slice().filter(b => b.n > 0)
        .sort((a, b) => (a.predicted || 0) - (b.predicted || 0));
      ordered.forEach(b => {
        const cx = x(b.predicted), cy = y(b.realized);
        // area ∝ n  →  r ∝ sqrt(n)
        const r = 3 + 9 * Math.sqrt((b.n || 0) / maxN);
        pts += '<circle class="rel-pt" cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) +
          '" r="' + r.toFixed(1) + '"><title>' +
          esc((b.p_lo * 100).toFixed(0) + '–' + (b.p_hi * 100).toFixed(0) + '%: predicted ' +
            (b.predicted * 100).toFixed(1) + '%, realized ' + (b.realized * 100).toFixed(1) +
            '%, n=' + b.n) + '</title></circle>';
        path += (path === '' ? 'M' : 'L') + cx.toFixed(1) + ' ' + cy.toFixed(1) + ' ';
      });
    }

    return '<svg class="chart chart-square" viewBox="0 0 ' + S + ' ' + S + '" role="img" ' +
      'aria-label="Reliability diagram: predicted probability versus realized frequency">' +
      grid + diagonal +
      (path ? '<path class="rel-line" d="' + path.trim() + '"/>' : '') + pts +
      '<text class="axis-title" x="' + (P.l + iw / 2) + '" y="' + (S - 4) + '" text-anchor="middle">predicted %</text>' +
      '<text class="axis-title" transform="rotate(-90)" x="' + -(P.t + ih / 2) + '" y="12" text-anchor="middle">realized %</text>' +
      '</svg>';
  }

  // ── Horizontal comparison bar (Brier agent vs market) ────
  function compareBars(rows) {
    if (!rows || !rows.length) return '';
    const max = Math.max.apply(null, rows.map(r => r.value || 0)) || 1;
    let html = '<div class="bars">';
    rows.forEach(r => {
      const w = ((r.value || 0) / max) * 100;
      html += '<div class="bar-row">' +
        '<div class="bar-label">' + esc(r.label) + '</div>' +
        '<div class="bar-track"><div class="bar-fill ' + (r.cls || '') + '" style="width:' + w.toFixed(1) + '%"></div></div>' +
        '<div class="bar-value">' + esc(r.display !== undefined ? r.display : r.value) + '</div>' +
        '</div>';
    });
    return html + '</div>';
  }

  return { lineChart, reliability, compareBars };
})();
