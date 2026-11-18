#!/usr/bin/env bash
# Re-capture the screenshots + walkthrough video of the public Lead Capture
# guide (/public/lead-capture/guide) from the REAL hosted wizard, on the
# simulated Facebook path, with fake data (lane META-LEADS-GUIDE-PAGE).
#
#   npm run capture:lead-capture-guide
#
# Needs (see documentation/plans/meta-leads/guide-page/README.md):
# - a LOCAL dev stack only (the script refuses any other host): backend on
#   SS_BACKEND (default http://localhost:8001) with NO Meta app configured
#   (META_APP_ID unset = the simulated Facebook path: "Sample Home Page",
#   "Sample lead form") and the dev seed; frontend on SS_FRONTEND (default
#   http://localhost:3001), freshly built;
# - the agent-browser CLI (AGENT_BROWSER=<path>, else `npx agent-browser`).
#
# Each run provisions its own fresh tenant with the FAKE partner name
# "Partner CRM" through the dev operator login (SS_PLATFORM_EMAIL /
# SS_PLATFORM_PASSWORD, default the dev seed's platform operator), installs
# Lead Capture and mints a gateway key listing SS_FRONTEND, so the wizard runs
# exactly as a partner's "Connect" button opens it. The key and tokens live in
# this process's environment only (never on a command line, never on disk) and
# the key is revoked at the end. Output is staged and only replaces the
# committed files when every step and the 5 MB video gate passed.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="${SS_FRONTEND:-http://localhost:3001}"
BACKEND="${SS_BACKEND:-http://localhost:8001}"
OUT="$HERE/public/media/lead-capture-guide"
MANIFEST="$HERE/lib/lead-capture-guide-shots.json"
WIDTH=760
HEIGHT=720
MAX_VIDEO_BYTES=$((5 * 1024 * 1024))
SESSION="lead-capture-guide-$$"

