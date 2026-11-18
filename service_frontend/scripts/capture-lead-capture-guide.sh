#!/usr/bin/env bash
# Re-capture the screenshots + walkthrough video of the public Lead Capture
# guide (/public/lead-capture/guide) from the REAL hosted wizard, on the
# simulated Facebook path, with fake data (lane META-LEADS-GUIDE-PAGE).
#
#   npm run capture:lead-capture-guide
#
# Needs (see documentation/plans/meta-leads/guide-page/README.md):
# - a LOCAL dev stack only: backend on SS_BACKEND (default
#   http://localhost:8001) with NO Meta app configured (META_APP_ID unset =
#   the simulated Facebook path: "Sample Home Page", "Sample lead form") and
#   the dev seed; frontend on SS_FRONTEND (default http://localhost:3001),
#   freshly built;
# - the agent-browser CLI (AGENT_BROWSER=<path>, else `npx agent-browser`).
#
# Each run provisions its own fresh tenant with the FAKE partner name
# "Partner CRM" through the dev operator login (SS_PLATFORM_EMAIL /
# SS_PLATFORM_PASSWORD, default the dev seed's platform operator), installs
# Lead Capture, and mints a gateway key listing SS_FRONTEND - so the wizard
# runs exactly as a partner's "Connect" button opens it. Nothing is written
# outside the local stack; the key lives in memory for this run only.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="${SS_FRONTEND:-http://localhost:3001}"
BACKEND="${SS_BACKEND:-http://localhost:8001}"
PLATFORM_EMAIL="${SS_PLATFORM_EMAIL:-platform@example.com}"
PLATFORM_PASSWORD="${SS_PLATFORM_PASSWORD:-platform1234}"
PARTNER_NAME="Partner CRM"
OUT="$HERE/public/media/lead-capture-guide"
MANIFEST="$HERE/lib/lead-capture-guide-shots.json"
WIDTH=760
HEIGHT=720
SESSION="lead-capture-guide-$$"

# A fresh capture tenant + its gateway key (dev operator API).
KEY="$(SS_BACKEND="$BACKEND" SS_FRONTEND="$FRONTEND" PLATFORM_EMAIL="$PLATFORM_EMAIL" \
  PLATFORM_PASSWORD="$PLATFORM_PASSWORD" PARTNER_NAME="$PARTNER_NAME" node - <<'NODE'
