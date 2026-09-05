/**
 * AC-DLA-53 - copy-to-clipboard actions show the inline checkmark only
 * (`isCopied` swaps an icon), never a toast. Checks: no consumer passes an
 * `onCopy` callback that fires a toast; every consumer that reads
 * `copyToClipboard` off the hook also reads `isCopied` (a copy button with
 * nowhere to put visual feedback is exactly the gap `form-builder-tab.tsx`
 * had - it fired `toast.success` instead of ever reading `isCopied`); and
 * (fix round 1 item 3) no file bypasses the hook entirely by calling
 * `navigator.clipboard.writeText` directly AND firing a toast on the result
 * (`secret-reveal.tsx`, `webhook-secret-panel.tsx`, `mint-api-key-dialog.tsx`
 * all did this pre-fix). T7: the one remaining exception
 * (`account/components/account-form-fields.tsx`, the real /account page's
 * email-copy control, NOT dead demo) is fixed onto the hook too - the
 * allowlist is now empty.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..');

/**
 * Pre-existing `account/**` Metronic DEMO pages (D8, plan 23 T7: "the 21
 * account/** demo pages ... DELETED, not migrated") - they copy an id with
 * no visual feedback at all today (no toast either, so AC-DLA-53's actual
 * ban - "no toast" - already holds for them). Wiring up `isCopied` for
 * pages T7 deletes wholesale would be wasted work; disclosed here instead
 * of silently passing or silently failing.
 */
const DEAD_DEMO_NO_FEEDBACK = [
  'app/(protected)/account/invite-a-friend/components/invites.tsx',
  'app/(protected)/account/members/permissions-toggle/components/members.tsx',
  'app/(protected)/account/members/team-info/components/members.tsx',
  'app/(protected)/account/members/team-members/components/members.tsx',
  'app/(protected)/account/security/current-sessions/components/current-sessions.tsx',
];

/**
 * T7: every file that used to bypass the hook is now either fixed onto it
 * (`account-form-fields.tsx`) or deleted (the other three, T6 fix round 1
 * item 3). Empty on purpose - a future entry needs a named reason, not a
 * silent re-add.
 */
const RAW_WRITE_TEXT_WITH_TOAST_ALLOWED: string[] = [];

function sourceFiles(): string[] {
  const out: string[] = [];
  const roots = ['app', 'components', 'hooks'];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        walk(full);
      } else if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.includes('.test.')) {
        out.push(full);
      }
    }
  };
  for (const root of roots) walk(path.join(repoRoot, root));
  return out;
}

describe('AC-DLA-53 copy-to-clipboard = inline checkmark only', () => {
  it('zero files pass an onCopy callback to useCopyToClipboard', () => {
    const offenders = sourceFiles().filter((f) => {
      if (f.endsWith('use-copy-to-clipboard.ts')) return false;
      const src = fs.readFileSync(f, 'utf8');
      return /useCopyToClipboard\(\s*\{[^}]*onCopy/s.test(src);
    });
    expect(offenders).toEqual([]);
  });

  it('every consumer destructuring copyToClipboard also destructures isCopied (baseline: 5 dead demo pages excepted)', () => {
    const allowed = new Set(DEAD_DEMO_NO_FEEDBACK.map((f) => path.join(repoRoot, f)));
    const offenders = sourceFiles().filter((f) => {
      if (f.endsWith('use-copy-to-clipboard.ts') || allowed.has(f)) return false;
      const src = fs.readFileSync(f, 'utf8');
      const usesHook = /const\s*\{([^}]*)\}\s*=\s*useCopyToClipboard\(/.exec(src);
      if (!usesHook) return false;
      return !/\bisCopied\b/.test(usesHook[1]);
    });
    expect(offenders).toEqual([]);
  });

  it('no file bypasses the hook via a raw writeText + toast (baseline: one T7-scheduled-for-deletion demo file)', () => {
    const allowed = new Set(RAW_WRITE_TEXT_WITH_TOAST_ALLOWED.map((f) => path.join(repoRoot, f)));
    const offenders = sourceFiles().filter((f) => {
      if (allowed.has(f)) return false;
      const src = fs.readFileSync(f, 'utf8');
      return /navigator\.clipboard\.writeText/.test(src) && /\btoast\.(success|error)\(/.test(src);
    });
    expect(offenders).toEqual([]);
  });

  it('the disclosed dead-demo baseline is exact - every named file still exists and still lacks isCopied', () => {
    for (const rel of DEAD_DEMO_NO_FEEDBACK) {
      const full = path.join(repoRoot, rel);
      expect(fs.existsSync(full), `${rel} should exist`).toBe(true);
      const src = fs.readFileSync(full, 'utf8');
      const usesHook = /const\s*\{([^}]*)\}\s*=\s*useCopyToClipboard\(/.exec(src);
      expect(usesHook, `${rel} should still call useCopyToClipboard`).not.toBeNull();
      expect(usesHook![1], `${rel} should still lack isCopied (remove it from the baseline once fixed)`).not.toMatch(
        /\bisCopied\b/,
      );
    }
  });
});
