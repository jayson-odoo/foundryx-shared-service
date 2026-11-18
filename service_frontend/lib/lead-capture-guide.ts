/**
 * Public Lead Capture guide (lane META-LEADS-GUIDE-PAGE): the page's content
 * as data, so a wizard change is one edit here (and the screenshots are
 * re-captured by `npm run capture:lead-capture-guide`).
 *
 * The wizard step titles come from `WIZARD_STEPS` (the wizard's own list), so
 * a renamed step renames the guide. Every sample is fake and every host is
 * built from configuration, never typed in. The contract of record stays
 * `documentation/lead-capture/consumer-integration-guide.md`.
 */
import { WIZARD_STEPS, type WizardStepKey } from '@/lib/lead-capture-wizard';

/** Fake partner web address used in every sample. */
export const SAMPLE_PARTNER_ORIGIN = 'https://app.partner.example';

/** `<backend>/api/v1/lead-capture` (in production the backend URL already
 * carries the `/be` proxy prefix). */
export function guideApiBase(env: Record<string, string | undefined> = process.env): string {
  const backend = (env.NEXT_PUBLIC_BACKEND_API_URL || 'http://localhost:8001').replace(/\/+$/, '');
  return `${backend}/api/v1/lead-capture`;
}

export interface DeveloperSamples {
  connectSession: string;
  popup: string;
  pull: string;
  pullAnswer: string;
  webhook: string;
  webhookBody: string;
  verify: string;
  fields: string;
}

export function developerSamples(apiBase: string): DeveloperSamples {
  return {
    connectSession: [
      `POST ${apiBase}/connect-sessions`,
      'Authorization: Bearer fxl_live_...',
      'Content-Type: application/json',
      '',
      `{"returnOrigin": "${SAMPLE_PARTNER_ORIGIN}"}`,
      '',
      '-> 201 {"url": "https://<shared-service>/public/lead-capture/connect#s=...",',
      '        "expiresAt": "2026-11-18T03:30:00Z"}',
    ].join('\n'),
    popup: [
      '// On the click: open the window first (a popup opened after an await is blocked),',
      '// then ask your backend for the link and send the window there.',
      "const popup = window.open('', 'lead_capture', 'popup,width=720,height=860');",
      "const { url } = await fetch('/your-backend/lead-capture/connect-link', { method: 'POST' }).then((r) => r.json());",
      'popup.location.href = url;',
      'const sharedService = new URL(url).origin;',
      "window.addEventListener('message', (event) => {",
      '  if (event.origin !== sharedService) return;',
      "  if (event.data?.type === 'lead-capture:done' || event.data?.type === 'lead-capture:closed') {",
      `    refreshConnectedPages();   // GET ${apiBase}/sources`,
      '  }',
      '});',
    ].join('\n'),
    pull: [`GET ${apiBase}/leads?cursor=<saved cursor>`, 'Authorization: Bearer fxl_live_...'].join('\n'),
    pullAnswer: [
      '{',
      '  "data": [{',
      '    "id": "e3a10000-0000-0000-0000-000000000001",',
      '    "sourceId": "4c1f0000-0000-0000-0000-000000000001",',
      '    "sourceName": "Sample Home Page",',
      '    "platform": "facebook",',
      '    "formName": "Sample lead form",',
      '    "receivedAt": "2026-11-18T03:20:05Z",',
      '    "createdAt": "2026-11-18T03:20:00Z",',
      '    "isTest": false,',
      '    "duplicateOf": null,',
      '    "fields": {"name": "Test Person", "phone": "+60120000000",',
      '               "email": "test.person@example.com",',
      '               "notes": "property_type: Condominium\\nbudget: 500k - 800k"},',
      '    "answers": [...], "attribution": {...}, "platformLeadId": "...", "pageId": "...", "formId": "..."',
      '  }],',
      '  "nextCursor": "WyIyMDI2LTExLTE4VDAzOjIwOjA1...",',
      '  "hasMore": false',
      '}',
    ].join('\n'),
    webhook: [
      `POST ${apiBase}/webhooks`,
      'Authorization: Bearer fxl_live_...',
      '',
      `{"url": "${SAMPLE_PARTNER_ORIGIN}/hooks/leads", "events": ["lead.created", "source.updated"]}`,
      '',
      '-> 201 {"id": "...", "url": "...", "events": [...], "secret": "whsec_..."}   // secret shown once: keep it',
    ].join('\n'),
    webhookBody: [
      'POST <your url>',
      'X-Lead-Capture-Event: lead.created',
      'X-Lead-Capture-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256>',
      '',
      '{"id": "<event id>", "type": "lead.created", "occurredAt": "2026-11-18T03:20:05Z",',
      ' "data": { <the same lead as in the pull, with its own id> }}',
    ].join('\n'),
    verify: [
      'import hashlib, hmac, time',
      '',
      'def verify(secret, header, raw_body):',
      '    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)',
      '    t, v1 = parts.get("t", ""), parts.get("v1", "")',
      '    if not t.isdigit() or abs(time.time() - int(t)) > 300:',
      '        return False',
      '    expected = hmac.new(secret.encode(), t.encode() + b"." + raw_body, hashlib.sha256).hexdigest()',
      '    return hmac.compare_digest(expected, v1)',
    ].join('\n'),
    fields: [
      `PUT ${apiBase}/fields`,
      'Authorization: Bearer fxl_live_...',
      '',
      '[{"key": "property_type", "label": "Property type", "type": "text"},',
      ' {"key": "budget_range",  "label": "Budget range",  "type": "text"},',
      ' {"key": "remarks",       "label": "Remarks",       "type": "notes"}]',
    ].join('\n'),
  };
}

