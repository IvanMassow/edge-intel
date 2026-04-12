# Phase 3 — Signal Integrations & Target Lists

Status: ready to build once Phase 2 is complete
Prereq: Phases 0, 1, 2
Blocks: Phase 4 (managed agent needs real target lists to be useful)

## Goal

Wire up the three data sources that make Noah Wire's outbound specifically good: Similarweb (traffic-drop trigger), Proxycurl (LinkedIn role lookup), Apollo REST (lead data). Add the `target_lists` data model and the signal-processing runner jobs. End state: a target list like "UK B2B trade publishers with organic traffic down >20% YoY, head-of-audience role" can be built, refreshed, and used to queue touches.

**All integrations in Phase 3 use direct REST APIs and the local credentials vault.** Phase 4 swaps Apollo and Smartlead to MCP once the managed agent is up, but Phase 3 deliberately uses REST so we can ship and test without depending on the agent layer.

## Data model: `007_phase3_target_lists.sql`

```sql
CREATE TABLE IF NOT EXISTS target_lists (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    description       TEXT,
    source            TEXT NOT NULL,   -- 'similarweb_traffic_drop'|'proxycurl_role'|'apollo_search'|'manual'
    filter_json       TEXT NOT NULL,   -- JSON blob, schema per source
    status            TEXT NOT NULL DEFAULT 'draft',  -- 'draft'|'active'|'archived'
    last_refreshed_at TIMESTAMP,
    row_count         INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS target_list_members (
    target_list_id INTEGER NOT NULL,
    prospect_id    INTEGER NOT NULL,
    added_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reason         TEXT,                -- why this prospect matched the filter
    PRIMARY KEY (target_list_id, prospect_id),
    FOREIGN KEY (target_list_id) REFERENCES target_lists(id) ON DELETE CASCADE,
    FOREIGN KEY (prospect_id)    REFERENCES prospects(id)    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_target_members_list ON target_list_members(target_list_id);

-- signal cache so we don't re-query the same thing every hour
CREATE TABLE IF NOT EXISTS signal_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    key         TEXT NOT NULL,           -- e.g., 'similarweb:tradewinds.com:2026-03'
    payload     TEXT NOT NULL,           -- JSON response
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP,
    UNIQUE(source, key)
);

CREATE INDEX IF NOT EXISTS idx_signal_cache_expires ON signal_cache(expires_at);
```

## Signal modules

Folder layout:

```
~/noah-marketing-suite/signals/
  __init__.py
  base.py           # signal result dataclass + cache helper
  similarweb.py
  proxycurl.py
  apollo.py
```

### `signals/base.py`

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
import json

from db import get_conn


@dataclass
class SignalResult:
    source: str
    key: str
    payload: dict
    fetched_at: datetime
    cached: bool = False


def cache_get(source: str, key: str, max_age: timedelta) -> Optional[dict]:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT payload, fetched_at
              FROM signal_cache
             WHERE source = ? AND key = ?
               AND fetched_at > datetime('now', ?)
        """, (source, key, f"-{int(max_age.total_seconds())} seconds"))
        row = cur.fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


def cache_put(source: str, key: str, payload: dict, ttl: timedelta) -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO signal_cache (source, key, payload, expires_at)
            VALUES (?, ?, ?, datetime('now', ?))
            ON CONFLICT(source, key) DO UPDATE SET
                payload = excluded.payload,
                fetched_at = CURRENT_TIMESTAMP,
                expires_at = excluded.expires_at
        """, (source, key, json.dumps(payload), f"+{int(ttl.total_seconds())} seconds"))
        conn.commit()
    finally:
        conn.close()
```

### `signals/similarweb.py`

```python
from datetime import datetime, timedelta
from typing import Optional
import requests

from credentials import get_credential
from signals.base import cache_get, cache_put


API_ROOT = "https://api.similarweb.com/v1"
CACHE_TTL = timedelta(days=7)   # traffic data doesn't change fast


class SimilarwebError(Exception):
    pass


