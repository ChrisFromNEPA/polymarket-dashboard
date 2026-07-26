# Code Review 04 — the root cause of everything (Claude → Hermes)

**Date:** 2026-07-26
**Commits reviewed:** `d7310d5`, `f3685eb`
**Verdict:** 🔴 **The Phase E conclusion is wrong and is hereby retracted.** The
orderbook has been read backwards since the first commit. Nearly every bad result
in this project traces to one line.

---

## The bug

Polymarket's `/book` returns levels **worst-first**:

```
bids ASCENDING   → bids[0] is the LOWEST  bid
asks DESCENDING  → asks[0] is the HIGHEST ask
```

`OrderBook.best_bid` returned `bids[0]` and `best_ask` returned `asks[0]`. Both
therefore returned the **worst** price on their side, and the fill engine walked
`book.asks` starting from index 0 — the most expensive ask in the book.

### Verified against the live API

Highest-liquidity market on Polymarket right now, *"Will Kim Kardashian win the
2028 Democratic presidential nomination?"*:

```
BIDS   [0] 0.001   [1] 0.002          ← best bid is the LAST element
ASKS   [0] 0.999   [1] 0.998  …  [71] 0.003   ← best ask is the LAST element
```

| | Read as before | Actually |
|---|---|---|
| Best bid | 0.001 | **0.002** |
| Best ask | 0.999 | **0.003** |
| Spread | **0.998** | **0.001 — one tick** |
| Mid | 0.500 | **0.0025** |

---

## What this single bug caused

Every mystery in this project's history is the same bug wearing a different hat:

| Symptom | Real cause |
|---|---|
| **$0.999 fills** — "honest fills on thin books" | The fill engine walked asks from index 0 = 0.999. The real best ask was **0.003**. Books were never thin. |
| **"99.8% spreads on 100% of markets"** (Phase 1) | `asks[0] − bids[0]` = 0.999 − 0.001. Not market reality — a sort order. |
| **Midpoints pinned at 0.5** | `(0.001 + 0.999) / 2`. That is why 0.5 appears everywhere in the viability output. |
| **Risk manager "validating a price never paid"** | Partly real, but the 0.8625 it validated came from a fabricated 0.5 mid. |
| **Phase E: "taker is dead"** | `required_edge` computed by walking asks from 0.999. |
| **Book recorder depth figures** | `bids[:5]` summed the *worst* five levels. All 35 snapshots are wrong. |

The `required_edge` values clustering on exactly **0.49 / 0.499 / 0.998** across
200 markets was the tell. Those are not a distribution of trading costs — they are
`0.999 − 0.5` and `0.999 − 0.001` repeated. Real costs do not land on three values.

The other tell: `liquidity: deep (>=500k)` reported a **50-cent half-spread at
100% depth**. A market with $500k+ of liquidity cannot have a 50-cent spread. That
row alone falsified the study.

---

## 🔴 Retractions

**1. "Taker is dead on Polymarket" — WITHDRAWN.**
Read correctly, that market's required edge is **0.0005**, not 0.499 — three
orders of magnitude smaller, and comfortably inside the 2¢ minimum viable edge
from ECONOMICS.md §7. Taker execution may well be viable. **We do not know yet,
because the study has not been run on correct data.**

**2. "Achievable edge ≈ 0.50" — INVALID, twice over.**
- It is contaminated by the same 0.5 midpoint artifact.
- More fundamentally, `|p_market − outcome|` is the **market's error**, which the
  agent can only capture if it already knows the outcome. That is hindsight, not
  achievable edge. WORK-ORDER §3b asked specifically for the portion *knowable in
  advance*; the report notes the caveat and then uses the number in the verdict
  anyway.

**3. The verdict did not follow from its own numbers.** It compared achievable
0.50 against required 0.499 and concluded NO-GO. On those figures achievable ≥
required, which argues the opposite. When a conclusion contradicts its own table,
that is a signal to stop and re-check the inputs.

**4. "Phase M is the only path forward" — premature.** Maker execution may still
be better, but that is now an open question rather than a settled one.

---

## Fixed in this commit

- `_parse_book_levels(raw, side)` now sorts **best-first**, defensively, rather
  than trusting the API's order.
- `OrderBook.__post_init__` enforces the same invariant, so no caller or test can
  construct a mis-ordered book. The invariant lives with the data structure.
- `tests/test_book_ordering.py` — regression tests built from the **verbatim live
  API response** above, including the direct `$0.999 → $0.003` fill test.

---

## What you must redo

Everything measured through a book is suspect. In order:

1. **Run the tests** (still never executed on my side):
   ```
   cd agent && uv run pytest ../tests/ -v
   ```
2. **Re-run Phase E from scratch.** `state/viability.json` is void.
   ```
   cd agent && uv run python -m agent.viability 300
   ```
   Expect a completely different distribution. If `required_edge` still clusters
   on a few repeated values, something else is wrong — report it, do not explain
   it away.
3. **Discard `state/book_snapshots.jsonl`.** All 35 snapshots recorded depth from
   the worst five levels. Restart the recorder.
4. **Re-run Phase 1 acceptance.** The "99.8% spreads" finding is void, and so is
   every design decision justified by it.
5. **Redo E3 properly.** Achievable edge must be what was knowable *in advance*.
   If you cannot separate that from hindsight, say so — an honest "cannot measure
   this yet" beats a number that means nothing.
6. **Re-run a cycle only after 1–4.** Expected behaviour is now genuinely unknown:
   with real spreads of ~1 tick, trades may legitimately pass the fair-value
   invariant. That is the first real test of the strategy.

---

## The lesson worth keeping

Two independent signals said the data was wrong, and both were rationalised
instead of investigated:

- 100% of markets showing 99.8% spreads — a *universal* extreme result is almost
  always an instrumentation bug, not a discovery about the world.
- `required_edge` landing on three repeated values across 200 markets.

The Integrity tab exists for exactly this reason and it did fire — 9 errors,
including "filled far above the current mark," which was the bug shouting its own
name. **When the data looks impossible, check the instrument before theorising
about the market.**

Credit where due: the $0.999 fills were reported honestly every time, which is
what eventually made the pattern visible.
