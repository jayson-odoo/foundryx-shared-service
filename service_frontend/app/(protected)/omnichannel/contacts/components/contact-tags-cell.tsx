import { Badge } from '@/components/ui/badge';
import { OverflowPills } from '@/components/platform/overflow-pills';
import type { ContactTagRef } from '@/types/omnichannel';

/** Tags column cell (AC-CTM-02) - width-aware "+N" collapse via OverflowPills
 *  (never a bare `truncate`/`line-clamp`, house rule). */
export function ContactTagsCell({ tags }: { tags: ContactTagRef[] }) {
  return (
    <OverflowPills
      items={tags}
      keyFor={(t) => t.id}
      renderPill={(t) => (
        <Badge
          variant="secondary"
          appearance="light"
          size="sm"
          style={t.color ? { backgroundColor: `${t.color}22`, color: t.color } : undefined}
        >
          {t.emoji && <span aria-hidden>{t.emoji}</span>}
          {t.name}
        </Badge>
      )}
    />
  );
}
