'use client';

/**
 * Shortcuts control (plan 27, AC-IVE-39) - a `SearchSelect` of the published
 * `entity.shortcut` workflows bound to this thread. Renders nothing when the
 * list is empty or the caller lacks the gating permission (foolproof-UI -
 * never show a control that would 403). Gated `conversations.shortcut` (main-
 * session decision on top of the plan's D-A3-5 `workflows.run` default - a
 * typical Agent should be able to fire a shortcut without a builder grant).
 */
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from '@/lib/toast';

import { workflowPath } from '@/app/(protected)/workflows/components/paths';
import { SearchSelect, type SearchSelectOption } from '@/components/platform/search-select';
import { useCan } from '@/hooks/use-can';
import { useShortcuts } from '@/hooks/use-shortcuts';
import { ApiError } from '@/lib/api-client';

export interface ShortcutMenuProps {
  contactId: string | null;
}

export function ShortcutMenu({ contactId }: ShortcutMenuProps) {
  const { can } = useCan();
  const hasPermission = can('conversations.shortcut');
  // F9 (round-3 codex triage) - `useShortcuts` fetches unconditionally on
  // every `contactId` (its effect has no permission awareness at all); the
  // OLD code called it BEFORE the permission guard below, so a caller
  // WITHOUT `conversations.shortcut` still fired a guaranteed-403 request on
  // every conversation opened. `useShortcuts` already treats a null contact
  // as "nothing to fetch" - pass `null` instead of `contactId` whenever the
  // permission is absent, rather than adding a separate `enabled` param.
  const { shortcuts, isRunning, run } = useShortcuts(hasPermission ? contactId : null);
  const [value, setValue] = useState<string | null>(null);
  const router = useRouter();

  if (!hasPermission || shortcuts.length === 0) return null;

  const options: SearchSelectOption[] = shortcuts.map((s) => ({ label: s.name, value: s.workflowId }));

  return (
    <SearchSelect
      options={options}
      value={value}
      onChange={async (workflowId) => {
        setValue(workflowId);
        try {
          const result = await run(workflowId);
          // AC-IVE-39: the success toast links to the run - the editor's
          // existing debug-overlay route (`?debug=<runId>`, the same one
          // "Debug in editor" from the Logs tab uses) is the one place a
          // run's data can be inspected today. Foolproof-UI: only offer the
          // link to a caller who actually holds `workflows.read` (a typical
          // Agent running a shortcut usually doesn't) - never a link that
          // would land on the permission wall.
          toast.success('Shortcut started.', {
            ...(can('workflows.read')
              ? {
                  action: {
                    label: 'View run',
                    onClick: () =>
                      router.push(`${workflowPath(workflowId)}?edit=1&debug=${result.runId}`),
                  },
                }
              : {}),
          });
        } catch (error) {
          // A 409 (e.g. the workflow's published version has an unauthorized
          // Code node) carries a plain-string `detail` - api-client already
          // promotes that into `ApiError.message` (F14 pattern, matching
          // `lifecycle-move.tsx`) - show the server's own message rather
          // than a generic one.
          toast.error(error instanceof ApiError ? error.message : 'Could not run the shortcut.');
        }
        setValue(null);
      }}
      placeholder="Shortcuts"
      ariaLabel="Run a shortcut"
      disabled={isRunning}
      className="w-40"
    />
  );
}
