# Noah Marketing Suite — Specs V2

Generated: 2026-04-12
Branch: `claude/setup-noah-marketing-suite-wVWnz`
Status: **Supersedes parts of `~/noah-marketing-suite/specs/` v1** — read "Corrections from v1" below before using any of these.

## What this directory is

Planning and implementation specs for the next phase of Campaign Lab, incorporating the Managed Agents pivot and the corrections from the local-session review on 2026-04-12.

These are source-of-truth planning artefacts. The implementation lives at `~/noah-marketing-suite/` on the Mac Mini. When executing, copy these files into `~/noah-marketing-suite/specs-v2/` locally before starting a Mac session so everything lives in one place.

## Files (read in this order)

| # | File | What it is |
|---|---|---|
| 1 | `README.md` (this file) | Index + corrections + build order |
| 2 | `PHASE_0_POLISH.md` | **Copy-paste-ready** SQL migration + Python changes to unbreak the Campaign Lab send path. Must run first. |
| 3 | `PHASE_1_DASHBOARD_SHELL.md` | The operator UI tab for Campaign Lab — sections, routes, minimal first-build scope |
| 4 | `PHASE_2_API_KEYS_PANEL.md` | Local credentials vault (encrypted SQLite) + `/settings/api-keys` page spec |
| 5 | `PHASE_3_SIGNAL_INTEGRATIONS.md` | Similarweb + Proxycurl + Apollo REST + target-lists data model |
| 6 | `PHASE_4_MANAGED_AGENT.md` | Noah the managed-agent architecture. **Deferred** until Phases 0–3 are validated in production for at least 5 days. |

## Corrections from v1 (adopted from local-session review)

These corrections apply to everything written earlier in `~/noah-marketing-suite/specs/` and in the earlier planning conversation. If anything below contradicts v1, this document wins.

### 1. Local operator is the sole control plane for irreversible actions

**Wrong (v1 plan):** Relying on Anthropic's `permission_policy: always_ask` on the Smartlead MCP toolset to gate sends.

**Right:** MCP is for reads, searches, enrichment, and planning only. Every **write** (send, launch ad, record spend, log conversion) goes through a narrow **custom tool** defined on our side. Custom tools write to the local DB at `status='queued'` or `status='proposed'`. The local operator (not the agent) promotes those to `sent`/`committed` after human approval via the dashboard.

This keeps the audit trail, the daily caps, the rollback, and the approval workflow in a single, locally-owned place. Third-party MCP servers are treated as **semi-trusted infrastructure** — they're not our system boundary.

### 2. Custom tools are NOT governed by Anthropic permission policies

Verified in the Managed Agents docs: `Permission Policies control when server-executed tools (agent toolset + MCP) run automatically vs wait for approval. Does not apply to custom tools.`

This means gating custom tools is our responsibility. The approach is **tool-design-as-gate**: every write tool we expose lands the action at a non-live status (`queued`, `draft`, `proposed`). Moving to live status requires a separate action the agent can't take directly — a human clicks in the dashboard, or a human-approved chat command triggers a different endpoint.

### 3. No `query_local_db`. Narrow tools only.

**Wrong (v1 plan):** Exposing `query_local_db(sql)` as an agent tool.

**Right:** Expose specific, well-typed tools: `list_campaigns`, `get_campaign`, `list_pitches`, `get_pitch`, `list_target_lists`, `list_prospects_in_target`, `list_routes`, `list_approvals_queue`, `get_metrics`, `search_prospects`, `get_reply_context`, `queue_touch`, `draft_pitch_variant`, `propose_target_list`, `log_conversion`, `propose_spend`, `post_status_note`. See `PHASE_4_MANAGED_AGENT.md` for the full signatures.

Principle of least privilege. Also gives Claude clearer semantic affordances than raw SQL.

### 4. Apollo MCP is real

As of 2026-02-26, Apollo's Claude integration / MCP beta is documented in their knowledge base (`knowledge.apollo.io/hc/en-us/articles/43827318678541-Integrate-Apollo-with-Claude`). My earlier plan marked Apollo as "no confirmed MCP yet" based on a stale web-search snippet. Upgrading Apollo from Tier 3 custom-REST to Tier 2 MCP in Phase 4. Still using Apollo REST directly in Phase 3 because Phase 3 doesn't use the managed agent yet.

### 5. HTTP MCP over SSE

Where a vendor supports both, use HTTP MCP endpoints. SSE is marked deprecated in the Claude Code MCP docs. All MCP server configs in Phase 4 will use the HTTP Streamable transport.

### 6. Treat third-party MCPs as semi-trusted

Anthropic's security docs are explicit: third-party MCP servers are not audited or managed by Anthropic. This reinforces correction 1 — MCP is for reads, writes go through locally-controlled custom tools.

## Build order

**Ship Phases 0–3 first.** Run for at least 5 days in production with real campaigns. Inspect behaviour. Only then start Phase 4.

| Phase | What | Ships |
|---|---|---|
| 0 | Polish (prospects table, fix `send_touch`, `POST /touches`, 404/409 on approve/reject, legacy pitch migration, page title tweak) | Campaign Lab is unbroken |
| 1 | Dashboard shell — Overview, Routes, Pitches, Approvals pages | You can see the system through a UI |
| 2 | API keys panel — encrypted credentials vault, test/rotate UI | You can enter keys for every provider |
| 3 | Signal integrations — Similarweb, Proxycurl, Apollo REST, target lists | Target lists populate from real data; triggers fire |
| **—** | **VALIDATION PERIOD — run for 5+ days** | Learn what the data model feels like under load |
| 4 | Managed Agent — Noah, custom tools, MCP servers, chat UI, approval round-trip | Marketing-director-in-a-chat |
| 5+ | Paid ads, inbox, runner automation, reporting | See V1 plan for details |

## What to do next on the Mac Mini

When you open the next Mac session, start it with:

```
I'm continuing work on Noah Marketing Suite Campaign Lab Phase 0. 
Read ~/noah-marketing-suite/specs-v2/README.md and 
~/noah-marketing-suite/specs-v2/PHASE_0_POLISH.md before doing anything else.
Phase 0 is the critical unblocking work — follow the SQL migration and 
code changes exactly.
```

To get the specs onto the Mac, either:

1. **Pull from this branch on the Mac** — `cd ~/edge-intel && git fetch origin claude/setup-noah-marketing-suite-wVWnz && git checkout claude/setup-noah-marketing-suite-wVWnz -- noah-marketing-suite/specs-v2/` then copy them into the live project: `cp -r ~/edge-intel/noah-marketing-suite/specs-v2 ~/noah-marketing-suite/specs-v2`.
2. **Or** have the local session SSH-download the files via the raw GitHub URLs.

Option 1 keeps the specs version-controlled alongside the deployed guide page. Recommended.

## Ground rules

- **Noah never sends outreach.** The agent queues touches to `status='queued'`. Humans approve. A separate local sender process performs the actual send.
- **Noah never commits money.** The agent proposes spend at `status='proposed'`. Humans approve. A separate local committer triggers the platform API.
- **MCP = reads only.** Smartlead MCP, Apollo MCP, HubSpot MCP — all used for search, enrichment, analytics. Writes go through local custom tools that touch only the local DB.
- **Tool design is the gate.** Custom tools can't be gated by Anthropic's permission policies. They gate themselves by writing to non-live statuses.
- **Everything is reversible through Phase 3.** Only Phase 4 (managed agents) begins to involve non-local state (Anthropic vaults). Even there, vaults are for credentials only — no campaign data leaves local SQLite.
