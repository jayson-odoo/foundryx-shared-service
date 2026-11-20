'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { ResourceList } from '@/components/platform/resource-list';
import { RecordDiff } from '@/components/platform/autocount/record-diff';
import type {
  AutocountStagedRecord,
  AutocountStagedStatus,
} from '@/types/autocount';
import { AC_STAGED_STATUS_REGISTRY, entityLabel } from '../../../components/autocount-meta';
import { useStagedListConfig } from './use-staged-list-config';

/** A staged record's detail body - its per-field diff, or its mapping errors
 * when it failed. Shown in the row's detail drawer, not inline per row. */
export function StagedRecordBody({ record }: { record: AutocountStagedRecord }) {
  if (record.status === 'FAILED') {
    return (
      <div className="flex flex-col gap-2">
        {record.error && <p className="text-sm text-destructive">{record.error}</p>}
        {(record.errors ?? []).map((err, i) => (
          <p key={i} className="text-sm text-destructive">
            {[
              err.field ? `Field ${err.field}` : null,
              err.line !== undefined && err.line !== null ? `line ${err.line}` : null,
              err.message ?? null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        ))}
        {!record.error && (record.errors ?? []).length === 0 && (
          <p className="text-sm text-destructive">This record could not be mapped.</p>
        )}
      </div>
    );
  }
  return <RecordDiff diff={record.diff} canonical={record.canonical} />;
}

export interface StagedRecordsListProps {
  jobId: string;
  /** No-field-change record count in the batch - the collapsed line (AC-15-11). */
  noChangeCount: number;
}

/**
 * The staged records for a batch (AC-15-10/11). Records the operator must act on
 * (changed / failed) render through a server-paginated, searchable, filterable
 * Resource list; the no-field-change re-fetches collapse into ONE expandable
 * line so they never bury the records that DID change. A row opens its full diff
 * in a drawer.
 */
export function StagedRecordsList({ jobId, noChangeCount }: StagedRecordsListProps) {
  const [openRecord, setOpenRecord] = useState<AutocountStagedRecord | null>(null);
  const [showNoChange, setShowNoChange] = useState(false);

  const changedConfig = useStagedListConfig({
    jobId,
    changed: true,
    onOpenRecord: setOpenRecord,
  });
  const noChangeConfig = useStagedListConfig({
    jobId,
    changed: false,
    onOpenRecord: setOpenRecord,
  });

  return (
    <div className="flex flex-col gap-4">
      <ResourceList config={changedConfig} hideHeader />

      {noChangeCount > 0 && (
        <div className="flex flex-col gap-3" data-testid="no-change-collapse">
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => setShowNoChange((v) => !v)}
            data-testid="no-change-toggle"
            aria-expanded={showNoChange}
          >
            {showNoChange ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
            {noChangeCount} record{noChangeCount === 1 ? '' : 's'} with no field changes
          </Button>
          {showNoChange && <ResourceList config={noChangeConfig} hideHeader />}
        </div>
      )}

      <Dialog open={openRecord !== null} onOpenChange={(open) => !open && setOpenRecord(null)}>
        <DialogContent className="sm:max-w-2xl">
          {openRecord && (
            <>
              <DialogHeader>
                <DialogTitle className="flex flex-wrap items-center gap-2">
                  {openRecord.docNo || openRecord.sourceRef}
                  <StatusBadge
                    status={openRecord.status as AutocountStagedStatus}
                    registry={AC_STAGED_STATUS_REGISTRY}
                    size="sm"
                  />
                </DialogTitle>
                <DialogDescription>{entityLabel(openRecord.entityType)}</DialogDescription>
              </DialogHeader>
              <DialogBody>
                <StagedRecordBody record={openRecord} />
              </DialogBody>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
