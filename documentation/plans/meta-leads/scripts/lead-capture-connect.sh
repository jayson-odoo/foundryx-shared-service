#!/usr/bin/env bash
# Step 3 of the Meta leads switch-on: create the Lead Capture key, register the CRM receiver, connect the Foundryx Page.
# Runs on the owner's Mac. Prints NO secrets: the admin password is typed hidden, every token stays in memory or in
# chmod 600 temp files that are deleted on exit. Needs: bash, curl, python3 (macOS has all three).
#
# Inputs:
#   ~/.config/crew/secrets/meta-leads.env (chmod 600), lines:
#     META_SYSTEM_USER_TOKEN=<token from Meta Business Settings, step 2>
#   Environment variables (not secret; crew fills them):
#     SS_BASE         production Shared Service backend, e.g. https://<prod host>/be
#     SS_TENANT       the Sorento company's tenant slug in Shared Service
#     SS_EMAIL        Admin login email of that company (password is asked, hidden)
#     CRM_HOOK_URL    the Sorento CRM Lead Capture receiver URL (from sorento-crm #2449)
#     FB_PAGE_ID      the Foundryx Page id (S-META-result.md)
# Output:
#   ~/.config/crew/secrets/meta-leads-out.env (chmod 600): LC_API_KEY=fxl_live_..., LC_WHSEC_SECRET=whsec_...
#   Paste LC_WHSEC_SECRET into the CRM (step 4), then delete both files.
set -euo pipefail
umask 077

IN="$HOME/.config/crew/secrets/meta-leads.env"
OUT="$HOME/.config/crew/secrets/meta-leads-out.env"
: "${SS_BASE:?set SS_BASE}" "${SS_TENANT:?set SS_TENANT}" "${SS_EMAIL:?set SS_EMAIL}"
: "${CRM_HOOK_URL:?set CRM_HOOK_URL}" "${FB_PAGE_ID:?set FB_PAGE_ID}"
[ -f "$IN" ] || { echo "missing $IN"; exit 1; }
META_SYSTEM_USER_TOKEN="$(grep -E '^META_SYSTEM_USER_TOKEN=' "$IN" | head -1 | cut -d= -f2-)"
[ -n "$META_SYSTEM_USER_TOKEN" ] || { echo "META_SYSTEM_USER_TOKEN not set in $IN"; exit 1; }
export META_SYSTEM_USER_TOKEN SS_TENANT SS_EMAIL CRM_HOOK_URL FB_PAGE_ID

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

json() { python3 -c "import json,os,sys; print(json.dumps($1))"; }
field() { python3 -c "import json,sys; print(json.load(sys.stdin).get('$1',''))"; }
post() { # post <path> <auth-header-file> <body-file> -> body on stdout, fails on non-2xx with the status + error code only
  local code
  code="$(curl -sS -o "$TMP/resp" -w '%{http_code}' -X POST "$SS_BASE$1" -H @"$2" \
    -H 'Content-Type: application/json' --data-binary @"$3")"
  if [ "${code:0:1}" != "2" ]; then
    echo >&2 "FAILED $1: HTTP $code $(python3 -c "import json,sys
try: d=json.load(open('$TMP/resp')).get('detail'); print(d.get('code') if isinstance(d,dict) else d)
except Exception: print('')")"; exit 1
  fi
  cat "$TMP/resp"
}

read -r -s -p "Shared Service password for $SS_EMAIL: " SS_PASSWORD; echo; export SS_PASSWORD

# 1. Admin session (24h JWT, memory/temp file only)
json "{'email':os.environ['SS_EMAIL'],'password':os.environ['SS_PASSWORD'],'tenantSlug':os.environ['SS_TENANT']}" > "$TMP/login.json"
echo "Content-Type: application/json" > "$TMP/noauth"
post /auth/login "$TMP/noauth" "$TMP/login.json" > "$TMP/r1"
JWT="$(field access_token < "$TMP/r1")"
unset SS_PASSWORD
printf 'Authorization: Bearer %s\n' "$JWT" > "$TMP/admin"; unset JWT
echo "1/3 signed in"

# 2+3. Lead Capture key (fxl_live_) and CRM receiver (whsec_ secret), both shown once.
# Skipped on a re-run when $OUT already holds them, so a retry never makes a second key or receiver.
if [ -s "$OUT" ] && grep -q '^LC_WHSEC_SECRET=whsec_' "$OUT"; then
  echo "2/3 key and CRM receiver already created earlier (kept in $OUT), skipping"
else
  json "{'name':'Sorento CRM'}" > "$TMP/key.json"
  post /lead-capture/keys "$TMP/admin" "$TMP/key.json" > "$TMP/r2"
  LC_API_KEY="$(field key < "$TMP/r2")"
  printf 'Authorization: Bearer %s\n' "$LC_API_KEY" > "$TMP/gw"
  json "{'url':os.environ['CRM_HOOK_URL'],'events':['lead.created']}" > "$TMP/hook.json"
  post /api/v1/lead-capture/webhooks "$TMP/gw" "$TMP/hook.json" > "$TMP/r3"
  LC_WHSEC_SECRET="$(field secret < "$TMP/r3")"
  printf 'LC_API_KEY=%s\nLC_WHSEC_SECRET=%s\n' "$LC_API_KEY" "$LC_WHSEC_SECRET" > "$OUT"; chmod 600 "$OUT"
  unset LC_API_KEY LC_WHSEC_SECRET
  echo "2/3 key created, CRM receiver registered (secrets saved to $OUT)"
fi

# 4. Connect the Foundryx Page with the system-user token
json "{'pageId':os.environ['FB_PAGE_ID'],'systemUserToken':os.environ['META_SYSTEM_USER_TOKEN'],'formsMode':'all'}" > "$TMP/connect.json"
post /lead-capture/sources/facebook "$TMP/admin" "$TMP/connect.json" > "$TMP/r4"
python3 -c "import json,sys; d=json.load(sys.stdin); print('3/3 connected:', d.get('pageName') or d.get('name'), '- status', d.get('status'))" < "$TMP/r4"
unset META_SYSTEM_USER_TOKEN
rm -f "$IN"
echo "Done. Token file deleted. Next: paste LC_WHSEC_SECRET from $OUT into the CRM (step 4), then delete $OUT."
