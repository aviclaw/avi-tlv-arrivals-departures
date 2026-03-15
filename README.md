# avi-tlv-arrivals-departures

GitHub Pages dashboard for TLV arrivals/departures.

## Features
- Static dashboard (`index.html`)
- Flight data file (`data/flights.json`)
- Auto refresh every 4 hours (`.github/workflows/refresh-data.yml`)
- Manual refresh button wired to Cloudflare Worker (`/api/refresh`)
- DDoS/rate-limit controls on refresh endpoint

## Security model
- API key is server-side only: GitHub secret `AVIATION_EDGE_API_KEY`
- Manual refresh endpoint protected by `x-refresh-token`
- Worker rate limits:
  - per-IP cooldown: 30s
  - global cap: 12 refreshes / 10 minutes
  - in-flight dispatch lock: 45s

## Setup

### 1) GitHub secrets
Add repo secret:
- `AVIATION_EDGE_API_KEY`

### 2) Pages deployment
Enable GitHub Pages for this repo (Actions workflow `pages.yml` handles deploy).

### 3) Cloudflare Worker
Create KV namespace and update `wrangler.jsonc` `kv_namespaces[0].id`.

Set Worker secrets:
- `GITHUB_TOKEN` (token with actions:write for this repo)
- `REFRESH_TOKEN` (shared secret for browser button)

Deploy:
```bash
wrangler deploy
```

### 4) Wire frontend runtime config
Set in `index.html` via an injected script at deploy time or maintain a small `config.js` that is not committed with secret values:
- `window.REFRESH_ENDPOINT`
- `window.REFRESH_TOKEN`

## Notes
- Do not commit `.env` or real tokens.
- Keep GitHub token scope minimal.
