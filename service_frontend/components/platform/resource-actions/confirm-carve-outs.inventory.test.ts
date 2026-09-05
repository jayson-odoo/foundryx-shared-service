/**
 * AC-DLA-43/47 (sprint-4/23, T5, D2/D13): `confirm:` (a `ResourceAction`'s
 * typed/plain confirm dialog) is RESERVED for the typed-confirmation
 * carve-outs - module uninstall, tenant purge (irreversible hard deletes),
 * and Documents > Shares' BULK revoke - PLUS the disclosed exceptions below.
 * Every other action in the app now carries `deferred` instead (the
 * grace-window engine).
 *
 * T5 fix round 1 (item 15) migrated the remaining 17 files (closes
 * BL-SS-051): autocount task pause + entity re-fetch-history (genuinely
 * non-destructive re-sync/pause actions - `confirm` dropped entirely, no
 * `deferred` needed, per the item's own "a resend/retry/re-sync needs no
 * confirm" rule), document types delete, the ideation module (ideas
 * archive/delete, BR delete, BR<->idea unlink, embed-connection delete/
 * toggle - registered in `modules/ideation/deferred_actions.py`), jobs
 * abort/complete, the omnichannel module (channel disconnect/delete,
 * WhatsApp template delete, webhook endpoint disable/delete, quick-reply
 * delete, API-key revoke, workspace trash - registered in
 * `modules/omnichannel/deferred_actions.py`), and the email-log cancel
 * (`email_outbox.cancel`, core). `PENDING_MIGRATION` is now EMPTY.
 *
 * T5 fix round 2, S1: Documents > Shares' BULK revoke typed confirm was
 * RESTORED (round 1 had migrated it to `deferred`, dropping a shipped
 * sprint-3/05 UAT criterion, AC-OVERSIGHT-03/AC-UX-03) - the row-surface
 * revoke on that page stays on `deferred`; only the bulk `ResourceAction`
 * (`id: 'revoke-bulk'`) carries `confirm`. This is the FOURTH typed
 * confirm.input site (module uninstall, tenant purge, tenant purge's typed
 * slug/DELETE input, and now shares bulk-revoke) - `CARVE_OUTS` below gains
 * the shares page as a fourth allowlisted FILE (BL-SS-052 still tracks the
 * tenant custom-status-edge PLAIN-confirm fallback separately, its own
 * disclosed exception within `use-tenant-actions.tsx`, not a migration gap).
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
  'app/(protected)/documents/shares/page.tsx',
];

/**
 * NOT YET migrated to `deferred` - empty since T5 fix round 1 item 15
 * (closes BL-SS-051). Kept as a named, asserted-empty array (rather than
 * deleted) so a future regression has somewhere obvious to land instead of
 * silently growing the allowlist above.
 */
const PENDING_MIGRATION: string[] = [];

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
  it('T5 fix round 1 item 15: PENDING_MIGRATION ends EMPTY - every confirm: site is migrated or a disclosed carve-out', () => {
    expect(PENDING_MIGRATION).toEqual([]);
  });

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

  it('the typed-confirmation carve-outs (module uninstall, tenant purge, shares bulk revoke) keep typed confirm.input', () => {
    const typed = [
      'components/platform/app-store/use-module-list-config.tsx',
      'app/(protected)/platform/tenants/components/use-tenant-actions.tsx',
      'app/(protected)/documents/shares/page.tsx',
    ];
    for (const file of typed) {
      const src = fs.readFileSync(path.join(repoRoot, file), 'utf8');
      expect(src, `${file} should still define confirm.input (typed)`).toMatch(
        /confirm:\s*\{[\s\S]*?input:/,
      );
    }
  });
});
