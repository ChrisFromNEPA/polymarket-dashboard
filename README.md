# Polymarket Dashboard — Paper Trading

A web dashboard for exploring Polymarket prediction markets with **fake money paper trading**. Test your strategies risk-free before committing real capital.

**Live:** [chrisfromnepa.github.io/polymarket-dashboard](https://chrisfromnepa.github.io/polymarket-dashboard)

## Features

- **Market Browser** — Browse trending events, search markets, view prices
- **Paper Trading** — Buy/sell YES/NO shares with $10,000 in fake USDC. Portfolio tracks P&L against live market prices. All data in localStorage.
- **Arbitrage Scanner** — Detects calendar spread violations, mutual exclusivity inconsistencies, and wide bid-ask spreads
- **News Edge** — Links high-volume markets to news search queries for information-edge detection
- **No backend needed** — Fully client-side, hosted on GitHub Pages, calls Polymarket APIs directly

## How to Use

1. Open the dashboard
2. Browse markets in the **Markets** tab
3. Click **Trade** on any market to open the trading panel
4. Select BUY/SELL, YES/NO, set price and shares
5. Click **Place Paper Trade**
6. Track your portfolio in the **Portfolio** tab
7. Run the **Arbitrage Scanner** to find mispriced markets

## Local Development

```bash
python3 -m http.server 8844
# Open http://localhost:8844
```

## Paper Trading Rules

- Starting balance: $10,000 (fake USDC)
- Buy at your chosen price (suggestion: use current market price)
- Sell positions at current best bid from orderbook
- P&L calculated against live market prices
- Reset anytime with the reset button

## Related

- [Polymarket Python tools](https://github.com/ChrisFromNEPA/polymarket-dashboard/tree/main/../polymarket-scripts) — Python scripts for CLI-based analysis and real-money trading
