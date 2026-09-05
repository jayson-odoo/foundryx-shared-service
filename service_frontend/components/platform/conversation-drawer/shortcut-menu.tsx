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
import { toast } from '@/lib/toast';

import { SearchSelect, type SearchSelectOption } from '@/components/platform/search-select';
import { useCan } from '@/hooks/use-can';
import { useShortcuts } from '@/hooks/use-shortcuts';
import { ApiError } from '@/lib/api-client';

export interface ShortcutMenuProps {
  contactId: string | null;
}

export function ShortcutMenu({ contactId }: ShortcutMenuProps) {
  const { can } = useCan();
  const { shortcuts, isRunning, run } = useShortcuts(contactId);
  const [value, setValue] = useState<string | null>(null);

  if (!can('conversations.shortcut') || shortcuts.length === 0) return null;

  const options: SearchSelectOption[] = shortcuts.map((s) => ({ label: s.name, value: s.workflowId }));

  return (
    <SearchSelect
      options={options}
      value={value}
      onChange={async (workflowId) => {
        setValue(workflowId);
        try {
          const result = await run(workflowId);
          toast.success('Shortcut started.', {
            description: `Run ${result.runId}`,
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
