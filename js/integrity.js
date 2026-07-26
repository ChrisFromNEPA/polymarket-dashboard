// Integrity checks — cross-verify the published state files against each other.
//
// The UI still does not compute statistics *for display* (docs/DASHBOARD.md §2.3).
// It recomputes only to VERIFY, and reports disagreement rather than substituting
// its own answer. When two published files contradict each other, the dashboard's
// job is to say so loudly — not to quietly pick the one that looks nicer.
//
// This exists because the project has repeatedly shipped state where P&L, equity
// and fills disagreed, and nothing on screen made that visible.
const Integrity = (() => {

  const MONEY_TOL = 0.02;   // dollars
  const PRICE_TOL = 0.02;   // probability points

  function check(d) {
    const issues = [];
    const sc = d.scorecard || {};
    const pf = d.portfolio || {};
    const eq = d.equity || {};
    const points = eq.points || [];
    const last = points.length ? points[points.length - 1] : null;
    const positions = pf.positions || [];

    // ── 1. P&L agreement across files ─────────────────────
    if (last && typeof sc.total_pnl === 'number' && typeof last.pnl === 'number') {
      const diff = Math.abs(sc.total_pnl - last.pnl);
      if (diff > MONEY_TOL) {
        issues.push({
          severity: 'error',
          title: 'P&L disagrees between scorecard and equity',
          detail: 'scorecard.total_pnl = ' + fmtMoney(sc.total_pnl) +
            ' but equity.points[last].pnl = ' + fmtMoney(last.pnl) +
            ' — a difference of ' + fmtMoney(diff) + '.',
          fix: 'Almost always means one path still computes cash − starting_cash and ' +
            'values open positions at zero. Both should use cash + Σ(shares × mark).',
        });
      }
    }

    // ── 2. Cash agreement ─────────────────────────────────
    if (typeof sc.current_cash === 'number' && typeof pf.cash === 'number') {
      if (Math.abs(sc.current_cash - pf.cash) > MONEY_TOL) {
        issues.push({
          severity: 'error',
          title: 'Cash disagrees between scorecard and portfolio',
          detail: 'scorecard.current_cash = ' + fmtMoney(sc.current_cash) +
            ' vs portfolio.cash = ' + fmtMoney(pf.cash) + '.',
          fix: 'Publish both from the same portfolio snapshot.',
        });
      }
    }

    // ── 3. Equity arithmetic ──────────────────────────────
    if (last && typeof last.total_equity === 'number' &&
        typeof last.cash === 'number' && typeof last.positions_value === 'number') {
      const expected = last.cash + last.positions_value;
      if (Math.abs(expected - last.total_equity) > MONEY_TOL) {
        issues.push({
          severity: 'error',
          title: 'Equity does not equal cash + positions',
          detail: fmtMoney(last.cash) + ' + ' + fmtMoney(last.positions_value) +
            ' = ' + fmtMoney(expected) + ', but total_equity = ' + fmtMoney(last.total_equity) + '.',
          fix: 'Check get_total_equity() and the marks dict passed to it.',
        });
      }
    }

    // ── 4. Positions value matches the position list ──────
    if (last && typeof last.positions_value === 'number' && positions.length) {
      let sum = 0, complete = true;
      positions.forEach(p => {
        if (typeof p.mark_price !== 'number' || typeof p.shares !== 'number') complete = false;
        else sum += p.mark_price * p.shares;
      });
      if (complete && Math.abs(sum - last.positions_value) > MONEY_TOL) {
        issues.push({
          severity: 'warn',
          title: 'Positions value does not match the position list',
          detail: 'Σ(shares × mark) = ' + fmtMoney(sum) +
            ' but equity.positions_value = ' + fmtMoney(last.positions_value) + '.',
          fix: 'The two snapshots were probably taken at different marks.',
        });
      }
    }

    // ── 5. Bought above own fair value ────────────────────
    // The invariant that is supposed to make this impossible.
    positions.forEach(p => {
      const fair = fairForSide(p);
      if (fair === null || typeof p.avg_entry_price !== 'number') return;
      if (p.avg_entry_price > fair + 1e-9) {
        issues.push({
          severity: 'error',
          title: 'Position entered above its own fair value',
          detail: trunc(p.market_question) + ' — paid ' + p.avg_entry_price.toFixed(4) +
            ' for ' + String(p.outcome).toUpperCase() + ' the agent valued at ' + fair.toFixed(4) +
            ' (' + fmtMoney((p.avg_entry_price - fair) * (p.shares || 0)) + ' lost at entry).',
          fix: 'The risk invariant should reject this. If it approved, it is validating a ' +
            'different price than the one actually filled.',
        });
      }
    });

    // ── 6. Filled far above the current mark ──────────────
    // The $0.999 signature: an execution price nowhere near the book.
    positions.forEach(p => {
      if (typeof p.avg_entry_price !== 'number' || typeof p.mark_price !== 'number') return;
      const gap = p.avg_entry_price - p.mark_price;
      if (gap > PRICE_TOL) {
        issues.push({
          severity: 'error',
          title: 'Filled far above the current mark',
          detail: trunc(p.market_question) + ' — filled at ' + p.avg_entry_price.toFixed(4) +
            ', now marked ' + p.mark_price.toFixed(4) + ' (' + (gap * 100).toFixed(1) +
            'pp worse than mark).',
          fix: 'Risk sizing likely used a mid-derived price while the fill walked the book. ' +
            'Validate against a simulated fill at the intended size, not the midpoint.',
        });
      }
    });

    // ── 7. Verdict asserted without evidence ──────────────
    if (sc.verdict && !sc.n_resolved) {
      issues.push({
        severity: 'warn',
        title: 'Verdict published with zero resolved forecasts',
        detail: 'verdict = "' + sc.verdict + '" but n_resolved = ' + (sc.n_resolved || 0) + '.',
        fix: 'Emit null until there is something to score. The UI ignores it, but a stored ' +
          'verdict with no evidence is a trap for anything else reading this file.',
      });
    }

    // ── 8. Unidentifiable build ───────────────────────────
    if (d.meta && !d.meta.agent_version) {
      issues.push({
        severity: 'warn',
        title: 'Agent version not recorded',
        detail: 'meta.agent_version is empty.',
        fix: 'Publish the git sha so a result can be traced to the code that produced it. ' +
          'Without it, a months-long run cannot be audited.',
      });
    }

    return issues;
  }

  function fairForSide(p) {
    if (typeof p.fair_estimate !== 'number') return null;
    return String(p.outcome).toLowerCase() === 'no' ? 1 - p.fair_estimate : p.fair_estimate;
  }

  function fmtMoney(n) {
    if (typeof n !== 'number' || isNaN(n)) return '—';
    return (n < 0 ? '-$' : '$') + Math.abs(n).toFixed(2);
  }

  function trunc(s, n) {
    s = String(s || '—');
    n = n || 46;
    return s.length > n ? s.slice(0, n) + '…' : s;
  }

  function counts(issues) {
    return {
      errors: issues.filter(i => i.severity === 'error').length,
      warns: issues.filter(i => i.severity === 'warn').length,
    };
  }

  return { check, counts };
})();