const env = process.env;
const base = env.SS_BACKEND;
async function call(method, path, token, body) {
  const res = await fetch(base + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status} ${await res.text()}`);
  return res.json();
}
(async () => {
  const stamp = Date.now().toString(36);
  const slug = `partner-crm-${stamp}`;
  const password = `Capture-${stamp}-9x!`;
  const op = await call('POST', '/auth/login', null, {
    email: env.PLATFORM_EMAIL, password: env.PLATFORM_PASSWORD, tenantSlug: 'platform',
  });
  const tenant = await call('POST', '/platform/tenants', op.access_token, {
    name: env.PARTNER_NAME, slug, adminName: 'Test Admin',
    adminEmail: `test.admin+${stamp}@example.com`, adminPassword: password,
  });
  await call('POST', `/platform/tenants/${tenant.id}/modules/lead_capture/install`, op.access_token);
  const admin = await call('POST', '/auth/login', null, {
    email: `test.admin+${stamp}@example.com`, password, tenantSlug: slug,
  });
  const key = await call('POST', '/lead-capture/keys', admin.access_token, {
    name: 'Guide capture', allowedOrigins: [env.SS_FRONTEND],
  });
  process.stdout.write(key.key);
})().catch((err) => { console.error(String(err)); process.exit(1); });
NODE
)"
[[ "$KEY" == fxl_live_* ]] || { echo "Could not set up the capture tenant." >&2; exit 1; }

read -r -a AB_CMD <<< "${AGENT_BROWSER:-npx --yes agent-browser@0.43.0}"
ab() { "${AB_CMD[@]}" --session "$SESSION" "$@"; }

# Leave the simulated Page free for the next run: disconnect every source of
# this run's own capture tenant (leads are kept).
release_page() {
  [[ "${KEY:-}" == fxl_live_* ]] || return 0
  LC_KEY="$KEY" LC_BASE="$BACKEND/api/v1/lead-capture" node -e '
    const h = { Authorization: "Bearer " + process.env.LC_KEY };
    fetch(process.env.LC_BASE + "/sources", { headers: h })
      .then((r) => r.json())
      .then((b) => Promise.all(b.data.filter((s) => s.status !== "DISCONNECTED")
        .map((s) => fetch(process.env.LC_BASE + "/sources/" + s.id, { method: "DELETE", headers: h }))));' || true
}

cleanup() {
  ab close >/dev/null 2>&1 || true
  release_page
}
trap cleanup EXIT

mkdir -p "$OUT"
WORK="$(mktemp -d)"
STEPS_JSON="$WORK/steps.ndjson"
CAPTIONS="$WORK/captions.tsv"
: > "$STEPS_JSON"
: > "$CAPTIONS"

# 1. A one-time wizard link, exactly as a partner backend asks for it.
URL="$(curl -fsS -X POST "$BACKEND/api/v1/lead-capture/connect-sessions" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d "{\"returnOrigin\": \"$FRONTEND\"}" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>process.stdout.write(JSON.parse(s).url))')"
# The backend builds the link on its own FRONTEND_URL; capture against ours.
URL="$FRONTEND/public/lead-capture/connect#${URL#*#}"

# Box of the visible button/option whose text is exactly $1, in viewport px,
# after scrolling it into the middle of the screen.
box_of() {
  ab eval "(() => {
    const want = $(node -e 'process.stdout.write(JSON.stringify(process.argv[1]))' "$1");
    const els = Array.from(document.querySelectorAll('button, [role=button], [role=option], a'));
    const el = els.find((e) => e.offsetParent !== null && e.textContent.trim() === want)
      || els.find((e) => e.offsetParent !== null && e.textContent.trim().startsWith(want));
    if (!el) return 'null';
    el.scrollIntoView({ block: 'center' });
    const r = el.getBoundingClientRect();
    return JSON.stringify({ x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) });
  })()" | tail -n 1 | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>process.stdout.write(String(JSON.parse(s))))'
}

T0=""
now() { node -e 'process.stdout.write(String(Date.now()/1000))'; }
caption() { printf '%s\t%s\n' "$(node -e "process.stdout.write(String(Date.now()/1000 - $T0))")" "$1" >> "$CAPTIONS"; }

# shot <key> <button text> <caption>: screenshot with the button's box recorded.
shot() {
  local key="$1" label="$2"
  local box
  box="$(box_of "$label")"
  [[ "$box" == "null" || -z "$box" ]] && { echo "Button not found: $label" >&2; exit 1; }
  sleep 0.4
  ab screenshot "$OUT/$key.png" >/dev/null
  printf '{"key":"%s","file":"media/lead-capture-guide/%s.png","width":%d,"height":%d,"box":%s}\n' \
    "$key" "$key" "$WIDTH" "$HEIGHT" "$box" >> "$STEPS_JSON"
  caption "$3"
  sleep "${STEP_PAUSE:-2.2}"
}

# A real mouse click in the middle of the button (shows in the video).
click_text() {
  local box cx cy
  box="$(box_of "$1")"
  [[ "$box" == "null" || -z "$box" ]] && { echo "Button not found: $1" >&2; exit 1; }
  read -r cx cy < <(node -e 'const b=JSON.parse(process.argv[1]);process.stdout.write(`${Math.round(b.x+b.width/2)} ${Math.round(b.y+b.height/2)}\n`)' "$box")
  ab mouse move "$cx" "$cy" >/dev/null
  sleep 0.3
  ab mouse down >/dev/null
  ab mouse up >/dev/null
}
wait_text() { ab wait --text "$1" >/dev/null; }

ab set viewport "$WIDTH" "$HEIGHT" >/dev/null
ab open "about:blank" >/dev/null
ab record start "$OUT/walkthrough.webm" --fps 12 >/dev/null
T0="$(now)"
ab open "$URL" >/dev/null
wait_text 'Where do the leads come from?'

shot channel 'Facebook' 'Click Facebook'
click_text 'Facebook'
wait_text 'Continue with Facebook'

shot signin 'Continue with Facebook' 'Click Continue with Facebook and sign in'
click_text 'Continue with Facebook'
wait_text 'Connect Page'
# Two simulated Pages: pick the first one.
click_text 'Pick a Page'
sleep 0.5
click_text 'Sample Home Page'

shot page 'Connect Page' 'Pick the Page and click Connect Page'
click_text 'Connect Page'
wait_text 'Save forms'

shot forms 'Save forms' 'Keep all forms and click Save forms'
click_text 'Save forms'
wait_text 'Save fields'

shot fields 'Save fields' 'Match the questions and click Save fields'
click_text 'Save fields'
wait_text 'Send test lead'

shot test 'Send test lead' 'Click Send test lead'
click_text 'Send test lead'
wait_text 'Finish setup'

shot finish 'Finish setup' 'Click Finish setup'
click_text 'Finish setup'
wait_text 'is connected'

shot done 'Done' 'Click Done: the Page is now Live'
sleep 1.5
caption ''
ab record stop >/dev/null

# 2. WebVTT captions: each caption runs until the next one starts.
node - "$CAPTIONS" "$OUT/walkthrough.vtt" <<'NODE'
const fs = require('fs');
const [, , src, dest] = process.argv;
const rows = fs.readFileSync(src, 'utf8').trim().split('\n').map((l) => l.split('\t'));
const ts = (s) => {
  const ms = Math.max(0, Math.round(Number(s) * 1000));
  const p = (n, w = 2) => String(n).padStart(w, '0');
  return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)}.${p(ms % 1000, 3)}`;
};
let out = 'WEBVTT\n';
rows.forEach(([start, text], i) => {
  if (!text || !rows[i + 1]) return;
  out += `\n${i + 1}\n${ts(Number(start))} --> ${ts(rows[i + 1][0])}\n${text}\n`;
});
fs.writeFileSync(dest, out);
NODE

# 3. The manifest the guide reads.
node - "$STEPS_JSON" "$MANIFEST" "$WIDTH" "$HEIGHT" <<'NODE'
const fs = require('fs');
const [, , src, dest, width, height] = process.argv;
const steps = {};
for (const line of fs.readFileSync(src, 'utf8').trim().split('\n')) {
  const { key, ...rest } = JSON.parse(line);
  steps[key] = rest;
}
const manifest = {
  viewport: { width: Number(width), height: Number(height) },
  video: 'media/lead-capture-guide/walkthrough.webm',
  captions: 'media/lead-capture-guide/walkthrough.vtt',
  steps,
};
fs.writeFileSync(dest, JSON.stringify(manifest, null, 2) + '\n');
NODE

rm -rf "$WORK"
SIZE=$(wc -c < "$OUT/walkthrough.webm")
echo "Captured $(ls "$OUT"/*.png | wc -l) screenshots; video $((SIZE / 1024)) KB."
if (( SIZE >= 5 * 1024 * 1024 )); then
  echo "Video is 5 MB or more: lower --fps or shorten the run." >&2
  exit 1
fi