def get_monthly_visits(domain: str, year_month: str) -> Optional[dict]:
    """
    year_month format: 'YYYY-MM' (e.g., '2026-02')
    Returns Similarweb's monthly traffic payload or None if unavailable.
    """
    cache_key = f"visits:{domain}:{year_month}"
    cached = cache_get("similarweb", cache_key, CACHE_TTL)
    if cached:
        return cached

    api_key = get_credential("similarweb")
    if not api_key:
        raise SimilarwebError("similarweb credential not set")

    r = requests.get(
        f"{API_ROOT}/website/{domain}/total-traffic-and-engagement/visits",
        params={
            "api_key": api_key,
            "start_date": year_month,
            "end_date": year_month,
            "country": "world",
            "granularity": "monthly",
            "main_domain_only": "false",
        },
        timeout=15,
    )
    if r.status_code == 404:
        return None  # domain not in Similarweb's index
    if r.status_code != 200:
        raise SimilarwebError(f"similarweb HTTP {r.status_code}: {r.text[:200]}")

    data = r.json()
    cache_put("similarweb", cache_key, data, CACHE_TTL)
    return data


def detect_traffic_drop(domain: str, min_drop_pct: float = 20.0) -> Optional[dict]:
    """
    Compare this-month-last-year vs this-month. Return a signal dict if the
    domain has dropped by more than min_drop_pct percent YoY.
    """
    now = datetime.utcnow()
    current_month = f"{now.year:04d}-{max(1, now.month - 1):02d}"    # last complete month
    year_ago      = f"{now.year - 1:04d}-{max(1, now.month - 1):02d}"

    try:
        cur_data  = get_monthly_visits(domain, current_month)
        past_data = get_monthly_visits(domain, year_ago)
    except SimilarwebError:
        return None

    if not cur_data or not past_data:
        return None

    cur_visits  = _extract_visits(cur_data)
    past_visits = _extract_visits(past_data)
    if past_visits == 0:
        return None

    drop_pct = ((past_visits - cur_visits) / past_visits) * 100
    if drop_pct < min_drop_pct:
        return None

    return {
        "domain": domain,
        "drop_pct": round(drop_pct, 1),
        "current_visits": cur_visits,
        "past_visits": past_visits,
        "current_month": current_month,
        "year_ago": year_ago,
    }


def _extract_visits(data: dict) -> int:
    """Pull the total visits number out of Similarweb's payload shape."""
    try:
        series = data.get("visits") or []
        if not series:
            return 0
        return int(series[-1].get("visits", 0))
    except Exception:
        return 0
```

### `signals/proxycurl.py`

```python
from datetime import timedelta
import requests

from credentials import get_credential
from signals.base import cache_get, cache_put


API_ROOT = "https://nubela.co/proxycurl/api/v2"
CACHE_TTL = timedelta(days=30)


class ProxycurlError(Exception):
    pass


