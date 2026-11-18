// @vitest-environment node
/**
 * Lane META-LEADS-GUIDE-PAGE: the public lead-capture guide's content rules.
 * - the customer steps follow the real wizard (WIZARD_STEPS), in order;
 * - code samples are built from the configured hosts, never a typed-in host;
 * - nothing that looks like a real key or a real host ships in the guide;
 * - the committed captures exist and the video stays under 5 MB.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { WIZARD_STEPS } from '@/lib/lead-capture-wizard';
import {
  CUSTOMER_STEPS,
  GUIDE_PROBLEMS,
  developerSamples,
  guideApiBase,
} from '@/lib/lead-capture-guide';
import shots from '@/lib/lead-capture-guide-shots.json';

const root = path.join(__dirname, '..');

describe('customer steps follow the wizard', () => {
  it('lists every wizard step, in the wizard order, with its own question', () => {
    const wizardKeys = CUSTOMER_STEPS.filter((s) => s.wizardStep).map((s) => s.wizardStep);
    expect(wizardKeys).toEqual(WIZARD_STEPS.map((s) => s.key));
    for (const def of WIZARD_STEPS) {
      const step = CUSTOMER_STEPS.find((s) => s.wizardStep === def.key);
      expect(step?.title).toBe(def.label);
    }
  });

  it('opens with the partner button and ends with Finish setup then Done', () => {
    expect(CUSTOMER_STEPS[0].key).toBe('open');
    expect(CUSTOMER_STEPS.slice(-2).map((s) => s.key)).toEqual(['finish', 'done']);
  });

  it('gives every step one line naming what to click', () => {
    for (const step of CUSTOMER_STEPS) {
      expect(step.click.length).toBeGreaterThan(0);
      expect(step.line).toContain(step.click);
    }
  });

  it('names the wizard error screens with their real buttons', () => {
    const actions = GUIDE_PROBLEMS.map((p) => p.action).join(' ');
    for (const label of ['Try again', 'Check again', 'Choose another Page', 'Sign in again']) {
      expect(actions).toContain(label);
    }
  });
});

describe('the guide quotes the wizard it describes', () => {
  // The wizard's own screens + the channel label the backend serves.
  const wizardSources = [
    'app/(public)/public/lead-capture/connect/page.tsx',
    'app/(public)/public/lead-capture/connect/components/wizard-steps.tsx',
    'app/(public)/public/lead-capture/connect/components/wizard-problem.tsx',
    'app/(public)/public/lead-capture/connect/components/done-screen.tsx',
    '../service_backend/modules/lead_capture/services/connect_session_service.py',
  ]
    .map((rel) => fs.readFileSync(path.join(root, rel), 'utf8'))
    .join('\n');

  it.each(CUSTOMER_STEPS.filter((s) => s.key !== 'open'))('step $key: "$click" is a real wizard button', (step) => {
    expect(wizardSources).toContain(step.click);
  });

  it.each(GUIDE_PROBLEMS)('problem "$message" is the wizard\'s own text', (problem) => {
    expect(wizardSources).toContain(problem.message.replace(/^<Page> /, ' '));
  });
});

describe('code samples', () => {
  it('builds the API base from the backend URL', () => {
    expect(guideApiBase({ NEXT_PUBLIC_BACKEND_API_URL: 'https://ss.example/be/' })).toBe(
      'https://ss.example/be/api/v1/lead-capture',
    );
    expect(guideApiBase({})).toBe('http://localhost:8001/api/v1/lead-capture');
  });

  it('uses only the given base and the fake partner origin', () => {
    const samples = developerSamples('https://ss.example/be/api/v1/lead-capture');
    const all = Object.values(samples).join('\n');
    expect(samples.connectSession).toContain('POST https://ss.example/be/api/v1/lead-capture/connect-sessions');
    expect(samples.connectSession).toContain('"returnOrigin": "https://app.partner.example"');
    expect(samples.popup).toContain("'lead-capture:done'");
    expect(samples.popup).toContain("'lead-capture:closed'");
    // The sender check is derived from the wizard URL, never typed in.
    expect(samples.popup).toContain('new URL(url).origin');
    expect(samples.pull).toContain('GET https://ss.example/be/api/v1/lead-capture/leads?cursor=');
    expect(samples.fields).toContain('PUT https://ss.example/be/api/v1/lead-capture/fields');
    expect(all).toContain('fxl_live_...');
    // A pushed lead is the event's `data`: dedupe key = data.id, not the event id.
    expect(samples.webhookBody).toContain('"data":');
    expect(samples.webhook).toContain('"secret"');
  });
});

describe('no secrets or real hosts in the guide', () => {
  const files = [
    'lib/lead-capture-guide.ts',
    'lib/lead-capture-guide-shots.json',
    'app/(public)/public/lead-capture/guide/page.tsx',
    'app/(public)/public/lead-capture/guide/lead-capture-guide.tsx',
    'app/(public)/public/lead-capture/guide/code-sample.tsx',
    'public/media/lead-capture-guide/walkthrough.vtt',
    'scripts/capture-lead-capture-guide.sh',
    '../documentation/plans/meta-leads/guide-page/README.md',
    '../documentation/plans/meta-leads/guide-page/mock-v1.html',
  ];

  it.each(files)('%s has no key, token or real host', (rel) => {
    const src = fs.readFileSync(path.join(root, rel), 'utf8');
    expect(src).not.toMatch(/fxl_live_[A-Za-z0-9_-]{6,}/);
    expect(src).not.toMatch(/\b(sk|pk)_(live|test)_[A-Za-z0-9]{6,}/);
    expect(src).not.toMatch(/EAA[A-Za-z0-9]{20,}/); // Meta access token shape
    expect(src).not.toMatch(/foundryx\.my/i);
  });
});

describe('committed captures', () => {
  it('has a screenshot for every customer step that shows the wizard', () => {
    for (const step of CUSTOMER_STEPS.filter((s) => s.shot)) {
      const shot = (shots.steps as Record<string, { file: string }>)[step.shot as string];
      expect(shot, step.key).toBeDefined();
      expect(fs.existsSync(path.join(root, 'public', shot.file)), shot.file).toBe(true);
    }
  });

  it('keeps the walkthrough video under 5 MB', () => {
    const video = path.join(root, 'public', shots.video);
    expect(fs.existsSync(video)).toBe(true);
    expect(fs.statSync(video).size).toBeLessThan(5 * 1024 * 1024);
  });
});
