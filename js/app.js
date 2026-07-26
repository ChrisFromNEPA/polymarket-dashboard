// Main Application — UI, event handling, tab management
const App = (() => {
  // ── DOM References ──
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // ── State ──
  let cachedEvents = [];
  let currentTradeMarket = null;

  // ── Formatting ──
  const fmtPct = (n) => `${(n * 100).toFixed(1)}%`;
  const fmtVol = (v) => {
    const n = Number(v);
    if (!n || isNaN(n)) return '$0';
    if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
    if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
    return `$${n.toFixed(0)}`;
  };
  const fmtMoney = (n, showSign = true) => {
    const abs = Math.abs(n);
    const sign = showSign ? (n >= 0 ? '+' : '−') : '';
    return `${sign}$${abs.toFixed(2)}`;
  };

  // ── Header Update ──
  async function updateHeader() {
    const vals = await Portfolio.getPositionValues(async (tokenId, outcome) => {
      try {
        const book = await API.orderbook(tokenId);
        const bids = book.bids || [];
        const asks = book.asks || [];
        if (outcome === 'yes') {
          // Current value = what we could sell at (best bid)
          return bids.length ? parseFloat(bids[0].price) : parseFloat(book.last_trade_price) || 0.5;
        } else {
          // NO token value = 1 - best ask for YES, or from orderbook
          return asks.length ? 1 - parseFloat(asks[0].price) : 0.5;
        }
      } catch { return 0.5; }
    });

    const state = Portfolio.getState();
    const totalValue = Portfolio.getTotalValue(vals);
    const totalPnl = Portfolio.getTotalPnl(vals);

    $('#header-balance').textContent = `$${totalValue.toFixed(2)}`;
    const pnlEl = $('#header-pnl');
    pnlEl.textContent = fmtMoney(totalPnl);
    pnlEl.className = 'pnl ' + (totalPnl >= 0 ? 'positive' : 'negative');

    return vals;
  }

  // ── Tab Navigation ──
  function initTabs() {
    $$('.tab').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.tab').forEach(b => b.classList.remove('active'));
        $$('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        $(`#tab-${btn.dataset.tab}`).classList.add('active');

        if (btn.dataset.tab === 'portfolio') loadPortfolio();
      });
    });
  }

  // ── Markets Tab ──
  async function loadTrending() {
    $('#markets-container').innerHTML = '<div class="loading">Loading trending markets...</div>';
    try {
      cachedEvents = await API.trending(25);
      renderEvents(cachedEvents);
    } catch (e) {
      $('#markets-container').innerHTML = `<div class="empty">Error loading markets: ${e.message}</div>`;
    }
  }

  async function searchMarkets(query) {
    $('#markets-container').innerHTML = '<div class="loading">Searching...</div>';
    try {
      cachedEvents = await API.search(query);
      renderEvents(cachedEvents);
    } catch (e) {
      $('#markets-container').innerHTML = `<div class="empty">Error: ${e.message}</div>`;
    }
  }

  function renderEvents(events) {
    if (!events.length) {
      $('#markets-container').innerHTML = '<div class="empty">No markets found.</div>';
      return;
    }

    let html = '';
    for (const evt of events) {
      html += `<div class="event-card">
        <div class="event-title">
          ${escHtml(evt.title)}
          <span class="event-volume">${fmtVol(evt.volume)}</span>
        </div>`;

      const active = evt.markets.filter(m => !m.closed);
      for (const m of active.slice(0, 8)) {
        const prices = m.outcomePrices || ['0.5', '0.5'];
        const yes = parseFloat(prices[0]) || 0;
        const no = parseFloat(prices[1]) || 0;
        html += `<div class="market-row" data-token-yes="${escAttr(m.clobTokenIds?.[0] || '')}" data-token-no="${escAttr(m.clobTokenIds?.[1] || '')}" data-question="${escAttr(m.question)}" data-yes-price="${yes}" data-no-price="${no}">
          <span class="market-question">${escHtml(m.question)}</span>
          <span class="market-price yes">Yes: ${fmtPct(yes)}</span>
          <span class="market-price no">No: ${fmtPct(no)}</span>
          <span class="market-vol">${fmtVol(m.volume || 0)}</span>
          <button class="market-trade-btn" data-token-yes="${escAttr(m.clobTokenIds?.[0] || '')}" data-token-no="${escAttr(m.clobTokenIds?.[1] || '')}" data-question="${escAttr(m.question)}" data-yes-price="${yes}" data-no-price="${no}">Trade</button>
        </div>`;
      }
      html += '</div>';
    }
    $('#markets-container').innerHTML = html;

    // Attach trade button handlers
    $$('.market-trade-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openTradeModal({
          question: btn.dataset.question,
          tokenYes: btn.dataset.tokenYes,
          tokenNo: btn.dataset.tokenNo,
          yesPrice: parseFloat(btn.dataset.yesPrice),
          noPrice: parseFloat(btn.dataset.noPrice),
        });
      });
    });
  }

  // ── Trade Modal ──
  function openTradeModal(market) {
    currentTradeMarket = market;
    $('#trade-title').textContent = 'Paper Trade';
    $('#trade-market-info').innerHTML = `
      <strong>${escHtml(market.question)}</strong><br>
      Yes: ${fmtPct(market.yesPrice)} | No: ${fmtPct(market.noPrice)}
    `;

    // Reset form
    $('#trade-price').value = market.yesPrice.toFixed(2);
    $('#trade-shares').value = 10;
    $$('.side-btn').forEach(b => b.classList.remove('active'));
    $('.side-btn[data-side="buy"]').classList.add('active');
    $$('.outcome-btn').forEach(b => b.classList.remove('active'));
    $('.outcome-btn[data-outcome="yes"]').classList.add('active');
    $('#trade-error').classList.add('hidden');
    updateTradeTotal();
    $('#trade-modal').classList.remove('hidden');
  }

  function closeTradeModal() {
    $('#trade-modal').classList.add('hidden');
    currentTradeMarket = null;
  }

  function updateTradeTotal() {
    const price = parseFloat($('#trade-price').value) || 0;
    const shares = parseInt($('#trade-shares').value) || 0;
    $('#trade-total').textContent = `$${(price * shares).toFixed(2)}`;

    const side = document.querySelector('.side-btn.active')?.dataset.side || 'buy';
    if (side === 'buy') {
      $('#trade-risk').textContent = `Max profit: $${((1 - price) * shares).toFixed(2)} | Max loss: $${(price * shares).toFixed(2)}`;
    } else {
      $('#trade-risk').textContent = `Max profit: $${(price * shares).toFixed(2)} | Max loss: $${((1 - price) * shares).toFixed(2)}`;
    }
  }

  function executeTrade() {
    if (!currentTradeMarket) return;
    const side = document.querySelector('.side-btn.active')?.dataset.side || 'buy';
    const outcome = document.querySelector('.outcome-btn.active')?.dataset.outcome || 'yes';
    const price = parseFloat($('#trade-price').value);
    const shares = parseInt($('#trade-shares').value);

    if (!price || price <= 0 || price > 1) {
      $('#trade-error').textContent = 'Price must be between 0.01 and 1.00';
      $('#trade-error').classList.remove('hidden');
      return;
    }
    if (!shares || shares < 1) {
      $('#trade-error').textContent = 'Shares must be at least 1';
      $('#trade-error').classList.remove('hidden');
      return;
    }

    let result;
    if (side === 'buy') {
      result = Portfolio.buy(
        outcome === 'yes' ? currentTradeMarket.tokenYes : currentTradeMarket.tokenNo,
        outcome,
        price,
        shares,
        currentTradeMarket.question
      );
    } else {
      // Sell — use token for the outcome
      const tokenId = outcome === 'yes' ? currentTradeMarket.tokenYes : currentTradeMarket.tokenNo;
      result = Portfolio.sell(tokenId, outcome, price, shares);
    }

    if (!result.success) {
      $('#trade-error').textContent = result.error;
      $('#trade-error').classList.remove('hidden');
      return;
    }

    closeTradeModal();
    updateHeader();
  }

  // ── Portfolio Tab ──
  async function loadPortfolio() {
    const vals = await Portfolio.getPositionValues(async (tokenId, outcome) => {
      try {
        const book = await API.orderbook(tokenId);
        if (outcome === 'yes') {
          const bids = book.bids || [];
          return bids.length ? parseFloat(bids[0].price) : 0;
        } else {
          const asks = book.asks || [];
          return asks.length ? 1 - parseFloat(asks[0].price) : 0;
        }
      } catch { return 0.5; }
    });

    const state = Portfolio.getState();
    const totalValue = Portfolio.getTotalValue(vals);
    const totalPnl = Portfolio.getTotalPnl(vals);
    const positionsValue = vals.reduce((s, p) => s + p.currentValue, 0);

    $('#port-cash').textContent = `$${state.cash.toFixed(2)}`;
    $('#port-positions').textContent = `$${positionsValue.toFixed(2)}`;
    $('#port-pnl').textContent = fmtMoney(totalPnl);
    $('#port-pnl').className = 'stat-value ' + (totalPnl >= 0 ? 'positive' : 'negative');
    $('#port-total').textContent = `$${totalValue.toFixed(2)}`;

    // Render positions
    if (vals.length === 0) {
      $('#positions-container').innerHTML = '<p class="empty">No open positions. Start trading in the Markets tab!</p>';
    } else {
      let html = '';
      for (const p of vals) {
        html += `<div class="position-card">
          <div class="position-q">${escHtml(p.marketQuestion)}</div>
          <div class="position-detail">${p.outcome.toUpperCase()} × ${p.shares} @ $${p.avgPrice.toFixed(4)}</div>
          <div class="position-detail">Now: $${p.currentPrice.toFixed(4)}</div>
          <div class="position-pnl ${p.pnl >= 0 ? 'positive' : 'negative'}">${fmtMoney(p.pnl)} (${p.pnlPct.toFixed(1)}%)</div>
          <button class="position-close" data-token="${p.tokenId}" data-outcome="${p.outcome}">Close</button>
        </div>`;
      }
      $('#positions-container').innerHTML = html;

      // Attach close handlers
      $$('.position-close').forEach(btn => {
        btn.addEventListener('click', async () => {
          const tokenId = btn.dataset.token;
          const outcome = btn.dataset.outcome;
          let currentPrice = 0.5;
          try {
            const book = await API.orderbook(tokenId);
            currentPrice = outcome === 'yes'
              ? (book.bids?.length ? parseFloat(book.bids[0].price) : 0.5)
              : (book.asks?.length ? 1 - parseFloat(book.asks[0].price) : 0.5);
          } catch {}
          Portfolio.closePosition(tokenId, outcome, currentPrice);
          loadPortfolio();
          updateHeader();
        });
      });
    }

    // Render history
    const history = state.history.slice(0, 50);
    if (history.length === 0) {
      $('#history-container').innerHTML = '<p class="empty">No trades yet.</p>';
    } else {
      let html = '';
      for (const h of history) {
        const time = new Date(h.time).toLocaleString();
        const pnlStr = h.pnl != null ? ` | P&L: ${fmtMoney(h.pnl)}` : '';
        html += `<div class="history-row">
          <span>${time}</span>
          <span style="color:${h.action === 'BUY' ? 'var(--green)' : 'var(--red)'}">${h.action}</span>
          <span>${h.outcome?.toUpperCase() || ''}</span>
          <span>${h.shares} × $${h.price.toFixed(4)}</span>
          <span>= $${((h.cost || h.revenue) || 0).toFixed(2)}${pnlStr}</span>
        </div>`;
      }
      $('#history-container').innerHTML = html;
    }
  }

  // ── Scanner Tab ──
  async function runScanner() {
    if (!cachedEvents.length) {
      $('#scan-status').textContent = 'Loading events first...';
      cachedEvents = await API.trending(30);
    }

    const strategy = $('#scan-strategy').value;
    $('#scan-status').textContent = 'Scanning...';
    $('#scanner-results').innerHTML = '<div class="loading">Running arbitrage scan...</div>';

    try {
      const results = await Scanner.run(strategy, cachedEvents);
      if (!results.length) {
        $('#scanner-results').innerHTML = '<p class="empty">No arbitrage opportunities found for this strategy. Markets appear efficient.</p>';
      } else {
        let html = '';
        for (const r of results) {
          html += `<div class="scan-result">
            <div class="scan-result-header"><span class="scan-type ${r.type}">${r.type.toUpperCase()}</span> ${escHtml(r.event || '')}</div>
            <div class="scan-result-detail">${escHtml(r.detail)}</div>
            <div class="scan-result-action">💡 ${escHtml(r.action)}</div>
          </div>`;
        }
        $('#scanner-results').innerHTML = html;
      }
      $('#scan-status').textContent = `Done — ${results.length} found`;
    } catch (e) {
      $('#scanner-results').innerHTML = `<div class="empty">Error: ${e.message}</div>`;
      $('#scan-status').textContent = 'Failed';
    }
  }

  // ── News Edge Tab ──
  async function loadNewsEdge() {
    $('#news-status').textContent = 'Loading...';
    try {
      const events = await API.trending(20);
      let html = '';
      let count = 0;
      for (const evt of events) {
        for (const m of evt.markets.slice(0, 5)) {
          if (m.closed) continue;
          const yes = parseFloat(m.outcomePrices?.[0] || 0);
          const query = encodeURIComponent(m.question.replace(/^Will\s+/i, ''));
          html += `<div class="news-market">
            <span class="news-market-q">${escHtml(m.question)}</span>
            <span class="news-market-price">${fmtPct(yes)}</span>
            <span>${fmtVol(m.volume || 0)}</span>
            <a class="news-search-link" href="https://www.google.com/search?q=${query}" target="_blank">🔍 Search News →</a>
          </div>`;
          count++;
        }
      }
      $('#news-container').innerHTML = html;
      $('#news-status').textContent = `Loaded ${count} markets — click 🔍 to search for breaking news`;
    } catch (e) {
      $('#news-container').innerHTML = `<div class="empty">Error: ${e.message}</div>`;
    }
  }

  // ── Helpers ──
  function escHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }
  function escAttr(s) {
    return String(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // ── Init ──
  function init() {
    initTabs();

    // Search
    $('#search-btn').addEventListener('click', () => {
      const q = $('#market-search').value.trim();
      if (q) searchMarkets(q);
    });
    $('#market-search').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const q = $('#market-search').value.trim();
        if (q) searchMarkets(q);
      }
    });
    $('#trending-btn').addEventListener('click', loadTrending);

    // Trade modal
    $('.modal-close').addEventListener('click', closeTradeModal);
    $('#trade-modal').addEventListener('click', (e) => {
      if (e.target === $('#trade-modal')) closeTradeModal();
    });
    $$('.side-btn').forEach(b => b.addEventListener('click', function() {
      $$('.side-btn').forEach(x => x.classList.remove('active'));
      this.classList.add('active');
      updateTradeTotal();
    }));
    $$('.outcome-btn').forEach(b => b.addEventListener('click', function() {
      $$('.outcome-btn').forEach(x => x.classList.remove('active'));
      this.classList.add('active');
      const outcome = this.dataset.outcome;
      const price = outcome === 'yes' ? currentTradeMarket?.yesPrice : currentTradeMarket?.noPrice;
      if (price != null) {
        $('#trade-price').value = price.toFixed(2);
        updateTradeTotal();
      }
    }));
    $('#trade-price').addEventListener('input', updateTradeTotal);
    $('#trade-shares').addEventListener('input', updateTradeTotal);
    $('#trade-execute').addEventListener('click', executeTrade);

    // Portfolio
    $('#reset-portfolio').addEventListener('click', () => {
      if (confirm('Reset your paper trading portfolio? This cannot be undone.')) {
        Portfolio.reset();
        loadPortfolio();
        updateHeader();
      }
    });
    $('#export-portfolio').addEventListener('click', () => {
      const state = Portfolio.getState();
      const blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `polymarket-portfolio-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    });

    // Scanner
    $('#scan-btn').addEventListener('click', runScanner);

    // News
    $('#news-load-btn').addEventListener('click', loadNewsEdge);

    // Keyboard shortcut: Escape closes modal
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeTradeModal();
    });

    // Load initial data
    loadTrending();
    updateHeader();
  }

  return { init };
})();

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());
