import type { ContactSegment } from '@/types/omnichannel';

/** The sentinel id for "every contact, no segment applied" (AC-CTM-05) - the
 *  shell's N-way `segments` control always needs an id, and `'all'` is the
 *  house convention (mirrors the email log's All|Pending|Sent... first entry). */
export const ALL_CONTACTS_SEGMENT_ID = 'all';

/** Build the `ResourceListConfig.segments` entries: "All contacts" first,
 *  then one per saved segment (AC-CTM-05). */
export function segmentOptions(segments: ContactSegment[]): { id: string; label: string }[] {
  return [
    { id: ALL_CONTACTS_SEGMENT_ID, label: 'All contacts' },
    ...segments.map((s) => ({ id: s.id, label: s.name })),
  ];
}
