# Phase 0 — Polish & Unblock

Status: **ready to execute on Mac Mini**
Prereq: nothing (this is the first step)
Blocks: all subsequent phases

## What Phase 0 fixes

From the handoff dated 2026-04-12:

1. `touches` has no recipient email/LinkedIn URL; `send_touch()` passes the subject as `to_email` (broken)
2. `POST /api/campaign-lab/touches` missing — touches can't be queued via API
3. Approve/reject endpoints return `{"ok": true}` for nonexistent IDs (silent pass)
4. Legacy `outreach.py` draft generation doesn't use the `pitches` table
5. Public page title says "NOAH Edge Magazine" — should be "NOAH Edge Systems"
6. "Publication of prediction" pitch angle label is opaque — should be "Predictive publishing"
7. Runner doesn't touch Campaign Lab yet

Items 1–3 are the critical path. Items 4–7 are hygiene and can be done in the same session or deferred one session. This document covers all 7.

## Pre-flight

Before running any migration:

```bash
# Back up the DB
cd ~/noah-marketing-suite
cp data/marketing_suite.db "data/marketing_suite.db.backup-$(date +%Y%m%d-%H%M%S)"

# Verify current table counts (sanity check against handoff)
sqlite3 data/marketing_suite.db "SELECT 'accounts', COUNT(*) FROM accounts
UNION ALL SELECT 'contacts', COUNT(*) FROM contacts
UNION ALL SELECT 'touches', COUNT(*) FROM touches
UNION ALL SELECT 'pitches', COUNT(*) FROM pitches
UNION ALL SELECT 'routes', COUNT(*) FROM routes;"
```

Expected: `accounts=100, contacts=24, touches=0, pitches=12, routes=8`. If `touches > 0`, stop and tell the operator — the migration below drops and recreates that table and will need adjustment to preserve rows.

## Step 1 — SQL migration `005_phase0_prospects_and_touches.sql`

Save this as `~/noah-marketing-suite/migrations/005_phase0_prospects_and_touches.sql` and apply with `sqlite3 data/marketing_suite.db < migrations/005_phase0_prospects_and_touches.sql`.

> Note: this migration assumes `touches` has 0 rows (verified in the handoff). If non-zero at migration time, back up the row data first and re-insert after the recreate.

```sql
-- migrations/005_phase0_prospects_and_touches.sql
-- Phase 0: normalised prospects table and fixed touches schema
-- Assumes touches currently has 0 rows (verified pre-migration)

BEGIN TRANSACTION;

-- ---------------------------------------------------------------
-- 1. Prospects table
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prospects (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER,
    full_name     TEXT NOT NULL,
    first_name    TEXT,
    last_name     TEXT,
    role          TEXT,
    seniority     TEXT,                     -- 'c_level'|'vp'|'director'|'manager'|'ic'|'unknown'
    email         TEXT,
    email_status  TEXT DEFAULT 'unknown',   -- 'verified'|'risky'|'invalid'|'unknown'
    linkedin_url  TEXT,
    source        TEXT NOT NULL,            -- 'apollo'|'proxycurl'|'manual'|'similarweb'|'legacy_contact'
    source_ref    TEXT,                     -- external provider id, if any
    enriched_at   TIMESTAMP,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_prospects_account ON prospects(account_id);
CREATE INDEX IF NOT EXISTS idx_prospects_email   ON prospects(email);
CREATE INDEX IF NOT EXISTS idx_prospects_source  ON prospects(source);

-- ---------------------------------------------------------------
-- 2. Backfill prospects from legacy contacts
-- ---------------------------------------------------------------
-- Use whatever columns contacts actually has. Adjust SELECT if schema differs.
-- If contacts has different column names, run:
--     sqlite3 data/marketing_suite.db ".schema contacts"
-- and edit the SELECT accordingly before applying.
INSERT INTO prospects (
    account_id, full_name, first_name, last_name, role, email, linkedin_url,
    source, created_at
)
SELECT
    account_id,
    COALESCE(NULLIF(full_name, ''), TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')), 'Unknown'),
    first_name,
    last_name,
    role,
    email,
    linkedin_url,
    'legacy_contact',
    COALESCE(created_at, CURRENT_TIMESTAMP)
FROM contacts;

-- ---------------------------------------------------------------
-- 3. Rebuild touches with prospect_id, richer status, audit fields
-- ---------------------------------------------------------------
-- SAFETY: verify empty before dropping.
-- If you need to preserve rows, dump them to touches_legacy_backup first.

CREATE TABLE IF NOT EXISTS touches_new (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id      INTEGER NOT NULL,
    prospect_id      INTEGER NOT NULL,
    route_id         INTEGER NOT NULL,
    pitch_id         INTEGER NOT NULL,
    sequence_step    INTEGER NOT NULL DEFAULT 1,
    variables        TEXT,                 -- JSON blob of variable bindings
    rendered_subject TEXT,
    rendered_body    TEXT,
    status           TEXT NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued','approved','rejected','sending','sent','failed','replied','bounced')),
    status_reason    TEXT,
    queued_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at      TIMESTAMP,
    approved_by      TEXT,                 -- 'human:ivan' | 'noah' | etc
    sent_at          TIMESTAMP,
    external_id      TEXT,                 -- Smartlead / HeyReach message id, etc
    error_message    TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
    FOREIGN KEY (prospect_id) REFERENCES prospects(id),
    FOREIGN KEY (route_id)    REFERENCES routes(id),
    FOREIGN KEY (pitch_id)    REFERENCES pitches(id)
);

DROP TABLE IF EXISTS touches;
ALTER TABLE touches_new RENAME TO touches;

CREATE INDEX idx_touches_campaign ON touches(campaign_id);
CREATE INDEX idx_touches_status   ON touches(status);
CREATE INDEX idx_touches_prospect ON touches(prospect_id);
CREATE INDEX idx_touches_route    ON touches(route_id);
CREATE INDEX idx_touches_queued   ON touches(queued_at);

-- ---------------------------------------------------------------
-- 4. noah_notes — status feed for the dashboard (used in phase 1)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS noah_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    severity   TEXT NOT NULL DEFAULT 'info'  CHECK (severity IN ('info','warning','error','success')),
    text       TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'system',  -- 'system'|'noah'|'human'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_noah_notes_created ON noah_notes(created_at DESC);

COMMIT;

-- verify
SELECT 'prospects', COUNT(*) FROM prospects
UNION ALL SELECT 'touches', COUNT(*) FROM touches
UNION ALL SELECT 'noah_notes', COUNT(*) FROM noah_notes;
```

