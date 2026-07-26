# Build Status Log

Newest entry at top. See [PLAN.md](../PLAN.md) §9 for the reporting protocol.

Hermes: append your entries above the separator. Keep each entry short — detailed findings belong in `reports/phase-N-report.md`.

---

## 2026-07-26 — Phase 2 — complete ✅

**Done:** Fill engine with strict book-walking (`agent/engine/fills.py`), portfolio engine with VWAP-based position tracking (`agent/engine/portfolio.py`), settlement engine with resolution polling (`agent/engine/settlement.py`).

**Acceptance:** 7/7 adversarial tests pass. Depth limits enforced (1000→530 fill). Round-trip loses $2.20 (buy 0.642, sell 0.620). NO positions marked from NO book (0.36) not YES book (0.62). Settlement ties to the cent ($1000→$1020, net +$20). Empty books reject fills. Settlement logic correct.

**Deviation:** Passive order adversarial test deferred to Phase 3 (requires replay harness). Justified in `reports/phase-2-report.md`.

**Design:** Two fill modes — `strict` (book-walking, for adversarial tests) and `realistic` (CLOB /price endpoint, for strategy backtesting). The realistic mode solves the Phase 1 problem of 99.8% spreads making book-walking unrealistic for strategy evaluation.

**Next:** Phase 3 (backtest harness) or Phase 4 (favorite-longshot strategy). Recommendation: skip Phase 3 initially and go straight to Phase 4 with realistic fills, since the mechanical favorite-longshot bias can be validated against known research without a full replay harness. Add the harness when the LLM forecaster needs backtesting.

## 2026-07-26 — Phase 1 — complete ✅

**Done:** Data layer ported to Python. `agent/polymarket/client.py` (async httpx client for Gamma + CLOB), `agent/polymarket/models.py` (Market, Token, OrderBook, BookLevel). Each market modeled with two separate outcome tokens, each with own book. Rate-limited with exponential backoff.

**Acceptance:** 50/50 markets pass token mapping check (p_yes + p_no within 2% of 1.0). All 100 orderbooks fetched. See `reports/phase-1-report.md`.

**Deviation from plan:** Used CLOB `/midpoint` endpoint for p_yes+p_no check instead of orderbook mid. Book mid on low-probability markets always shows 0.5 (bid=0.1¢, ask=99.9¢) — not a probability estimate. Book data still fetched and verified. Justification in report.

**Discovery:** 100% of tested markets (50 YES + 50 NO books) have 99.8% spreads. Books are essentially empty for non-mainstream markets. Phase 2 fill engine must handle this — walking these books is "honest" but produces fills no real trader would see.

**Next:** Start Phase 2 (fill engine). See Phase 1 report recommendations on using `/price` endpoint for realistic fills on thin books.

## 2026-07-26 — Phase 0 — environment confirmed + defaults proposed

**Done:** Python 3.12.3 (≥3.11 ✓), uv 0.11.32 installed, git push auth via HTTPS credentials ✓. Repo pulled with Claude's PLAN.md and reports/STATUS.md.

**Proposed defaults for PLAN.md §10 open questions:**

1. **Bankroll:** $10,000 — keep as stated. Standard round number, enough to demonstrate edge without absurd position sizes.
2. **Cadence:** 4-hourly — frequent enough to catch market moves, infrequent enough to avoid churning on noise. Matches typical Polymarket resolution cadence for active markets.
3. **Circuit breaker:** 20% drawdown — halts trading for human review. Quarter-Kelly sizing should make this rare; if triggered, something is wrong.
4. **Market scope:** All categories except explicit joke/meme markets (Jesus return, etc.). Politics + crypto + world events + sports = enough variety for statistical power. Filter by min volume ($100K) and min liquidity.

**Blocked:** awaiting human confirmation on defaults. Will proceed with these as working assumptions per PLAN.md §10 ("propose defaults rather than blocking on them").

---

## 2026-07-26 — Phase 0 — plan published

**Done:** Build plan committed to `PLAN.md`. Repo cloned and reviewed.

**Findings from initial code review:**
- Confirmed bug — NO positions mismarked at `js/app.js:39` (see PLAN.md §3.4). A NO position trading at $0.30 is valued at ~$0.69.
- All three existing scanner strategies in `js/scanner.js` are false-positive generators as written (PLAN.md §3.1–3.3). Do not port forward unfixed.
- No settlement mechanic exists anywhere in the codebase (PLAN.md §3.5).
- Correction to an earlier review claim: token routing in `app.js` is **correct**. The earlier "reuses one tokenId for both outcomes" claim was wrong. Don't chase that bug.

**Next (Hermes):** Phase 0 report — confirm VM environment (Python 3.11+, uv, git push auth), then propose defaults for the four open questions in PLAN.md §10. Then begin Phase 1 (data layer).

**Blocked:** nothing.
