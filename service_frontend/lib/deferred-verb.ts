/**
 * Present-continuous form of a `ResourceAction.label` for a deferred
 * countdown's copy (sprint-4/23, T5, D2): "Delete permanently" -> "Deleting
 * permanently", so the countdown reads "Deleting in 10s" / "Deleting 3
 * users in 8s" rather than the bare imperative label. Only the FIRST word
 * (the verb) is conjugated; every registered action's label leads with one
 * (Delete/Trash/Archive/Disconnect/...).
 */
export function presentContinuous(label: string): string {
  const [first, ...rest] = label.trim().split(/\s+/);
  if (!first) return label;
  const verb = /e$/i.test(first) && !/ee$/i.test(first) ? `${first.slice(0, -1)}ing` : `${first}ing`;
  return [verb, ...rest].join(' ');
}
