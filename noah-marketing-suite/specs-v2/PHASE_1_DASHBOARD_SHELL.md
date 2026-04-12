# Phase 1 — Dashboard Shell

Status: ready to build once Phase 0 is complete
Prereq: Phase 0
Blocks: Phase 2

## Goal

Ship a functional Campaign Lab UI inside the operator at `http://127.0.0.1:8114/campaign-lab`. Read-only plus approve/reject. Matches the NOAH Edge design vocabulary (Playfair Display, Lato, Montserrat, `#0d7680` teal on `#FFF1E5` cream).

**Scope decision**: build only 4 pages in Phase 1. The rest arrive in later phases.

| Page | Phase 1? | Why |
|---|---|---|
| `/campaign-lab` (Overview) | Yes | Landing surface |
| `/campaign-lab/routes` | Yes | Visual health of sending infra |
| `/campaign-lab/pitches` | Yes | Browse + edit the 12 seeded pitches |
| `/campaign-lab/approvals` | Yes | The daily driver |
| `/campaign-lab/campaigns` | Phase 3 | Nothing to list until target lists exist |
| `/campaign-lab/prospects` | Phase 3 | Same |
| `/campaign-lab/target-lists` | Phase 3 | Same |
| `/campaign-lab/spend` | Phase 3 | Spend log is empty until campaigns run |
| `/campaign-lab/inbox` | Phase 5 | Needs Smartlead webhook handler |
| `/campaign-lab/chat` | Phase 4 | Needs managed agent |
| `/campaign-lab/paid-ads` | Phase 5 | Needs LinkedIn/Google Ads integration |
| `/campaign-lab/settings/api-keys` | Phase 2 | Its own phase |

## Tech choices

- **Backend**: Flask (existing). Add a new blueprint `campaign_lab_ui` under `~/noah-marketing-suite/assistant.py`.
- **Frontend**: server-rendered Jinja templates + vanilla JS `fetch()` calls. No build step. No React. HTMX optional for the approval queue if partial-refresh behaviour is desired.
- **Styling**: inline `<style>` in the base template copying the design tokens from `~/edge-intel/about/index.html` (see the list under "Design tokens" below).
- **State**: none. The page is a view of the DB. On approve/reject, fetch and re-render.

## File layout

```
~/noah-marketing-suite/
  templates/
    campaign_lab/
      base.html            # shared header, nav, footer, styles
      overview.html        # /campaign-lab
      routes.html          # /campaign-lab/routes
      pitches.html         # /campaign-lab/pitches
      pitch_detail.html    # /campaign-lab/pitches/<id>
      approvals.html       # /campaign-lab/approvals
  static/
    campaign_lab.css       # the design tokens, extracted (optional)
    campaign_lab.js        # fetch helpers, approve/reject handlers
```

If `templates/` doesn't exist yet, add `template_folder="templates"` to the Flask app init.

## Design tokens

Copy these into `base.html`'s `<style>` block — lifted from `site/about/index.html`:

```css
:root {
  --white: #FFFFFF;
  --off: #F7F7F5;
  --cream: #FFF1E5;
  --ink: #1A1A1A;
  --ink-soft: #2D3748;
  --muted: #4B5563;
  --light: #6B7280;
  --rule: #E5E5E5;
  --teal: #0d7680;
  --teal-dark: #0a5c64;
  --teal-light: #e8f4f5;
  --teal-mist: #f0f9fa;
  --green: #16a34a;
  --amber: #d97706;
  --red: #dc2626;
  --max-width: 1200px;
}
body {
  font-family: 'Lato', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--cream);
  color: var(--ink);
}
h1, h2, h3 { font-family: 'Playfair Display', serif; font-weight: 900; }
.eyebrow { font-family: 'Montserrat', sans-serif; font-weight: 800;
           font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase;
           color: var(--teal); }
```

Load Google Fonts in `<head>`:

```html
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Lato:wght@400;700;900&family=Montserrat:wght@700;800&display=swap" rel="stylesheet">
```

## Navigation

Top nav lives in `base.html`, sticky at top, ~60px tall:

