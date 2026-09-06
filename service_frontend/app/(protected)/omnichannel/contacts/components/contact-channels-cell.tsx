import { MessageCircle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { OverflowPills } from '@/components/platform/overflow-pills';
import type { ContactChannelRef } from '@/types/omnichannel';

/** Channel column cell (D-A2-11) - resolved from `contact_channel_identities`,
 *  NEVER the last message's channel (a manually created contact has no
 *  message and would otherwise render a fabricated type). Empty = never
 *  messaged in on any channel. */
export function ContactChannelsCell({ channels }: { channels: ContactChannelRef[] }) {
  return (
    <OverflowPills
      items={channels}
      keyFor={(c) => c.channelId}
      renderPill={(c) => (
        <Badge variant="secondary" appearance="light" size="sm" className="gap-1">
          <MessageCircle className="size-3" />
          {c.name}
        </Badge>
      )}
    />
  );
}
