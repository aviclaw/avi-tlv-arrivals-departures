export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname !== '/api/refresh') {
      return new Response('Not found', { status: 404 });
    }

    if (request.method !== 'POST') {
      return json({ error: 'method not allowed' }, 405);
    }

    // CSRF + origin gate for browser-side trigger
    const origin = request.headers.get('Origin') || '';
    const allowedOrigin = env.ALLOWED_ORIGIN || '';
    if (allowedOrigin && origin !== allowedOrigin) {
      return json({ error: 'forbidden origin' }, 403);
    }

    const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
    const ua = request.headers.get('User-Agent') || '';
    const now = Date.now();

    // DDoS protection layer 1: per-IP cooldown (30s)
    const cooldownKey = `cd:${ip}`;
    const last = await env.REFRESH_KV.get(cooldownKey);
    if (last && now - Number(last) < 30_000) {
      return json({ error: 'cooldown active, try again in ~30s' }, 429, {
        'Retry-After': '30'
      });
    }

    // DDoS protection layer 2: global token bucket (max 12 per 10 min)
    const bucketWindowMs = 10 * 60 * 1000;
    const bucketKey = `bucket:${Math.floor(now / bucketWindowMs)}`;
    const usedRaw = await env.REFRESH_KV.get(bucketKey);
    const used = usedRaw ? Number(usedRaw) : 0;
    if (used >= 12) {
      return json({ error: 'rate limit exceeded, try later' }, 429, {
        'Retry-After': '600'
      });
    }

    const lockKey = 'dispatch-lock';
    const lockRaw = await env.REFRESH_KV.get(lockKey);
    if (lockRaw && now - Number(lockRaw) < 45_000) {
      return json({ error: 'refresh already in progress' }, 429, {
        'Retry-After': '45'
      });
    }

    if (!env.GITHUB_TOKEN || !env.GH_REFRESH_URL) {
      return json({ error: 'worker secrets missing' }, 500);
    }

    const ghRes = await fetch(env.GH_REFRESH_URL, {
      method: 'POST',
      headers: {
        'Accept': 'application/vnd.github+json',
        'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ ref: 'main', inputs: { reason: 'manual-refresh-button' } })
    });

    if (!ghRes.ok) {
      return json({ error: `github dispatch failed (${ghRes.status})` }, 502);
    }

    // only set counters after successful dispatch
    await env.REFRESH_KV.put(cooldownKey, String(now), { expirationTtl: 90 });
    await env.REFRESH_KV.put(lockKey, String(now), { expirationTtl: 60 });
    await env.REFRESH_KV.put(bucketKey, String(used + 1), { expirationTtl: 700 });

    return json({ ok: true, message: 'Refresh queued. GitHub Action will update data shortly.', ip, ua: ua.slice(0, 120) });
  },

  async scheduled(_event, env) {
    if (!env.GITHUB_TOKEN || !env.GH_REFRESH_URL) return;
    await fetch(env.GH_REFRESH_URL, {
      method: 'POST',
      headers: {
        'Accept': 'application/vnd.github+json',
        'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ ref: 'main', inputs: { reason: 'scheduled-4h-worker' } })
    });
  }
};

function json(obj, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      ...extraHeaders
    }
  });
}
