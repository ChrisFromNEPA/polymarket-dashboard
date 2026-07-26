// Data layer — fetches state/*.json, tolerates missing files, computes nothing.
//
// Design rule (docs/DASHBOARD.md §2.3): the UI renders what the agent published.
// It does NOT derive statistics. When a contract field is missing we surface a
// visible warning rather than silently substituting something plausible — a
// wrong number that looks right is worse than an obvious gap.
const Data = (() => {
  const FILES = {
    meta: 'state/meta.json',
    scorecard: 'state/scorecard.json',
    calibration: 'state/calibration.json',
    equity: 'state/equity.json',
    portfolio: 'state/portfolio.json',
    decisions: 'state/decisions.json',
    resolutions: 'state/resolutions.json',
    viability: 'state/viability.json',
  };

  let cache = null;

  async function fetchOne(path) {
    try {
      const resp = await fetch(path + '?t=' + Date.now(), { cache: 'no-store' });
      if (!resp.ok) return { ok: false, reason: 'HTTP ' + resp.status, data: null };
      return { ok: true, reason: null, data: await resp.json() };
    } catch (e) {
      // file:// or offline — both look the same to fetch()
      return { ok: false, reason: e.message || 'unreachable', data: null };
    }
  }

  async function load(force) {
    if (cache && !force) return cache;
    const keys = Object.keys(FILES);
    const results = await Promise.all(keys.map(k => fetchOne(FILES[k])));

    const out = { missing: [], errors: [] };
    keys.forEach((k, i) => {
      const r = results[i];
      out[k] = r.data;
      if (!r.ok) {
        out.missing.push(k);
        out.errors.push({ file: FILES[k], reason: r.reason });
      }
    });
    cache = out;
    return out;
  }

  // ── Contract checks ──────────────────────────────────────
  // Reports which docs/DASHBOARD.md §4 fields the publisher is not yet emitting.
  // Rendered as a banner so D0 gaps are visible instead of quietly wrong.
  function contractGaps(d) {
    const gaps = [];
    if (!d.meta) gaps.push('meta.json (health strip)');
    if (!d.calibration) gaps.push('calibration.json (reliability diagram)');
    if (!d.resolutions) gaps.push('resolutions.json (settled forecasts)');

    if (d.scorecard && d.scorecard.brier_delta === undefined) {
      gaps.push('scorecard.brier_delta / ci95 / verdict');
    }
    const pt = d.equity && d.equity.points && d.equity.points[0];
    if (pt && pt.total_equity === undefined) {
      gaps.push('equity.points[].total_equity (chart falls back to cash)');
    }
    const pos = d.portfolio && d.portfolio.positions && d.portfolio.positions[0];
    if (pos && pos.mark_price === undefined) {
      gaps.push('portfolio.positions[].mark_price / unrealized_pnl');
    }
    return gaps;
  }

  // ── Formatting helpers (presentation only) ───────────────
  const fmt = {
    money(n) {
      if (n === null || n === undefined || isNaN(n)) return '—';
      const s = Math.abs(n).toLocaleString('en-US', {
        minimumFractionDigits: 2, maximumFractionDigits: 2,
      });
      return (n < 0 ? '-$' : '$') + s;
    },
    signedMoney(n) {
      if (n === null || n === undefined || isNaN(n)) return '—';
      return (n >= 0 ? '+' : '') + fmt.money(n).replace('-$', '-$');
    },
    pct(n, dp) {
      if (n === null || n === undefined || isNaN(n)) return '—';
      return (n * 100).toFixed(dp === undefined ? 1 : dp) + '%';
    },
    prob(n) {
      if (n === null || n === undefined || isNaN(n)) return '—';
      return (n * 100).toFixed(1) + '%';
    },
    brier(n) {
      if (n === null || n === undefined || isNaN(n)) return '—';
      return n.toFixed(4);
    },
    num(n, dp) {
      if (n === null || n === undefined || isNaN(n)) return '—';
      return n.toFixed(dp === undefined ? 0 : dp);
    },
    ago(iso) {
      if (!iso) return 'never';
      const then = new Date(iso).getTime();
      if (isNaN(then)) return 'unknown';
      let s = Math.floor((Date.now() - then) / 1000);
      if (s < 0) s = 0;
      if (s < 60) return s + 's ago';
      if (s < 3600) return Math.floor(s / 60) + 'm ago';
      if (s < 86400) return Math.floor(s / 3600) + 'h ago';
      return Math.floor(s / 86400) + 'd ago';
    },
    date(iso) {
      if (!iso) return '—';
      const d = new Date(iso);
      if (isNaN(d.getTime())) return '—';
      return d.toISOString().slice(0, 16).replace('T', ' ') + 'Z';
    },
  };

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function empty(title, detail) {
    return '<div class="empty"><div class="empty-title">' + esc(title) + '</div>' +
      (detail ? '<div class="empty-detail">' + esc(detail) + '</div>' : '') + '</div>';
  }

  return { load, contractGaps, fmt, esc, empty, FILES };
})();
