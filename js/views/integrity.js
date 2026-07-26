// Integrity view — contradictions between published state files.
const IntegrityView = (() => {

  function render(d) {
    const issues = Integrity.check(d);
    const c = Integrity.counts(issues);

    let html = '<div class="card"><div class="card-head"><h2>Data integrity</h2>' +
      '<div class="chips">' +
        '<span class="badge ' + (c.errors ? 'badge-no' : 'badge-ok') + '">' +
          c.errors + ' error' + (c.errors === 1 ? '' : 's') + '</span>' +
        '<span class="badge ' + (c.warns ? 'badge-muted' : 'badge-ok') + '">' +
          c.warns + ' warning' + (c.warns === 1 ? '' : 's') + '</span>' +
      '</div></div>';

    if (!issues.length) {
      html += Data.empty('All checks pass',
        'The published state files agree with each other. This does not mean the agent is ' +
        'right — only that it is not contradicting itself.');
      return html + '</div>' + explainer();
    }

    issues.forEach(it => {
      html += '<div class="issue issue-' + it.severity + '">' +
        '<div class="issue-head">' +
          '<span class="badge ' + (it.severity === 'error' ? 'badge-no' : 'badge-muted') + '">' +
            it.severity.toUpperCase() + '</span>' +
          '<span class="issue-title">' + Data.esc(it.title) + '</span>' +
        '</div>' +
        '<div class="issue-detail">' + Data.esc(it.detail) + '</div>' +
        (it.fix ? '<div class="issue-fix"><strong>Likely cause:</strong> ' +
          Data.esc(it.fix) + '</div>' : '') +
        '</div>';
    });

    return html + '</div>' + explainer();
  }

  function explainer() {
    return '<div class="card card-quiet"><h2>Why this tab exists</h2>' +
      '<p>This project has repeatedly published state where P&amp;L, equity and fill prices ' +
      'disagreed with each other, and nothing on screen made that visible. A dashboard that ' +
      'renders whatever it is given will happily show a confident, wrong number.</p>' +
      '<p>These checks recompute only to <strong>verify</strong>. Where two published files ' +
      'disagree, the dashboard reports the disagreement instead of quietly picking one — ' +
      'because choosing the nicer-looking number is exactly how a long experiment drifts ' +
      'into telling you what you want to hear.</p></div>';
  }

  return { render };
})();
