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


def do_get(url: str, cf_token: str):
    req = urllib.request.Request(url, headers=make_headers(cf_token), method="GET")
    try:
        with urllib.request.urlopen(req) as r:
            body = decompress(r.read(), r.headers)
            return json.loads(body), r.status, None
    except urllib.error.HTTPError as e:
        body = decompress(e.read(), e.headers)
        try:
            detail = json.loads(body)
        except Exception:
            detail = {"error": body.decode(errors="replace")[:500]}
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
            return (json.loads(raw) if raw.strip() else {}), r.status, None
    except urllib.error.HTTPError as e:
        raw = decompress(e.read(), e.headers)
        try:
            detail = json.loads(raw)
        except Exception:
            detail = {"error": raw.decode(errors="replace")[:500]}
        return None, e.code, detail
    except Exception as exc:
        return None, 502, {"error": str(exc)}


def get_cf_token() -> str:
    return request.headers.get("X-CF-Token", "").strip()


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/whoami")
def whoami():
    """
    Return the logged-in user's email.
    On Railway (behind Cloudflare Access): reads from /cdn-cgi/access/get-identity.
    Locally: decodes the CF_Authorization JWT passed in X-CF-Token.
    """
    # ── Cloudflare Access identity (works when deployed behind CF Access) ──
    cf_cookie = request.cookies.get("CF_Authorization", "")
    if cf_cookie:
        try:
            identity_url = "https://aliquot.txgmesh.net/cdn-cgi/access/get-identity"
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
                if email:
                    return jsonify({"email": email, "source": "cf-identity"})
        except Exception:
            pass

    # ── Fall back: decode JWT from X-CF-Token header ──────────────────────
    user_token = request.headers.get("X-CF-Token", "")
    if user_token:
        try:
            import base64
            parts = user_token.split(".")
            pad = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(pad))
            email = payload.get("email") or (payload.get("custom") or {}).get("email", "")
            if email:
                return jsonify({"email": email, "source": "jwt-decode"})
        except Exception:
            pass

    return jsonify({"email": "", "source": "none"}), 200


@app.route("/api/search")
def search():
    """Search biospecimens by name: GET /api/search?q=<name>"""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Missing query parameter: q"}), 400

    cf_token = get_cf_token()
    url = f"{ALIQUOT_BASE}?name={urllib.parse.quote(q)}"
    print(f"SEARCH → {url}")

    data, status, err = do_get(url, cf_token)
    if err:
        print(f"  ← {status} {err}")
        return jsonify(err), status

    # Unwrap envelope: { data: [...], total: N }
    records = data.get("data", []) if isinstance(data, dict) else data
    if not records:
        return jsonify({"error": f"No biospecimen found with name '{q}'"}), 404

    print(f"  ← {status} OK — {len(records)} result(s)")
    return jsonify(records[0]), 200


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
