#!/usr/bin/env bash
# Step 3 of the Meta leads switch-on: create the Lead Capture key, register the CRM receiver, connect the Foundryx Page.
# Runs on the owner's Mac. Prints NO secrets: the admin password is typed hidden; every token stays in memory or in
# chmod 600 temp files deleted on exit (never on a command line, so nothing shows in `ps`). Error output shows only
# the HTTP status and an error code or a short message, never a request or response body.
# Needs: bash, curl, python3 (macOS has all three).
#
# Inputs:
#   ~/.config/crew/secrets/meta-leads.env (chmod 600):
#     META_SYSTEM_USER_TOKEN=<token from Meta Business Settings, step 2>
#   Environment variables (not secret; crew fills them):
#     SS_BASE         production Shared Service backend, e.g. https://<prod host>/be
#     SS_TENANT       the Sorento company's tenant slug in Shared Service
#     SS_EMAIL        Admin login email of that company (password is asked, hidden)
#     CRM_HOOK_URL    the Sorento CRM Lead Capture receiver URL (from sorento-crm #2449), https only
#     FB_PAGE_ID      the Foundryx Page id (S-META-result.md)
#     GRAPH_VERSION   optional, default v25.0
# Output:
#   ~/.config/crew/secrets/meta-leads-out.env (chmod 600): LC_API_KEY=fxl_live_..., then LC_WHSEC_SECRET=whsec_...
#   Paste LC_WHSEC_SECRET into the CRM (step 4), then delete the file.
#
# Order: read-only preflight (nothing is created until every check passes) -> key (saved at once) -> CRM receiver
# (secret saved at once) -> Page connect -> verify the connect is real (not the server's dev stand-in).
set -euo pipefail
umask 077

IN="$HOME/.config/crew/secrets/meta-leads.env"
OUT="$HOME/.config/crew/secrets/meta-leads-out.env"
GRAPH_VERSION="${GRAPH_VERSION:-v25.0}"
GRAPH_BASE="${GRAPH_BASE:-https://graph.facebook.com}"
: "${SS_BASE:?set SS_BASE}" "${SS_TENANT:?set SS_TENANT}" "${SS_EMAIL:?set SS_EMAIL}"
: "${CRM_HOOK_URL:?set CRM_HOOK_URL}" "${FB_PAGE_ID:?set FB_PAGE_ID}"
SS_BASE="${SS_BASE%/}"
[ -f "$IN" ] || { echo "missing $IN"; exit 1; }
META_SYSTEM_USER_TOKEN="$(grep -E '^META_SYSTEM_USER_TOKEN=' "$IN" | head -1 | cut -d= -f2- || true)"
[ -n "$META_SYSTEM_USER_TOKEN" ] || { echo "STOP: $IN has no line META_SYSTEM_USER_TOKEN=<token> (one line, no spaces around =). Add it and re-run."; exit 1; }
export META_SYSTEM_USER_TOKEN SS_TENANT SS_EMAIL CRM_HOOK_URL FB_PAGE_ID

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail() { echo >&2 "STOP: $*"; echo >&2 "Nothing secret was printed. $IN is kept for a re-run."; exit 1; }

json() { python3 -c "import json,os,sys; print(json.dumps($1))"; }
# Read one top-level field from a saved response file (value goes to stdout for capture, never echoed by us).
field() { python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]) or '')" "$1" "$2"; }
# Short, safe error text: detail.code, or a plain string detail cut to 80 chars. Lists (validation errors, which
# echo the request input) and anything else print as "-".
errtext() { python3 -c "
import json,sys
try: d=json.load(open(sys.argv[1])).get('detail')
except Exception: d=None
if isinstance(d,dict): print(str(d.get('code') or '-')[:80])
elif isinstance(d,str): print(d[:80])
else: print('-')" "$1"; }
# call <METHOD> <url> <auth-header-file|-> <body-file|-> <out-file> -> sets HTTP_CODE; never prints bodies.
call() {
  local args=(-sS -o "$5" -w '%{http_code}' -X "$1" "$2" --max-time 30)
  [ "$3" != "-" ] && args+=(-H @"$3")
  [ "$4" != "-" ] && args+=(-H 'Content-Type: application/json' --data-binary @"$4")
  HTTP_CODE="$(curl "${args[@]}" 2>/dev/null || true)"
  [ -n "$HTTP_CODE" ] || HTTP_CODE=000
}
must2xx() { [ "${HTTP_CODE:0:1}" = "2" ] || fail "$1: HTTP $HTTP_CODE $(errtext "$2")"; }

# ---------- Preflight (read-only) ----------
case "$CRM_HOOK_URL" in https://*) ;; *) fail "CRM_HOOK_URL must start with https://";; esac
case "$FB_PAGE_ID" in *[!0-9]*|"") fail "FB_PAGE_ID must be digits only";; esac

