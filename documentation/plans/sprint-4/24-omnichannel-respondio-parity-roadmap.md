# 24 - Omnichannel: respond.io parity program (gap analysis + slice roadmap)

> **Status:** ROADMAP AGREED 2026-09-05 (two grill rounds, every question closed, see §5) - the program document. Each phase below becomes its own UAC + plan
> pair (`documentation/plans/sprint-4/<NN>-<slice>-acceptance-criteria.md` then `<NN>-<slice>.md`)
> before any code. This file is the map, not the contract.
> **Goal:** migrate one customer fully off respond.io onto the Foundryx omnichannel Service.
> **Source:** survey of the respond.io sandbox (space `467434`, org `459229`, Growth-plan trial)
> on 2026-09-05. Evidence: `24-evidence/respondio-survey/` (screenshots + README).
> **Caveat:** the sandbox had **no channel connected**, so the live conversation view (composer,
> contact side panel, snooze/close dialogs) was not observed - those rows are marked `(docs)`
> and must be re-verified once a channel is connected to the sandbox.
> **Relates to:** plan 23 (design-language alignment - the UI restructure in flight),
> BL-128 (respond.io-style conversation automation - superseded by Phase A5 here),
> BL-018 (additional channel adapters), BL-SS-014 (membership-scoped reads).

## 1. respond.io surface inventory (as surveyed)

Left rail: Onboarding checklist, Dashboard, Inbox, Contacts, AI Agents, Broadcasts, Workflows,
Reports, Settings (workspace). Bottom rail: global search, support, notifications, avatar, AI
Copilot. Top-left workspace switcher (org may have many workspaces; org-level settings separate).