is_local() { [[ "$1" =~ ^http://(localhost|127\.0\.0\.1|[a-z0-9-]+\.localhost)(:[0-9]+)?/?$ ]]; }
if ! is_local "$FRONTEND" || ! is_local "$BACKEND"; then
  echo "Local dev stack only: SS_FRONTEND and SS_BACKEND must be http://localhost[:port]." >&2
  exit 1
fi

read -r -a AB_CMD <<< "${AGENT_BROWSER:-npx --yes agent-browser@0.43.0}"
ab() { "${AB_CMD[@]}" --session "$SESSION" "$@"; }

WORK="$(mktemp -d)"
STAGE="$WORK/out"
mkdir -p "$STAGE"
STEPS_JSON="$WORK/steps.ndjson"
CAPTIONS="$WORK/captions.tsv"
: > "$STEPS_JSON"
: > "$CAPTIONS"

export LC_BACKEND="$BACKEND" LC_FRONTEND="$FRONTEND"
export LC_PLATFORM_EMAIL="${SS_PLATFORM_EMAIL:-platform@example.com}"
export LC_PLATFORM_PASSWORD="${SS_PLATFORM_PASSWORD:-platform1234}"

# api <step>: one Lead Capture setup/clean-up call, done in node so the key
# and tokens are read from the environment (never an argv). Prints the result.
api() {
  LC_STEP="$1" node - <<'NODE'
const env = process.env;
async function call(method, path, token, body) {
  const res = await fetch(env.LC_BACKEND + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.status === 204 ? null : res.json();
}
const steps = {
  // A fresh capture tenant named with the fake partner name + its key.
  async setup() {
    const stamp = Date.now().toString(36);
    const slug = `partner-crm-${stamp}`;
    const email = `test.admin+${stamp}@example.com`;
    const password = `Capture-${stamp}-9x!`;
    const op = await call('POST', '/auth/login', null, {
      email: env.LC_PLATFORM_EMAIL, password: env.LC_PLATFORM_PASSWORD, tenantSlug: 'platform',
    });
    const tenant = await call('POST', '/platform/tenants', op.access_token, {
      name: 'Partner CRM', slug, adminName: 'Test Admin', adminEmail: email, adminPassword: password,
    });
    await call('POST', `/platform/tenants/${tenant.id}/modules/lead_capture/install`, op.access_token);
    const admin = await call('POST', '/auth/login', null, { email, password, tenantSlug: slug });
    const key = await call('POST', '/lead-capture/keys', admin.access_token, {
      name: 'Guide capture', allowedOrigins: [env.LC_FRONTEND],
    });
    // Shell-safe: three tokens with no spaces, one line.
    return `${key.key} ${key.id} ${admin.access_token}`;
  },
  // A one-time wizard link, exactly as a partner backend asks for it.
  async session() {
    const auth = { Authorization: `Bearer ${env.LC_KEY}`, 'Content-Type': 'application/json' };
    const res = await fetch(`${env.LC_BACKEND}/api/v1/lead-capture/connect-sessions`, {
      method: 'POST', headers: auth, body: JSON.stringify({ returnOrigin: env.LC_FRONTEND }),
    });
    if (!res.ok) throw new Error(`connect-sessions -> ${res.status}`);
    return (await res.json()).url;
  },
  // Leave the simulated Page free for the next run (disconnect this tenant's
  // sources; leads are kept), then revoke the key.
  async release() {
    const h = { Authorization: `Bearer ${env.LC_KEY}` };
    const list = await (await fetch(`${env.LC_BACKEND}/api/v1/lead-capture/sources`, { headers: h })).json();
    for (const s of list.data ?? []) {
      if (s.status !== 'DISCONNECTED') {
        await fetch(`${env.LC_BACKEND}/api/v1/lead-capture/sources/${s.id}`, { method: 'DELETE', headers: h });
      }
    }
    await call('DELETE', `/lead-capture/keys/${env.LC_KEY_ID}`, env.LC_ADMIN_TOKEN);
    return 'released';
  },
};
steps[env.LC_STEP]()
  .then((out) => process.stdout.write(String(out)))
  .catch((err) => { console.error(String(err)); process.exit(1); });
NODE
}

cleanup() {
  ab close >/dev/null 2>&1 || true
  if [[ -n "${LC_KEY:-}" ]]; then api release >/dev/null || echo "Clean-up failed: disconnect the capture tenant's source." >&2; fi
  rm -rf "$WORK"
}
trap cleanup EXIT

read -r LC_KEY LC_KEY_ID LC_ADMIN_TOKEN <<< "$(api setup)"
export LC_KEY LC_KEY_ID LC_ADMIN_TOKEN
[[ "$LC_KEY" == fxl_live_* ]] || { echo "Could not set up the capture tenant." >&2; exit 1; }

URL="$(api session)"
# The backend builds the link on its own FRONTEND_URL; capture against ours.
URL="$FRONTEND/public/lead-capture/connect#${URL#*#}"

# Box of the visible button/option whose text is $1, in viewport px, after
# scrolling it into the middle of the screen. Prints JSON or "null".
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
  local key="$1" label="$2" box
  box="$(box_of "$label")"
  [[ "$box" == "null" || -z "$box" ]] && { echo "Button not found: $label" >&2; exit 1; }
  sleep 0.4
  ab screenshot "$STAGE/$key.png" >/dev/null
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
ab record start "$STAGE/walkthrough.webm" --fps 12 >/dev/null
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

SIZE=$(wc -c < "$STAGE/walkthrough.webm")
if (( SIZE >= MAX_VIDEO_BYTES )); then
  echo "Video is 5 MB or more ($((SIZE / 1024)) KB): lower --fps or STEP_PAUSE. Nothing replaced." >&2
  exit 1
fi

# WebVTT captions: each caption runs until the next one starts.
node - "$CAPTIONS" "$STAGE/walkthrough.vtt" <<'NODE'
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

# The manifest the guide reads.
node - "$STEPS_JSON" "$WORK/manifest.json" "$WIDTH" "$HEIGHT" <<'NODE'
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

# Every step passed: publish the staged set as one.
mkdir -p "$OUT"
rm -f "$OUT"/*.png "$OUT"/walkthrough.webm "$OUT"/walkthrough.vtt
cp "$STAGE"/* "$OUT"/
cp "$WORK/manifest.json" "$MANIFEST"
echo "Captured $(ls "$OUT"/*.png | wc -l) screenshots; video $((SIZE / 1024)) KB."
