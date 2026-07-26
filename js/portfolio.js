// Paper Trading Engine — fake money, real market prices
const Portfolio = (() => {
  const STORAGE_KEY = 'pm_paper_portfolio';
  const STARTING_BALANCE = 10000;

  let state = loadState();

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed.cash != null && Array.isArray(parsed.positions) && Array.isArray(parsed.history)) {
          return parsed;
        }
      }
    } catch (e) { /* corrupt — reset */ }
    return { cash: STARTING_BALANCE, positions: [], history: [] };
  }

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function posKey(tokenId, outcome) {
    return `${tokenId}:${outcome}`;
  }

  function getPosition(tokenId, outcome) {
    return state.positions.find(p => p.tokenId === tokenId && p.outcome === outcome);
  }

  // Buy shares: outcome='yes'|'no', price in $, shares count
  function buy(tokenId, outcome, price, shares, marketQuestion) {
    const cost = price * shares;
    if (state.cash < cost) {
      return { success: false, error: `Insufficient funds. Need $${cost.toFixed(2)}, have $${state.cash.toFixed(2)}` };
    }

    state.cash -= cost;
    const key = posKey(tokenId, outcome);
    let pos = state.positions.find(p => p.key === key);
    if (pos) {
      const totalShares = pos.shares + shares;
      pos.avgPrice = (pos.avgPrice * pos.shares + price * shares) / totalShares;
      pos.shares = totalShares;
    } else {
      pos = {
        key,
        tokenId,
        outcome,
        shares,
        avgPrice: price,
        marketQuestion: marketQuestion || 'Unknown market',
      };
      state.positions.push(pos);
    }

    state.history.unshift({
      time: new Date().toISOString(),
      action: 'BUY',
      outcome,
      tokenId,
      price,
      shares,
      cost,
      marketQuestion: marketQuestion || 'Unknown market',
    });

    saveState();
    return { success: true, cost, newBalance: state.cash, position: pos };
  }

  // Sell shares
  function sell(tokenId, outcome, price, shares) {
    const key = posKey(tokenId, outcome);
    const pos = state.positions.find(p => p.key === key);
    if (!pos) {
      return { success: false, error: 'No position to sell' };
    }
    if (pos.shares < shares) {
      return { success: false, error: `Only ${pos.shares} shares available` };
    }

    const revenue = price * shares;
    const costBasis = pos.avgPrice * shares;
    const pnl = revenue - costBasis;

    pos.shares -= shares;
    state.cash += revenue;

    state.history.unshift({
      time: new Date().toISOString(),
      action: 'SELL',
      outcome,
      tokenId,
      price,
      shares,
      revenue,
      pnl,
      marketQuestion: pos.marketQuestion,
    });

    // Remove empty positions
    if (pos.shares <= 0) {
      state.positions = state.positions.filter(p => p.key !== key);
    }

    saveState();
    return { success: true, revenue, pnl, newBalance: state.cash, remainingShares: pos.shares };
  }

  // Close entire position at market price
  function closePosition(tokenId, outcome, currentPrice) {
    const key = posKey(tokenId, outcome);
    const pos = state.positions.find(p => p.key === key);
    if (!pos || pos.shares <= 0) return { success: false, error: 'No position' };
    return sell(tokenId, outcome, currentPrice, pos.shares);
  }

  // Calculate current value of all positions using live prices
  async function getPositionValues(priceFetcher) {
    const values = [];
    for (const pos of state.positions) {
      try {
        const tokenIdx = pos.outcome === 'yes' ? 0 : 1;
        // We need the token ID for the specific outcome
        // For now, use midpoint as current price
        let currentPrice;
        if (priceFetcher) {
          currentPrice = await priceFetcher(pos.tokenId, pos.outcome);
        } else {
          currentPrice = pos.avgPrice; // fallback
        }
        const currentValue = currentPrice * pos.shares;
        const costBasis = pos.avgPrice * pos.shares;
        const pnl = currentValue - costBasis;
        values.push({
          ...pos,
          currentPrice,
          currentValue,
          costBasis,
          pnl,
          pnlPct: costBasis > 0 ? (pnl / costBasis) * 100 : 0,
        });
      } catch (e) {
        values.push({
          ...pos,
          currentPrice: pos.avgPrice,
          currentValue: pos.avgPrice * pos.shares,
          costBasis: pos.avgPrice * pos.shares,
          pnl: 0,
          pnlPct: 0,
        });
      }
    }
    return values;
  }

  function getState() {
    return {
      cash: state.cash,
      positions: [...state.positions],
      history: [...state.history].slice(0, 100),
      totalTrades: state.history.length,
    };
  }

  function reset() {
    state = { cash: STARTING_BALANCE, positions: [], history: [] };
    saveState();
  }

  function getTotalValue(positionValues = []) {
    const positionsValue = positionValues.reduce((sum, p) => sum + p.currentValue, 0);
    return state.cash + positionsValue;
  }

  function getTotalPnl(positionValues = []) {
    return positionValues.reduce((sum, p) => sum + p.pnl, 0);
  }

  return {
    buy, sell, closePosition, getPositionValues,
    getState, reset, getTotalValue, getTotalPnl,
    STARTING_BALANCE,
  };
})();
