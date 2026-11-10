'use client';

import { Fragment, type ReactNode } from 'react';
import { Plus, TriangleAlert } from 'lucide-react';
import { Alert, AlertContent, AlertIcon } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useTerminology } from '@/hooks/use-terminology';
import type { AutocountDocumentPrerequisite } from '@/types/autocount';
import { AC_DOC_FEED_KEYS, docFeedLabel } from '../../components/autocount-meta';

/** AC-CANCEL-PULL - a doc-feed key in `inactive` (e.g. `delivery_orders`) is not a
 *  master: it means the company has no doc-feed book, which the cancel and
 *  consignment documents are filed under. Rendered as its own clause. */
function isDocFeedKey(key: string): boolean {
  return (AC_DOC_FEED_KEYS as string[]).includes(key);
}

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
          const feeds = line.inactive.filter(isDocFeedKey);
          const blockers = [...line.missing, ...line.inactive.filter((m) => !isDocFeedKey(m))];
          return (
            <div
              key={line.entityType}
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5"
              data-testid={`prerequisite-${line.entityType}`}
            >
              {blockers.length > 0 && (
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
              )}
              {feeds.length > 0 && (
                <span className="text-sm" data-testid={`prerequisite-${line.entityType}-feed`}>
                  {labelPlural(line.entityType)} cannot be delivered until the{' '}
                  <strong className="font-semibold">{docFeedLabel(feeds[0])}</strong> feed has a book.
                </span>
              )}
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
