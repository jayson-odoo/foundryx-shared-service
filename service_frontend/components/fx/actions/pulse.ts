/**
 * The attention pulse (playbook 0.71.0 "Blocked red action"): the thing an
 * action waits for swells to x1.08 and settles back over about 1.8 s, with a
 * soft red glow behind it shaped like the element. A blocked action names its
 * target with `data-fx-pulse-target="<name>"` on that element; the look lives
 * in css/styles.css under the switch (`[data-fx-pulsing]`). Reduced motion
 * keeps the pulse: it says what to do, so it is not decoration.
 */
export const FX_PULSE_MS = 1800;

const timers = new WeakMap<Element, ReturnType<typeof setTimeout>>();

/** Pulses every element named `target`. Returns how many it found. */
export function pulseFxTarget(target: string): number {
  if (typeof document === 'undefined' || !target) return 0;
  const nodes = Array.from(
    document.querySelectorAll(
      `[data-fx-pulse-target="${target.replace(/["\\]/g, '\\$&')}"]`,
    ),
  );
  for (const node of nodes) {
    const previous = timers.get(node);
    if (previous) clearTimeout(previous);
    // Restart the animation when it is already running.
    node.removeAttribute('data-fx-pulsing');
    void (node as HTMLElement).offsetWidth;
    node.setAttribute('data-fx-pulsing', '');
    timers.set(
      node,
      setTimeout(() => {
        node.removeAttribute('data-fx-pulsing');
        timers.delete(node);
      }, FX_PULSE_MS),
    );
  }
  return nodes.length;
}
