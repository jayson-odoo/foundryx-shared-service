'use client';

import { useCallback, useMemo, useState } from 'react';
import { LoaderCircleIcon, TriangleAlert } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { SearchSelect } from '@/components/platform/search-select';
import { FormRow } from '@/components/platform/resource-form';
import { ApiError } from '@/lib/api-client';
import { autocountService } from '@/services/autocount-service';
import { useAutocountConsumerConnections } from '@/hooks/use-autocount-consumer-connections';
import type { AutocountCompany, AutocountSinkImpl } from '@/types/autocount';

const SINK_OPTIONS = [
  { label: 'No delivery (logging only)', value: 'logging' },
  { label: 'Sorento', value: 'sorento' },
];

function sinkLabel(company: AutocountCompany): string {
  return company.sinkImpl === 'sorento' ? 'Sorento' : 'No delivery (logging only)';
}

export interface SinkTargetCardProps {
  company: AutocountCompany;
  canManage: boolean;
  onSaved: () => void;
}

/**
 * Where a company pushes its synced masters (plan 14 hop 2). `logging` is the
 * no-op default; `sorento` requires a consumer connection. Read-only when the
 * operator lacks `autocount.companies.manage` — the picker is offered only when
 * a save could actually succeed (foolproof-UI).
 */
export function SinkTargetCard({ company, canManage, onSaved }: SinkTargetCardProps) {
  const { options, isLoading, emptyReason } = useAutocountConsumerConnections();
  const [sinkImpl, setSinkImpl] = useState<AutocountSinkImpl>(
    company.sinkImpl === 'sorento' ? 'sorento' : 'logging',
  );
  const [connectionId, setConnectionId] = useState<string | null>(
    company.sinkConnectionId,
  );
  const [saving, setSaving] = useState(false);

  const needsConnection = sinkImpl === 'sorento';
  const noConnections = needsConnection && !isLoading && options.length === 0;
  const dirty =
    sinkImpl !== company.sinkImpl ||
    (needsConnection && connectionId !== company.sinkConnectionId);
  const canSave =
    dirty && !saving && (!needsConnection || (Boolean(connectionId) && !noConnections));

  const onSelectSink = useCallback((value: string) => {
    const next = value === 'sorento' ? 'sorento' : 'logging';
    setSinkImpl(next);
    // Switching back to logging clears the target — a stale connection id must
    // not linger on a no-delivery company.
    if (next === 'logging') setConnectionId(null);
  }, []);

  const onSave = useCallback(async () => {
    setSaving(true);
    try {
      await autocountService.updateSinkTarget(company.id, {
        sinkImpl,
        sinkConnectionId: sinkImpl === 'sorento' ? connectionId : null,
      });
      toast.success('Push target updated.');
      onSaved();
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : 'That push target could not be saved.',
      );
    } finally {
      setSaving(false);
    }
  }, [company.id, connectionId, onSaved, sinkImpl]);

  const currentConnectionLabel = useMemo(() => {
    if (company.sinkImpl !== 'sorento') return null;
    const match = options.find((o) => o.value === company.sinkConnectionId);
    return match?.label ?? company.sinkConnectionId ?? '—';
  }, [company.sinkConnectionId, company.sinkImpl, options]);

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Push target</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!canManage ? (
          <div className="flex flex-col gap-1 text-sm">
            <span className="text-foreground">{sinkLabel(company)}</span>
            {currentConnectionLabel && (
              <span className="text-muted-foreground">{currentConnectionLabel}</span>
            )}
          </div>
        ) : (
          <>
            <FormRow label="Delivery">
              <SearchSelect
                options={SINK_OPTIONS}
                value={sinkImpl}
                onChange={onSelectSink}
                ariaLabel="Push delivery target"
              />
            </FormRow>

            {needsConnection && (
              <FormRow label="Sorento connection">
                <div className="flex flex-col gap-2">
                  <SearchSelect
                    options={options}
                    value={connectionId}
                    onChange={(value) => setConnectionId(value)}
                    placeholder={isLoading ? 'Loading…' : 'Select a connection'}
                    disabled={isLoading || noConnections}
                    ariaLabel="Sorento consumer connection"
                  />
                  {emptyReason && (
                    <Alert variant="warning" appearance="light">
                      <AlertIcon>
                        <TriangleAlert />
                      </AlertIcon>
                      <AlertTitle>{emptyReason}</AlertTitle>
                    </Alert>
                  )}
                </div>
              </FormRow>
            )}

            <div className="flex justify-end">
              <Button size="sm" disabled={!canSave} onClick={() => void onSave()}>
                {saving ? <LoaderCircleIcon className="size-4 animate-spin" /> : null}
                Save
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
