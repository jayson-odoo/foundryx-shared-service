/**
 * AC-DLA-43/47 (sprint-4/23, T5, D2/D13): `confirm:` (a `ResourceAction`'s
 * typed/plain confirm dialog) is RESERVED for the two typed-confirmation
 * carve-outs - module uninstall and tenant purge (irreversible hard
 * deletes) - PLUS the disclosed exceptions below. Every other action in the
 * app now carries `deferred` instead (the grace-window engine).
 *
 * This T5 pass migrated the actions AC-DLA-38 names explicitly (users,
 * roles, workflows, forms, templates x2, connections x2, ai_agents,
 * ai_skills, tenants x3, document_shares, products - 16 registered deferred
 * actions across 12 files) plus disclosed the 3 sites that don't fit the
 * grace-window model. The BASELINE below (18 files) is what's LEFT -
 * autocount task/entity delete, ideation BR/idea/embed-connection delete,
 * jobs abort, the omnichannel channel/template/webhook/quick-reply/api-key/
 * workspace deletes, and the email-log purge - tracked as BL-SS-XXX
 * (backlog: "T5 follow-up - migrate the remaining confirm: sites to
 * deferred"), not silently dropped. A file leaving this list (migrated) MUST
 * be deleted from `PENDING_MIGRATION` in the same commit; the baseline never
 * grows.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..', '..');

/**
 * AC-DLA-47 names TWO typed-confirmation carve-outs (module uninstall, tenant
 * purge). This inventory ALSO allows a third, DISCLOSED exception: Users'
 * "Impersonate" (`use-user-actions.tsx`) - a session action, not a delete/
 * archive-style record mutation, so D2's grace-window "commit after Ns unless
 * Cancelled" model has no sensible meaning for it (see the T5 report). The
 * tenants file ALSO keeps a `confirm:` fallback for a lifecycle edge whose
 * target status shares a LABEL with a well-known one (archived/suspended/
 * active) but a DIFFERENT key (an operator-added custom status) - the
 * platform-owned tenant graph is edge-agnostic for the three seeded keys but
 * not for an arbitrary custom one without a per-row-payload deferred action
 * (backlog).
 */
const CARVE_OUTS = [
  'components/platform/app-store/use-module-list-config.tsx',
  'app/(protected)/platform/tenants/components/use-tenant-actions.tsx',
  'app/(protected)/user-management/users/components/use-user-actions.tsx',
];

/**
 * NOT YET migrated to `deferred` (T5 follow-up, disclosed scope reduction -
 * see the T5 report and the file-header comment above). Every entry here is
 * a real gap, not a carve-out - remove an entry the moment its file no
 * longer defines `confirm:`.
 */
const PENDING_MIGRATION = [
  'app/(protected)/autocount/companies/[id]/entities/[entityType]/components/task-editor-view.tsx',
  'app/(protected)/autocount/companies/components/use-entities-list-config.tsx',
  'app/(protected)/documents/types/page.tsx',
  'app/(protected)/ideation/business-requirements/components/br-ideas-tab.tsx',
  'app/(protected)/ideation/business-requirements/components/use-br-form.tsx',
  'app/(protected)/ideation/business-requirements/use-br-list-config.tsx',
  'app/(protected)/ideation/embed-connections/use-embed-connections-list-config.tsx',
  'app/(protected)/ideation/ideas/components/use-idea-form.tsx',
  'app/(protected)/ideation/ideas/use-ideas-list-config.tsx',
  'app/(protected)/jobs/use-job-actions.tsx',
  'app/(protected)/omnichannel/settings/channels/components/use-channel-actions.tsx',
  'app/(protected)/omnichannel/settings/channels/components/use-template-list.tsx',
  'app/(protected)/omnichannel/settings/channels/components/use-webhook-list.tsx',
  'app/(protected)/omnichannel/settings/quick-replies/use-quick-replies-list-config.tsx',
  'app/(protected)/omnichannel/settings/workspaces/components/use-api-key-list.tsx',
  'app/(protected)/omnichannel/settings/workspaces/components/use-workspace-actions.tsx',
  'app/(protected)/settings/email-log/components/use-email-log-actions.tsx',
];

function walk(dirs: string[]): string[] {
  const out: string[] = [];
  const visit = (dir: string) => {
    const full = path.join(repoRoot, dir);
    if (!fs.existsSync(full)) return;
    for (const entry of fs.readdirSync(full, { withFileTypes: true })) {
      const entryPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        visit(entryPath);
      } else if (
        (/\.tsx$/.test(entry.name) || /\.ts$/.test(entry.name)) &&
        !entry.name.includes('.test.')
      ) {
        out.push(entryPath);
      }
    }
  };
  for (const dir of dirs) visit(dir);
  return out;
}

function definesConfirm(file: string): boolean {
  const src = fs.readFileSync(path.join(repoRoot, file), 'utf8');
  return /^\s*confirm:\s*\{/m.test(src);
}

describe('AC-DLA-43/47 confirm: is reserved to the carve-outs + the disclosed pending baseline', () => {
  it('zero files outside the carve-outs + the pending baseline define a ResourceAction.confirm', () => {
    const dirs = ['app', 'components'];
    const allowed = new Set([
      ...CARVE_OUTS,
      ...PENDING_MIGRATION,
      'components/platform/resource-actions/confirm-action-dialog.tsx',
      'components/platform/resource-actions/confirm-carve-outs.inventory.test.ts',
      'components/platform/resource-list/types.ts',
    ]);
    const offenders: string[] = [];
    for (const file of walk(dirs)) {
      if (allowed.has(file)) continue;
      if (definesConfirm(file)) offenders.push(file);
    }
    expect(offenders).toEqual([]);
  });

  it('the pending baseline never grows - every listed file still defines confirm', () => {
    for (const file of PENDING_MIGRATION) {
      const full = path.join(repoRoot, file);
      expect(fs.existsSync(full), `${file} should exist`).toBe(true);
      expect(definesConfirm(file), `${file} should still define confirm (remove it from PENDING_MIGRATION once migrated)`).toBe(true);
    }
  });

  it('every carve-out file still exists and defines confirm', () => {
    for (const file of CARVE_OUTS) {
      const full = path.join(repoRoot, file);
      expect(fs.existsSync(full), `${file} should exist`).toBe(true);
      expect(definesConfirm(file), `${file} should still define a confirm`).toBe(true);
    }
  });

  it('the two AC-DLA-47 carve-outs (module uninstall, tenant purge) keep typed confirm.input', () => {
    const typed = [
      'components/platform/app-store/use-module-list-config.tsx',
      'app/(protected)/platform/tenants/components/use-tenant-actions.tsx',
    ];
    for (const file of typed) {
      const src = fs.readFileSync(path.join(repoRoot, file), 'utf8');
      expect(src, `${file} should still define confirm.input (typed)`).toMatch(
        /confirm:\s*\{[\s\S]*?input:/,
      );
    }
  });
});
