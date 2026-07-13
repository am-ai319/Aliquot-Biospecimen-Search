"""
Aliquot Spatial Biology Tool
Flask proxy server — forwards requests to aliquot.txgmesh.net using the
user's CF_Authorization token (passed via X-CF-Token header from the browser).

Deploy to Railway:
  Set no required env vars — auth is per-user via their CF_Authorization token.

Run locally:
  pip install flask gunicorn
  python app.py
  Open http://localhost:8080
"""

import gzip
import json
import os
import random
import string
import urllib.parse
import urllib.request
import urllib.error

from flask import Flask, jsonify, request, send_from_directory

ALIQUOT_BASE = "https://aliquot.txgmesh.net/api/biospecimens"

# Optional service token — if set, the server authenticates all Aliquot API
# calls so users never need to paste their CF_Authorization token.
CF_CLIENT_ID     = os.environ.get("CF_CLIENT_ID", "")
CF_CLIENT_SECRET = os.environ.get("CF_CLIENT_SECRET", "")
USE_SERVICE_TOKEN = bool(CF_CLIENT_ID and CF_CLIENT_SECRET)

app = Flask(__name__, static_folder=".")


# ── Helpers ────────────────────────────────────────────────────────────────

def make_headers(cf_token: str = "") -> dict:
    h = {
        "Accept": "application/json, */*",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Origin": "https://aliquot.txgmesh.net",
        "Referer": "https://aliquot.txgmesh.net/",
    }
    if USE_SERVICE_TOKEN:
        # Service token: server-level auth — no user token needed
        h["CF-Access-Client-Id"]     = CF_CLIENT_ID
        h["CF-Access-Client-Secret"] = CF_CLIENT_SECRET
    elif cf_token:
        # Per-user token passed from the browser
        h["Cookie"] = f"CF_Authorization={cf_token}"
        h["CF-Access-Jwt-Assertion"] = cf_token
    return h


def decompress(raw: bytes, headers) -> bytes:
    enc = headers.get("Content-Encoding", "")
    if enc == "gzip" or raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw)
        except Exception:
            pass
    return raw


def parse_json_safe(raw: bytes):
    """Parse JSON, returning None (not raising) on empty or non-JSON bodies."""
    text = raw.strip()
    if not text:
        return None
    # Reject HTML responses (SPA catch-all pages)
    if text[:1] in (b"<", b"\xef"):
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def do_get(url: str, cf_token: str):
    headers = make_headers(cf_token)
    print(f"GET {url}")
    print(f"Token present: {bool(cf_token)}, length: {len(cf_token) if cf_token else 0}")
    print(f"Headers: Cookie={'yes' if 'Cookie' in headers else 'no'}")

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as r:
            body = decompress(r.read(), r.headers)
            print(f"Response: {len(body)} bytes, first 100 chars: {body[:100]}")
            data = parse_json_safe(body)
            if data is None:
                return None, r.status, {"error": f"Non-JSON response from upstream (HTTP {r.status})", "body_preview": body[:200].decode('utf-8', errors='replace')}
            return data, r.status, None
    except urllib.error.HTTPError as e:
        body = decompress(e.read(), e.headers)
        detail = parse_json_safe(body) or {"error": body.decode(errors="replace")[:500]}
        return None, e.code, detail
    except Exception as exc:
        return None, 502, {"error": str(exc)}


def do_put_formdata(url: str, record: dict, cf_token: str):
    """PUT the full biospecimen record as multipart/form-data (Aliquot's update pattern)."""
    boundary = "----FormBoundary" + "".join(
        random.choices(string.ascii_letters + string.digits, k=16)
    )
    json_bytes = json.dumps(record).encode("utf-8")
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="jsonData"\r\n\r\n'
    ).encode() + json_bytes + f"\r\n--{boundary}--\r\n".encode()

    headers = make_headers(cf_token)
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    headers["Content-Length"] = str(len(body))

    req = urllib.request.Request(url, data=body, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req) as r:
            raw = decompress(r.read(), r.headers)
            return (parse_json_safe(raw) or {}), r.status, None
    except urllib.error.HTTPError as e:
        raw = decompress(e.read(), e.headers)
        detail = parse_json_safe(raw) or {"error": raw.decode(errors="replace")[:500]}
        return None, e.code, detail
    except Exception as exc:
        return None, 502, {"error": str(exc)}


