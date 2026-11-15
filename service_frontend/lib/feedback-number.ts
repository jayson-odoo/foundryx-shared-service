/** What a user reads for a stored item number: `IDEA-0016` shows as `FB-0016`
 * (lane FEEDBACK-RENAME, owner ruling 15 Nov - users never see "idea"). The
 * stored value and the wire field `ideaNumber` stay `IDEA-...`; anything else
 * passes through. Backend twin: `numbering.display_idea_number`. */
export function formatFeedbackNumber(number: string): string;
export function formatFeedbackNumber(number: string | null | undefined): string | null;
export function formatFeedbackNumber(number: string | null | undefined): string | null {
  if (!number) return number ?? null;
  const m = /^IDEA-(\d+)$/.exec(number);
  return m ? `FB-${m[1]}` : number;
}
