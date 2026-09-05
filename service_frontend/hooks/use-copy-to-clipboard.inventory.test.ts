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
 * all did this pre-fix). T7: the account/** demo pages that used to carry
 * disclosed exceptions here (no feedback at all, or a raw writeText+toast)
 * are DELETED (AC-DLA-57); the one real exception
 * (`account/components/account-form-fields.tsx`, the surviving /account
 * page's email-copy control) is fixed onto the hook. Both allowlists are
 * empty - a future entry needs a named reason, not a silent re-add.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..');

const NO_FEEDBACK_ALLOWED: string[] = [];
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

  it('every consumer destructuring copyToClipboard also destructures isCopied (allowlist empty)', () => {
    const allowed = new Set(NO_FEEDBACK_ALLOWED.map((f) => path.join(repoRoot, f)));
    const offenders = sourceFiles().filter((f) => {
      if (f.endsWith('use-copy-to-clipboard.ts') || allowed.has(f)) return false;
      const src = fs.readFileSync(f, 'utf8');
      const usesHook = /const\s*\{([^}]*)\}\s*=\s*useCopyToClipboard\(/.exec(src);
      if (!usesHook) return false;
      return !/\bisCopied\b/.test(usesHook[1]);
    });
    expect(offenders).toEqual([]);
  });

  it('no file bypasses the hook via a raw writeText + toast (allowlist empty)', () => {
    const allowed = new Set(RAW_WRITE_TEXT_WITH_TOAST_ALLOWED.map((f) => path.join(repoRoot, f)));
    const offenders = sourceFiles().filter((f) => {
      if (allowed.has(f)) return false;
      const src = fs.readFileSync(f, 'utf8');
      return /navigator\.clipboard\.writeText/.test(src) && /\btoast\.(success|error)\(/.test(src);
    });
    expect(offenders).toEqual([]);
  });
});