Expected verify output: `prospects=24, touches=0, noah_notes=0`.

## Step 2 — Python changes: `campaign_lab.py`

The new signatures for the affected functions. Replace the existing implementations.

```python
# campaign_lab.py — Phase 0 changes

import json
import sqlite3
from datetime import datetime
from typing import Optional

from adapters import get_adapter
from db import get_conn  # assume this exists — if not, use sqlite3.connect() directly


# ---------------------------------------------------------------
# queue_touch — now takes prospect_id and renders pitch up-front
# ---------------------------------------------------------------
def queue_touch(
    campaign_id: int,
    prospect_id: int,
    route_id: int,
    pitch_id: int,
    variables: Optional[dict] = None,
    sequence_step: int = 1,
) -> dict:
    """
    Queue a touch for approval. The touch is rendered at queue time so
    humans see the final copy in the approval queue, not a template.
    Status always starts as 'queued' — sending is a separate action.
    """
    variables = variables or {}
    conn = get_conn()
    try:
        cur = conn.cursor()

        # Validate referenced rows exist
        cur.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,))
        if not cur.fetchone():
            raise ValueError(f"campaign {campaign_id} not found")

        cur.execute("SELECT id, full_name, email, linkedin_url FROM prospects WHERE id = ?", (prospect_id,))
        prospect = cur.fetchone()
        if not prospect:
            raise ValueError(f"prospect {prospect_id} not found")

        cur.execute("SELECT id FROM routes WHERE id = ?", (route_id,))
        if not cur.fetchone():
            raise ValueError(f"route {route_id} not found")

        cur.execute("SELECT id, subject_template, body_template FROM pitches WHERE id = ?", (pitch_id,))
        pitch = cur.fetchone()
        if not pitch:
            raise ValueError(f"pitch {pitch_id} not found")

        # Render
        rendered = render_pitch(pitch_id, {
            "name": prospect[1].split()[0] if prospect[1] else "",
            "full_name": prospect[1] or "",
            **variables,
        })

        cur.execute("""
            INSERT INTO touches (
                campaign_id, prospect_id, route_id, pitch_id, sequence_step,
                variables, rendered_subject, rendered_body, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued')
        """, (
            campaign_id, prospect_id, route_id, pitch_id, sequence_step,
            json.dumps(variables),
            rendered["subject"],
            rendered["body"],
        ))
        touch_id = cur.lastrowid
        conn.commit()

        return {
            "id": touch_id,
            "status": "queued",
            "rendered_subject": rendered["subject"],
            "rendered_body": rendered["body"],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------
# approve_touch — returns proper errors for missing / wrong-state
# ---------------------------------------------------------------
class TouchNotFound(Exception): pass
class TouchWrongState(Exception): pass


def approve_touch(touch_id: int, approver: str = "human") -> dict:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, status FROM touches WHERE id = ?", (touch_id,))
        row = cur.fetchone()
        if not row:
            raise TouchNotFound(f"touch {touch_id} not found")
        if row[1] != "queued":
            raise TouchWrongState(f"touch {touch_id} is in status '{row[1]}', can only approve from 'queued'")

        cur.execute("""
            UPDATE touches
               SET status = 'approved', approved_at = ?, approved_by = ?
             WHERE id = ?
        """, (datetime.utcnow().isoformat(), approver, touch_id))
        conn.commit()
        return {"id": touch_id, "status": "approved"}
    finally:
        conn.close()


def reject_touch(touch_id: int, reason: str = "") -> dict:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, status FROM touches WHERE id = ?", (touch_id,))
        row = cur.fetchone()
        if not row:
            raise TouchNotFound(f"touch {touch_id} not found")
        if row[1] not in ("queued", "approved"):
            raise TouchWrongState(f"touch {touch_id} is in status '{row[1]}', cannot reject")

        cur.execute("""
            UPDATE touches
               SET status = 'rejected', status_reason = ?
             WHERE id = ?
        """, (reason, touch_id))
        conn.commit()
        return {"id": touch_id, "status": "rejected"}
    finally:
        conn.close()


def approve_touch_batch(touch_ids: list[int], approver: str = "human") -> dict:
    """Batch approve. Non-atomic — any individual failure is reported in 'failed'."""
    approved = []
    failed = []
    for tid in touch_ids:
        try:
            approve_touch(tid, approver=approver)
            approved.append(tid)
        except (TouchNotFound, TouchWrongState) as e:
            failed.append({"id": tid, "error": str(e)})
    return {"approved": approved, "failed": failed}


# ---------------------------------------------------------------
# send_touch — now JOINs prospects to get real recipient data
# ---------------------------------------------------------------
def send_touch(touch_id: int) -> dict:
    """
    Send a touch that has already been approved. Called by the local sender
    process, NOT by any agent or MCP tool. This function should not be exposed
    via an unauthenticated API endpoint — it triggers real outbound sends.
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT t.id, t.status, t.rendered_subject, t.rendered_body,
                   p.email, p.linkedin_url, p.full_name,
                   r.adapter, r.config
              FROM touches t
              JOIN prospects p ON p.id = t.prospect_id
              JOIN routes    r ON r.id = t.route_id
             WHERE t.id = ?
        """, (touch_id,))
        row = cur.fetchone()
        if not row:
            raise TouchNotFound(f"touch {touch_id} not found")
        (_, status, subject, body, email, linkedin_url, full_name, adapter_name, route_config_json) = row

        if status != "approved":
            raise TouchWrongState(f"touch {touch_id} is in status '{status}', must be 'approved' to send")

        route_config = json.loads(route_config_json) if route_config_json else {}
        adapter = get_adapter(adapter_name)

        # Mark sending
        cur.execute("UPDATE touches SET status = 'sending' WHERE id = ?", (touch_id,))
        conn.commit()

        # Dispatch
        try:
            result = adapter.send(
                to_email=email,
                to_linkedin=linkedin_url,
                to_name=full_name,
                subject=subject,
                body=body,
                route_config=route_config,
            )
            cur.execute("""
                UPDATE touches
                   SET status = 'sent',
                       sent_at = ?,
                       external_id = ?
                 WHERE id = ?
            """, (datetime.utcnow().isoformat(), result.external_id, touch_id))
            conn.commit()
            return {"id": touch_id, "status": "sent", "external_id": result.external_id}
        except Exception as e:
            cur.execute("""
                UPDATE touches
                   SET status = 'failed',
                       error_message = ?
                 WHERE id = ?
            """, (str(e), touch_id))
            conn.commit()
            raise
    finally:
        conn.close()
```

