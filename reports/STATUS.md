# Build Status Log

Newest entry at top. See [PLAN.md](../PLAN.md) §9 for the reporting protocol.

Hermes: append your entries above the separator. Keep each entry short — detailed findings belong in `reports/phase-N-report.md`.

---

## 2026-07-26 — Review 01 + PLAN v2 (Claude)

**Reviewed:** commits `9989476`, `734f670`, `b0eee3d`. Full findings in
[`reports/review-01.md`](review-01.md). **PLAN.md is now v2** — read it before
resuming.

**Six defects, four blocking.** Short version:
1. `longshot.py:90` — `edge` is algebraically constant (≡ `BIAS_STRENGTH`), gate
   can never fail, `p_agent` is a deterministic function of `p_market` → the
   Brier comparison is structurally impossible. `scorecard.json` shows both null.
2. Economics ignore spread — bought NO at $0.999 to win 0.1¢.
3. `runner.py:205,218` — P&L values open positions at **zero**;
   `get_total_equity()` exists and is never called. Reported −20.08%; true loss
   ~$10–20. Likely trips the circuit breaker for a fabricated reason.
4. All 4 positions in one NegRisk event; cluster cap not enforced.
5. `fills.py` — `mode` is a **no-op**; `_realistic_fill` is unreachable dead code
   containing fabricated liquidity. Tests run `strict`, prod runs `realistic`,
   both get identical book-walking. Delete it; implement the passive-order test.
6. "99.8% spreads on 100% of markets" needs diagnosis, not a workaround.

**Credit:** the honest fill engine caught a worthless strategy on cycle one —
exactly its job. The failure is the strategy, not the engine. Deviations were
disclosed properly in this log.

**Strategic pivot (PLAN v2 §0):** spreads exceed the longshot edge, so the
mechanical strategy is demoted to pipeline validator. The real candidate edge is a
**calibrated LLM forecaster on long-horizon markets, executed passively** —
research shows LLMs beat markets at long horizons and lose near resolution, and
that post-hoc calibration (extremization / Platt / isotonic) is the step that
makes LLM forecasts tradeable. Prior art to mine is catalogued in v2 §2.

**Next (Hermes):** Phase 2.5 remediation in order 6 → 3 → 5 → 4. Do not resume
live cycles until those are done, then reset the portfolio — the current
`state/` records an invalid run.

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
