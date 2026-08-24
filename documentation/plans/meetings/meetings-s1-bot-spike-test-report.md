# Meetings S1 - Bot spike: Test report (in progress)

**Date:** 2026-08-24 (day 1 of the spike). **Runs:** 6 on the Mac Mini (colima, arm64 Linux, Playwright Chromium `--headless=new`).
**Identity used:** `jayson@foundryx.my` (own session via one VNC login). `notetaker@foundryx.my` not yet created.
**Meetings:** `him-bwpx-vyi` (FoundryX-hosted by the same account) and `kfp-sofm-cnr` (hosted by Jayson's personal Gmail, bot external).

## UAC status

| AC | Status | Evidence |
|---|---|---|
| AC-S1-1 join, mic/cam off, no admit | **partial** | Joined `kfp-sofm-cnr` in ~1 s from "Join now" (runs 2, 6b). Display name not settable: a signed-in account has no name field, the bot shows as "Jayson Teh". Needs the notetaker account for the real name. |
| AC-S1-2 consent in chat < 10 s | **pass** | `consent_posted` at +2.5 s (runs 2, 5b, 6b). Skipped once (run 4) because the bot was on the host-hold screen where chat is disabled. |
| AC-S1-3 external host: lobby, 3 min timeout | **pass (admit path)** | Run 5b: `in_lobby` -> `joined {lobby: true}` after admit. Timeout path exercised in run 4 as the host-hold variant. |
| AC-S1-4 profile reuse / re-login | **pass (reuse)** | Every run after the one VNC login started signed in headless. Password re-login path not exercised (2SV on this account). |
| AC-S1-5 audio chunks, intelligible | **pass** | 60 s opus segments, uploaded as they close. Speech segments mean -20 to -25 dB, peak ~0 dB; silence -91 dB. Headless Chromium plays to the pulse null sink; Meet's "Speaker not found" label is cosmetic. |
| AC-S1-6 active-speaker events | **fail** | No `active_speaker` events. The speaking indicator selector matched nothing. `participants` events (count + tile names, 1 s poll) do work. |
| AC-S1-7 leave within 60 s of empty room | **pass** | Run 6b: human left at +58 s, bot left at +244 s = 180 s floor (now 60 s) + 60 s empty. |
| AC-S1-8 removed by host | **not tested** | |
| AC-S1-9 failure exits with reason + screenshot | **pass** | `error:join_button_not_found`, `error:not_logged_in_and_no_credentials`, `denied` all produced `last.png` + `events.jsonl`. |
| AC-S1-10 5/5 scheduled FoundryX Meets | **pending** | Needs the notetaker account (same account cannot be host and bot) and the 5 scheduled links. |
| AC-S1-11 peak memory recorded | **pass** | 636-790 MiB per container, CPU 10-190 % (spikes = incoming video decode). |

## What broke and what was learned

1. **Same account cannot be human and bot.** Meet offers only "Switch here". The notetaker account is a v1 requirement, not an S2 nicety.
2. **The host-hold screen ("Please wait until a meeting host brings you into the call") has a Leave button.** Detecting "joined" by the Leave button alone is wrong; hold text must take precedence. Fixed.
3. **A hard-killed bot leaves a ghost seat for 1-2 min** and the account then cannot rejoin. Bot now leaves on SIGTERM (`run.sh stop`), and the join loop waits out a ghost instead of failing.
4. **No People panel list in the DOM.** The People button renders the count as its only text ("2"); tiles carry `data-participant-id` with the name as first text line; the bot's own tile shows only icon labels. Counting = badge minus one, tiles as fallback.
5. **Chat disabled by host = no consent line.** Personal-account hosts had "Let participants send messages" off at times; consent falls back to the display name only. Note for the consent policy (M9).
6. **Page load can exceed 30 s**; `commit` + 60 s + one retry.
7. **Docker Desktop is broken on this Mac Mini**; colima works. arm64 means Playwright Chromium, not Google Chrome; sign-in was not blocked.
8. Personal-account Meets show "Your call is ending soon" (free-tier limit); irrelevant for Workspace-hosted meetings.

## Selectors the join path depends on (`bot/meet_selectors.py`)

`button:has-text("Join now")`, `button:has-text("Ask to join")`, `button:has-text("Switch here")` (never clicked), hold/lobby text regex, `button[aria-label*="Leave call"]`, `button[aria-label*="Chat with everyone"]`, `textarea[aria-label*="Send a message"]`, `[data-participant-id]`, People count badge (digits-only button text).

## Remaining for the gate

- Create `notetaker@foundryx.my` (Bots OU, 2SV off), log it in once, run 5 scheduled FoundryX Meets (AC-S1-10).
- Speaker indicator (AC-S1-6): capture a DOM probe while someone is talking and pin the selector, or defer diarization to WhisperX only (S3) and drop the DOM timeline.
- AC-S1-8 removed-by-host, AC-S1-4 password re-login with the notetaker account.
- Turn off incoming video after join to cut CPU (selector not yet found).
