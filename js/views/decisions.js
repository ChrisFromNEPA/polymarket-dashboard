// Decision feed — what the agent thought, including what it declined.
//
// docs/DASHBOARD.md §5.3: the filter defaults to "all". A feed showing only
// executed trades hides most of the agent's behaviour and reads as survivorship bias.
const DecisionsView = (() => {

  let filter = 'all';

  function render(d) {
    const f = Data.fmt;
    const raw = d.decisions;
    const items = (raw && (raw.decisions || raw.items)) || [];

    let html = '<div class="card"><div class="card-head">' +
      '<h2>Decision feed</h2>' + filterBar(items) + '</div>';

    if (!items.length) {
      html += Data.empty(
        'No decisions recorded yet',
        'The agent publishes every evaluation here — both trades it placed and markets it ' +
        'rejected, with the reason. Rejections are shown by default.'
      );
      return html + '</div>' + explainer();
    }

    const shown = items.filter(matches);
    if (!shown.length) {
      html += Data.empty('Nothing matches this filter', 'Switch back to "All" to see every evaluation.');
      return html + '</div>' + explainer();
    }

    shown.forEach(it => { html += entry(it, f); });
    return html + '</div>' + explainer();
  }

  function matches(it) {
    if (filter === 'all') return true;
    const action = String(it.action || (it.traded ? 'traded' : 'rejected')).toLowerCase();
    return filter === 'traded' ? action === 'traded' : action !== 'traded';
  }

  function filterBar(items) {
    const traded = items.filter(i => String(i.action || '').toLowerCase() === 'traded').length;
    const rejected = items.length - traded;
    const opt = (key, label, count) =>
      '<button class="chip ' + (filter === key ? 'chip-on' : '') + '" data-filter="' + key + '">' +
      Data.esc(label) + (count === undefined ? '' : ' <span class="chip-n">' + count + '</span>') + '</button>';
    return '<div class="chips">' +
      opt('all', 'All', items.length) +
      opt('traded', 'Traded', traded) +
      opt('rejected', 'Rejected', rejected) +
      '</div>';
  }

  function entry(it, f) {
    const action = String(it.action || (it.traded ? 'traded' : 'rejected')).toLowerCase();
    const isTraded = action === 'traded';
    const pa = it.p_agent, pm = it.p_market;

    let edgeHtml = '';
    if (typeof pa === 'number' && typeof pm === 'number') {
      edgeHtml = '<span class="kv"><em>agent</em> ' + f.prob(pa) + '</span>' +
        '<span class="kv"><em>market</em> ' + f.prob(pm) + '</span>';
    }
    if (typeof it.edge_net === 'number') {
      edgeHtml += '<span class="kv"><em>edge net</em> ' +
        ((it.edge_net >= 0 ? '+' : '') + (it.edge_net * 100).toFixed(1)) + 'pp</span>';
    }

    let outcomeBadge = '';
    if (it.outcome === 1 || it.outcome === 0) {
      outcomeBadge = '<span class="badge ' + (it.outcome === 1 ? 'badge-yes' : 'badge-no') + '">' +
        'resolved ' + (it.outcome === 1 ? 'YES' : 'NO') + '</span>';
    }

    let html = '<div class="decision ' + (isTraded ? 'd-traded' : 'd-rejected') + '">' +
      '<div class="d-head">' +
        '<span class="badge ' + (isTraded ? 'badge-traded' : 'badge-rejected') + '">' +
          (isTraded ? 'TRADED' : 'REJECTED') + '</span>' +
        (it.strategy || it.strategy_name ? '<span class="badge badge-muted">' +
          Data.esc(it.strategy || it.strategy_name) + '</span>' : '') +
        outcomeBadge +
        '<span class="d-time">' + Data.esc(f.ago(it.time || it.timestamp)) + '</span>' +
      '</div>' +
      '<div class="d-q">' + Data.esc(it.market_question || it.question || 'Unknown market') + '</div>' +
      (edgeHtml ? '<div class="d-kvs">' + edgeHtml + '</div>' : '');

    if (!isTraded && (it.reject_reason || it.reason)) {
      html += '<div class="d-reason"><strong>Rejected:</strong> ' +
        Data.esc(it.reject_reason || it.reason) + '</div>';
    }
    if (it.reasoning) {
      html += '<details class="d-reasoning"><summary>Reasoning</summary><div>' +
        Data.esc(it.reasoning) + '</div></details>';
    }
    return html + '</div>';
  }

  function explainer() {
    return '<div class="card card-quiet"><h2>Why rejections are shown</h2>' +
      '<p>Most of what an agent does is decline to act. Showing only executed trades would ' +
      'hide the majority of its behaviour and make the strategy look far more selective — or ' +
      'far more reckless — than it is.</p>' +
      '<p>Rejections are also free calibration data: the agent logs a probability estimate for ' +
      'markets it never traded, and those forecasts still get scored when the market resolves.</p></div>';
  }

  // Delegated click handling — the feed re-renders on filter change.
  function bind(rerender) {
    document.addEventListener('click', e => {
      const btn = e.target.closest && e.target.closest('[data-filter]');
      if (!btn) return;
      filter = btn.getAttribute('data-filter');
      rerender();
    });
  }

  return { render, bind };
})();