| Area | What respond.io shows |
|---|---|
| **Dashboard** | Lifecycle stage tiles (count, %, open/assigned/unassigned per stage), Contacts tabs (Open / Assigned / Unassigned), Team Members online list (status filter, "assigned to N contacts", since), Conversations opened vs closed chart (last 14 days selector), links to Reports / Broadcasts. Workspace timezone shown. |
| **Inbox** | Views: All / Mine / Collaborations / Unassigned / Incoming Calls; **Lifecycle** views (one per stage); **Team Inbox** (per team); **Custom Inbox** (saved advanced filter). List header: Chats / Calls tabs, filter `Show: All / Open / Closed / Snoozed` + `Sort: Newest / Oldest / Longest Open / Shortest Open`, **Unreplied** toggle, **Advanced filters** (Contact Field / Collaborators / ... with `has any of`, filter groups, "Save as Custom Inbox"). Conversation (docs): assign to user / team / AI agent, close with closing notes + category, snooze, collaborators via @mention, internal comments, snippets via `/`, AI Assist reply, AI Prompts (tone / translate / grammar / simplify), contact side panel with fields + lifecycle + tags. |
| **Contacts** | Views: All, Lifecycle stages (+ Lost stages), **Segments** (saved filters, e.g. "created < 7 days", "inactive > 30 days", "with tags"), Blocked Contacts. Table columns: Name, Channels, Lifecycle, Email, Phone, Tags, Country, Language, Conversation Status, Assignee, Collaborators, Last Message, Date Added. Add contact (first/last/phone/email/lifecycle/collaborators/tags), Add segment, bulk actions, 25/page. |
| **Contact fields** | System fields (tags MultiValue, profilePic, phone, firstName, lastName, language, email, countryCode) + custom fields: Name, Field ID, Description, Type = Text / List (Dropdown) / Checkbox / Email / Number / URL / Date / Time; Visibility; **Customize View** (order + visibility of the side panel). |
| **Lifecycle** | Ordered stages with emoji + description (default New Lead → Hot Lead → Payment → Customer), **Lost stages** (Cold Lead), show/hide toggle. Feeds dashboard tiles, inbox + contacts views, reports funnel, workflow trigger "Lifecycle Updated" and step "Update Lifecycle", AI-agent action. |
| **Tags** | Emoji + name + colour + description; on contacts; used by inbox filters, segments, workflow trigger/step. |
| **Teams / Users** | Teams (name, description, members). Workspace users: access level Owner / Manager / Agent + **Advanced restrictions**. Org users: Admin / Billing Admin / User Admin / Member. Org security: SAML SSO, enforce 2FA. |
| **Snippets** | Name, Field ID, message, topic, optional file; usable in Inbox (`/`), Broadcasts, Workflows. |
| **Files** | Workspace file library (name, description, upload) for messages / broadcasts / workflows. |
| **Conversation settings** | Auto-close after N days/hours of inactivity (reply reopens); AI-generated closing notes; **conversation categories** (managed list, seeded with 4); advanced: manual closing notes, add collaborators via @mention. |
| **Broadcasts** | List by status (Draft / Scheduled / In Progress / Completed / Failed), Table or **Calendar** view, columns Status / Broadcast time / Name / Labels / Channel / Segment / Recipients / Total messages. Builder: name + labels → Segment → Channel type (specific / last interacted) → Channel → Message content → Next (schedule / send / test broadcast). |
| **Workflows** | List (Status, Name, Last published by/at, Created by/at; row menu Publish / Edit / Open in builder / Clone / Export / Settings / Delete), templates gallery, canvas builder with Save / Test / Publish, 100-step cap. **Triggers:** Conversation Opened, Conversation Closed, Contact Field Updated, Contact Tag Updated, Shortcut (agent-fired from inbox), Incoming Webhook, Click-to-Chat Ads, TikTok Messaging Ads, Lifecycle Updated, Call Ended; each has Conditions + exposed `$conversation.*` variables + "trigger once per contact". **Steps:** Send a Message (Text / File or Image; channel = last interacted or specific; per-channel response variants; failure branch), Ask a Question (Text / Multiple Choice / Number / Date / Phone / Email / URL / Rating / Location; timeout + failure branches; save answer to field), Assign To (specific user or AI agent / team round-robin / unassign), Branch, Update Contact Field, Update Contact Tag, Open Conversation, Close Conversation (notes), Add Comment, Jump to Another Step, Date & Time (business hours / holidays), Wait, Send Conversions API Event, TikTok Lower Funnel Event, Trigger Another Workflow, HTTP Request, Add Google Sheets Row, Update Lifecycle, AI step. |
| **AI Agents** | Templates (Receptionist / Sales / Support) or scratch. Builder: emoji, name, instructions (+ prompt templates, Optimize), **Actions** toggles each with its own guideline text: close conversation, assign to agent/team, update lifecycle, update contact fields, update tags, trigger workflows, add comments, handle calls, HTTP requests; **Knowledge sources** (documents / links, "train"); side-by-side **Test chat** (Chat / Contact fields tabs, reset). AI agent is an assignee like a user. Workspace-level **AI Assist** (persona, snippets as knowledge, allow general knowledge) and **AI Prompts** (change tone / translate / fix grammar / simplify + custom). |
| **Reports** | Lifecycle (funnel, conversion / drop-off / time-in-stage, group by source), Calls, Conversations (opened / closed, group by), Responses (avg first response, first-assignment-to-response, last-assignment-to-response + breakdown buckets), Resolutions (avg resolution, first/last-assignment-to-close + buckets), Messages (incoming by channel, outgoing delivery Sent / Delivered / Read / Failed), Contacts (added / deleted / merged), Assignments (chart + **assignment log**: timestamp, conversation, contact, previous assignee, assigned to, source, assigned by), Leaderboard (per user / team / AI agent), Users (per-user performance table + comment log), Broadcasts. All: date range + Add filter + Group by. |
| **Channels** | Catalog: WhatsApp Business Platform (API), TikTok, Facebook Messenger, Instagram, Telegram, Viber, LINE, WeChat, WhatsApp Cloud API, Custom Channel; Calls (Telnyx); SMS (Twilio / MessageBird / Vonage / custom); Email (Google Workspace / Gmail / Yahoo / Microsoft 365 / other SMTP); Live Chat (Website Chat, custom). |
| **Growth widgets** | Multichannel widget, per-channel widgets, Email / SMS widgets, **QR code + chat link** generator. Need a channel. |
| **Integrations** | Browse by CRM / Scheduling / Automation / Ads & conversions / Developer tools; includes an **MCP** integration and the developer API. |
| **Data** | Contacts import (CSV, 3 steps: upload → mapping → review; identify by email / phone / contact id; 20 MB, 200k rows), Data export (Contacts / Messages / Failed Messages, async with history). |
| **Org** | Account info, org users, security (SSO, 2FA), workspaces list (users / contacts counts), WhatsApp fees, Billing & usage (MAC, AI credits). |

