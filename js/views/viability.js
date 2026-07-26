// Market Fit — cost of trading, and whether we're trading the right markets.
//
// docs/RESEARCH.md §1: the agent has been trading 2028-election longshots —
// >800 day horizon, prices at $0.002-$0.13, inside a 128-outcome NegRisk event.
// Published guidance says target 7-60 days, $0.10-$0.90, binary only. That is a
// bigger lever than any model improvement, so it belongs on screen.
const ViabilityView = (() => {

  // docs/RESEARCH.md §1
  const CRITERIA = {
    priceMin: 0.10,
    priceMax: 0.90,
    horizonMinDays: 7,
    horizonMaxDays: 60,
  };

  function render(d) {
    const f = Data.fmt;
    return fitCard(d, f) + costCard(d, f) + criteriaCard();
  }

  // ── Are we trading markets we can be right about? ─────────

  function fitCard(d, f) {
    const positions = (d.portfolio && d.portfolio.positions) || [];
    let html = '<div class="card"><h2>Market fit <span class="hint">open positions vs. selection criteria</span></h2>';

    if (!positions.length) {
      return html + Data.empty('No open positions',
        'When the agent holds something, each position is checked here against the ' +
        'target profile: 7–60 day horizon, $0.10–$0.90, binary structure.') + '</div>';
    }

    let violations = 0;
    let rows = '';
    positions.forEach(p => {
      // fair_estimate is P(YES); express the position's own price on its side.
      const price = typeof p.mark_price === 'number' ? p.mark_price : p.avg_entry_price;
      // Price-range criterion applies to the underlying YES probability, not the
      // side we happen to hold — buying NO at 0.95 is still an extreme market.
      const yesProb = String(p.outcome).toLowerCase() === 'no'
        ? (typeof price === 'number' ? 1 - price : null)
        : price;

      const priceOk = typeof yesProb === 'number'
        && yesProb >= CRITERIA.priceMin && yesProb <= CRITERIA.priceMax;
      const days = daysTo(p.end_date);
      const horizonOk = days === null ? null
        : days >= CRITERIA.horizonMinDays && days <= CRITERIA.horizonMaxDays;

      if (!priceOk || horizonOk === false) violations++;

      rows += '<tr>' +
        '<td class="td-q">' + Data.esc(p.market_question || '—') + '</td>' +
        '<td class="num">' + Data.esc(typeof yesProb === 'number' ? f.prob(yesProb) : '—') + '</td>' +
        '<td>' + flag(priceOk, priceOk ? 'in range' : 'extreme') + '</td>' +
        '<td class="num">' + Data.esc(days === null ? '—' : Math.round(days) + 'd') + '</td>' +
        '<td>' + flag(horizonOk, horizonOk === null ? 'no end_date'
          : (horizonOk ? 'in range' : 'out of range')) + '</td>' +
        '</tr>';
    });

    if (violations) {
      html += '<div class="banner banner-warn"><strong>' + violations + ' of ' +
        positions.length + ' positions sit outside the target profile</strong>' +
        '<div class="banner-sub">Cheap to trade is not the same as possible to be ' +
        'right about. Extreme prices leave no room to be right in — at $0.002 the ' +
        'tick size is half the price.</div></div>';
    }

    html += '<table class="tbl"><thead><tr><th>Market</th><th class="num">P(Yes)</th>' +
      '<th>Price</th><th class="num">Horizon</th><th>Horizon fit</th></tr></thead><tbody>' +
      rows + '</tbody></table>';

    html += '<div class="footnote">Target profile (docs/RESEARCH.md §1): ' +
      '<strong>7–60 day</strong> horizon, <strong>$0.10–$0.90</strong>, binary ' +
      'structure, ≥$50k volume. Horizon needs <code>end_date</code> on published ' +
      'positions — add it to the publisher if it shows as “—”.</div>';

    return html + '</div>';
  }

  function flag(ok, label) {
    if (ok === null) return '<span class="badge badge-muted">' + Data.esc(label) + '</span>';
    return '<span class="badge ' + (ok ? 'badge-ok' : 'badge-no') + '">' +
      Data.esc(label) + '</span>';
  }

  function daysTo(iso) {
    if (!iso) return null;
    const t = new Date(iso).getTime();
    if (isNaN(t)) return null;
    return (t - Date.now()) / 86400000;
  }

  // ── Cost of entry ─────────────────────────────────────────

  function costCard(d, f) {
    const v = d.viability;
    let html = '<div class="card"><h2>Cost of entry <span class="hint">Phase E</span></h2>';

    if (!v) {
      return html + Data.empty('No viability study published',
        'Run `python -m agent.viability 300` to measure what it costs to enter ' +
        'each market segment.') + '</div>';
    }

    html += '<div class="stats">' +
      stat('Markets measured', f.num(v.markets_measured)) +
      stat('Cost ≤ 2¢', f.num(v.markets_under_2c_cost)) +
      stat('Viable fraction', f.pct(v.viable_fraction)) +
      stat('Required edge p50', v.required_edge_p50 === null ? '—' : f.brier(v.required_edge_p50)) +
      stat('Required edge p90', v.required_edge_p90 === null ? '—' : f.brier(v.required_edge_p90)) +
      '</div>';

    const segs = (v.by_segment || []).filter(s => s.required_edge_p50 !== null);
    if (segs.length) {
      html += '<table class="tbl"><thead><tr><th>Segment</th><th class="num">n</th>' +
        '<th class="num">Depth</th><th class="num">p50</th><th class="num">p90</th>' +
        '</tr></thead><tbody>';
      segs.forEach(s => {
        html += '<tr>' +
          '<td>' + Data.esc(s.segment) + '</td>' +
          '<td class="num">' + Data.esc(f.num(s.markets)) + '</td>' +
          '<td class="num">' + Data.esc(f.pct(s.depth_rate, 0)) + '</td>' +
          '<td class="num">' + Data.esc(f.brier(s.required_edge_p50)) + '</td>' +
          '<td class="num">' + Data.esc(f.brier(s.required_edge_p90)) + '</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    }

    html += '<div class="footnote"><strong>Required edge</strong> is how much better ' +
      'than the market you must be, per share, just to break even at ' +
      Data.esc(v.probe_size || '$200') + '. Where it exceeds any plausible ' +
      'forecasting edge, the segment is dead regardless of model quality. ' +
      'The 2¢ bar is the minimum viable net edge from ECONOMICS.md §7.</div>';

    return html + '</div>';
  }

  function stat(label, value) {
    return '<div class="stat"><span class="stat-label">' + Data.esc(label) + '</span>' +
      '<span class="stat-value">' + Data.esc(value) + '</span></div>';
  }

  // ── Why these criteria ────────────────────────────────────

  function criteriaCard() {
    return '<div class="card card-quiet"><h2>Why these criteria</h2>' +
      '<ul class="notes">' +
      '<li><strong>Extreme prices lack edge.</strong> At $0.002 the market is ' +
      'already saying “essentially never”, the tick size is half the price, and ' +
      'no forecaster meaningfully distinguishes 0.2% from 0.4%.</li>' +
      '<li><strong>Long horizons dilute information.</strong> Edge means knowing ' +
      'something unpriced. Over 800 days almost any information decays.</li>' +
      '<li><strong>Multi-outcome events are one bet, not many.</strong> 128 ' +
      'candidates for one nomination is a single correlated exposure.</li>' +
      '<li><strong>Cheap ≠ winnable.</strong> Phase E shows these markets cost ' +
      '~0.0005 to enter. That is necessary, not sufficient — low cost plus no ' +
      'edge is still no profit.</li>' +
      '</ul></div>';
  }

  return { render };
})();
