// Calibration — reliability diagram + ECE.
// Marker area encodes bin count so sparse buckets look sparse (see charts.js).
const CalibrationView = (() => {

  function render(d) {
    const f = Data.fmt;
    const cal = d.calibration;
    const sc = d.scorecard || {};

    if (!cal || !cal.bins || !cal.bins.length) {
      return '<div class="card"><h2>Calibration</h2>' +
        Data.empty(
          'No calibration data yet',
          'Needs state/calibration.json from the publisher, plus resolved forecasts to bin. ' +
          'Until markets resolve there is nothing to calibrate against.'
        ) + explainer() + '</div>';
    }

    const bins = cal.bins.filter(b => b && b.n > 0);
    const total = bins.reduce((s, b) => s + (b.n || 0), 0);

    let html = '<div class="grid-2">';
    html += '<div class="card"><h2>Reliability diagram</h2>' +
      Charts.reliability(bins) +
      '<div class="footnote">Points on the diagonal are perfectly calibrated. Above the line = ' +
      'underconfident (events happened more often than predicted); below = overconfident. ' +
      'Marker area is proportional to the number of forecasts in that bucket.</div></div>';

    html += '<div class="card"><h2>Bins</h2>' + table(bins, total, f) + '</div>';
    html += '</div>';

    if (typeof sc.ece === 'number') {
      html += '<div class="card"><h2>Expected Calibration Error</h2>' +
        '<div class="bignum">' + Data.esc(f.brier(sc.ece)) + '</div>' +
        '<div class="footnote">Average gap between predicted probability and realized frequency, ' +
        'weighted by bin size. Lower is better. ECE and Brier measure different things — a model ' +
        'can be well calibrated and still uninformative, so read this alongside the Verdict tab.</div>' +
        '</div>';
    }

    return html + explainer();
  }

  function table(bins, total, f) {
    let html = '<table class="tbl"><thead><tr>' +
      '<th>Bucket</th><th class="num">n</th><th class="num">Predicted</th>' +
      '<th class="num">Realized</th><th class="num">Gap</th></tr></thead><tbody>';
    bins.forEach(b => {
      const gap = (b.realized || 0) - (b.predicted || 0);
      const cls = Math.abs(gap) > 0.1 ? 'bad' : (Math.abs(gap) > 0.05 ? 'warn' : 'good');
      html += '<tr>' +
        '<td>' + Data.esc((b.p_lo * 100).toFixed(0) + '–' + (b.p_hi * 100).toFixed(0) + '%') + '</td>' +
        '<td class="num">' + Data.esc(f.num(b.n)) + '</td>' +
        '<td class="num">' + Data.esc(f.prob(b.predicted)) + '</td>' +
        '<td class="num">' + Data.esc(f.prob(b.realized)) + '</td>' +
        '<td class="num ' + cls + '">' + Data.esc((gap >= 0 ? '+' : '') + (gap * 100).toFixed(1) + 'pp') + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    html += '<div class="footnote">' + Data.esc(f.num(total)) + ' resolved forecasts across ' +
      Data.esc(f.num(bins.length)) + ' buckets. Buckets with few forecasts are noisy — ' +
      'treat a large gap on a small n as unproven.</div>';
    return html;
  }

  function explainer() {
    return '<div class="card card-quiet"><h2>Why calibration matters here</h2>' +
      '<p>RLHF-tuned language models systematically <strong>hedge toward mid-range ' +
      'probabilities</strong>. That bias is correctable statistically — via extremization ' +
      '(log-odds power transform), Platt scaling, or isotonic regression — but not by prompting.</p>' +
      '<p>Post-hoc calibration is the step most likely to be skipped and the one most likely ' +
      'to determine whether this project works. When the calibration layer lands, this view ' +
      'should show pre- and post-calibration curves side by side; if calibration is not visibly ' +
      'improving the curve, it is not earning its place.</p></div>';
  }

  return { render };
})();
