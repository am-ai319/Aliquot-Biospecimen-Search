# Aliquot Biospecimen Search Tool

A web tool for searching biospecimens in [Aliquot](https://aliquot.txgmesh.net) and viewing their inventory locations. Built for the spatial biology team at 10x Genomics.

## What it does

- Search biospecimens by name, tissue type, disease type, and specimen type
- Automatically filters out **INACTIVE** specimens
- Only shows specimens that are physically in inventory
- Displays **Drawer** and **Column** location for each result
- Displays H&E images inline where available

## APIs used

| Endpoint | Purpose |
|---|---|
| `GET /api/biospecimens?searchQuery=<q>` | Search biospecimens by name, tissue, or disease |
| `GET /api/biospecimens/{uuid}/inventory` | Fetch inventory location (Drawer / Column) |
| `GET /api/tissuetypes` | Load active tissue types for the dropdown |

## Running locally

**Requirements:** Python 3.10+, a valid `CF_Authorization` cookie from [aliquot.txgmesh.net](https://aliquot.txgmesh.net)

```bash
# Install dependencies
pip install flask gunicorn

# Start the server
python app.py

# Open in browser
open http://localhost:8080
```

Or if using the project's virtual environment:

```bash
.venv/bin/python app.py
```

## Deploying to Railway

The repo includes a `Procfile` and `railway.toml` for one-click Railway deployment.

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select `am-ai319/Aliquot-Biospecimen-Search`
3. Railway builds and serves it automatically — every `git push` triggers a redeploy

The app must sit behind the same Cloudflare Access policy as Aliquot so the `CF_Authorization` cookie is shared and user identity is resolved automatically.

## Authentication

Authentication is handled via Cloudflare Access. When deployed on Railway behind the same Access policy as Aliquot, the `CF_Authorization` cookie is set automatically when the user logs in — no token pasting required.

For local development, paste your `CF_Authorization` token into the token field on the page (DevTools → Application → Cookies → `CF_Authorization` on aliquot.txgmesh.net).

