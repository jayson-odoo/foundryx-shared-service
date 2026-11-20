'use client';

/**
 * "Reset to preset" preview dialog (sprint-5/12, Group B - AC-12-20..23).
 * ONE component: the SAME lightbox spring `MappingSimulator` rides (no new
 * primitive, D6) - a preview surface, never a `ResourceAction.confirm` and
 * never a `deferred` action (D6): the value is SEEING the diff before
 * acting, and the apply stays editable afterwards (reversible through the
 * mapping table itself), so it does not qualify for the T5 typed-confirm
 * carve-out inventory.
 */
import { LoaderCircle, TriangleAlert } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge, type StatusRegistry } from '@/components/platform/status-badge';
import { toast } from '@/lib/toast';
import { humanizeFieldKey } from '@/lib/autocount-diff';
import { useMappingReset } from '@/hooks/use-mapping-reset';
import type { AutocountMappingResetRow, AutocountMappingView } from '@/types/autocount';
import { isMappingResetPreviewEmpty } from '@/types/autocount';

export interface MappingResetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  companyId: string;
  entityType: string;
  /** The fresh mapping view after a successful apply (AC-12-23) - the
   *  caller reloads its own table from this. */
  onApplied: (view: AutocountMappingView) => void;
}

const CHANGE_REGISTRY: StatusRegistry<AutocountMappingResetRow['change']> = {
  added: { label: 'Added', tone: 'success' },
  changed: { label: 'Changed', tone: 'warning' },
  unchanged: { label: 'Unchanged', tone: 'secondary' },
};

function rowChip(row: { transform: string; formula: string | null }): string {
  return row.formula ?? humanizeFieldKey(row.transform);
}

export function MappingResetDialog({
  open,
  onOpenChange,
  companyId,
  entityType,
  onApplied,
}: MappingResetDialogProps) {
  const { preview, isLoading, loadError, isApplying, applyError, apply } = useMappingReset(
    companyId,
    entityType,
    open,
    (view) => {
      toast.success('Mapping reset to preset.');
      onOpenChange(false);
      onApplied(view);
    },
  );

  const isEmpty = preview ? isMappingResetPreviewEmpty(preview) : false;
  const canReset = Boolean(preview) && !isEmpty && !isLoading && !isApplying;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Reset to preset
            {preview && (
              <Badge variant="secondary" appearance="light" size="sm">
                {preview.label}
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>

        <DialogBody className="flex flex-col gap-4">
          {isLoading && (
            <div
              className="flex items-center gap-2 py-6 text-sm text-muted-foreground"
              data-testid="mapping-reset-loading"
            >
              <LoaderCircle className="size-4 animate-spin" />
              Comparing to the preset…
            </div>
          )}

          {!isLoading && loadError && (
            <Alert variant="destructive" appearance="light" data-testid="mapping-reset-load-error">
              <AlertIcon>
                <TriangleAlert />
              </AlertIcon>
              <AlertTitle>{loadError}</AlertTitle>
            </Alert>
          )}

          {!isLoading && !loadError && preview && isEmpty && (
            <p className="py-4 text-sm text-muted-foreground" data-testid="mapping-reset-empty">
              This mapping already matches the preset.
            </p>
          )}

          {!isLoading && !loadError && preview && !isEmpty && (
            <div className="flex max-h-96 flex-col gap-3 overflow-y-auto" data-testid="mapping-reset-rows">
              {preview.rows.map((row) => (
                <div
                  key={row.canonicalField}
                  className="flex flex-col gap-1 rounded-md border border-border p-2.5"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={row.change} registry={CHANGE_REGISTRY} size="sm" />
                    <span className="text-sm font-medium text-foreground">
                      {humanizeFieldKey(row.canonicalField)}
                    </span>
                    {row.isRequired && (
                      <Badge variant="secondary" appearance="light" size="sm">
                        Required
                      </Badge>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <code>{row.sourcePath}</code>
                    <span>→</span>
                    <ClampedText
                      text={rowChip(row)}
                      lines={2}
                      className="font-mono text-2xs text-muted-foreground/80"
                    />
                  </div>
                  {!row.enabled && (
                    <span className="text-xs text-warning" data-testid="mapping-reset-disabled-reason">
                      Disabled - {row.disabledReason}
                    </span>
                  )}
                </div>
              ))}

              {preview.removed.length > 0 && (
                <div className="flex flex-col gap-2 border-t border-border pt-3">
                  <span className="text-xs font-medium text-muted-foreground">Removed</span>
                  <div className="flex flex-col gap-1.5" data-testid="mapping-reset-removed">
                    {preview.removed.map((row) => (
                      <div key={row.canonicalField} className="flex flex-wrap items-center gap-2 text-xs">
                        <code className="text-muted-foreground">{row.sourcePath}</code>
                        <span className="text-muted-foreground">→</span>
                        <span className="text-foreground">{humanizeFieldKey(row.canonicalField)}</span>
                        <Badge variant="destructive" appearance="light" size="sm">
                          Removed
                        </Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

        </DialogBody>

        {/* AC-12-23: a failed apply keeps the dialog open, the server
            message taking the primary button's row (mirrors
            `MappingSimulator`'s own inline run-error placement - no new
            error-surface pattern). */}
        <DialogFooter className="flex-wrap items-center gap-2">
          {applyError && (
            <span className="me-auto text-xs text-destructive" data-testid="mapping-reset-apply-error">
              {applyError}
            </span>
          )}
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isApplying}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void apply()} disabled={!canReset}>
            {isApplying && <LoaderCircle className="size-4 animate-spin" />}
            Reset mapping
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
