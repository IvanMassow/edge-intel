# Phase 2 — API Keys Panel

Status: ready to build once Phase 1 is complete
Prereq: Phase 1
Blocks: Phase 3 (integrations need credentials)

## Goal

A local, encrypted credentials vault and a UI at `/campaign-lab/settings/api-keys` where the user enters, tests, and rotates keys for every provider Campaign Lab talks to. Keys never leave the Mac Mini and are never stored in plaintext on disk.

**Design principle**: every value that's a secret (API key, OAuth access token, refresh token, webhook signing secret, SMTP password) goes through this vault. Nothing in `.env` except boot config (host, port, DB path, master-key path).

## Threat model

- **Attacker has read access to the repo** — gets nothing. `.gitignore` excludes `master.key` and the DB.
- **Attacker has read access to the DB file** — gets ciphertext. Without the master key, useless.
- **Attacker has read access to the master key but not the DB** — useless (one without the other is nothing).
- **Attacker has root on the Mac Mini** — game over; all bets are off. Mitigation: launchd service runs as the user, not root; keys live in the user home directory with 0600 permissions.

Not trying to defend against root. Trying to defend against accidental leakage (committed files, shared screens, backups).

## Crypto choice

**libsodium / PyNaCl secretbox (XSalsa20-Poly1305).** Reasons:
- Authenticated encryption (ciphertext tampering fails verification)
- Single well-reviewed primitive
- PyNaCl ships on macOS via `pip install pynacl` with no compilation
- 32-byte key, 24-byte nonce per encryption

Do not hand-roll AES. Do not use `cryptography.fernet` unless the Mac session already has it — PyNaCl is simpler.

## Master key

Single 32-byte key at `~/.noah-marketing-suite/master.key` (binary file, not base64). chmod 0600. Generated on first run:

```python
# credentials.py — bootstrap
import os
from pathlib import Path

KEY_PATH = Path.home() / ".noah-marketing-suite" / "master.key"

def get_master_key() -> bytes:
    if not KEY_PATH.exists():
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        key = os.urandom(32)
        KEY_PATH.write_bytes(key)
        KEY_PATH.chmod(0o600)
        print(f"[credentials] generated new master key at {KEY_PATH}")
        return key
    data = KEY_PATH.read_bytes()
    if len(data) != 32:
        raise RuntimeError(f"master key at {KEY_PATH} is {len(data)} bytes, expected 32")
    return data
```

**Add to `.gitignore`** immediately:
```
.noah-marketing-suite/
master.key
data/*.db
data/*.db.backup-*
```

(Even though the key lives in `$HOME`, not in the project, the `.gitignore` entry is a belt-and-braces rule in case anyone ever symlinks or copies it into the project tree.)

## Schema: `006_phase2_credentials.sql`

```sql
CREATE TABLE IF NOT EXISTS api_credentials (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    provider           TEXT NOT NULL,     -- 'smartlead'|'apollo'|'similarweb'|...
    credential_type    TEXT NOT NULL,     -- 'api_key'|'oauth'|'bearer'|'webhook_secret'
    label              TEXT NOT NULL,     -- human-readable tag, e.g., "smartlead-pro-uk"
    ciphertext         BLOB NOT NULL,
    nonce              BLOB NOT NULL,
    masked_preview     TEXT,              -- safe to display: e.g., "sk-abc...xyz"
    scopes             TEXT,              -- JSON array of scopes (OAuth) or empty
    expires_at         TIMESTAMP,         -- for OAuth access tokens
    last_tested_at     TIMESTAMP,
    last_test_status   TEXT,              -- 'ok'|'fail'|'expired'|'unknown'
    last_test_message  TEXT,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, label)
);

CREATE INDEX IF NOT EXISTS idx_credentials_provider ON api_credentials(provider);
```

## Python module: `credentials.py`