## 2. What Foundryx omnichannel has today (verified in repo)

- **Channels:** WhatsApp Cloud API only (Embedded Signup + manual token), Configuration / Profile / Templates tabs, dev-safe adapter. Adapter seam exists (`ChannelAdapter`), BL-018 for more channels.
- **Inbox:** thread list with server search (name / phone / body) + basic filters, `ConversationDrawer`: assign to workspace member, snooze / close / reopen, priority, in-thread search, templates + quick replies + media + structured (interactive / location) messages, reactions, CSW enforcement. Realtime via WS. Embeddable inbox / thread routes for external hosts.
- **Contacts:** `contacts` row = the thread (first / last / email / phone / avatar / `custom_fields_json` untyped / assignee / external agent / status OPEN-SNOOZED-CLOSED / priority / CSW / timestamps) + `contact_channel_identities`. No contacts module UI, no typed custom fields, no tags, no lifecycle, no segments, no import, no export, no merge / block.
- **Workspaces + members**, quick replies, media (storage) settings, embed config, API keys, consumer webhooks, public `/api/v1/omnichannel/*` gateway (guide = contract, `?format=rio` parity shapes).
- **Workflow engine (core):** DAG builder, IF, manual + cron + entity + form triggers, `omnichannel.message_received` trigger, `omnichannel.get_contact` / `send_message` actions, `ai_agent.run`, `email.send`, `entity.update` / `transition_status`, storage nodes, code runner, plan 19 stateful agent state + serialized runs. No wait / delay node, no HTTP request node, no ask-a-question, no assign / close / tag steps, no shortcut trigger.
- **AI (core `app/ai`):** `AiAgent` personas (connection / model / temperature), skills + versions, conversations, traces / spans, stub LLM. No knowledge sources, no action toggles, no test chat, no inbox-side AI assist.
- **Engines available to build on:** status engine (scoped machines, trait flags, `sort_order`, transition notifications, `entity.status_changed` trigger), rule engine (`validate_tree` / `evaluate`, whitelisted facts), `filter_translator`, import engine (`ImporterDef`, two-phase Test → Import), template engine, terminology, background jobs, storage.
- **No teams, no tags, no reports, no dashboard, no broadcasts, no global search / notification centre.**

## 3. Gap matrix

Priority: **P0** = the customer cannot leave respond.io without it; **P1** = expected within the first weeks after cut-over; **P2** = parity polish. "Phase" points at §4.

