// Verdict — the hero view. Brier delta, not P&L.
//
// docs/DASHBOARD.md §2.1: if P&L is the biggest number on screen, that is what
// gets optimized. So the headline is the paired Brier delta, and the verdict
// string comes from the publisher — the UI never decides whether we have edge.
const VerdictView = (() => {

  const VERDICT_TEXT = {
    edge_detected: 'EDGE DETECTED',
    no_detectable_edge: 'NO DETECTABLE EDGE YET',
    worse_than_market: 'WORSE THAN MARKET',
  };
  const VERDICT_CLASS = {
    edge_detected: 'v-good',
    no_detectable_edge: 'v-neutral',
    worse_than_market: 'v-bad',
  };

  function render(d) {
    const f = Data.fmt;
    const sc = d.scorecard || {};
    const n = sc.n_resolved;

    let html = gapsBanner(d);
    html += heroCard(sc, n, f);
    html += healthStrip(d, f);
    html += benchmarks(sc, f);
    html += notes(n);
    return html;
  }

  function gapsBanner(d) {
    const gaps = Data.contractGaps(d);
    if (!gaps.length) return '';
    let html = '<div class="banner banner-warn"><strong>Publisher contract incomplete</strong>' +
      '<div class="banner-sub">These <code>docs/DASHBOARD.md</code> §4 fields are not being emitted yet, ' +
      'so the views below are partial. This is D0 work on the agent side.</div><ul>';
    gaps.forEach(g => { html += '<li>' + Data.esc(g) + '</li>'; });
    return html + '</ul></div>';
  }

  function heroCard(sc, n, f) {
    // No resolutions yet → say so plainly. Never render a verdict we can't support.
    if (!n) {
      return '<div class="hero v-neutral">' +
        '<div class="hero-verdict">AWAITING RESOLVED FORECASTS</div>' +
        '<div class="hero-sub">The experiment has not scored anything yet. ' +
        'A verdict needs markets to actually resolve.</div>' +
        '<div class="hero-stats"><div class="hstat"><span class="hstat-label">Resolved</span>' +
        '<span class="hstat-value">0</span></div></div></div>';
    }

    const verdict = sc.verdict || 'no_detectable_edge';
    const cls = VERDICT_CLASS[verdict] || 'v-neutral';
    const label = VERDICT_TEXT[verdict] || String(verdict).toUpperCase();
    const ci = sc.brier_delta_ci95;

    let ciText = '';
    if (Array.isArray(ci) && ci.length === 2) {
      ciText = '95% CI [' + f.brier(ci[0]) + ', ' + f.brier(ci[1]) + ']';
    }

    return '<div class="hero ' + cls + '">' +
      '<div class="hero-verdict">' + Data.esc(label) + '</div>' +
      '<div class="hero-sub">Lower Brier is better. Negative delta means the agent beat the market.</div>' +
      '<div class="hero-stats">' +
        hstat('Agent Brier', f.brier(sc.brier_agent)) +
        hstat('Market Brier', f.brier(sc.brier_market)) +
        hstat('Delta', f.brier(sc.brier_delta), sc.brier_delta < 0 ? 'good' : (sc.brier_delta > 0 ? 'bad' : '')) +
        hstat('Resolved', f.num(n)) +
      '</div>' +
      (ciText ? '<div class="hero-ci">' + Data.esc(ciText) + '</div>' : '') +
      '</div>';
  }

  function hstat(label, value, cls) {
    return '<div class="hstat"><span class="hstat-label">' + Data.esc(label) + '</span>' +
      '<span class="hstat-value ' + (cls || '') + '">' + Data.esc(value) + '</span></div>';
  }

  function healthStrip(d, f) {
    const m = d.meta;
    if (!m) {
      return '<div class="strip strip-muted">' +
        '<span class="dot dot-unknown"></span> Agent health unknown — ' +
        '<code>state/meta.json</code> not published yet.</div>';
    }
    const last = m.last_cycle_at;
    const ageMin = last ? (Date.now() - new Date(last).getTime()) / 60000 : Infinity;
    const stale = !(ageMin < 300); // > ~2 cycles at 4h cadence
    const errs = m.errors_last_24h || 0;

    return '<div class="strip">' +
      '<span class="' + (stale || errs ? 'dot dot-warn' : 'dot dot-ok') + '"></span>' +
      '<span>' + (stale ? 'Stale' : 'Live') + '</span>' +
      sep() + '<span>last cycle ' + Data.esc(f.ago(last)) + '</span>' +
      (m.next_cycle_eta ? sep() + '<span>next ' + Data.esc(f.date(m.next_cycle_eta)) + '</span>' : '') +
      sep() + '<span class="badge badge-muted">mode: ' + Data.esc(m.mode || '?') + '</span>' +
      sep() + '<span>' + Data.esc(f.num(m.cycles_total)) + ' cycles</span>' +
      sep() + '<span class="' + (errs ? 'bad' : '') + '">' + Data.esc(f.num(errs)) + ' errors/24h</span>' +
      '</div>';
  }

  function sep() { return '<span class="strip-sep">·</span>'; }

  function benchmarks(sc, f) {
    if (!sc.n_resolved) return '';
    const rows = [];
    if (typeof sc.brier_agent === 'number') {
      rows.push({ label: 'Agent', value: sc.brier_agent, display: f.brier(sc.brier_agent), cls: 'bar-agent' });
    }
    if (typeof sc.brier_market === 'number') {
      rows.push({ label: 'Market', value: sc.brier_market, display: f.brier(sc.brier_market), cls: 'bar-market' });
    }
    const bm = sc.benchmarks || {};
    Object.keys(bm).forEach(k => {
      if (typeof bm[k] === 'number') {
        rows.push({ label: k.replace(/_/g, ' '), value: bm[k], display: f.brier(bm[k]), cls: 'bar-bench' });
      }
    });
    if (rows.length < 2) return '';

    return '<div class="card"><h2>Brier comparison <span class="hint">lower is better</span></h2>' +
      Charts.compareBars(rows) +
      '<div class="footnote">Reference points — ForecastBench: human superforecasters ≈ 0.096, ' +
      'best LLMs ≈ 0.122–0.136, general public ≈ 0.121. Absolute Brier is not comparable across ' +
      'different question sets; only the paired agent-vs-market delta counts.</div></div>';
  }

  function notes(n) {
    let html = '<div class="card card-quiet"><h2>How to read this</h2><ul class="notes">' +
      '<li><strong>Brier, not P&amp;L.</strong> Over a few hundred trades P&amp;L is mostly variance. ' +
      'Brier measures whether the forecasts were actually better.</li>' +
      '<li><strong>A confidence interval crossing zero means no detectable edge</strong> — ' +
      'not a small edge. The honest reading is "we cannot tell yet."</li>' +
      '<li><strong>Sample size gates everything.</strong> A month gives roughly 100–200 ' +
      'resolutions, which is a smoke test rather than a verdict.</li>';
    if (n) {
      html += '<li><strong>A negative result is a valid outcome</strong> and is not a reason ' +
        'to retune the model.</li>';
    }
    return html + '</ul></div>';
  }

  return { render };
})();