/** Lead field -> partner field, for the scheduled job. */
export const LEAD_FIELD_MAP: ReadonlyArray<{ from: string; to: string }> = [
  { from: 'name', to: 'Client name' },
  { from: 'phone', to: 'Phone' },
  { from: 'email', to: 'Email' },
  { from: 'notes', to: 'Remarks' },
];

export interface CustomerStep {
  key: string;
  /** The wizard step this card shows (null = outside the wizard). */
  wizardStep: WizardStepKey | null;
  title: string;
  /** The exact label of what to click. */
  click: string;
  /** One line; always contains `click`. */
  line: string;
  /** Screenshot key in `lead-capture-guide-shots.json` (null = none). */
  shot: string | null;
}

function wizardTitle(key: WizardStepKey): string {
  return WIZARD_STEPS.find((s) => s.key === key)?.label ?? key;
}

const WIZARD_LINES: Record<WizardStepKey, { click: string; line: string }> = {
  channel: { click: 'Facebook', line: 'Click Facebook.' },
  signin: {
    click: 'Continue with Facebook',
    line: 'Click Continue with Facebook, sign in, leave every box ticked and click Save.',
  },
  page: { click: 'Connect Page', line: 'Pick the Page that runs the ads and click Connect Page.' },
  forms: {
    click: 'Save forms',
    line: 'Keep "All forms, including new ones" (or tick only some forms) and click Save forms.',
  },
  fields: {
    click: 'Save fields',
    line: 'Match each form question to a field and click Save fields. Anything not matched goes into the notes.',
  },
  test: { click: 'Send test lead', line: 'Click Send test lead and wait about a minute until it arrives.' },
};

/** `partner` = the partner app's name (or "your app"). */
export function customerSteps(partner: string): CustomerStep[] {
  return [
    {
      key: 'open',
      wizardStep: null,
      title: 'Open',
      click: 'Connect Facebook Page',
      line: `In ${partner} settings, click Connect Facebook Page. A window opens with ${partner}'s name and logo.`,
      shot: null,
    },
    ...WIZARD_STEPS.map((def) => ({
      key: def.key,
      wizardStep: def.key,
      title: wizardTitle(def.key),
      click: WIZARD_LINES[def.key].click,
      line: WIZARD_LINES[def.key].line,
      shot: def.key,
    })),
    { key: 'finish', wizardStep: null, title: 'Finish', click: 'Finish setup', line: 'Click Finish setup.', shot: 'finish' },
    {
      key: 'done',
      wizardStep: null,
      title: 'Done',
      click: 'Done',
      line: `Click Done. The window closes and the Page shows in ${partner} as Live. Every new ad on that Page is covered.`,
      shot: 'done',
    },
  ];
}

export const CUSTOMER_STEPS: CustomerStep[] = customerSteps('your app');

export interface GuideProblem {
  message: string;
  action: string;
}

/** The wizard's own messages (`connect/components/wizard-problem.tsx`,
 * `wizard-steps.tsx`, `connect/page.tsx`). */
export const GUIDE_PROBLEMS: GuideProblem[] = [
  {
    message: 'Facebook did not give permission to read leads.',
    action: 'Click Try again and leave every permission ticked.',
  },
  {
    message: 'No Page was shared.',
    action: 'Sign in with a Facebook account that is an admin of the Page, then click Try again.',
  },
  {
    message: '<Page> only lets chosen apps read its leads.',
    action: 'In Meta Business settings > Integrations > Leads Access, add the app, then click Check again.',
  },
  {
    message: '<Page> is already connected to another account.',
    action: 'Click Choose another Page, or ask support to move it.',
  },
  { message: 'This Page has no lead forms yet.', action: 'Create one in Instant Forms, then click Check again.' },
  { message: 'This link has expired', action: 'Close the window and click Connect Facebook Page again.' },
  {
    message: 'Facebook stopped sharing leads for this Page.',
    action: 'Click Sign in again. Leads from the gap are caught up automatically.',
  },
];
