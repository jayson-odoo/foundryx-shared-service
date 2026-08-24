# PLAN - Meetings (AI meeting assistant) program master

**Status:** Planning (grilled + confirmed 2026-08-24; UAC-first, no code yet). Next: S1 spike.
**Classification:** MODULE / Service on the FoundryX shared-service platform. Multi-tenant from day one.
**Repos in scope:** `foundryx-shared-service` (primary), `sorento_crm` (iframe host + record linkage).
**This file is the spine.** Per-slice PLAN + UAC files key back to the Cross-Repo Contracts section here. If a contract changes, change it here first, then the slice plans.

---

## 1. Vision

Every meeting a tenant user attends is captured, transcribed and summarised into minutes that live
next to the tenant's operational data. Own bot, own speech-to-text, own storage, configurable LLM.
No third-party meeting-bot vendor in the path: no per-meeting middleman cost, no single external
point of failure, recordings in the tenant's own bucket.

```
Google Calendar (domain-wide delegation)
  -> calendar_events (conference link parsed)
  -> user opted in? event not opted out? -> one meeting per link+start
  -> bot container joins Meet as notetaker@tenant-domain, records audio, leaves on empty room
  -> audio chunks in tenant storage (core files)
  -> WhisperX on Modal (GPU): transcript + speakers + language per segment
  -> LLM (anthropic | openai | gemini): structured minutes
  -> shared-service UI (list, detail, share) + sorento iframes + contact/company linkage
  -> in-app + email "minutes ready"
```

## 2. Locked decisions (from the grill, 2026-08-24)

