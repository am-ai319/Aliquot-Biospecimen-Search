"""
Aliquot Spatial Biology Tool — Flask server
Proxies requests to aliquot.txgmesh.net using a Cloudflare Service Token.

Required environment variables:
  CF_CLIENT_ID      — Cloudflare Access Service Token Client ID
  CF_CLIENT_SECRET  — Cloudflare Access Service Token Client Secret

Optional:
  PORT              — HTTP port (default 8080)
"""

import gzip
import json
import os
import urllib.parse
import urllib.request
import urllib.error

from flask import Flask, jsonify, request, send_from_directory, Response

ALIQUOT_BASE = "https://aliquot.txgmesh.net/api/biospecimens"

CF_CLIENT_ID     = os.environ.get("CF_CLIENT_ID", "")
CF_CLIENT_SECRET = os.environ.get("CF_CLIENT_SECRET", "")

app = Flask(__name__, static_folder="static")


# ── Helpers ────────────────────────────────────────────────────────────────

def cf_headers():
    """Build headers that authenticate via Cloudflare Access Service Token."""
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    if CF_CLIENT_ID and CF_CLIENT_SECRET:
        h["CF-Access-Client-Id"]     = CF_CLIENT_ID
        h["CF-Access-Client-Secret"] = CF_CLIENT_SECRET
    else:
        print("WARNING: CF_CLIENT_ID / CF_CLIENT_SECRET not set — requests may return 403.")
    return h


def decompress(raw, headers):
    """Decompress gzip body if needed."""
    enc = headers.get("Content-Encoding", "")
    if enc == "gzip" or raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw)
        except Exception:
            pass
    return raw


def upstream_get(url):
    req = urllib.request.Request(url, headers=cf_headers(), method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            body = decompress(resp.read(), resp.headers)
            return json.loads(body), resp.status, None
    except urllib.error.HTTPError as e:
        body = decompress(e.read(), e.headers)
        try:
            detail = json.loads(body)
        except Exception:
            detail = {"error": body.decode(errors="replace")}
        return None, e.code, detail
    except Exception as exc:
        return None, 502, {"error": str(exc)}


def upstream_put_formdata(url, record):
    """PUT a biospecimen using multipart/form-data with jsonData field (matches Aliquot's frontend)."""
    import email.generator
    import io
    import random
    import string

    boundary = "----FormBoundary" + "".join(random.choices(string.ascii_letters + string.digits, k=16))
    json_str = json.dumps(record).encode("utf-8")

    # Build raw multipart body manually (no external deps)
    body_parts = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="jsonData"\r\n\r\n'
    ).encode("utf-8") + json_str + f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = cf_headers()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    headers["Content-Length"] = str(len(body_parts))

    req = urllib.request.Request(url, data=body_parts, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req) as resp:
            body = decompress(resp.read(), resp.headers)
            return json.loads(body) if body else {}, resp.status, None
    except urllib.error.HTTPError as e:
        body = decompress(e.read(), e.headers)
        try:
            detail = json.loads(body)
        except Exception:
            detail = {"error": body.decode(errors="replace")}
        return None, e.code, detail
    except Exception as exc:
        return None, 502, {"error": str(exc)}


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "aliquot-spatial-biology.html")


@app.route("/api/biospecimens/search")
def search_specimen():
    """Search biospecimens by name."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Missing query parameter q"}), 400

    upstream = f"{ALIQUOT_BASE}?name={urllib.parse.quote(q)}"
    print(f"SEARCH → {upstream}")
    data, status, err = upstream_get(upstream)
    if err:
        print(f"  ← {status} {err}")
        return jsonify(err), status
    print(f"  ← {status} OK")
    return jsonify(data), status


@app.route("/api/biospecimens/<path:specimen_id>", methods=["GET"])
def get_specimen(specimen_id):
    """Fetch a biospecimen by UUID."""
    upstream = f"{ALIQUOT_BASE}/{urllib.parse.quote(specimen_id)}"
    print(f"GET → {upstream}")
    data, status, err = upstream_get(upstream)
    if err:
        print(f"  ← {status} {err}")
        return jsonify(err), status
    print(f"  ← {status} OK")
    return jsonify(data), status


@app.route("/api/biospecimens/<path:specimen_id>", methods=["PATCH"])
def patch_specimen(specimen_id):
    """Update a biospecimen's description using PUT + multipart/form-data (Aliquot's pattern).

    The frontend sends the full record it already has so we avoid a re-fetch
    (the single-record GET endpoint returns the SPA HTML, not JSON).
    Expected body: { "description": "...", "record": { ...full biospecimen... } }
    """
    payload = request.get_json(force=True)
    if not payload:
        return jsonify({"error": "Empty request body"}), 400

    record = payload.get("record")
    if not record:
        return jsonify({"error": "Missing 'record' field — send the full biospecimen object"}), 400

    # Merge updated description into the record
    record["description"] = payload.get("description", record.get("description", ""))

    upstream = f"{ALIQUOT_BASE}/{urllib.parse.quote(specimen_id)}"
    print(f"PUT (update) → {upstream}")
    data, status, err = upstream_put_formdata(upstream, record)
    if err:
        print(f"  ← {status} {err}")
        return jsonify(err), status
    print(f"  ← {status} OK")
    return jsonify(data), status


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    if not CF_CLIENT_ID or not CF_CLIENT_SECRET:
        print("⚠️  Set CF_CLIENT_ID and CF_CLIENT_SECRET environment variables before deploying.")
    print(f"Starting on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