def get_cf_token() -> str:
    """Read CF token from header, cookie, or env fallback."""
    # 1. Prefer explicit header sent by the browser JS
    token = request.headers.get("X-CF-Token", "").strip()
    if token:
        return token

    # 2. Cookie set by browser JS
    token = request.cookies.get("CF_Authorization", "").strip()
    if token:
        return token

    # 3. Local dev fallback
    token = os.environ.get("DEV_CF_TOKEN", "")
    if token:
        print(f"Using DEV_CF_TOKEN: {token[:50]}...")
    return token


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/test")
def test():
    """Ultra-simple test endpoint"""
    cf_token = get_cf_token()

    # Fetch data
    url = f"{ALIQUOT_BASE}?searchQuery=brain&bioSpecimenType=FFPE_BLOCK&limit=10"
    data, status, err = do_get(url, cf_token)

    if err:
        return f"ERROR: {err}", 500

    records = data.get('data', [])

    # Build plain text response
    output = f"SEARCH RESULTS: Found {len(records)} specimens\n\n"

    for i, r in enumerate(records, 1):
        output += f"{i}. {r['name']}\n"
        tissues = ', '.join([t['name'] for t in (r.get('tissueTypes') or [])])
        output += f"   Tissue: {tissues}\n"
        output += f"   Disease: {r.get('diseaseType', {}).get('name', 'N/A')}\n"
        output += f"   Link: https://aliquot.txgmesh.net/biospecimen/{r['id']}\n\n"

    return f"<pre>{output}</pre>", 200, {'Content-Type': 'text/html'}


@app.route("/debug.html")
def debug_page():
    return send_from_directory(".", "debug.html")


@app.route("/search.html")
def search_page():
    return send_from_directory(".", "search.html")


