/**
 * Switch-off parity harness helpers (Foundryx UIUX, playbook-uiux.md).
 *
 * Every shared shell is rendered with the Foundryx UIUX switch OFF and its
 * markup is snapshotted. The snapshots were recorded on the code as it was
 * before any switch work, so a later change that alters what a user sees with
 * the switch off fails here. A change that needs a parity snapshot updated is
 * wrong by definition: fix the code, never the snapshot.
 *
 * Three normalisations keep the snapshots about markup, not test order or
 * runner speed (the third, Radix's tab mount guard, is documented below):
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

/**
 * Radix Tabs gives the tab panel that is selected at mount an inline
 * `animation-duration: 0s` (so it does not play its enter animation on first
 * paint) and drops it on the first re-render after the next animation frame.
 * Whether a snapshot lands before or after that frame is runner speed, not
 * markup, so the dropped form (`style=""`, only ever left behind by that
 * guard) is recorded as the at-mount form.
 */
function canonicaliseTabMountGuard(clone: Element): void {
  clone.querySelectorAll('[role="tabpanel"][style=""]').forEach((panel) => {
    panel.setAttribute('style', 'animation-duration: 0s;');
  });
}

/** The markup a parity snapshot records for `root` (its children). */
export function parityHtml(root: Element): string {
  const clone = root.cloneNode(true) as Element;
  clone.querySelectorAll(`[${FX_ENTRY_ATTR}]`).forEach((node) => node.remove());
  canonicaliseTabMountGuard(clone);
  return normaliseIds(clone.innerHTML);
}
