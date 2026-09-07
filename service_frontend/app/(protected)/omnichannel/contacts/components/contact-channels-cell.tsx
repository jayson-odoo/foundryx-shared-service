import { Badge } from '@/components/ui/badge';
import { OverflowPills } from '@/components/platform/overflow-pills';
import { CHANNEL_CAPABILITIES } from '@/lib/channel-capabilities';
import type { ContactChannelRef } from '@/types/omnichannel';

/** Channel column cell (D-A2-11) - resolved from `contact_channel_identities`,
 *  NEVER the last message's channel (a manually created contact has no
 *  message and would otherwise render a fabricated type). Empty = never
 *  messaged in on any channel. A type-to-icon lookup (plan 32 / A7a,
 *  AC-CHN-09) - `OverflowPills` still owns the truncation. */
export function ContactChannelsCell({ channels }: { channels: ContactChannelRef[] }) {
  return (
    <OverflowPills
      items={channels}
      keyFor={(c) => c.channelId}
      renderPill={(c) => {
        const Icon = CHANNEL_CAPABILITIES[c.channelType].icon;
        return (
          <Badge variant="secondary" appearance="light" size="sm" className="gap-1">
            <Icon className="size-3" />
            {c.name}
          </Badge>
        );
      }}
    />
  );
}
