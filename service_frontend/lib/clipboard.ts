/**
 * The ONE copy-to-clipboard function (shared by `useCopyToClipboard` and the
 * Lead Capture wizard). A plain-HTTP page is not a secure context and has NO
 * `navigator.clipboard` (crew passes 70e96f2b, 3208a91e), and the Clipboard API
 * can also refuse; both fall back to the legacy hidden-textarea copy command.
 * Resolves true when the text was copied.
 */

/** The pre-Clipboard-API copy: select a hidden textarea and run the browser's
 * own copy command. True when the browser says it copied. */
function legacyCopy(value: string): boolean {
  try {
    const area = document.createElement('textarea');
    area.value = value;
    area.setAttribute('readonly', '');
    area.className = 'fixed -left-[9999px] top-0 opacity-0';
    // Inside a modal, attach within it: a focus trap would otherwise pull
    // focus back out of a textarea placed on <body>.
    const host = document.activeElement?.closest('[role="dialog"]') ?? document.body;
    host.appendChild(area);
    area.focus();
    area.select();
    let ok = false;
    try {
      ok = typeof document.execCommand === 'function' && document.execCommand('copy');
    } finally {
      host.removeChild(area);
    }
    return Boolean(ok);
  } catch {
    return false;
  }
}

export async function copyText(value: string): Promise<boolean> {
  if (typeof window === 'undefined' || !value) return false;
  const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : undefined;
  if (!clipboard?.writeText) return legacyCopy(value);
  try {
    await clipboard.writeText(value);
    return true;
  } catch {
    return legacyCopy(value);
  }
}