@app.route("/simple-search")
def simple_search():
    """Server-rendered search - no JavaScript required"""
    tissue = request.args.get('tissue', '').strip()
    bio_type = request.args.get('type', '').strip()

    results_html = ''
    count = 0

    if tissue or bio_type:
        cf_token = get_cf_token()
        params = []
        if tissue:
            params.append(f'searchQuery={urllib.parse.quote(tissue)}')
        if bio_type:
            params.append(f'bioSpecimenType={urllib.parse.quote(bio_type)}')

        url = f"{ALIQUOT_BASE}?{'&'.join(params)}&limit=50"
        data, status, err = do_get(url, cf_token)

        if not err and data:
            records = data.get('data', [])
            count = len(records)

            for r in records[:20]:
                tissues = ', '.join([t.get('name', '') for t in (r.get('tissueTypes') or [])])
                disease = r.get('diseaseType', {}).get('name') or r.get('primaryDiagnosis', 'N/A')
                aliquot_url = f"https://aliquot.txgmesh.net/biospecimen/{r['id']}"

                results_html += f'''
                <div style="background:#f9f9f9;padding:15px;margin:10px 0;border-left:3px solid #2563eb;border-radius:4px;">
                    <strong><a href="{aliquot_url}" target="_blank" style="color:#2563eb;">{r['name']}</a></strong><br>
                    <small>Tissue: {tissues} | Disease: {disease}</small>
                </div>
                '''

            if count > 20:
                results_html += f'<p style="color:#666;margin:10px 0;"><em>...and {count - 20} more results</em></p>'

    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Aliquot Simple Search</title>
        <style>
            body {{ font-family: Arial; padding: 20px; background: #f5f5f5; }}
            .box {{ background: white; padding: 20px; margin: 10px 0; border-radius: 8px; }}
            input, select {{ padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 4px; width: 300px; }}
            button {{ padding: 12px 24px; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }}
        </style>
    </head>
    <body>
        <h1>🔬 Aliquot Biospecimen Search (Server-Side)</h1>

        <div class="box">
            <form method="GET" action="/simple-search">
                <div>
                    <label><strong>Tissue Type:</strong></label><br>
                    <input type="text" name="tissue" placeholder="e.g., brain" value="{tissue}">
                </div>
                <div>
                    <label><strong>Biospecimen Type:</strong></label><br>
                    <select name="type">
                        <option value="">All Types</option>
                        <option value="FFPE_BLOCK" {'selected' if bio_type == 'FFPE_BLOCK' else ''}>FFPE Block</option>
                        <option value="FROZEN_OCT_BLOCK" {'selected' if bio_type == 'FROZEN_OCT_BLOCK' else ''}>Frozen OCT Block</option>
                        <option value="TISSUE_MICROARRAY" {'selected' if bio_type == 'TISSUE_MICROARRAY' else ''}>Tissue Microarray</option>
                    </select>
                </div>
                <br>
                <button type="submit">🔍 Search</button>
            </form>
        </div>

        {f'<div class="box"><h3>Results ({count} found)</h3>{results_html}</div>' if count > 0 else ''}
        {f'<div class="box"><p>No results found. Try different search terms.</p></div>' if (tissue or bio_type) and count == 0 else ''}
    </body>
    </html>
    '''

    return html


@app.route("/api/debug")
def debug():
    """Debug endpoint to see what the API actually returns"""
    cf_token = get_cf_token()

    # Try a simple query with limit
    test_url = f"{ALIQUOT_BASE}?limit=5"
    print(f"DEBUG → {test_url}")

    data, status, err = do_get(test_url, cf_token)
    if err:
        return jsonify({
            "error": "API call failed",
            "details": err,
            "status": status,
            "has_cf_token": bool(cf_token)
        }), status

    records = data.get("data", []) if isinstance(data, dict) else data

    # Show structure
    result = {
        "total_returned": len(records) if records else 0,
        "response_type": str(type(data)),
        "envelope_keys": list(data.keys()) if isinstance(data, dict) else None,
        "has_cf_token": bool(cf_token)
    }

    if records and len(records) > 0:
        result["sample_record_keys"] = sorted(list(records[0].keys()))
        result["sample_records"] = records

        # Show unique tissue types
        tissue_types = set()
        for r in records:
            if r.get("tissueType"):
                tissue_types.add(r.get("tissueType"))
        result["tissue_types_in_sample"] = sorted(list(tissue_types))

    return jsonify(result), 200


@app.route("/api/whoami")
def whoami():
    """
    Resolve the logged-in user's email via Cloudflare Access.

    On Railway the CF_Authorization cookie is set automatically when the user
    authenticates through the shared Okta/CF Access policy — no token paste needed.
    The server calls /cdn-cgi/access/get-identity on the same host to retrieve
    the verified identity.
    """
    cf_cookie = request.cookies.get("CF_Authorization", "")
    if not cf_cookie:
        return jsonify({"email": "", "source": "none"}), 200

    try:
        # Ask Cloudflare to resolve the identity for this session cookie
        host = request.host  # e.g. aliquot-spatial-bio.up.railway.app
        identity_url = f"https://{host}/cdn-cgi/access/get-identity"
        req = urllib.request.Request(
            identity_url,
            headers={
                "Cookie": f"CF_Authorization={cf_cookie}",
                "User-Agent": "Mozilla/5.0 Chrome/124.0.0.0",
            },
        )
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
            email = data.get("email", "")
            name  = data.get("name", "")
            if email:
                print(f"  whoami → {email} (CF identity)")
                return jsonify({"email": email, "name": name, "source": "cf-identity"})
    except Exception as exc:
        print(f"  whoami CF identity failed: {exc}")

    # Fallback: decode the JWT payload directly (works on localhost too)
    try:
        import base64 as _b64
        parts = cf_cookie.split(".")
        pad = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(_b64.urlsafe_b64decode(pad))
        email = payload.get("email") or (payload.get("custom") or {}).get("email", "")
        if email:
            print(f"  whoami → {email} (JWT decode)")
            return jsonify({"email": email, "name": "", "source": "jwt-decode"})
    except Exception:
        pass

    return jsonify({"email": "", "source": "none"}), 200


@app.route("/api/search")
def search():
    """
    Advanced biospecimen search with multiple filters.
    Query params:
      - q: biospecimen name or ID (partial match)
      - bioSpecimenType: FFPE_BLOCK, FROZEN_OCT_BLOCK, or TISSUE_MICROARRAY
      - tissueType: tissue type filter (partial match)
      - diseaseType: disease type filter (partial match)
      - hasInventoryLocations: true/false
      - hasImageLinks: true/false
      - hasExperiments: true/false
    """
    cf_token = get_cf_token()

    # Get user filters
    q = request.args.get("q", "").strip().lower()
    spec_type = request.args.get("bioSpecimenType", "").strip()
    tissue_type = request.args.get("tissueType", "").strip().lower()
    disease_type = request.args.get("diseaseType", "").strip().lower()
    has_inv = request.args.get("hasInventoryLocations", "").lower() == "true"
    has_img = request.args.get("hasImageLinks", "").lower() == "true"
    has_exp = request.args.get("hasExperiments", "").lower() == "true"

    print(f"SEARCH filters: q={q!r}, type={spec_type!r}, tissue={tissue_type!r}, disease={disease_type!r}")

    # Fetch from API - try using searchQuery for broad search
    params = []

    # Build a search query combining all text filters
    search_terms = []
    if q:
        search_terms.append(q)
    if tissue_type:
        search_terms.append(tissue_type)
    if disease_type:
        search_terms.append(disease_type)

    if search_terms:
        # Use searchQuery parameter for general search
        search_query = " ".join(search_terms)
        params.append(f"searchQuery={urllib.parse.quote(search_query)}")
    else:
        # If no search terms, get recent records
        params.append("limit=100")

    # Add specimen type to API query if provided
    if spec_type:
        params.append(f"bioSpecimenType={urllib.parse.quote(spec_type)}")

    query_string = "&".join(params)
    url = f"{ALIQUOT_BASE}?{query_string}"
    print(f"  API URL: {url}")

    data, status, err = do_get(url, cf_token)
    if err:
        print(f"  ← {status} {err}")
        return jsonify(err), status

    # Unwrap envelope: { data: [...], total: N }
    records = data.get("data", []) if isinstance(data, dict) else data
    print(f"  API returned {len(records) if records else 0} records")

    if not records:
        return jsonify({"results": [], "total": 0, "message": "No biospecimens found"}), 200

    # Apply client-side filters
    filtered = []
    for r in records:
        # Filter by name/ID (partial match if not already filtered by API)
        if q and not any(q in str(v).lower() for k, v in r.items() if k in ['name', 'id']):
            continue

        # Filter by specimen type
        if spec_type and r.get("bioSpecimenType") != spec_type:
            continue

        # Filter by tissue type (search in tissueTypes array)
        if tissue_type:
            tissue_types = r.get("tissueTypes", [])
            if not isinstance(tissue_types, list):
                tissue_types = [tissue_types] if tissue_types else []
            # Check if any tissue type contains our search term
            if not any(tissue_type in str(t).lower() for t in tissue_types):
                continue

        # Filter by disease type (search in diseaseType array or diseaseTypeId)
        if disease_type:
            disease_types = r.get("diseaseType", [])
            disease_type_ids = r.get("diseaseTypeId", [])
            primary_diagnosis = r.get("primaryDiagnosis", "")

            if not isinstance(disease_types, list):
                disease_types = [disease_types] if disease_types else []
            if not isinstance(disease_type_ids, list):
                disease_type_ids = [disease_type_ids] if disease_type_ids else []

            # Check if disease_type appears in any of these fields
            found = False
            for dt in disease_types:
                if disease_type in str(dt).lower():
                    found = True
                    break
            if not found:
                for dt_id in disease_type_ids:
                    if disease_type in str(dt_id).lower():
                        found = True
                        break
            if not found and primary_diagnosis:
                if disease_type in str(primary_diagnosis).lower():
                    found = True

            if not found:
                continue

        # Note: Inventory locations, images, and experiments are optional
        # Don't filter them out - just display what's available
        filtered.append(r)

    print(f"  After filtering: {len(filtered)} result(s)")
    return jsonify({"results": filtered, "total": len(filtered)}), 200


@app.route("/api/biospecimens", methods=["GET"])
def list_biospecimens():
    """
    Proxy for list endpoint - forwards all query params to Aliquot API.
    """
    cf_token = get_cf_token()

    # Forward all query parameters
    query_string = request.query_string.decode('utf-8')
    url = f"{ALIQUOT_BASE}?{query_string}" if query_string else ALIQUOT_BASE
    print(f"GET → {url}")

    data, status, err = do_get(url, cf_token)
    if err:
        print(f"  ← {status} {err}")
        return jsonify(err), status

    print(f"  ← {status} OK (returned {len(data.get('data', []))} records)")
    return jsonify(data), 200


@app.route("/api/biospecimens/<specimen_id>", methods=["GET"])
def get_specimen(specimen_id):
    """
    Fetch a single biospecimen by ID (UUID).
    Returns full detail including inventoryLocations, experiments, etc.
    """
    cf_token = get_cf_token()
    url = f"{ALIQUOT_BASE}/{urllib.parse.quote(specimen_id)}"
    print(f"GET → {url}")

    data, status, err = do_get(url, cf_token)
    if err:
        print(f"  ← {status} {err}")
        return jsonify(err), status

    print(f"  ← {status} OK")
    return jsonify(data), 200


@app.route("/api/biospecimens/<specimen_id>/debug", methods=["GET"])
def debug_specimen(specimen_id):
    """Show all top-level keys in a biospecimen detail response."""
    cf_token = get_cf_token()
    url = f"{ALIQUOT_BASE}/{urllib.parse.quote(specimen_id)}"
    data, status, err = do_get(url, cf_token)
    if err:
        return jsonify(err), status
    summary = {k: (v if not isinstance(v, (dict, list)) else f"[{type(v).__name__} len={len(v)}]") for k, v in data.items()}
    return jsonify(summary), 200


@app.route("/api/biospecimens/<specimen_id>", methods=["PUT"])
def update_specimen(specimen_id):
    """
    Update a biospecimen's userNotes (inside additionalProperties) and description.
    Body: {
      "record":              <full biospecimen object>,
      "transcripts_per_cell": [1234.5, 1100.0],   # list of floats
      "experiment_ids":      ["EXP-001", "EXP-002"],
      "updated_by":          "user@example.com",
      "description":         "<full new description string>"
    }
    """
    payload = request.get_json(force=True) or {}
    record = payload.get("record")
    if not record:
        return jsonify({"error": "Missing 'record' in request body"}), 400

    # ── Write to additionalProperties.userNotes (structured) ──────────────
    tc_vals = payload.get("transcripts_per_cell", [])
    exp_ids = payload.get("experiment_ids", [])
    updated_by = payload.get("updated_by", "")
    updated_at = payload.get("updated_at", "")

    avg_tc = round(sum(tc_vals) / len(tc_vals), 4) if tc_vals else None

    user_notes = {}
    if avg_tc is not None:
        user_notes["transcripts_per_cell"] = avg_tc
        if len(tc_vals) > 1:
            user_notes["transcripts_per_cell_values"] = tc_vals
    if exp_ids:
        user_notes["experiment_ids"] = exp_ids
    if updated_by:
        user_notes["updated_by"] = updated_by
    if updated_at:
        user_notes["updated_at"] = updated_at

    if "additionalProperties" not in record or record["additionalProperties"] is None:
        record["additionalProperties"] = {}
    record["additionalProperties"]["userNotes"] = user_notes

    # ── Also update description ────────────────────────────────────────────
    record["description"] = payload.get("description", record.get("description", ""))

    cf_token = get_cf_token()

    url = f"{ALIQUOT_BASE}/{urllib.parse.quote(specimen_id)}"
    print(f"PUT → {url}")

    data, status, err = do_put_formdata(url, record, cf_token)
    if err:
        print(f"  ← {status} {err}")
        return jsonify(err), status

    print(f"  ← {status} OK")
    return jsonify({"ok": True}), 200


# ── Dev server ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"\n  Aliquot Spatial Biology Tool")
    print(f"  Open → http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
