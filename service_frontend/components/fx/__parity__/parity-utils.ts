/**
 * Switch-off parity harness helpers (Foundryx UIUX, playbook-uiux.md).
 *
 * Every shared shell is rendered with the Foundryx UIUX switch OFF and its
 * markup is snapshotted. The snapshots were recorded on the code as it was
 * before any switch work, so a later change that alters what a user sees with
 * the switch off fails here. A change that needs a parity snapshot updated is
 * wrong by definition: fix the code, never the snapshot.
 *
 * Two normalisations keep the snapshots about markup, not test order:
 * - React/Radix generated ids (`«r3»`, `:r3:`) are renamed in order of first
 *   appearance, so an unrelated `useId` call elsewhere cannot shift them.
 * - Elements marked `data-fx-entry` are dropped. That marks the one sanctioned
 *   addition while the switch is off (the playbook's "the only visible addition
 *   while off is the switch in the Theme panel"), which has its own tests.
 */
export const FX_ENTRY_ATTR = 'data-fx-entry';

const GENERATED_ID = /«[^»\s"]+»|:r[0-9a-z]+:/g;

function normaliseIds(html: string): string {
  const seen = new Map<string, string>();
  return html.replace(GENERATED_ID, (id) => {
    let stable = seen.get(id);
    if (!stable) {
      stable = `«id${seen.size}»`;
      seen.set(id, stable);
    }
    return stable;
  });
}

/** The markup a parity snapshot records for `root` (its children). */
export function parityHtml(root: Element): string {
  const clone = root.cloneNode(true) as Element;
  clone.querySelectorAll(`[${FX_ENTRY_ATTR}]`).forEach((node) => node.remove());
  return normaliseIds(clone.innerHTML);
}
