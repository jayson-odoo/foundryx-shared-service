'use client';

import { Badge } from '@/components/ui/badge';

export interface VarChipsProps {
  /** The template body currently on screen (draft or a saved version). */
  template: string;
  /** Declared variables for this prompt, e.g. ["title", "participants"]. */
  variables: string[];
}

/**
 * `{{var}}` chips for the declared template variables - green when the
 * token is present in `template`, amber (soft warn only, nothing blocks
 * saving) when a declared variable isn't used. No unknown-token detection
 * in v1 - trigger to add one: a save that shipped a silently-broken token.
 */
export function VarChips({ template, variables }: VarChipsProps) {
  if (variables.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="var-chips">
      {variables.map((name) => {
        const present = template.includes(`{{${name}}}`);
        return (
          <Badge
            key={name}
            variant={present ? 'success' : 'warning'}
            appearance="light"
            size="sm"
            className="font-mono"
            data-testid={`var-chip-${name}`}
            data-state={present ? 'present' : 'missing'}
          >
            {`{{${name}}}`}
          </Badge>
        );
      })}
    </div>
  );
}