# P1. CRM receiver reachable over https (any HTTP answer counts; a connection or TLS error does not). GET only.
call GET "$CRM_HOOK_URL" - - "$TMP/p1"
[ "$HTTP_CODE" != "000" ] || fail "CRM receiver $CRM_HOOK_URL is not reachable over https"
echo "preflight 1/5: CRM receiver reachable (HTTP $HTTP_CODE)"

# P2. The token really holds the Page: ask Meta directly for its name.
printf 'Authorization: Bearer %s\n' "$META_SYSTEM_USER_TOKEN" > "$TMP/meta"
call GET "$GRAPH_BASE/$GRAPH_VERSION/$FB_PAGE_ID?fields=name" "$TMP/meta" - "$TMP/p2"
[ "$HTTP_CODE" = "200" ] || fail "Meta refused the token for this Page (HTTP $HTTP_CODE). Check step 2 and the Page asset"
REAL_PAGE_NAME="$(field "$TMP/p2" name)"
[ -n "$REAL_PAGE_NAME" ] || fail "Meta returned no Page name"
echo "preflight 2/5: token holds the Page \"$REAL_PAGE_NAME\""

# P3. Admin session (24 h token, temp file only).
read -r -s -p "Shared Service password for $SS_EMAIL: " SS_PASSWORD; echo; export SS_PASSWORD
json "{'email':os.environ['SS_EMAIL'],'password':os.environ['SS_PASSWORD'],'tenantSlug':os.environ['SS_TENANT']}" > "$TMP/login.json"
unset SS_PASSWORD
call POST "$SS_BASE/auth/login" - "$TMP/login.json" "$TMP/p3"; rm -f "$TMP/login.json"
must2xx "sign-in" "$TMP/p3"
printf 'Authorization: Bearer %s\n' "$(field "$TMP/p3" access_token)" > "$TMP/admin"; rm -f "$TMP/p3"
echo "preflight 3/5: signed in"

# P4. Lead Capture active for this company (403 "Module not installed" otherwise) + current sources.
call GET "$SS_BASE/lead-capture/sources" "$TMP/admin" - "$TMP/p4"
[ "$HTTP_CODE" = "403" ] && fail "Lead Capture is not installed or not active for $SS_TENANT, or this login lacks lead_capture.view"
must2xx "list sources" "$TMP/p4"
SRC_STATE="$(python3 -c "
import json,sys
rows=[r for r in json.load(open(sys.argv[1])).get('data',[]) if r.get('pageId')==sys.argv[2] and r.get('status')=='LIVE']
if not rows: print('none')
elif any((r.get('pageName') or '').startswith('Dev Page ') for r in rows): print('dev')
else: print('real')" "$TMP/p4" "$FB_PAGE_ID")"
[ "$SRC_STATE" = "real" ] && fail "the Page is already connected (LIVE) for $SS_TENANT. Nothing to do"
echo "preflight 4/5: Lead Capture active (Page currently: $SRC_STATE)"

# P5. Re-run guard: never a second key or a second receiver (double delivery).
call GET "$SS_BASE/lead-capture/keys" "$TMP/admin" - "$TMP/p5"
must2xx "list keys" "$TMP/p5"
ACTIVE_KEYS="$(python3 -c "import json,sys; print(sum(1 for k in json.load(open(sys.argv[1])).get('data',[]) if not k.get('revokedAt')))" "$TMP/p5")"
HAVE_KEY=""; HAVE_SECRET=""
if [ -s "$OUT" ]; then
  HAVE_KEY="$(grep -E '^LC_API_KEY=fxl_live_' "$OUT" | head -1 | cut -d= -f2- || true)"
  HAVE_SECRET="$(grep -E '^LC_WHSEC_SECRET=whsec_' "$OUT" | head -1 | cut -d= -f2- || true)"
fi
if [ -z "$HAVE_KEY" ] && [ "$ACTIVE_KEYS" != "0" ]; then
  fail "$ACTIVE_KEYS active Lead Capture key(s) already exist and $OUT has none. Crew decides (revoke or restore) before a re-run"
