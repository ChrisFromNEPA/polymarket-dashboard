// Resolutions — the long-run track record. Every settled forecast, scored.
const ResolutionsView = (() => {

  let sortKey = 'resolved_at';
  let sortDir = -1;

  function render(d) {
    const f = Data.fmt;
    const res = d.resolutions;
    const items = (res && (res.items || res.resolutions)) || [];

    let html = '<div class="card"><h2>Settled forecasts</h2>';

    if (!items.length) {
      return html + Data.empty(
        'Nothing has resolved yet',
        'When a market settles, its forecast is scored here — the agent\'s probability, the ' +
        'market\'s, the actual outcome, and each side\'s Brier contribution. This is the record ' +
        'the whole experiment is judged on.'
      ) + '</div>' + explainer();
    }

    const rows = items.slice().sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x === y) return 0;
      return (x > y ? 1 : -1) * sortDir;
    });

    let wins = 0, losses = 0;
    items.forEach(it => {
      if (typeof it.brier_agent === 'number' && typeof it.brier_market === 'number') {
        if (it.brier_agent < it.brier_market) wins++; else losses++;
      }
    });

    html += '<div class="stats">' +
      '<div class="stat"><span class="stat-label">Settled</span><span class="stat-value">' +
        Data.esc(f.num(items.length)) + '</span></div>' +
      '<div class="stat"><span class="stat-label">Beat market</span><span class="stat-value good">' +
        Data.esc(f.num(wins)) + '</span></div>' +
      '<div class="stat"><span class="stat-label">Lost to market</span><span class="stat-value bad">' +
        Data.esc(f.num(losses)) + '</span></div>' +
      '</div>';

    html += '<table class="tbl"><thead><tr>' +
      th('Market', 'question') + th('Agent', 'p_agent', true) + th('Market', 'p_market', true) +
      '<th class="num">Outcome</th>' +
      th('Brier A', 'brier_agent', true) + th('Brier M', 'brier_market', true) +
      th('P&L', 'pnl', true) + th('Resolved', 'resolved_at') +
      '</tr></thead><tbody>';

    rows.forEach(it => {
      const better = typeof it.brier_agent === 'number' && typeof it.brier_market === 'number'
        && it.brier_agent < it.brier_market;
      html += '<tr class="' + (better ? 'tr-win' : '') + '">' +
        '<td class="td-q">' + Data.esc(it.question || it.market_question || '—') + '</td>' +
        '<td class="num">' + Data.esc(f.prob(it.p_agent)) + '</td>' +
        '<td class="num">' + Data.esc(f.prob(it.p_market)) + '</td>' +
        '<td class="num"><span class="badge ' + (it.outcome === 1 ? 'badge-yes' : 'badge-no') + '">' +
          (it.outcome === 1 ? 'YES' : 'NO') + '</span></td>' +
        '<td class="num ' + (better ? 'good' : '') + '">' + Data.esc(f.brier(it.brier_agent)) + '</td>' +
        '<td class="num">' + Data.esc(f.brier(it.brier_market)) + '</td>' +
        '<td class="num ' + (it.pnl >= 0 ? 'good' : 'bad') + '">' +
          Data.esc(typeof it.pnl === 'number' ? f.signedMoney(it.pnl) : '—') + '</td>' +
        '<td>' + Data.esc(f.ago(it.resolved_at)) + '</td>' +
        '</tr>';
    });

    html += '</tbody></table>';
    html += '<div class="footnote">"Beat market" counts forecasts where the agent\'s Brier ' +
      'contribution was lower than the market\'s on that question. A raw win count is not a ' +
      'verdict — a few large misses outweigh many small wins, which is why the Verdict tab ' +
      'uses the aggregate delta with a confidence interval.</div>';

    return html + '</div>' + explainer();
  }

  function th(label, key, num) {
    const active = sortKey === key;
    return '<th class="' + (num ? 'num ' : '') + 'sortable' + (active ? ' sorted' : '') +
      '" data-sort="' + key + '">' + Data.esc(label) +
      (active ? (sortDir === 1 ? ' ▲' : ' ▼') : '') + '</th>';
  }

  function explainer() {
    return '<div class="card card-quiet"><h2>Reading the record</h2>' +
      '<p>A forecast can be "wrong" and still good. Predicting 20% for something that happens ' +
      'is not a failure if it really was a 20% event — over many such calls, roughly one in five ' +
      'should happen. That is what the Calibration tab checks.</p>' +
      '<p>What matters here is the <strong>paired comparison</strong>: on the same question at ' +
      'the same moment, was the agent closer to the truth than the market price was?</p></div>';
  }

  function bind(rerender) {
    document.addEventListener('click', e => {
      const th = e.target.closest && e.target.closest('[data-sort]');
      if (!th) return;
      const key = th.getAttribute('data-sort');
      if (sortKey === key) sortDir = -sortDir; else { sortKey = key; sortDir = -1; }
      rerender();
    });
  }

  return { render, bind };
})();