| # | Area | respond.io | Foundryx today | Gap | Pri | Phase |
|---|---|---|---|---|---|---|
| G1 | Contact fields | typed custom fields + side-panel view config | untyped JSON blob | field registry (type, id, visibility, order), typed validation, side panel | P0 | A1 |
| G2 | Tags | emoji / colour tags on contacts, filterable | none | `contact_tags` + assignment, filters, workflow trigger / step | P0 | A1 |
| G3 | Lifecycle | ordered stages + lost stages, everywhere | none | scoped status machine on `contacts` (see D2), views, trigger / step, dashboard tiles | P0 | A1 |
| G4 | Contacts module | list + columns + segments + add / edit + bulk | none (inbox only) | Resource-shell list + form, segments-lite (status / lifecycle / tag / assignee), bulk assign / tag | P0 | A2 |
| G5 | Contacts import / export | CSV 3-step, async export | import engine exists, no `ImporterDef` for contacts; no export | `contacts` importer (id / phone / email match, tags, lifecycle, custom fields), CSV export job | P0 | A2 |
| G6 | Inbox views | All / Mine / Unassigned / Collaborations / lifecycle / team / custom | flat list + filters | view rail, Show / Sort, Unreplied, saved custom views (filter tree) | P0 (views) / P1 (custom + team) | A3 / B1 |
| G7 | Conversation actions | assign to user / team / AI, close with notes + category, snooze, collaborators, comments | assign to member, snooze / close, priority | closing notes + categories, collaborators, internal comments (verify), assign-to-team, assign-to-AI | P0 (notes, comments) / P1 (team, AI, collaborators) | A3 / B1 / C1 |
| G8 | Snippets | `/` picker, topics, files, usable in broadcasts + workflows | quick replies (text) | topics, file attachment, `/` picker, reuse in A4 / A5 | P1 | B2 |
| G9 | Broadcasts | segment × channel × template, schedule, calendar, statuses, delivery counts, report | none | broadcast model + Celery fan-out through `MessageService.send_message` (template-only for WA), status list, schedule, counts | P0 | A4 |
| G10 | Workflow triggers | conversation opened / closed, field / tag / lifecycle updated, shortcut, webhook, ads | `message_received`, entity events | `omnichannel.conversation_opened` / `closed`, `contact.field_updated` / `tag_updated` / `lifecycle_updated`, `shortcut` (inbox button), incoming webhook | P0 | A5 |
| G11 | Workflow steps | send, ask a question, assign, branch, update field / tag / lifecycle, open / close, comment, jump, business hours, wait, HTTP, trigger workflow, AI | send_message, get_contact, IF, ai_agent.run, entity.update | ask-a-question (stateful wait for reply, typed validation, timeout), assign, tag / field / lifecycle update, open / close, comment, wait, business hours, HTTP request, trigger workflow | P0 | A5 |
| G12 | Workflow list UX | templates gallery, clone / export / settings | list + builder | templates gallery (P2), clone (P1) | P1 / P2 | B3 |
| G13 | Teams | teams + team inbox + round-robin | none | core `teams` + members (D4), assign-to-team, round-robin | P0 | A8 |
| G14 | Access levels | Owner / Manager / Agent + restrictions | RBAC keys | role templates per workspace + "own conversations only" scoping (BL-SS-014) | P1 | B1 |
| G15 | Dashboard | lifecycle tiles, open / assigned / unassigned, team presence, opened vs closed chart | none | aggregate endpoints + page | P0 | A9 |
| G16 | Reports | 11 reports, filters, group-by, assignment log | none | event tables (conversation opened / closed / assigned / first response) + report pages (conversations, responses, resolutions, messages, users, leaderboard, assignments) | P0 | A9 |
| G17 | Conversation settings | auto-close, categories, AI closing notes, @mention collaborators | none | settings page + beat job (auto-close), categories CRUD | P1 | B2 |
| G18 | AI agent builder | actions toggles, knowledge sources, test chat, assignable | personas + `ai_agent.run` node + plan 19 state | **Decided: no separate builder.** An AI agent = a workflow (trigger + `ai_agent.run` + A5 steps). Needs: "assign conversation to a workflow" semantics, knowledge-source retrieval as an `ai_agent.run` option | P1 | C1 |
| G19 | AI Assist / AI Prompts | composer suggestions, tone / translate / grammar | none | composer actions on `AiClient` | P2 | C1 |
| G20 | Channels | 10 messaging + SMS + email + web chat | WhatsApp Cloud | **Q1 answered: the customer uses WhatsApp, Messenger, Instagram, Telegram, website chat, email, SMS** - all move into Phase A | P0 | A7 |
| G21 | QR / chat links, growth widgets | generator + embeddable widgets | none | QR + `wa.me` link generator (cheap), multichannel widget (later) | P2 | C2 |
| G22 | Files library | workspace file library | storage exists | small CRUD over storage | P2 | C3 |
| G23 | Global search, notifications | search contacts / messages, notification centre | inbox search only | omnibox + notification feed | P1 | B3 |
| G24 | Contact merge / block | merge duplicates, block | none | merge (identity move), block flag honoured by inbound | P2 | B2 |
| G25 | Integrations directory, MCP | browse + connect | API keys + webhooks + guide | directory page (P2); MCP server over the gateway (P2) | P2 | D |
| G26 | Org / security | SSO, 2FA, workspaces, billing | tenants, workspaces | 2FA / SSO = core auth backlog; billing n/a (internal) | P2 | core |
| G27 | Calls | Telnyx VoIP, call reports | none | **out of scope** | - | - |
| G28 | Migration tooling | - | - | **Q3 answered: message history migrates.** respond.io Developer API (contacts, messages incl. media URLs) → Foundryx importers; CSV exports as fallback | P0 | A6 |

