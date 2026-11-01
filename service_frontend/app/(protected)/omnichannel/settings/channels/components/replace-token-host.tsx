'use client';

import { closeReplaceToken, useReplaceTokenRequest } from './replace-token-store';
import { ReplaceTokenDialog } from './replace-token-dialog';

/** Renders the Replace token dialog for whichever row or record asked for it. */
export function ReplaceTokenHost() {
  const request = useReplaceTokenRequest();
  if (!request) return null;
  return (
    <ReplaceTokenDialog
      channel={request.channel}
      open
      onOpenChange={(open) => {
        if (!open) closeReplaceToken();
      }}
      onReplaced={request.onReplaced}
    />
  );
}