```python
# ~/noah-marketing-suite/credentials.py
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from nacl.secret import SecretBox
from nacl.utils import random as nacl_random

from db import get_conn


KEY_PATH = Path.home() / ".noah-marketing-suite" / "master.key"


def _master_key() -> bytes:
    if not KEY_PATH.exists():
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        key = os.urandom(32)
        KEY_PATH.write_bytes(key)
        KEY_PATH.chmod(0o600)
        return key
    data = KEY_PATH.read_bytes()
    if len(data) != 32:
        raise RuntimeError(f"master key at {KEY_PATH} is {len(data)} bytes, expected 32")
    return data


def _box() -> SecretBox:
    return SecretBox(_master_key())


def _mask(secret: str) -> str:
    """Return a safe-to-display masked preview: first 4 + last 4 chars if length > 12."""
    if len(secret) <= 12:
        return "***"
    return f"{secret[:4]}…{secret[-4:]}"


def set_credential(
    provider: str,
    label: str,
    plaintext: str,
    credential_type: str = "api_key",
    scopes: Optional[list] = None,
    expires_at: Optional[datetime] = None,
) -> int:
    """Encrypt and persist a credential. Returns the row id."""
    box = _box()
    nonce = nacl_random(SecretBox.NONCE_SIZE)
    ct = box.encrypt(plaintext.encode("utf-8"), nonce).ciphertext
    masked = _mask(plaintext)

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO api_credentials
                (provider, credential_type, label, ciphertext, nonce, masked_preview, scopes, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(provider, label) DO UPDATE SET
                ciphertext = excluded.ciphertext,
                nonce = excluded.nonce,
                masked_preview = excluded.masked_preview,
                scopes = excluded.scopes,
                expires_at = excluded.expires_at,
                updated_at = CURRENT_TIMESTAMP
        """, (
            provider, credential_type, label, ct, nonce, masked,
            json.dumps(scopes) if scopes else None,
            expires_at.isoformat() if expires_at else None,
        ))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_credential(provider: str, label: Optional[str] = None) -> Optional[str]:
    """Load and decrypt a credential. Plaintext is returned in-memory only."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        if label:
            cur.execute(
                "SELECT ciphertext, nonce FROM api_credentials WHERE provider = ? AND label = ?",
                (provider, label),
            )
        else:
            cur.execute(
                "SELECT ciphertext, nonce FROM api_credentials WHERE provider = ? ORDER BY updated_at DESC LIMIT 1",
                (provider,),
            )
        row = cur.fetchone()
        if not row:
            return None
        box = _box()
        return box.decrypt(row[0], row[1]).decode("utf-8")
    finally:
        conn.close()


def list_credentials() -> list[dict]:
    """List all credentials — masked only, never plaintext."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, provider, credential_type, label, masked_preview,
                   scopes, expires_at, last_tested_at, last_test_status, last_test_message
              FROM api_credentials
             ORDER BY provider, label
        """)
        return [
            {
                "id": r[0], "provider": r[1], "credential_type": r[2], "label": r[3],
                "masked_preview": r[4], "scopes": json.loads(r[5]) if r[5] else [],
                "expires_at": r[6], "last_tested_at": r[7],
                "last_test_status": r[8], "last_test_message": r[9],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def delete_credential(credential_id: int) -> bool:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM api_credentials WHERE id = ?", (credential_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def record_test_result(credential_id: int, status: str, message: str = "") -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE api_credentials
               SET last_tested_at = CURRENT_TIMESTAMP,
                   last_test_status = ?,
                   last_test_message = ?
             WHERE id = ?
        """, (status, message, credential_id))
        conn.commit()
    finally:
        conn.close()
```

## Test connection helpers

Per-provider tests. Each returns `(status, message)` where status is `'ok'|'fail'|'expired'`.

```python
# ~/noah-marketing-suite/credentials_tests.py
import requests
from credentials import get_credential, record_test_result


def test_anthropic(credential_id: int) -> tuple[str, str]:
    key = get_credential("anthropic")
    if not key:
        return ("fail", "no credential stored")
    r = requests.get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        timeout=10,
    )
    if r.status_code == 200:
        return ("ok", f"{len(r.json().get('data', []))} models visible")
    if r.status_code == 401:
        return ("fail", "authentication rejected")
    return ("fail", f"HTTP {r.status_code}")


def test_smartlead(credential_id: int) -> tuple[str, str]:
    key = get_credential("smartlead")
    if not key:
        return ("fail", "no credential stored")
    r = requests.get(
        "https://server.smartlead.ai/api/v1/campaigns",
        params={"api_key": key},
        timeout=10,
    )
    if r.status_code == 200:
        return ("ok", f"{len(r.json())} campaigns visible")
    if r.status_code in (401, 403):
        return ("fail", "authentication rejected")
    return ("fail", f"HTTP {r.status_code}")


def test_apollo(credential_id: int) -> tuple[str, str]:
    key = get_credential("apollo")
    if not key:
        return ("fail", "no credential stored")
    # Apollo "me" endpoint for health check
    r = requests.get(
        "https://api.apollo.io/v1/auth/health",
        headers={"X-Api-Key": key, "Content-Type": "application/json"},
        timeout=10,
    )
    if r.status_code == 200:
        return ("ok", "authenticated")
    return ("fail", f"HTTP {r.status_code}")


def test_similarweb(credential_id: int) -> tuple[str, str]:
    key = get_credential("similarweb")
    if not key:
        return ("fail", "no credential stored")
    r = requests.get(
        f"https://api.similarweb.com/v1/website/bbc.com/total-traffic-and-engagement/visits",
        params={"api_key": key, "start_date": "2026-02", "end_date": "2026-02", "country": "world", "granularity": "monthly"},
        timeout=15,
    )
    if r.status_code == 200:
        return ("ok", "authenticated")
    if r.status_code in (401, 403):
        return ("fail", "authentication rejected")
    return ("fail", f"HTTP {r.status_code}")


def test_proxycurl(credential_id: int) -> tuple[str, str]:
    key = get_credential("proxycurl")
    if not key:
        return ("fail", "no credential stored")
    r = requests.get(
        "https://nubela.co/proxycurl/api/credit-balance",
        headers={"Authorization": f"Bearer {key}"},
        timeout=10,
    )
    if r.status_code == 200:
        data = r.json()
        return ("ok", f"credit balance: {data.get('credit_balance', '?')}")
    return ("fail", f"HTTP {r.status_code}")


# Register tests
TESTS = {
    "anthropic":  test_anthropic,
    "smartlead":  test_smartlead,
    "apollo":     test_apollo,
    "similarweb": test_similarweb,
    "proxycurl":  test_proxycurl,
}


def run_test(provider: str, credential_id: int) -> tuple[str, str]:
    fn = TESTS.get(provider)
    if not fn:
        return ("unknown", f"no test registered for {provider}")
    try:
        status, msg = fn(credential_id)
    except Exception as e:
        status, msg = ("fail", f"exception: {e}")
    record_test_result(credential_id, status, msg)
    return status, msg
```

