'use client';

import { Fragment, type ReactNode } from 'react';
import { Plus, TriangleAlert } from 'lucide-react';
import { Alert, AlertContent, AlertIcon } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useTerminology } from '@/hooks/use-terminology';
import type { AutocountDocumentPrerequisite } from '@/types/autocount';

export interface DocumentPrerequisiteCardProps {
  prerequisites: AutocountDocumentPrerequisite[];
  /** Open the task editor for a MISSING master. Omit (no manage permission) = no button. */
  onAdd?: (entityType: string) => void;
}

/** "A", "A and B", "A, B and C" - the blockers as one clause. */
function joinAnd(parts: ReactNode[]): ReactNode {
  return parts.map((part, i) => (
    <Fragment key={i}>
      {i > 0 && (i === parts.length - 1 ? ' and ' : ', ')}
      {part}
    </Fragment>
  ));
}

/**
 * The prerequisite-master warning above a company's Entities list (plan
 * sprint-5/01, AC-01-20). A document's rows stay `retryable` (never lost)
 * while a master they reference is missing or inactive - so this WARNS, one
 * line per document entity naming only the masters that block it, and offers
 * to add the missing ones; it never blocks. Absent when nothing is blocked.
 * Labels come from Terminology, so a tenant's renames carry through.
 */
export function DocumentPrerequisiteCard({ prerequisites, onAdd }: DocumentPrerequisiteCardProps) {
  const { label, labelPlural } = useTerminology();
  const lines = prerequisites.filter((p) => p.missing.length + p.inactive.length > 0);
  if (lines.length === 0) return null;

  return (
    <Alert variant="warning" appearance="light" data-testid="document-prerequisites">
      <AlertIcon>
        <TriangleAlert />
      </AlertIcon>
      <AlertContent>
        {lines.map((line) => {
          const blockers = [...line.missing, ...line.inactive];
          return (
            <div
              key={line.entityType}
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5"
              data-testid={`prerequisite-${line.entityType}`}
            >
              <span className="text-sm">
                {labelPlural(line.entityType)} will stay retryable until{' '}
                {joinAnd(
                  blockers.map((master) => (
                    <strong key={master} className="font-semibold">
                      {labelPlural(master)}
                    </strong>
                  )),
                )}{' '}
                {blockers.length === 1 ? 'is' : 'are'} active.
              </span>
              {onAdd &&
                line.missing.map((master) => (
                  <Button
                    key={master}
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onAdd(master)}
                    data-testid={`add-prerequisite-${master}`}
                  >
                    <Plus />
                    Add {label(master)}
                  </Button>
                ))}
            </div>
          );
        })}
      </AlertContent>
    </Alert>
  );
}
