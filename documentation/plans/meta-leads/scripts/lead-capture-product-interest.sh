#!/usr/bin/env bash
# Owner ruling 17 Nov (ask a53007814 = b): fill the CRM's Product interest from a Meta form answer, for one product
# (Sorento = tenant "chat"). Two staff calls: publish the product's field list including product_interest, then map
# the form question to it for every form ("*").
# Dry run by default (reads and prints the plan only); APPLY=1 makes the two changes. Prints no secrets.
#
# Environment (not secret):
#   SS_BASE        https://chat.foundryx.my/be
#   SS_TENANT      chat
#   SS_EMAIL       the Sorento company's Admin email (password asked, hidden)
#   FB_PAGE_ID     1407353105803175
#   QUESTION_KEY   the form question's key, e.g. "interest" (read it from a delivered lead's Notes line
#                  "<key>: <answer>" in the CRM, or from answers[].key)
#   APPLY          1 to apply, anything else = dry run
set -euo pipefail
umask 077
: "${SS_BASE:?}" "${SS_TENANT:?}" "${SS_EMAIL:?}" "${FB_PAGE_ID:?}" "${QUESTION_KEY:?}"
SS_BASE="${SS_BASE%/}"
case "$QUESTION_KEY" in *[!A-Za-z0-9_]*|"") echo "STOP: QUESTION_KEY must be letters, digits or _"; exit 1;; esac
export SS_TENANT SS_EMAIL FB_PAGE_ID QUESTION_KEY
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail() { echo >&2 "STOP: $*"; exit 1; }
call() { # METHOD URL HEADERFILE|- BODYFILE|- OUT
  local a=(-sS -o "$5" -w '%{http_code}' -X "$1" "$2" --max-time 30)
  [ "$3" != "-" ] && a+=(-H @"$3"); [ "$4" != "-" ] && a+=(-H 'Content-Type: application/json' --data-binary @"$4")
  HTTP_CODE="$(curl "${a[@]}" 2>/dev/null || true)"; [ -n "$HTTP_CODE" ] || HTTP_CODE=000
}
must2xx() { [ "${HTTP_CODE:0:1}" = "2" ] || fail "$1: HTTP $HTTP_CODE $(python3 -c "
import json,sys
try: d=json.load(open(sys.argv[1])).get('detail')
except Exception: d=None
print(str(d.get('code') or '-')[:80] if isinstance(d,dict) else (d[:80] if isinstance(d,str) else '-'))" "$2")"; }

read -r -s -p "Shared Service password for $SS_EMAIL: " SS_PASSWORD; echo; export SS_PASSWORD
python3 -c "import json,os; print(json.dumps({'email':os.environ['SS_EMAIL'],'password':os.environ['SS_PASSWORD'],'tenantSlug':os.environ['SS_TENANT']}))" > "$TMP/login.json"
unset SS_PASSWORD
call POST "$SS_BASE/auth/login" - "$TMP/login.json" "$TMP/l"; rm -f "$TMP/login.json"; must2xx "sign-in" "$TMP/l"
printf 'Authorization: Bearer %s\n' "$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['access_token'])" "$TMP/l")" > "$TMP/admin"; rm -f "$TMP/l"

# Read the current field list and the Page's source.
call GET "$SS_BASE/lead-capture/fields" "$TMP/admin" - "$TMP/f"; must2xx "read fields" "$TMP/f"
call GET "$SS_BASE/lead-capture/sources" "$TMP/admin" - "$TMP/s"; must2xx "read sources" "$TMP/s"
python3 - "$TMP/f" "$TMP/s" "$TMP" <<'PY'
import json, os, sys
fields = json.load(open(sys.argv[1])); sources = json.load(open(sys.argv[2])).get("data", [])
page, q = os.environ["FB_PAGE_ID"], os.environ["QUESTION_KEY"]
src = [s for s in sources if s.get("pageId") == page and s.get("status") in ("LIVE", "WAITING_FOR_TEST")]
if len(src) != 1:
    sys.exit(f"STOP: expected one live source for the Page, found {len(src)}")
cur = [{"key": f["key"], "label": f.get("label", ""), "type": f.get("type", "text")} for f in fields.get("data", [])]
print("current fields:", [f["key"] for f in cur], "(defaults)" if fields.get("isDefault") else "")
# Keep every existing field; add product_interest if missing. The CRM reads name/phone/email/notes/product_interest.
new = list(cur)
if not any(f["key"] == "product_interest" for f in new):
    i = next((n for n, f in enumerate(new) if f["type"] == "notes"), len(new))
    new.insert(i, {"key": "product_interest", "label": "Product interest", "type": "text"})
fm = {"formId": "*", "map": {**(src[0].get("fieldMap", {}).get("*", {}) or {}), q: "product_interest"}}
print("new fields:    ", [f["key"] for f in new])
print("source", src[0]["id"], "page", src[0].get("pageName"), "map for every form:", fm["map"])
json.dump(new, open(os.path.join(sys.argv[3], "newfields.json"), "w"))
json.dump(fm, open(os.path.join(sys.argv[3], "map.json"), "w"))
open(os.path.join(sys.argv[3], "sid"), "w").write(src[0]["id"])
PY
[ "${APPLY:-}" = "1" ] || { echo "Dry run only. Re-run with APPLY=1 to make these two changes."; exit 0; }

call PUT "$SS_BASE/lead-capture/fields" "$TMP/admin" "$TMP/newfields.json" "$TMP/r1"; must2xx "publish fields" "$TMP/r1"
echo "1/2 fields published"
call PUT "$SS_BASE/lead-capture/sources/$(cat "$TMP/sid")/field-map" "$TMP/admin" "$TMP/map.json" "$TMP/r2"; must2xx "save field map" "$TMP/r2"
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print('2/2 field map saved:', d.get('fieldMap'))" "$TMP/r2"
echo "Done. Next: send one test lead (Meta Lead Ads Testing Tool) and check Product interest on the new CRM lead."