```
[NOAH  edge | Systems]                                                           [Overview] [Routes] [Pitches] [Approvals] [Settings]
```

Brand links back to `/sandbox/` (the Systems page you maintain on noah-edge.com — but for the local operator link it to `http://127.0.0.1:8114/`).

## Page specs

### 1. `/campaign-lab` Overview

**Top row — four stat tiles:**
| Tile | Calculation | Source |
|---|---|---|
| Active campaigns | `COUNT(*) FROM campaigns WHERE status='active'` | `GET /api/campaign-lab/summary` |
| Queued touches | `COUNT(*) FROM touches WHERE status='queued'` | same |
| Sent today | `COUNT(*) FROM touches WHERE status='sent' AND DATE(sent_at)=DATE('now')` | same |
| Spend today | `SUM(amount) FROM spend_log WHERE DATE(logged_at)=DATE('now')` | same |

**Middle — route health strip:** 8 pills (one per route). Each pill shows `{route_name} — {status_dot} — {sends_today}/{daily_cap}`. Green dot = healthy, amber = degraded, red = down. Pull from `GET /api/campaign-lab/routes/health` (already exists).

**Below — two-column layout:**
- Left col: "Recent activity" — last 20 rows from `noah_notes` ordered by `created_at DESC`.
- Right col: "Approval queue preview" — top 5 rows from `/api/campaign-lab/touches?status=queued&limit=5` with a "Review all →" link.

**Bottom footer row:** a greeting line reading `"Noah Marketing Suite — Mac Mini — last runner tick: <X> min ago"`.

### 2. `/campaign-lab/routes`

Table with columns: Name, Adapter, Status, Sends Today, Daily Cap, Last Send, Last Error. One row per route (8 seeded). `routes.status` comes from the existing `route_health()` function; everything else is a direct DB read.

Click row → opens a drawer with the full `routes.config` JSON (pretty-printed) and a "test send" button that calls a new `POST /api/campaign-lab/routes/<id>/test` endpoint. **Test send uses a hardcoded test prospect (`prospects.source = 'test'`), not a real lead**, and goes through `send_touch()` end-to-end so it validates the entire chain. Adding the test prospect is a Phase 1 migration step:

```sql
-- Run once when implementing Phase 1
INSERT INTO prospects (full_name, email, source)
VALUES ('Noah Test Prospect', 'noahtest+test@noahwire.com', 'test');
```

### 3. `/campaign-lab/pitches`

Grid of cards, 3 columns. One card per pitch (12 seeded):
- Eyebrow: pitch `category` (or slug prefix)
- Title: the pitch label (human-readable)
- Body preview: first 140 chars of `body_template`
- Footer row: variables count, last used date, "Edit" button

Click Edit → `/campaign-lab/pitches/<id>` detail page.

**Pitch detail page:**
- Subject template (editable)
- Body template (editable, textarea)
- Variables list (read-only, extracted from `{{...}}` in the body)
- Version history (read-only — Phase 1 just shows `updated_at`)
- "Save" writes via `PATCH /api/campaign-lab/pitches/<id>` (new endpoint — add it in this phase)
- "Preview render" uses variables from a test prospect to preview the final copy

**Add endpoint:**

```python
@app.route("/api/campaign-lab/pitches/<int:pitch_id>", methods=["PATCH"])
def api_update_pitch(pitch_id):
    body = request.get_json() or {}
    fields = {k: v for k, v in body.items() if k in ("subject_template", "body_template", "label", "category")}
    if not fields:
        return jsonify({"error": "no editable fields"}), 400
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [pitch_id]
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE pitches SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", params)
        if cur.rowcount == 0:
            return jsonify({"error": f"pitch {pitch_id} not found"}), 404
        conn.commit()
        cur.execute("SELECT id, slug, label, subject_template, body_template, category, updated_at FROM pitches WHERE id = ?", (pitch_id,))
        row = cur.fetchone()
        return jsonify(dict(zip(
            ("id","slug","label","subject_template","body_template","category","updated_at"), row
        )))
    finally:
        conn.close()
```

### 4. `/campaign-lab/approvals`

The daily driver. Needs to be fast.

