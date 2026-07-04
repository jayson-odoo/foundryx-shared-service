import fs from 'node:fs';
import path from 'node:path';

/**
 * Shared maildir-reading helpers for mail-asserting E2E specs (plan 10
 * pattern, extracted in the sprint-2/04 review — password-reset and
 * account-security specs previously carried diverging copies).
 *
 * Rig (see CLAUDE.md §7): a maildir-handler smtpd the backend's SMTP
 * connection points at —
 *   python -m aiosmtpd -n -l localhost:1025 \
 *     -c aiosmtpd.handlers.Mailbox /tmp/foundryx-e2e-mailbox
 * Pre-create the tmp/new/cur subdirs (the handler doesn't).
 */
export const MAILBOX_DIR = '/tmp/foundryx-e2e-mailbox/new';

/**
 * Newest mailbox message addressed to `to` (and containing `containing`,
 * when given — flows that send SEVERAL mails to one address would otherwise
 * race the dispatcher and match a stale message). Returns the
 * quoted-printable-decoded body, or null.
 */
export function readMailTo(to: string, containing?: string): string | null {
  if (!fs.existsSync(MAILBOX_DIR)) return null;
  const files = fs
    .readdirSync(MAILBOX_DIR)
    .map((f) => path.join(MAILBOX_DIR, f))
    .sort((a, b) => fs.statSync(a).mtimeMs - fs.statSync(b).mtimeMs);
  for (const file of files.reverse()) {
    const raw = fs.readFileSync(file, 'utf8');
    if (!raw.includes(`To: ${to}`)) continue;
    // Quoted-printable soft line breaks + encoded '=' would split tokens.
    const decoded = raw.replace(/=\r?\n/g, '').replace(/=3D/g, '=');
    if (containing && !decoded.includes(containing)) continue;
    return decoded;
  }
  return null;
}

/**
 * Polls until a matching mail lands. Default timeout is generous — the
 * outbox dispatcher's claim/retry cadence was observed to deliver up to
 * ~35s after enqueue under a busy local stack (pair with a raised Playwright
 * test timeout when waits can stack).
 */
export async function expectMailTo(
  to: string,
  containing?: string,
  timeoutMs = 60_000,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const body = readMailTo(to, containing);
    if (body) return body;
    if (Date.now() > deadline) {
      throw new Error(`no mail for ${to} within ${timeoutMs}ms`);
    }
    await new Promise((r) => setTimeout(r, 500));
  }
}