## 4. Roadmap - vertical slices (each = own UAC + plan; build order inside each phase is top-down)

### Phase A - migration spine (P0, cut-over blocking)

| Slice | Content | Notes |
|---|---|---|
| **A1 Contact data model** | typed contact fields registry + values, tags, lifecycle stages (status engine, scoped to contacts, see D2), contact side panel in the drawer (fields / lifecycle / tags editable), `Customize View` | BE first here (data model is the spine everything else hangs on), then the panel |
| **A2 Contacts module** | `/omnichannel/contacts` Resource-shell list (columns per §1), add / edit form, segments-lite (saved filter trees via rule engine + `filter_translator`), bulk assign / tag / lifecycle, CSV import via `ImporterDef("omnichannel_contacts")`, CSV export as a `background_jobs` job | Reuse Users list as the clone reference; segments = stored rule tree per workspace |
| **A3 Inbox views + conversation actions** | view rail (All / Mine / Unassigned / lifecycle stages), Show / Sort / Unreplied, close-with-notes + categories, internal comments (audit that structured "note" messages cover it), Shortcut trigger button | inbox restructure coordinates with plan 23 |
| **A4 Broadcasts v1** | `broadcasts` + `broadcast_recipients`, builder (name / labels → segment → channel → template + variables → schedule / send now / test send), status list + counts, Celery fan-out through `MessageService.send_message` with per-number rate tier, failure capture | WhatsApp = approved template only; calendar view deferred to D |
| **A5 Workflow parity v1** | triggers G10; steps G11 with **Ask a Question** as a stateful wait (run parks in `workflow_agent_states`-style wait row keyed by contact, resumed by the next inbound - reuses plan 19 serialized-run machinery), `wait`, `business_hours`, `http.request` (SSRF guard = `assert_deliverable`), `assign`, `tag` / `field` / `lifecycle` update, `open` / `close` / `comment`, `trigger_workflow` | Supersedes BL-128; "trigger once per contact" flag |
| **A7 Channel adapters** | Messenger + Instagram (Meta Graph, share the WhatsApp adapter's app + webhook plumbing), Telegram (Bot API), website chat (new adapter + embeddable widget + visitor identity), email (SMTP out + IMAP/Graph in, threading), SMS (Twilio first); each = `ChannelAdapter` impl + channel-connect wizard entry + inbound webhook route + identity stitch + composer capabilities (CSW is WhatsApp-only) | Q1 = all of them. Biggest single risk in Phase A; each channel is its own slice. **Order decided 2026-09-05: A7a Messenger + Instagram first**, then A7b web chat (drives A6 identity mapping), A7c Telegram, A7d email, A7e SMS |
| **A8 Teams** | core `teams` table + membership (D4), Team Inbox views, assign-to-team with round-robin / least-open, workflow Assign To "user in a team", reports grouped by team | Pulled from B1 by the grill; access-level presets stay in B1 |
| **A9 Dashboard + Reports v1** | append-only `omni_conversation_events` (opened, closed, assigned, first agent reply, resolved) written from A1/A3 onward; dashboard (lifecycle tiles, open / assigned / unassigned, team presence, opened vs closed); reports: conversations, responses, resolutions, messages, users, leaderboard, assignment log | Pulled from B4 by the grill. The events table is designed in A1 so A3/A8 write it from day one; A6 backfills events from migrated history |
| **A6 Migration tool** | **Q3 = yes: contacts AND message history.** A `background_jobs` migration job driven by the respond.io Developer API (`/contact`, `/contact/{id}/message`, custom fields, tags, lifecycle; media pulled by URL into our storage) with the CSV exports as fallback; maps respond.io channel identities onto A7 channels; writes messages as read-only history rows (`sender_type` preserved, original timestamps, `migrated_from` marker) and backfills A9 events; snippets → quick replies; workflows re-authored by hand (no import format); WABA number move (Embedded Signup re-onboarding, template re-sync); dry-run + counts report before the real run | Last in Phase A - needs every other slice. Prerequisite: confirm the customer's respond.io plan includes Developer API access (Business plan); if not, CSV-only (no media) |

### Phase B - operations polish (P1, first weeks after cut-over)

B1 Access-level presets (Owner / Manager / Agent) + own-conversations scoping (BL-SS-014); core Teams admin UI polish if A8 ships only the minimum. B2 Snippets full (topics, files, `/` picker, use in A4 / A5), conversation settings (auto-close beat job, categories, AI closing notes), contact merge / block. B3 Workflow list UX (clone, settings, templates gallery-lite) + global search + notification centre.

### Phase C - AI via workflows + channel extras (P1 / P2)

C1 **AI agents as workflows** (decided: no separate builder). Adds what the workflow tool lacks to play that role: "assign conversation to a workflow" (the workflow's `ai_agent.run` loop owns the thread until it hands off - plan 19 stateful state), knowledge-source retrieval as an `ai_agent.run` option (documents / links → chunks), a per-agent test chat on the workflow Test panel; AI Assist + AI Prompts in the composer as P2 extras. C2 QR / chat-link generator + growth widgets. C3 Files library.

### Phase D - polish (P2)

Reports v2 (lifecycle funnel, broadcasts, contacts), broadcast calendar view, integrations directory + MCP over the gateway, onboarding checklist, org security (core).

## 5. Decisions (grilled 2026-09-05 - all closed; recommendations not marked Decided/Accepted were accepted by default)

| # | Question | Recommendation |
|---|---|---|
| Q1 | Which channels does the customer actually use on respond.io? | **Answered 2026-09-05: all of them** - WhatsApp, Facebook Messenger, Instagram, Telegram, website chat widget, email, SMS. Channels are Phase A (A7). Still get their Channels page screenshot to pin providers (which SMS vendor, which email host). |
| Q2 | Which respond.io features does the customer use daily? | **Answered: all** - lifecycle, segments, broadcasts, workflows, AI agents, teams, reports. Nothing pruned; still collect their exports (Contacts CSV, fields, tags, snippets, workflow list + screenshots) to size A5/A6. |
| Q3 | Must message history migrate? | **Answered: yes, definitely.** A6 = API-driven migration tool incl. media; CSV fallback. |
| D1 | Contact fields storage | Registry table (`contact_fields`: key, label, type, options, visibility, order) + keep `custom_fields_json` for values, validated against the registry on write. No EAV. |
| D2 | Lifecycle implementation | **Accepted 2026-09-05.** Status engine, scoped machine on `contacts` with materialized full-mesh edges (any stage → any stage), `is_initial` = first stage, `is_terminal` = won, `is_archived` = lost, `sort_order` = funnel order. Buys transition notifications + `entity.status_changed` trigger + reports "time in stage" for free. Alternative (own `lifecycle_stages` table) is simpler but re-implements transitions and the trigger. |
| D3 | Conversation status vs lifecycle | Keep `contacts.status_id` = conversation state (OPEN / SNOOZED / CLOSED) as today; lifecycle = second `lifecycle_status_id` FK on `contacts` (two scoped machines, one row). |
| D4 | Teams location | What Teams do in respond.io: group users; assignment target (assign to team → round-robin / least-open member), Team Inbox view per team, workflow Assign To "user in a team", reports leaderboard by team, share saved views. **Decided 2026-09-05: CORE `teams` table** (platform-wide, shared by every Service; omnichannel consumes it for assignment / team inbox / reports). Teams = core users grouping next to roles; membership by user; the omnichannel `WorkspaceMember` resolves team membership through core. |
| D5 | Access levels | Ship three role templates per workspace (Owner / Manager / Agent) as presets over existing keys; "Advanced restrictions" = BL-SS-014 membership scoping + `own_conversations_only` flag on the member. |
| D6 | Segments | Stored rule-engine tree per workspace (`contact_segments`), evaluated via `filter_translator` on the contacts query; same object drives inbox custom views and broadcast audiences. |
| D7 | Ask-a-Question runtime | **Accepted 2026-09-05.** Park the run in a wait row keyed by (workflow, contact); the inbound pipeline resumes it before firing new `message_received` triggers. Timeout via beat. Needs the plan 19 serialized mode. |
| D8 | Broadcast sending | Celery chunks through the one `send_message` path; WhatsApp template-only; rate tier per number (BL-SS-007 becomes a prerequisite for large sends). |
| D9 | Reports data | Append-only `omni_conversation_events` (opened, closed, assigned, first_agent_reply, ...) written by the same services that mutate threads; reports aggregate over it. Backfill from existing rows for the launch tenant. |
| D11 | AI agents | **Decided 2026-09-05: no respond.io-style builder.** An AI agent is a workflow (trigger + `ai_agent.run` + steps). Gap to close = "assign conversation to a workflow" + knowledge retrieval (C1). |
| D12 | Migration source | **Decided 2026-09-05: try the respond.io Developer API first; fall back to CSV exports only if the customer's plan lacks API access** (CSV = no media, no message metadata). First A6 task = verify API access on the customer's plan. |
| D10 | Menu placement | Contacts / Broadcasts / Reports as top-level omnichannel menu entries alongside Inbox, gated by module + new permission resources (`contacts.*`, `broadcasts.*`, `reports.*`, `teams.*`, `segments.*` - grep core for collisions first). Coordinate with plan 23's restructure. |

## 6. Sizing (rough, one coder lane + tester + reviewer per slice)

| Slice | Size | Why |
|---|---|---|
| A1 | M | data model + status-engine adoption + side panel |
| A2 | L | list + form + segments + importer + export |
| A3 | M | views + actions; drawer already rich |
| A4 | L | new model, scheduler, fan-out, rate limits, UI |
| A5 | XL | 6 triggers + 12 steps + stateful wait; split into A5a (triggers + simple steps) / A5b (ask-a-question, wait, http) |
| A6 | L | API-driven migration job incl. messages + media + events backfill, dry-run report |
| A7 | M per channel (x5) | Meta pair share plumbing; web chat needs a widget; email needs inbound polling + threading |
| A8 | M | teams, round-robin, team views |
| A9 | L | events table + dashboard + 7 reports |
| B1 / B2 / B3 | S / M / M | |
| C1 | M | assign-to-workflow + retrieval + test chat on existing builder |

## 7. Not doing

A respond.io-style AI agent builder (decided: workflows are the builder), calls / VoIP, respond.io billing / MAC metering, TikTok / Meta ads triggers and Conversions API events (until a customer asks), Google Sheets step (HTTP request covers it), AI Copilot.

## 8. Survey method + residue

Explored with the `agent-browser` CLI against the sandbox using the Brave "Default" profile session
(`--profile Default`); 45 pages captured. Two throwaway objects were created to open the builders
(workflow "FX explore 20260905", broadcast "FX explore bc 20260905") and **deleted afterwards**; one
Contacts data-export request was left in the export history (harmless). The workspace switcher
lists a second workspace ("Jayson Test") that was never opened.
