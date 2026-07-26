// Polymarket API wrapper — client-side, no auth needed
const API = (() => {
  const GAMMA = 'https://gamma-api.polymarket.com';
  const CLOB = 'https://clob.polymarket.com';
  const DATA = 'https://data-api.polymarket.com';

  async function get(url) {
    const resp = await fetch(url, { headers: { 'User-Agent': 'pm-dashboard/1.0' } });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
    return resp.json();
  }

  function parseJSON(val) {
    if (typeof val === 'string') {
      try { return JSON.parse(val); } catch { return val; }
    }
    return val;
  }

  return {
    // Search
    async search(query) {
      const data = await get(`${GAMMA}/public-search?q=${encodeURIComponent(query)}`);
      return (data.events || []).map(evt => ({
        title: evt.title,
        slug: evt.slug,
        volume: evt.volume || 0,
        markets: (evt.markets || []).map(m => ({
          question: m.question,
          slug: m.slug,
          outcomePrices: parseJSON(m.outcomePrices),
          outcomes: parseJSON(m.outcomes),
          clobTokenIds: parseJSON(m.clobTokenIds),
          conditionId: m.conditionId,
          volume: m.volume || 0,
          closed: m.closed || false,
        })),
      }));
    },

    // Trending events
    async trending(limit = 25) {
      const events = await get(
        `${GAMMA}/events?limit=${limit}&active=true&closed=false&order=volume&ascending=false`
      );
      return events.map(evt => ({
        title: evt.title,
        slug: evt.slug,
        volume: evt.volume || 0,
        markets: (evt.markets || []).map(m => ({
          question: m.question,
          slug: m.slug,
          outcomePrices: parseJSON(m.outcomePrices),
          outcomes: parseJSON(m.outcomes),
          clobTokenIds: parseJSON(m.clobTokenIds),
          conditionId: m.conditionId,
          volume: m.volume || 0,
          closed: m.closed || false,
        })),
      }));
    },

    // Get orderbook for a token
    async orderbook(tokenId) {
      return get(`${CLOB}/book?token_id=${tokenId}`);
    },

    // Get midpoint price
    async midpoint(tokenId) {
      return get(`${CLOB}/midpoint?token_id=${tokenId}`);
    },

    // Get spread
    async spread(tokenId) {
      return get(`${CLOB}/spread?token_id=${tokenId}`);
    },

    // Get CLOB markets list (used by scanner)
    async clobMarkets(limit = 100, nextCursor = null) {
      let url = `${CLOB}/markets?limit=${limit}`;
      if (nextCursor) url += `&next_cursor=${nextCursor}`;
      return get(url);
    },

    // Get events by tag (used by scanner for multi-market events)
    async eventBySlug(slug) {
      const events = await get(`${GAMMA}/events?slug=${encodeURIComponent(slug)}`);
      return events[0] || null;
    },
  };
})();