## Step 3 — Python changes: `assistant.py`

Add these routes. Patterns follow whatever the existing blueprint uses.

```python
# assistant.py — Phase 0 additions

from flask import request, jsonify
from campaign_lab import (
    queue_touch, approve_touch, reject_touch, approve_touch_batch,
    TouchNotFound, TouchWrongState,
)

# --- POST /api/campaign-lab/touches (NEW) ---
@app.route("/api/campaign-lab/touches", methods=["POST"])
def api_queue_touch():
    body = request.get_json() or {}
    required = ("campaign_id", "prospect_id", "route_id", "pitch_id")
    missing = [k for k in required if k not in body]
    if missing:
        return jsonify({"error": f"missing fields: {missing}"}), 400

    try:
        result = queue_touch(
            campaign_id=body["campaign_id"],
            prospect_id=body["prospect_id"],
            route_id=body["route_id"],
            pitch_id=body["pitch_id"],
            variables=body.get("variables"),
            sequence_step=body.get("sequence_step", 1),
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


# --- PATCH existing approve/reject to return proper errors ---
@app.route("/api/campaign-lab/touches/<int:touch_id>/approve", methods=["POST"])
def api_approve_touch(touch_id):
    try:
        return jsonify(approve_touch(touch_id, approver=request.json.get("approver", "human") if request.is_json else "human"))
    except TouchNotFound as e:
        return jsonify({"error": str(e)}), 404
    except TouchWrongState as e:
        return jsonify({"error": str(e)}), 409


@app.route("/api/campaign-lab/touches/<int:touch_id>/reject", methods=["POST"])
def api_reject_touch(touch_id):
    try:
        body = request.get_json() or {}
        return jsonify(reject_touch(touch_id, reason=body.get("reason", "")))
    except TouchNotFound as e:
        return jsonify({"error": str(e)}), 404
    except TouchWrongState as e:
        return jsonify({"error": str(e)}), 409


# --- POST /api/campaign-lab/touches/bulk-approve (NEW) ---
@app.route("/api/campaign-lab/touches/bulk-approve", methods=["POST"])
def api_bulk_approve_touches():
    body = request.get_json() or {}
    ids = body.get("ids", [])
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids must be a non-empty list"}), 400
    result = approve_touch_batch(ids, approver=body.get("approver", "human"))
    status = 200 if not result["failed"] else 207  # multi-status if any failed
    return jsonify(result), status


# --- GET /api/campaign-lab/prospects (NEW) ---
@app.route("/api/campaign-lab/prospects", methods=["GET"])
def api_list_prospects():
    limit  = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))
    q      = request.args.get("q", "").strip()

    conn = get_conn()
    try:
        cur = conn.cursor()
        if q:
            like = f"%{q}%"
            cur.execute("""
                SELECT id, full_name, role, email, linkedin_url, source, account_id
                  FROM prospects
                 WHERE full_name LIKE ? OR email LIKE ? OR role LIKE ?
                 ORDER BY created_at DESC
                 LIMIT ? OFFSET ?
            """, (like, like, like, limit, offset))
        else:
            cur.execute("""
                SELECT id, full_name, role, email, linkedin_url, source, account_id
                  FROM prospects
                 ORDER BY created_at DESC
                 LIMIT ? OFFSET ?
            """, (limit, offset))
        rows = cur.fetchall()
        return jsonify({
            "prospects": [
                {
                    "id": r[0], "full_name": r[1], "role": r[2], "email": r[3],
                    "linkedin_url": r[4], "source": r[5], "account_id": r[6],
                }
                for r in rows
            ],
            "limit": limit,
            "offset": offset,
        })
    finally:
        conn.close()
```