def find_person_by_company_and_role(company_domain: str, role_keywords: list[str]) -> list[dict]:
    """
    Search for people at a company whose role matches one of role_keywords.
    Uses Proxycurl's /linkedin/company/employee/search endpoint.
    """
    key = get_credential("proxycurl")
    if not key:
        raise ProxycurlError("proxycurl credential not set")

    cache_key = f"employees:{company_domain}:{'|'.join(sorted(role_keywords))}"
    cached = cache_get("proxycurl", cache_key, CACHE_TTL)
    if cached:
        return cached.get("employees", [])

    # Role regex joined with | for OR
    role_regex = "(?i)(" + "|".join(role_keywords) + ")"

    r = requests.get(
        f"{API_ROOT}/linkedin/company/employee/search",
        headers={"Authorization": f"Bearer {key}"},
        params={
            "linkedin_company_profile_url": f"https://www.linkedin.com/company/{company_domain}",
            "keyword_regex": role_regex,
            "page_size": 25,
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise ProxycurlError(f"proxycurl HTTP {r.status_code}: {r.text[:200]}")

    data = r.json()
    employees = data.get("employees", [])
    cache_put("proxycurl", cache_key, {"employees": employees}, CACHE_TTL)
    return employees
```

Note: Proxycurl's exact endpoint shape may differ — verify against their current docs before shipping. The module signature is correct; the internal URL may need adjusting.

### `signals/apollo.py`

```python
from datetime import timedelta
import requests

from credentials import get_credential
from signals.base import cache_get, cache_put


API_ROOT = "https://api.apollo.io/v1"
CACHE_TTL = timedelta(days=14)


class ApolloError(Exception):
    pass


def search_people(filters: dict, limit: int = 50) -> list[dict]:
    """
    Search Apollo for people matching filters.
    Filters dict supports: q_organization_domains, person_titles, person_seniorities,
    organization_num_employees_ranges, page, per_page.
    """
    key = get_credential("apollo")
    if not key:
        raise ApolloError("apollo credential not set")

    cache_key = f"people_search:{hash(frozenset(str((k, v)) for k, v in filters.items()))}:{limit}"
    cached = cache_get("apollo", cache_key, CACHE_TTL)
    if cached:
        return cached.get("people", [])

    body = {**filters, "per_page": min(limit, 100)}
    r = requests.post(
        f"{API_ROOT}/mixed_people/search",
        headers={
            "X-Api-Key": key,
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        },
        json=body,
        timeout=30,
    )
    if r.status_code != 200:
        raise ApolloError(f"apollo HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    people = data.get("people", [])
    cache_put("apollo", cache_key, {"people": people}, CACHE_TTL)
    return people


def enrich_person(email: str) -> dict | None:
    """Enrich a single person by email. Returns None if not found."""
    key = get_credential("apollo")
    if not key:
        raise ApolloError("apollo credential not set")

    r = requests.post(
        f"{API_ROOT}/people/match",
        headers={"X-Api-Key": key, "Content-Type": "application/json"},
        json={"email": email},
        timeout=15,
    )
    if r.status_code == 200:
        return r.json().get("person")
    return None
```

**Apollo's MCP is now available** (per the corrections in `README.md`). We still use REST in Phase 3 because Phase 3 runs without a managed agent. Phase 4 will wrap Apollo as an MCP tool instead, and the managed agent will call the MCP directly — the REST module above becomes a dead-letter fallback for the local runner only.

## Target list builder module

```python
# ~/noah-marketing-suite/target_lists.py
import json
from typing import Optional

from db import get_conn
from signals.similarweb import detect_traffic_drop
from signals.proxycurl import find_person_by_company_and_role
from signals.apollo import search_people


def create_target_list(name: str, source: str, filter_json: dict, description: str = "") -> int:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO target_lists (name, description, source, filter_json, status)
            VALUES (?, ?, ?, ?, 'draft')
        """, (name, description, source, json.dumps(filter_json)))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def refresh_target_list(target_list_id: int) -> dict:
    """Pull fresh members for a target list based on its source + filter."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT source, filter_json FROM target_lists WHERE id = ?", (target_list_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"target_list {target_list_id} not found")
        source, filter_json = row[0], json.loads(row[1])

        if source == "similarweb_traffic_drop":
            members = _refresh_traffic_drop(filter_json)
        elif source == "apollo_search":
            members = _refresh_apollo_search(filter_json)
        elif source == "proxycurl_role":
            members = _refresh_proxycurl_role(filter_json)
        else:
            raise ValueError(f"unknown source {source}")

        # Upsert prospects + link to target list
        cur.execute("DELETE FROM target_list_members WHERE target_list_id = ?", (target_list_id,))
        for m in members:
            prospect_id = _upsert_prospect(cur, m)
            cur.execute("""
                INSERT OR IGNORE INTO target_list_members (target_list_id, prospect_id, reason)
                VALUES (?, ?, ?)
            """, (target_list_id, prospect_id, m.get("reason", "")))

        cur.execute("""
            UPDATE target_lists
               SET last_refreshed_at = CURRENT_TIMESTAMP,
                   row_count = (SELECT COUNT(*) FROM target_list_members WHERE target_list_id = ?)
             WHERE id = ?
        """, (target_list_id, target_list_id))
        conn.commit()

        cur.execute("SELECT row_count FROM target_lists WHERE id = ?", (target_list_id,))
        count = cur.fetchone()[0]
        return {"target_list_id": target_list_id, "row_count": count}
    finally:
        conn.close()


def _refresh_apollo_search(filters: dict) -> list[dict]:
    people = search_people(filters.get("apollo_filters", {}), limit=filters.get("limit", 50))
    out = []
    for p in people:
        out.append({
            "full_name": p.get("name"),
            "first_name": p.get("first_name"),
            "last_name": p.get("last_name"),
            "email": p.get("email"),
            "linkedin_url": p.get("linkedin_url"),
            "role": p.get("title"),
            "seniority": p.get("seniority"),
            "source": "apollo",
            "source_ref": p.get("id"),
            "account_domain": (p.get("organization") or {}).get("primary_domain"),
            "reason": "apollo_search match",
        })
    return out


def _refresh_traffic_drop(filters: dict) -> list[dict]:
    """
    Filter shape: {"domains": [...], "min_drop_pct": 20, "role_keywords": ["head of audience", ...]}
    """
    domains       = filters.get("domains", [])
    min_drop      = filters.get("min_drop_pct", 20.0)
    role_keywords = filters.get("role_keywords", ["head of audience", "editor in chief"])

    matched = []
    for domain in domains:
        signal = detect_traffic_drop(domain, min_drop_pct=min_drop)
        if not signal:
            continue
        # For each dropped domain, look up the target role via Proxycurl
        try:
            people = find_person_by_company_and_role(domain, role_keywords)
        except Exception:
            people = []
        for p in people:
            matched.append({
                "full_name": p.get("full_name"),
                "email": p.get("work_email"),
                "linkedin_url": p.get("profile_url"),
                "role": p.get("title"),
                "source": "similarweb",
                "account_domain": domain,
                "reason": f"traffic -{signal['drop_pct']}% YoY",
            })
    return matched


def _refresh_proxycurl_role(filters: dict) -> list[dict]:
    # Left as an exercise in Phase 3 if you need a pure-Proxycurl list
    return []


def _upsert_prospect(cur, member: dict) -> int:
    # Try to find by email first
    email = member.get("email")
    if email:
        cur.execute("SELECT id FROM prospects WHERE email = ?", (email,))
        row = cur.fetchone()
        if row:
            return row[0]

    cur.execute("""
        INSERT INTO prospects
            (full_name, first_name, last_name, role, email, linkedin_url, source, source_ref, enriched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (
        member.get("full_name", "Unknown"),
        member.get("first_name"),
        member.get("last_name"),
        member.get("role"),
        email,
        member.get("linkedin_url"),
        member.get("source", "unknown"),
        member.get("source_ref"),
    ))
    return cur.lastrowid
```

## API endpoints

```python
# assistant.py — Phase 3 additions
from target_lists import create_target_list, refresh_target_list

@app.route("/api/campaign-lab/target-lists", methods=["GET"])
def api_list_target_lists():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, description, source, filter_json, status,
                   last_refreshed_at, row_count, created_at
              FROM target_lists
             ORDER BY created_at DESC
        """)
        return jsonify({
            "target_lists": [
                {
                    "id": r[0], "name": r[1], "description": r[2],
                    "source": r[3], "filter_json": json.loads(r[4]),
                    "status": r[5], "last_refreshed_at": r[6],
                    "row_count": r[7], "created_at": r[8],
                }
                for r in cur.fetchall()
            ]
        })
    finally:
        conn.close()


@app.route("/api/campaign-lab/target-lists", methods=["POST"])
def api_create_target_list():
    body = request.get_json() or {}
    tlid = create_target_list(
        name=body["name"],
        source=body["source"],
        filter_json=body.get("filter_json", {}),
        description=body.get("description", ""),
    )
    return jsonify({"id": tlid, "status": "draft"}), 201


@app.route("/api/campaign-lab/target-lists/<int:tlid>/refresh", methods=["POST"])
def api_refresh_target_list(tlid):
    try:
        return jsonify(refresh_target_list(tlid))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.route("/api/campaign-lab/target-lists/<int:tlid>/members", methods=["GET"])
def api_target_list_members(tlid):
    limit = min(int(request.args.get("limit", 50)), 500)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.full_name, p.role, p.email, p.linkedin_url, p.account_id,
                   tlm.reason, tlm.added_at
              FROM target_list_members tlm
              JOIN prospects p ON p.id = tlm.prospect_id
             WHERE tlm.target_list_id = ?
             ORDER BY tlm.added_at DESC
             LIMIT ?
        """, (tlid, limit))
        return jsonify({
            "target_list_id": tlid,
            "members": [
                {
                    "id": r[0], "full_name": r[1], "role": r[2], "email": r[3],
                    "linkedin_url": r[4], "account_id": r[5],
                    "reason": r[6], "added_at": r[7],
                }
                for r in cur.fetchall()
            ],
        })
    finally:
        conn.close()
```

## UI additions

Add a `/campaign-lab/target-lists` page and a `/campaign-lab/target-lists/<id>` detail page. List view columns: Name, Source, Row count, Last refresh, Status. Detail view: metadata up top, "Refresh" button, members table below.

Also add a "Create target list" modal with three source templates:

1. **Similarweb traffic-drop trigger**
   - Input: a list of domains (paste-in)
   - Minimum drop %
   - Target role keywords
2. **Apollo search**
   - Filters UI: titles, seniority, industries, countries, employee count ranges
3. **Manual upload**
   - CSV with columns `full_name, email, role, linkedin_url, company_domain`

Keep the UI minimal — source templates produce a `filter_json`, which is just a form serialisation.

## Runner integration

Extend the Phase 0 runner hook:

```python
# runner.py — Phase 3 extension
from target_lists import refresh_target_list

def phase3_runner_hook():
    """Refresh any active target lists that haven't been refreshed in >24h."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name FROM target_lists
             WHERE status = 'active'
               AND (last_refreshed_at IS NULL OR last_refreshed_at < datetime('now', '-24 hours'))
        """)
        stale = cur.fetchall()
    finally:
        conn.close()

    for tl_id, name in stale:
        try:
            result = refresh_target_list(tl_id)
            _note(f"target list '{name}' refreshed: {result['row_count']} members")
        except Exception as e:
            _note(f"target list '{name}' refresh FAILED: {e}", severity="error")


def _note(text: str, severity: str = "info") -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO noah_notes (severity, text, source) VALUES (?, ?, ?)",
            (severity, text, "runner"),
        )
        conn.commit()
    finally:
        conn.close()
```

Call `phase3_runner_hook()` in the main runner loop, after `phase0_runner_hook()`.

## Cost budget during Phase 3

These are the main cost centres:

| Provider | Typical Phase 3 usage | Rough monthly cost |
|---|---|---|
| Similarweb API | 100 domains × 2 lookups/week, 7-day cache | $50–150 (scales with plan) |
| Proxycurl | ~20 role lookups/day, cached 30 days | $30–50 (pay per credit) |
| Apollo | 2–5 person searches/day, cached 14 days | within the $99/mo Pro tier |

**Build a cost-per-day ticker into the runner** that counts API calls across the three providers and adds a daily note to `noah_notes`. Prevents runaway spend if a filter goes haywire.

## Exit criteria

- [ ] `target_lists`, `target_list_members`, `signal_cache` tables exist
- [ ] All three signal modules import and run
- [ ] Credentials for at least Apollo + Similarweb are set in Phase 2's vault
- [ ] You can create a target list via the UI
- [ ] You can refresh a target list and see real members appear
- [ ] The traffic-drop trigger returns ≥1 match against a test list of 20 known-dropping B2B publishers
- [ ] Apollo search returns a valid response for a test filter
- [ ] Runner adds 24h-refresh notes when a target list is stale
- [ ] Signal cache reduces API calls on repeat queries (verify by inspecting `signal_cache` counts after a second run)

## Validation period

Once Phase 3 exits, run the system for at least 5 days before starting Phase 4. What you're looking for:

1. **Signal quality** — does the traffic-drop trigger surface publishers that are actually plausible targets? If it surfaces junk, the filter needs tuning or the Similarweb plan isn't returning useful data.
2. **Prospect freshness** — do Apollo and Proxycurl return emails that are actually deliverable? Bounce rate >10% on test sends means the enrichment data is stale.
3. **Approval queue volume** — is the human (you) able to review everything the system queues? If the queue backs up >50 touches, the system is queuing too fast — slow the runner.
4. **Failure modes** — which API fails most? Which costs the most? This informs whether to swap providers or cache harder.

Only start Phase 4 once all four questions have clear answers.
