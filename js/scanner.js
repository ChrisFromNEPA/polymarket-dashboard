// Arbitrage Scanner — runs in-browser against live Polymarket data
const Scanner = (() => {
  // Calendar spread: P(event by earlier date) > P(event by later date)
  async function findCalendarSpreads(events) {
    const results = [];
    for (const evt of events) {
      const active = evt.markets.filter(m => !m.closed && (m.volume || 0) >= 100000);
      if (active.length < 2) continue;

      // Extract date-stamped markets
      const dated = [];
      for (const m of active) {
        const dates = extractDates(m.question);
        if (dates.length > 0) dated.push({ market: m, dates });
      }
      if (dated.length < 2) continue;

      dated.sort((a, b) => a.dates[0].dt - b.dates[0].dt);

      for (let i = 0; i < dated.length; i++) {
        for (let j = i + 1; j < dated.length; j++) {
          const early = dated[i];
          const late = dated[j];
          if (early.dates[0].dt === late.dates[0].dt) continue;
          if ((late.dates[0].dt - early.dates[0].dt) > 730 * 86400000) continue;

          // Check common words
          const wordsE = new Set(early.market.question.toLowerCase().match(/\b[a-z]{4,}\b/g) || []);
          const wordsL = new Set(late.market.question.toLowerCase().match(/\b[a-z]{4,}\b/g) || []);
          const stopwords = new Set(['will','that','this','with','from','have','been','were','they','what','when','which','there','their']);
          const common = [...wordsE].filter(w => wordsL.has(w) && !stopwords.has(w));
          if (common.length < 3) continue;

          const pEarly = parseFloat(early.market.outcomePrices[0]);
          const pLate = parseFloat(late.market.outcomePrices[0]);

          if (pEarly > pLate + 0.02) {
            results.push({
              type: 'cal',
              event: evt.title,
              detail: `${early.market.question} (${(pEarly*100).toFixed(1)}%) > ${late.market.question} (${(pLate*100).toFixed(1)}%)`,
              action: `BUY NO on earlier, BUY YES on later — edge: ${((pEarly-pLate)*100).toFixed(1)}%`,
            });
          }
        }
      }
    }
    return results;
  }

  function extractDates(text) {
    const dates = [];
    const months = { january: 1, february: 2, march: 3, april: 4, may: 5, june: 6, july: 7, august: 8, september: 9, october: 10, november: 11, december: 12 };

    // "by July 31" / "by July 31, 2026"
    const byPat = /by\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:,?\s*(\d{4}))?/gi;
    for (const m of text.matchAll(byPat)) {
      const mo = months[m[1].toLowerCase()];
      const day = parseInt(m[2]);
      const year = parseInt(m[3] || '2026');
      if (mo && day >= 1 && day <= 31) {
        dates.push({ dt: new Date(year, mo - 1, day).getTime(), label: m[0] });
      }
    }

    // "by end of 2026" / "before 2027"
    const endPat = /(?:by\s+)?(?:the\s+)?end\s+of\s+(\d{4})|before\s+(\d{4})/gi;
    for (const m of text.matchAll(endPat)) {
      const year = parseInt(m[1] || m[2]);
      dates.push({ dt: new Date(year, 11, 31).getTime(), label: m[0] });
    }

    // "in July 2026" / "in July"
    const inPat = /in\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s*(?:of\s*)?(\d{4})?/gi;
    for (const m of text.matchAll(inPat)) {
      const mo = months[m[1].toLowerCase()];
      const year = parseInt(m[2] || '2026');
      let day = 31;
      if (mo === 2) day = year % 4 === 0 ? 29 : 28;
      else if ([4, 6, 9, 11].includes(mo)) day = 30;
      dates.push({ dt: new Date(year, mo - 1, day).getTime(), label: m[0] });
    }

    // ISO: 2026-12-31
    const isoPat = /(\d{4})-(\d{2})-(\d{2})/g;
    for (const m of text.matchAll(isoPat)) {
      dates.push({ dt: new Date(parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3])).getTime(), label: m[0] });
    }

    return dates;
  }

  // Mutual exclusivity: sum of probabilities > 100%
  async function findExclusivityViolations(events) {
    const results = [];
    const exclusivePatterns = [
      /will\s+\S+\s+win\s+the/i, /will\s+\S+\s+be\s+the\s+next/i,
      /who\s+will\s+win/i, /next\s+prime\s+minister/i,
      /presidential\s+election/i, /presidential\s+nominee/i,
      /drivers.?\s+champion/i,
    ];

    for (const evt of events) {
      const active = evt.markets.filter(m => !m.closed && (m.volume || 0) >= 100000);
      if (active.length < 3) continue;

      const looksExclusive = exclusivePatterns.some(p =>
        p.test(evt.title) || active.slice(0, 5).some(m => p.test(m.question))
      );
      if (!looksExclusive) continue;

      let total = 0;
      const details = [];
      for (const m of active) {
        const p = parseFloat(m.outcomePrices[0]) || 0;
        total += p;
        details.push({ question: m.question.slice(0, 80), prob: p, volume: m.volume });
      }
      details.sort((a, b) => b.prob - a.prob);

      const excess = total - 1.0;
      if (excess > 0.03) {
        results.push({
          type: 'excl',
          event: evt.title,
          detail: `Sum: ${(total*100).toFixed(1)}% across ${details.length} markets (excess: ${(excess*100).toFixed(1)}%)`,
          action: `BUY NO on all ${details.length} outcomes — gross return ${(excess*100).toFixed(1)}%`,
        });
      }
    }
    return results;
  }

  // Wide spreads: check orderbooks for wide bid-ask
  async function findWideSpreads(events) {
    const results = [];
    const candidates = [];
    for (const evt of events) {
      for (const m of evt.markets) {
        const vol = m.volume || 0;
        if (!m.closed && vol >= 500000 && m.clobTokenIds && m.clobTokenIds[0]) {
          candidates.push({ question: m.question.slice(0, 100), volume: vol, tokenId: m.clobTokenIds[0], mid: parseFloat(m.outcomePrices[0]) || 0 });
        }
      }
    }
    candidates.sort((a, b) => b.volume - a.volume);
    const topCandidates = candidates.slice(0, 25);

    for (const c of topCandidates) {
      try {
        const book = await API.orderbook(c.tokenId);
        const bids = book.bids || [];
        const asks = book.asks || [];
        if (!bids.length || !asks.length) continue;
        const bestBid = parseFloat(bids[0].price);
        const bestAsk = parseFloat(asks[0].price);
        if (bestBid <= 0) continue;
        const spreadPct = (bestAsk - bestBid) / bestBid * 100;
        if (spreadPct > 5) {
          results.push({
            type: 'wide',
            detail: `${c.question} — Spread: ${spreadPct.toFixed(1)}% (bid: ${(bestBid*100).toFixed(1)}%, ask: ${(bestAsk*100).toFixed(1)}%)`,
            action: `Market-make inside spread. Roundtrip profit: ${(bestAsk-bestBid).toFixed(4)}/share. Min size: $${Math.min(parseFloat(bids[0].size), parseFloat(asks[0].size)).toFixed(0)}`,
          });
        }
      } catch (e) { /* skip failed orderbook fetch */ }
    }
    return results;
  }

  async function run(strategy, events) {
    const results = [];
    if (strategy === 'cal' || strategy === 'all') {
      results.push(...await findCalendarSpreads(events));
    }
    if (strategy === 'excl' || strategy === 'all') {
      results.push(...await findExclusivityViolations(events));
    }
    if (strategy === 'wide' || strategy === 'all') {
      results.push(...await findWideSpreads(events));
    }
    return results;
  }

  return { run };
})();