fi
if [ -n "$HAVE_KEY" ]; then
  printf 'Authorization: Bearer %s\n' "$HAVE_KEY" > "$TMP/gw"
  call GET "$SS_BASE/api/v1/lead-capture/webhooks" "$TMP/gw" - "$TMP/p6"
  must2xx "list CRM receivers" "$TMP/p6"
  HOOKS="$(python3 -c "import json,sys; print(sum(1 for w in json.load(open(sys.argv[1])).get('data',[]) if w.get('url')==sys.argv[2]))" "$TMP/p6" "$CRM_HOOK_URL")"
  if [ "$HOOKS" != "0" ] && [ -z "$HAVE_SECRET" ]; then
    fail "a CRM receiver for this URL exists but its secret was not saved. Crew deletes it (DELETE /api/v1/lead-capture/webhooks/{id}) before a re-run"
  fi
  if [ "$HOOKS" = "0" ] && [ -n "$HAVE_SECRET" ]; then
    fail "$OUT has a receiver secret but no receiver exists for this URL. Crew checks before a re-run"
  fi
fi
echo "preflight 5/5: no duplicate key or receiver"

# ---------- Changes ----------
# Key: created only when none is saved; written to $OUT immediately so a later failure never loses it.
if [ -z "$HAVE_KEY" ]; then
  json "{'name':'Sorento CRM'}" > "$TMP/key.json"
  call POST "$SS_BASE/lead-capture/keys" "$TMP/admin" "$TMP/key.json" "$TMP/r2"
  must2xx "create key" "$TMP/r2"
  printf 'LC_API_KEY=%s\n' "$(field "$TMP/r2" key)" > "$OUT"; chmod 600 "$OUT"; rm -f "$TMP/r2"
  HAVE_KEY="$(grep -E '^LC_API_KEY=' "$OUT" | cut -d= -f2-)"
  printf 'Authorization: Bearer %s\n' "$HAVE_KEY" > "$TMP/gw"
  echo "1/3 key created (saved to $OUT)"
else
  echo "1/3 key already saved in $OUT, kept"
fi

# CRM receiver: registered only when no secret is saved; secret appended to $OUT immediately.
if [ -z "$HAVE_SECRET" ]; then
  json "{'url':os.environ['CRM_HOOK_URL'],'events':['lead.created']}" > "$TMP/hook.json"
  call POST "$SS_BASE/api/v1/lead-capture/webhooks" "$TMP/gw" "$TMP/hook.json" "$TMP/r3"
  must2xx "register CRM receiver" "$TMP/r3"
  printf 'LC_WHSEC_SECRET=%s\n' "$(field "$TMP/r3" secret)" >> "$OUT"; chmod 600 "$OUT"; rm -f "$TMP/r3"
  echo "2/3 CRM receiver registered (secret saved to $OUT)"
else
  echo "2/3 CRM receiver already registered, kept"
fi
unset HAVE_KEY HAVE_SECRET

# Page connect (a "dev" source from an earlier run is replaced in place by the same call).
json "{'pageId':os.environ['FB_PAGE_ID'],'systemUserToken':os.environ['META_SYSTEM_USER_TOKEN'],'formsMode':'all'}" > "$TMP/connect.json"
call POST "$SS_BASE/lead-capture/sources/facebook" "$TMP/admin" "$TMP/connect.json" "$TMP/r4"; rm -f "$TMP/connect.json"
must2xx "connect Page" "$TMP/r4"

# Verify it is a REAL connect: production without META_APP_ID/SECRET answers with a stand-in
# ("Dev Page <id>", dev token) instead of calling Meta.
GOT_NAME="$(field "$TMP/r4" pageName)"; GOT_STATUS="$(field "$TMP/r4" status)"
if [ -z "$GOT_NAME" ] || [ "${GOT_NAME#Dev Page }" != "$GOT_NAME" ] || [ "$GOT_STATUS" != "LIVE" ]; then
  fail "production answered with a stand-in connect (Page name \"${GOT_NAME:-empty}\", status \"${GOT_STATUS:-empty}\"): its Meta app settings are missing. Crew sets META_APP_ID/META_APP_SECRET in production, then re-run (the re-run replaces this source in place)"
fi
[ "$GOT_NAME" = "$REAL_PAGE_NAME" ] || fail "connected Page name \"$GOT_NAME\" differs from Meta's \"$REAL_PAGE_NAME\". Crew checks before going on"
echo "3/3 connected: $GOT_NAME - LIVE"

unset META_SYSTEM_USER_TOKEN
rm -f "$IN"
echo "Done. Token file deleted. Next: paste LC_WHSEC_SECRET from $OUT into the CRM (step 4), then delete $OUT."
