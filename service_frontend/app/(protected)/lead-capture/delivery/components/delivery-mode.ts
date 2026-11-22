export type DeliveryMode = 'push' | 'pull';

/**
 * Delivery's Push / Pull only choice after the receivers (re)load. The first
 * load follows the stored state (receivers = push, none = pull); once the last
 * receiver is removed, from any menu, the page shows Pull only. A Push picked
 * by hand with no receivers yet stays, so the first one can be added.
 */
export function nextDeliveryMode(
  mode: DeliveryMode | null,
  prevCount: number | null,
  count: number,
): DeliveryMode {
  if (mode === null) return count > 0 ? 'push' : 'pull';
  if (mode === 'push' && count === 0 && (prevCount ?? 0) > 0) return 'pull';
  return mode;
}