Add more tests in Phase 3 as new providers come online.

## Flask endpoints

```python
# assistant.py — Phase 2 additions
from credentials import list_credentials, set_credential, delete_credential
from credentials_tests import run_test

@app.route("/api/campaign-lab/credentials", methods=["GET"])
def api_list_credentials():
    return jsonify({"credentials": list_credentials()})

@app.route("/api/campaign-lab/credentials", methods=["POST"])
def api_set_credential():
    body = request.get_json() or {}
    required = ("provider", "label", "plaintext")
    missing = [k for k in required if k not in body]
    if missing:
        return jsonify({"error": f"missing: {missing}"}), 400
    cred_id = set_credential(
        provider=body["provider"],
        label=body["label"],
        plaintext=body["plaintext"],
        credential_type=body.get("credential_type", "api_key"),
        scopes=body.get("scopes"),
    )
    return jsonify({"id": cred_id, "status": "stored"}), 201

@app.route("/api/campaign-lab/credentials/<int:cid>", methods=["DELETE"])
def api_delete_credential(cid):
    if delete_credential(cid):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "not found"}), 404

@app.route("/api/campaign-lab/credentials/<int:cid>/test", methods=["POST"])
def api_test_credential(cid):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT provider FROM api_credentials WHERE id = ?", (cid,))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    status, message = run_test(row[0], cid)
    return jsonify({"status": status, "message": message})

@app.route("/campaign-lab/settings/api-keys")
def cl_settings_apikeys():
    return render_template("campaign_lab/settings_apikeys.html")
```

## UI: `/campaign-lab/settings/api-keys`

Single-page layout:

**Top section — provider catalogue**. Grid of tiles, one per known provider (seeded below). Each tile:
- Provider name + logo (just a letter/emoji if no image)
- Status pill: `Not set` / `Set` / `Tested OK` / `Test failed` / `Expired`
- Preview: the masked value if set (e.g., `sk-a…xyz`)
- Actions: [Edit] [Test] [Remove]

**Click [Edit]** — modal with:
- Label field (e.g., `smartlead-primary`)
- Secret field (password input, never pre-filled; typing replaces the stored value)
- Optional fields per credential type (scopes, expires_at)
- Save button → `POST /api/campaign-lab/credentials`

**Click [Test]** — `POST /api/campaign-lab/credentials/<id>/test`; update the pill + preview with the result inline.

**Provider seed list** (render as tiles even before any are set):

| Provider | credential_type | Notes |
|---|---|---|
| `anthropic` | `api_key` | Claude API + Managed Agents |
| `smartlead` | `api_key` | Sending infra |
| `apollo` | `api_key` | Lead data (Phase 3 uses REST; Phase 4 can swap to MCP vault) |
| `similarweb` | `api_key` | Traffic-drop trigger |
| `proxycurl` | `bearer` | LinkedIn enrichment |
| `hubspot` | `oauth` | CRM (Phase 4) |
| `linkedin_ads` | `oauth` | Matched audiences (Phase 5) |
| `google_ads` | `oauth` | Customer Match (Phase 5) |
| `heyreach` | `api_key` | LinkedIn automation (optional) |
| `newsapi` | `api_key` | News-mention trigger (Phase 3) |
| `crunchbase` | `api_key` | Funding trigger (Phase 3) |
| `cal_com_webhook` | `webhook_secret` | Calendly/Cal.com booking webhook signature |
| `smtp_fallback` | `api_key` | Only if you keep a direct-SMTP route for testing |

UI should render all 13 tiles even when unset, so the user can see the full range of what's possible.

## Install PyNaCl

```bash
cd ~/noah-marketing-suite
./venv/bin/pip install pynacl==1.5.0
./venv/bin/pip freeze | grep -i nacl  # verify
```

Add to `requirements.txt` too.

## Exit criteria

- [ ] `credentials` table exists
- [ ] `~/.noah-marketing-suite/master.key` exists with 0600 permissions
- [ ] `.gitignore` updated to exclude `master.key`, the DB, and backups
- [ ] UI page loads and shows all seeded provider tiles
- [ ] Setting a credential encrypts it — verify by inspecting `api_credentials.ciphertext` in the DB (should be binary, not readable)
- [ ] Getting a credential decrypts it correctly — verify via the `/test` endpoint for at least 2 providers
- [ ] Deleting a credential works
- [ ] Masked previews never expose more than first-4/last-4 of the secret
- [ ] `GET /api/campaign-lab/credentials` never returns plaintext or ciphertext in its JSON response — only masked previews and metadata