## Step 4 — Public guide page polish

On the Mac Mini:

```bash
cd ~/edge-intel
sed -i '' 's|NOAH Edge Magazine|NOAH Edge Systems|g' site/noah-marketing-suite/index.html
sed -i '' 's|Publication of prediction|Predictive publishing|g' site/noah-marketing-suite/index.html
source venv/bin/activate
python3 builder.py && python3 deploy.py
```

Then verify: `curl -s https://noah-edge.com/noah-marketing-suite/ | grep -E '(Systems|Predictive)'`.

## Step 5 — Legacy outreach.py pitch migration

Scope: make `~/noah-marketing-suite/outreach.py`'s draft generator use rows from the `pitches` table instead of its own internal templates. Don't rip out the legacy code paths — just switch the data source.

Implementation sketch:

1. Read the existing draft generator in `outreach.py`. Find where it chooses which template/copy to use.
2. Replace that lookup with `SELECT id, subject_template, body_template FROM pitches WHERE slug = ? AND status = 'active'`. Keep a `DEFAULT_PITCH_SLUG` constant for fallback.
3. When legacy code writes to `outreach_drafts`, also write the `pitch_id` it resolved.
4. The legacy UI keeps working — it reads from `outreach_drafts` as before — but now every draft is traceable to a row in `pitches`.