| # | Decision |
|---|----------|
| M1 | Meetings is a **Service module on foundryx-shared-service**: `modules/meetings`, schema `app_meetings`, own alembic table. Sorento consumes via iframe + a thin link table; nothing mirrored. |
| M2 | **Own bot**, not Recall.ai or similar. Google Meet first. Zoom / Teams later as guest-join browser adapters behind the same `JoinAdapter` interface; native SDKs only if guest join proves too flaky. |
| M3 | **Multi-tenant from day one.** Pilot tenant = FoundryX internal; Sorento = tenant 2. |
| M4 | **Calendar read = Google domain-wide delegation** (tenant admin grants once at onboarding, no per-user OAuth, no Google app verification). Per-user OAuth is a later adapter for tenants that refuse DWD. Google only; Microsoft 365 later. |
| M5 | **Bot identity = one Workspace account inside each tenant's domain** (`notetaker@<tenant-domain>`), created by the tenant admin, 2SV-exempt OU. Credentials stored encrypted in a tenant `Connection` of kind `meet_bot`; persistent Chromium profile volume per tenant. Auto-admitted to tenant-hosted meetings. |
| M6 | **Opt-in model:** user flips a master toggle; after that every event with a conference link is joined unless the user opts that event out. Cutoff 2 min before start. |
| M7 | **Externally hosted meetings are attempted:** bot waits in lobby 3 min, then marks the meeting `not_admitted` and tells the user. |
| M8 | **One bot per meeting** (dedupe key = conference link + start). Minutes visible to opted-in attendees only; share-to-user in v1, share-link later. |
| M9 | **Consent:** bot display name `Notetaker (for <user name>)`, posts a consent message in the Meet chat on join. Message text is a tenant setting with a default. |
| M10 | **Audio only.** Chunked to storage every 60 s (so live transcript can be added later without changing capture). No video. |
| M11 | **Batch processing after the meeting ends.** No live transcript in v1. |
| M12 | **STT = self-hosted WhisperX** (`large-v3`, pyannote diarization, word timestamps, language auto-detect per segment) on **serverless GPU (Modal)** first, dedicated GPU VM when volume justifies. `SttProvider` adapter; Deepgram is the configured fallback. Not on the Mac Mini. |
| M13 | **LLM is configurable:** `LlmProvider` adapter with `anthropic`, `openai`, `gemini` drivers. Platform default (provider, model, key) + per-tenant override through a `Connection` of category `llm`. Structured JSON output. Prompts versioned in DB (immutable versions + label, ported from sorento's prompt registry). **Amends ideation D20:** shared-service may call an LLM directly for a single structured call; agent loops still belong to the Mac Mini brain. |
| M14 | **Minutes shape:** summary, decisions, action items (owner, due), open questions, topic notes. Editable, versioned (original kept). Minutes language = per-tenant setting, default English. Transcript stays verbatim in whatever languages were spoken. |
| M15 | **Retention:** transcript + minutes kept; audio deleted after N days, per-tenant setting (default 90, 0 = keep). Bytes live in the tenant's own storage connection. |
| M16 | **Notify on minutes ready:** in-app and email, to opted-in attendees. |
| M17 | **Bot fleet = Celery worker on queue `bots`** (same Redis, same `app/jobs` framework) spawning one Docker container per meeting through the local Docker socket. Pilot: worker on the Mac Mini. Prod: separate Linux VM (4 vCPU / 8 GB, ~4 concurrent), never the app server. |
| M18 | **Ops safety net:** a daily canary Meet in the FoundryX domain the bot must join and record non-silent audio; alert (email to platform owner + red banner on the tenant admin page) on canary fail or join-failure rate above 20 % in an hour. Meet DOM selectors live in one file. |
| M19 | **Reuse core, not new tables:** recordings = core `files` / `file_versions`; bot / STT / minutes runs = core `background_jobs`; credentials and provider config = `connections`; emails = `notification_specs` -> `email_outbox`; sync + LLM call logs = `integration_activity`; search = `pg_trgm` on segments. Meeting status is a plain enum column (machine-driven), not the status engine. |
| M20 | **Sorento side:** module key `meetings`, permissions `meetings.view` / `meetings.manage`, nav item, three iframes via embed-SSO on the module's own prefix `/meetings/embed/session`, `meeting_links` table, `POST /api/v1/external/meetings/ready` webhook, auto-link attendees by email + manual link. MCP tools (`list_meetings`, `get_meeting_minutes`) later. |
| M21 | **Simplest thing that works** governs every slice (PRINCIPLES.md design mandate). Ten thin module tables, adapters only where a second implementation is already planned (calendar, join, STT, LLM). |

## 3. Data model (`app_meetings`, every row tenant-scoped)

| Table | Purpose | Key columns |
|---|---|---|
| `user_opt_ins` | master toggle per user | `user_id` (unique per tenant), `enabled`, `updated_at` |
| `calendar_events` | mirror of calendar events that carry a conference link | `external_id`, `calendar_user_id`, `organiser_email`, `attendees_json`, `conference_url`, `platform` (`meet`/`zoom`/`teams`/`other`), `starts_at`, `ends_at`, `opted_out`, `synced_at` |
| `meetings` | one per link + start | `dedupe_key`, `conference_url`, `platform`, `starts_at`, `ends_at`, `status`, `recording_file_id` (core `files`), `language`, `not_admitted_reason`, `duration_s` |
| `meeting_participants` | who was invited / seen | `meeting_id`, `email`, `display_name`, `user_id` (nullable), `is_opted_in` |
| `transcripts` | one per meeting (re-runs replace) | `meeting_id`, `stt_provider`, `model`, `created_at` |
| `transcript_segments` | diarised text | `transcript_id`, `speaker`, `start_ms`, `end_ms`, `text`, `language`; `pg_trgm` index on `text` |
| `minutes` | versioned | `meeting_id`, `version`, `sections_json`, `created_by` (`user_id` or `llm`), `prompt_version_id`, `llm_provider`, `llm_model` |
| `action_items` | extracted + ticked | `minutes_id`, `text`, `owner_email`, `due_on`, `done_at` |
| `shares` | user-to-user | `meeting_id`, `user_id`, `shared_by` |
| `tenant_settings` | module settings | `tenant_id` pk, `minutes_language`, `audio_retention_days`, `llm_connection_id`, `bot_display_name`, `consent_message` |

Meeting `status`: `scheduled | joining | in_lobby | recording | processing | ready | failed | not_admitted | skipped`.

Core rows the module writes: `connections` (kinds `google_dwd`, `meet_bot`, `llm`), `files` + `file_versions` (audio, folder "Meetings"), `background_jobs` (types `meetings.calendar_sync`, `meetings.bot_run`, `meetings.transcribe`, `meetings.minutes`, `meetings.retention`, `meetings.canary`), `notification_specs`, `integration_activity`.

## 4. Adapters (only where a second implementation is already planned)

| Interface | v1 | later |
|---|---|---|
| `CalendarSource` | `google_dwd` | `google_oauth`, `m365_graph` |
| `JoinAdapter` | `meet` (Chromium) | `zoom_guest`, `teams_guest` |
| `SttProvider` | `whisperx_modal` | `deepgram` (fallback config) |
| `LlmProvider` | `anthropic`, `openai`, `gemini` | - |

Everything else is a direct call.

## 5. Cross-repo contracts

### 5.1 Embed SSO (shared-service provides, sorento renders)

Same mechanism as `PLAN-ideation-embed-sso.md`, mounted on the module's own prefix so it cannot collide with ideation / omnichannel `/embed/session`:

- `POST /meetings/embed/session` body `{ connection_id, assertion }`; assertion = HS256 JWT signed with the per-connection secret, `aud: meetings-embed`, `sub: <sorento user email>`, `exp <= 5 min`, single-use `jti`. Returns `{ token, expires_at }` (15 min, `typ: embed`, scope `meetings`).
- Chrome-less pages under `service_frontend/app/embed/meetings/`: `settings` (master toggle + upcoming events with per-event opt-out), `list`, `[id]` (player, synced transcript, minutes, action items, share). Token travels in the URL fragment `#token=`.
- Read API for the host: `GET /meetings/embed/meetings?attendee_email=<email>&since=<iso>` (embed token), returns `{ items: [{ id, title, starts_at, status, attendees: [email] }] }`.

### 5.2 Minutes-ready webhook (shared-service calls sorento)

`POST <sorento>/api/v1/external/meetings/ready` with `X-API-Key`, body
`{ meeting_id, tenant_id, starts_at, attendees: [email], minutes_url }`. Sorento matches attendee emails to `users` / contacts and writes `meeting_links`. Idempotent on `meeting_id`.

### 5.3 Tenant onboarding (human steps, wizard-scripted in S7)

1. Google Cloud: FoundryX service account + OAuth client ID exist once (platform-owned).
2. Tenant Workspace admin: create `notetaker@<domain>`, put it in a 2SV-exempt OU, grant domain-wide delegation to the FoundryX client ID with scopes `https://www.googleapis.com/auth/calendar.readonly` and `https://www.googleapis.com/auth/admin.directory.user.readonly` (the second one is what the connection Test button and the opt-in user lookup use; found in S0).
3. Tenant admin in shared-service: connection of type `calendar` (provider `google_dwd`: service-account JSON + admin email to impersonate), connection of type `meeting_bot` (notetaker email + password), storage connection (existing), optional `llm` connection. Two connection types because core allows one active connection per type per tenant (S0 decision).

## 6. Slices, gates, estimates

| # | Slice | Plan file | Gate | Est. |
|---|---|---|---|---|
| S1 | Bot spike: throwaway container joins a real Meet under a notetaker account, records audio, uploads, leaves on empty room | `PLAN-meetings-s1-bot-spike.md` | 5/5 joins on FoundryX Meets, audio audible, leaves within 60 s of last human leaving | 1 wk |
| S0 | Module skeleton, DWD calendar sync, `calendar_events`, opt-in toggles, settings page | `PLAN-meetings-s0-calendar-optin.md` | new calendar event with a Meet link appears in the settings page within 60 s | 1 wk |
| S2 | Orchestrator: `bots` queue, scheduling at T-2 min, container lifecycle, lobby timeout, dedupe, retries, `background_jobs` | `PLAN-meetings-s2-orchestrator.md` | two overlapping meetings both captured; not-admitted path surfaces to the user | 1 wk |
| S3 | STT: WhisperX on Modal, diarization, language per segment, Deepgram fallback, `transcripts` | `PLAN-meetings-s3-stt.md` | 1 h audio -> transcript in under 5 min; mixed Malay / English / Chinese meeting transcribed | 1-2 wk |
| S4 | Minutes: `LlmProvider` x3, prompt registry, structured output, versions, edit, action items | `PLAN-meetings-s4-minutes.md` | minutes render for 10 real meetings; tenant language honoured | 1 wk |
| S5 | Shared-service UI: list, detail (player + synced transcript + minutes + actions), share, tenant settings | `PLAN-meetings-s5-ui.md` | UAC pass at 375 px and 1280 px | 2 wk |
| S6 | Sorento: module, nav, 3 iframes, `meeting_links`, ready webhook, auto-link | `sorento_crm/documentation/plans/meetings/PLAN-meetings-sorento-embed.md` | contact detail shows the meeting it was part of | 1 wk |
| S7 | Notifications (in-app + email), retention job, canary + alerting, onboarding wizard | `PLAN-meetings-s7-ops.md` | Sorento onboarded as tenant 2 through the wizard | 1 wk |

S1 goes first because it is the only unknown. Each slice ships its own PLAN + UAC + test report (`documentation/plans/meetings/`).

**v1 exit criteria:** 20 real meetings, at least 90 % joined, minutes within 10 min of meeting end, zero rows visible across tenants.

**Pilot path:** S1 spike = bot worker on the Mac Mini against a local stack. Founders pilot (after S4) = Mac Mini worker attached to prod Redis. Bot VM procured only after the S2 gate passes. Sorento staff pilot (3-5 users) after S6.

## 7. Infrastructure

| Piece | Pilot | Prod |
|---|---|---|
| shared-service app + Postgres + Redis + Celery (`workflow`, `omni`, `beat`) | existing VPS | existing VPS, untouched |
| Bot fleet (`worker_bots` + Docker) | Mac Mini | separate Linux VM, 4 vCPU / 8 GB, Docker, same Redis over private network / TLS |
| STT | Modal (serverless GPU, WhisperX image) | Modal; dedicated GPU VM if monthly bill exceeds one |
| LLM | provider APIs | provider APIs |
| Storage | tenant storage connection (R2 / S3) | same |
| Google | one Cloud project, service account + OAuth client (platform-owned) | same |
| Images | `foundryx-shared-service:bot-<tag>` on Docker Hub | same |

Run cost at pilot volume (rough): Modal ~USD 0.03 per meeting-hour, LLM ~USD 0.05-0.20 per meeting, storage ~50 MB per meeting-hour, bot VM ~USD 30-50 / month.

## 8. Risks and how each is caught

| Risk | Mitigation | Caught by |
|---|---|---|
| Google flags the bot login as automation | headed Chromium under Xvfb (no `--headless`), persistent profile, one manual first login, no automation flags | daily canary |
| Meet DOM changes | selectors in one file, join steps assert each stage | daily canary + join-failure alert |
| Bot stuck in lobby on external meetings | 3 min timeout, `not_admitted` status shown to the user | S2 UAC |
| Notetaker account 2SV re-enforced by tenant admin | login failure surfaces as "admin action needed" banner | S7 UAC |
| STT provider outage | `SttProvider` fallback to Deepgram by config | S3 UAC |
| Wrong-tenant data | every query tenant-scoped from JWT; storage resolves through the tenant connection | S5 UAC cross-tenant test |

## 9. Deferred (backlog)

Zoom / Teams adapters, Microsoft 365 calendar, per-user Google OAuth, live transcript, video capture, share links, action items -> sorento tasks, MCP tools for the sorento AI bubble, WhatsApp alerting via omnichannel, dedicated GPU VM.
