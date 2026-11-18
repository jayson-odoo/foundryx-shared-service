/** One row of a record's History (owner standing rule: who, on behalf of,
 * when, plain action, old -> new). Display text only, never ids. */
export interface HistoryEntry {
  /** Row key only (never shown). */
  id: string;
  /** ISO-8601 UTC. */
  at: string | null;
  who: string | null;
  onBehalfOf: string | null;
  action: string;
  from: string | null;
  to: string | null;
}
