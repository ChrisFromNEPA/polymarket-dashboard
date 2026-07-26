// Positions & equity — deliberately NOT the headline (docs/DASHBOARD.md §2.1).
const PositionsView = (() => {

  function render(d) {
    const f = Data.fmt;
    const p = d.portfolio || {};
    const eq = d.equity || {};
    const points = eq.points || [];

    // Prefer published total_equity. Falling back to cash silently would repeat
    // the exact bug this dashboard exists to surface, so the fallback is labelled.
    const hasTotal = points.length > 0 && points[0].total_equity !== undefined;
    const series = points.map(pt => ({
      t: pt.time || pt.t,
      v: hasTotal ? pt.total_equity : pt.cash,
    }));

    let html = '';

    if (!hasTotal && points.length) {
      html += '<div class="banner banner-warn"><strong>Equity chart is showing cash only</strong>' +
        '<div class="banner-sub">The publisher is not emitting <code>total_equity</code>, so open ' +
        'positions count as zero. Any P&amp;L below understates or overstates reality until ' +
        '<code>runner.py</code> publishes equity as cash + Σ(shares × mark).</div></div>';
    }

    html += summary(p, eq, f, hasTotal);

    if (series.length > 1) {
      html += '<div class="card"><div class="card-head"><h2>Equity</h2>' +
        execBadge(eq) + '</div>' +
        Charts.lineChart(series, {
          money: true,
          baseline: p.starting_cash,
          ariaLabel: 'Portfolio equity over time',
        }) +
        '<div class="footnote">Dashed line is starting capital (' +
        Data.esc(f.money(p.starting_cash)) + ').</div></div>';
    }

    html += positionsCard(p, f);
    return html;
  }

  function execBadge(eq) {
    const q = eq.execution_quality;
    if (!q) return '';
    const measured = q === 'measured';
    return '<span class="badge ' + (measured ? 'badge-ok' : 'badge-muted') + '" ' +
      'title="' + (measured
        ? 'Fills measured against recorded order books'
        : 'Fills estimated from a spread model — no historical order books exist') + '">' +
      'execution: ' + Data.esc(q) + '</span>';
  }

  function summary(p, eq, f, hasTotal) {
    const cash = p.cash;
    const start = p.starting_cash;
    const positions = p.positions || [];
    const posValue = positions.reduce((s, x) => {
      const mark = typeof x.mark_price === 'number' ? x.mark_price : null;
      return mark === null ? s : s + mark * (x.shares || 0);
    }, 0);
    const total = hasTotal && eq.points && eq.points.length
      ? eq.points[eq.points.length - 1].total_equity
      : null;

    return '<div class="stats">' +
      stat('Cash', f.money(cash)) +
      stat('Positions', f.num(positions.length)) +
      stat('Position value', positions.length ? f.money(posValue) : '—') +
      stat('Total equity', total === null ? '—' : f.money(total)) +
      stat('Starting', f.money(start)) +
      '</div>';
  }

  function stat(label, value) {
    return '<div class="stat"><span class="stat-label">' + Data.esc(label) + '</span>' +
      '<span class="stat-value">' + Data.esc(value) + '</span></div>';
  }

  function positionsCard(p, f) {
    const positions = p.positions || [];
    let html = '<div class="card"><h2>Open positions</h2>';

    if (!positions.length) {
      return html + Data.empty('No open positions',
        'The agent holds nothing right now. This is the expected state most of the time — ' +
        'the trade gate rejects anything whose edge does not survive costs.') + '</div>';
    }

    // Group by NegRisk cluster so concentrated bets read as one exposure.
    const groups = {};
    positions.forEach(pos => {
      const key = pos.cluster_id || pos.event_id || pos.condition_id || '_';
      (groups[key] = groups[key] || []).push(pos);
    });

    html += '<table class="tbl"><thead><tr>' +
      '<th>Market</th><th>Side</th><th class="num">Shares</th><th class="num">Entry</th>' +
      '<th class="num">Mark</th><th class="num">Fair</th><th class="num">Unrealized</th>' +
      '</tr></thead><tbody>';

    Object.keys(groups).forEach(key => {
      const g = groups[key];
      if (g.length > 1) {
        html += '<tr class="tr-group"><td colspan="7">Cluster — ' + Data.esc(g.length) +
          ' positions in one event group</td></tr>';
      }
      g.forEach(pos => { html += row(pos, f); });
    });

    return html + '</tbody></table>' +
      '<div class="footnote">"Fair" is the agent\'s own probability estimate at entry. ' +
      'If entry is worse than fair, the trade lost money the moment it was placed — the risk ' +
      'manager now rejects those outright.</div></div>';
  }

  function row(pos, f) {
    const mark = typeof pos.mark_price === 'number' ? pos.mark_price : null;
    const entry = pos.avg_entry_price;
    const shares = pos.shares || 0;
    const unreal = typeof pos.unrealized_pnl === 'number'
      ? pos.unrealized_pnl
      : (mark === null ? null : (mark - entry) * shares);

    const fair = pos.fair_estimate;
    // fair_estimate is P(YES); for a NO position the comparable fair value is 1 - p.
    const fairForSide = typeof fair === 'number'
      ? (String(pos.outcome).toLowerCase() === 'no' ? 1 - fair : fair)
      : null;
    const overpaid = fairForSide !== null && entry > fairForSide + 1e-9;

    return '<tr>' +
      '<td class="td-q">' + Data.esc(pos.market_question || '—') + '</td>' +
      '<td><span class="badge ' + (String(pos.outcome).toLowerCase() === 'no' ? 'badge-no' : 'badge-yes') +
        '">' + Data.esc(String(pos.outcome || '?').toUpperCase()) + '</span></td>' +
      '<td class="num">' + Data.esc(f.num(shares)) + '</td>' +
      '<td class="num' + (overpaid ? ' bad' : '') + '">' + Data.esc(f.brier(entry)) +
        (overpaid ? ' <span class="warn-mark" title="Entry is worse than the agent\'s own fair value">!</span>' : '') + '</td>' +
      '<td class="num">' + Data.esc(mark === null ? '—' : f.brier(mark)) + '</td>' +
      '<td class="num">' + Data.esc(fairForSide === null ? '—' : f.brier(fairForSide)) + '</td>' +
      '<td class="num ' + (unreal === null ? '' : (unreal >= 0 ? 'good' : 'bad')) + '">' +
        Data.esc(unreal === null ? '—' : f.signedMoney(unreal)) + '</td>' +
      '</tr>';
  }

  return { render };
})();