**Top bar:** filters — all / by campaign / by route / by pitch. Batch actions: Approve all visible, Reject all visible.

**List:** one card per queued touch. Each card:
- Header: `{campaign name} · {route name} · {queued timestamp}`
- Recipient: `{prospect full_name} — {role} at {account name}` ({email} · {linkedin_url link})
- Subject: `{rendered_subject}`
- Body: `{rendered_body}` (monospace, scroll if > 12 lines)
- Variables (collapsed by default)
- Actions row: [Approve] [Reject] [Edit in chat] (Phase 4 for Edit)

**JS behaviour:** approve/reject calls `POST /api/campaign-lab/touches/<id>/approve|reject`. On 200, the card fades and is removed. On 404/409, the card shows an inline error and stays.

**Bulk approve:** select checkboxes → click "Approve 14 selected" → `POST /api/campaign-lab/touches/bulk-approve` with the ids array → re-fetch the page data.

Recommended max page size: 20. Paginate via `?offset=N`.

## Shared JS helpers (`static/campaign_lab.js`)

```javascript
// Minimal fetch wrapper
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

async function approveTouch(id) {
  const r = await api('POST', `/api/campaign-lab/touches/${id}/approve`);
  if (!r.ok) alert(`Approve failed (${r.status}): ${r.data.error || 'unknown'}`);
  return r.ok;
}

async function rejectTouch(id, reason) {
  const r = await api('POST', `/api/campaign-lab/touches/${id}/reject`, { reason });
  if (!r.ok) alert(`Reject failed (${r.status}): ${r.data.error || 'unknown'}`);
  return r.ok;
}

async function bulkApprove(ids) {
  const r = await api('POST', '/api/campaign-lab/touches/bulk-approve', { ids });
  if (!r.ok && r.status !== 207) {
    alert(`Bulk approve failed (${r.status})`);
    return false;
  }
  if (r.data.failed?.length) {
    alert(`${r.data.approved.length} approved, ${r.data.failed.length} failed`);
  }
  return true;
}
```

## Flask blueprint

```python
# assistant.py — Phase 1 additions
from flask import render_template

@app.route("/campaign-lab")
def cl_overview():
    summary = campaign_lab_summary()
    return render_template("campaign_lab/overview.html", summary=summary)

@app.route("/campaign-lab/routes")
def cl_routes():
    routes = list_routes()
    health = route_health()
    return render_template("campaign_lab/routes.html", routes=routes, health=health)

@app.route("/campaign-lab/pitches")
def cl_pitches():
    pitches = list_pitches()
    return render_template("campaign_lab/pitches.html", pitches=pitches)

@app.route("/campaign-lab/pitches/<int:pitch_id>")
def cl_pitch_detail(pitch_id):
    pitch = get_pitch(pitch_id)
    if not pitch:
        return "Pitch not found", 404
    return render_template("campaign_lab/pitch_detail.html", pitch=pitch)

@app.route("/campaign-lab/approvals")
def cl_approvals():
    # Page uses JS to load data; template just renders the shell
    return render_template("campaign_lab/approvals.html")
```

## Exit criteria for Phase 1

- [ ] All four pages load without server errors
- [ ] Overview shows live counts from the DB (matching `GET /api/campaign-lab/summary`)
- [ ] Routes page shows 8 rows, each with a health dot
- [ ] Pitches page shows 12 cards; clicking one opens the detail page; editing and saving persists
- [ ] Approvals page loads queued touches (or shows "No touches in queue" when empty)
- [ ] Approve/reject buttons work and update the UI
- [ ] Bulk approve works
- [ ] Test prospect exists and `POST /api/campaign-lab/routes/<id>/test` sends end-to-end for at least one route without error
- [ ] Design looks like a NOAH Edge systems page, not a Bootstrap admin

## What's NOT in Phase 1

- Campaign CRUD — Phase 3
- Target list builder — Phase 3
- Chat interface — Phase 4
- Spend dashboard — Phase 3 (but only if a campaign has actually sent something)
- Inbox / reply handling — Phase 5
- API keys panel — Phase 2 (next)
