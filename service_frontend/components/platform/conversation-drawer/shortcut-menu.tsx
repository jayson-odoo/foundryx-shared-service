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
import { toast } from 'sonner';

import { SearchSelect, type SearchSelectOption } from '@/components/platform/search-select';
import { useCan } from '@/hooks/use-can';
import { useShortcuts } from '@/hooks/use-shortcuts';

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
        const result = await run(workflowId);
        if (result) {
          toast.success('Shortcut started.', {
            description: `Run ${result.runId}`,
          });
        } else {
          toast.error('Could not run the shortcut.');
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