This is the lowest-friction migration path. Don't try to unify `outreach_drafts` and `touches` in Phase 0 — that's a Phase 4+ project.

## Step 6 — Runner integration (minimal)

In `~/noah-marketing-suite/runner.py`, add these two calls at the end of each hourly run:

```python
# Phase 0 addition — Campaign Lab metrics refresh
from campaign_lab import campaign_lab_summary, route_health

def phase0_runner_hook():
    summary  = campaign_lab_summary()
    health   = route_health()
    note_text = (
        f"Active campaigns: {summary['active_campaigns']}, "
        f"queued touches: {summary['queued_touches']}, "
        f"routes healthy: {health['healthy']}/{health['total']}"
    )
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO noah_notes (severity, text, source) VALUES (?, ?, ?)",
            ("info", note_text, "runner"),
        )
        conn.commit()
    finally:
        conn.close()
```

Add `phase0_runner_hook()` as the last call in the existing runner's main loop. If `route_health()` doesn't exist yet, stub it to return `{"healthy": 0, "total": 0}` — real health checks arrive in Phase 1.

## Step 7 — Kickstart + verify

```bash
# Restart the assistant service so new endpoints go live
launchctl kickstart -k gui/$(id -u)/com.noah.marketing-suite-assistant

# Sanity check the new endpoints
curl -s http://127.0.0.1:8114/api/campaign-lab/prospects | python3 -m json.tool | head -40

# Should show 24 prospects (backfilled from contacts)

# Test queue_touch via API (use real IDs from your DB)
curl -s -X POST http://127.0.0.1:8114/api/campaign-lab/touches \
  -H "Content-Type: application/json" \
  -d '{
    "campaign_id": 1,
    "prospect_id": 1,
    "route_id": 1,
    "pitch_id": 1
  }'
# Expect either 201 with the queued touch, or 404 for missing campaign_id=1 (no campaigns exist yet)

# Test approve on nonexistent touch
curl -s -X POST http://127.0.0.1:8114/api/campaign-lab/touches/99999/approve
# Expect 404 with {"error": "touch 99999 not found"}

# Test bulk approve on empty list
curl -s -X POST http://127.0.0.1:8114/api/campaign-lab/touches/bulk-approve \
  -H "Content-Type: application/json" -d '{"ids": []}'
# Expect 400 with {"error": "ids must be a non-empty list"}
```

## Exit criteria for Phase 0

Before moving to Phase 1, all of these must be true:

- [ ] `prospects` table exists and has 24 rows (or however many contacts were backfilled)
- [ ] `touches` table has the new schema including `prospect_id` column
- [ ] `noah_notes` table exists
- [ ] `POST /api/campaign-lab/touches` responds with 201 or 400/404, not 500
- [ ] `POST /api/campaign-lab/touches/<id>/approve` on nonexistent id returns 404 JSON
- [ ] `POST /api/campaign-lab/touches/<id>/approve` on wrong-state touch returns 409 JSON
- [ ] `POST /api/campaign-lab/touches/bulk-approve` works for happy and sad paths
- [ ] `GET /api/campaign-lab/prospects` returns the backfilled prospects
- [ ] `send_touch()` reads `prospects.email` correctly (inspect via a unit test or ad-hoc call — do NOT actually send in production unless you want to)
- [ ] Public page title says "NOAH Edge Systems" and the card says "Predictive publishing"
- [ ] Runner adds a note to `noah_notes` once per run
- [ ] Legacy `outreach.py` draft generation reads from `pitches` (verify by editing a pitch body and confirming a new legacy draft reflects the change)

When all boxes are ticked, post a status note to the next Mac session:

> Phase 0 complete. Moving to Phase 1 — read specs-v2/PHASE_1_DASHBOARD_SHELL.md.

## Rollback

If Phase 0 goes wrong:

```bash
cd ~/noah-marketing-suite
# Stop the assistant first
launchctl bootout gui/$(id -u)/com.noah.marketing-suite-assistant
# Restore DB
cp "data/marketing_suite.db.backup-<timestamp>" data/marketing_suite.db
# Revert code changes via git
git diff  # confirm what's changed
git checkout -- campaign_lab.py assistant.py runner.py outreach.py
# Restart
launchctl bootstrap gui/$(id -u)/ ~/Library/LaunchAgents/com.noah.marketing-suite-assistant.plist
```
