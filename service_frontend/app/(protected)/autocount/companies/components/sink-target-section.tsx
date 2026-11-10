'use client';

import { useMemo } from 'react';
import { TriangleAlert } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { SearchSelect } from '@/components/platform/search-select';
import { useAutocountConsumerConnections } from '@/hooks/use-autocount-consumer-connections';
import type { AutocountCompany, AutocountSinkImpl } from '@/types/autocount';
import { DetailRow } from './detail-row';

const SINK_OPTIONS = [
  { label: 'No delivery (logging only)', value: 'logging' },
  { label: 'Sorento', value: 'sorento' },
];

function sinkLabel(impl: AutocountSinkImpl | string): string {
  return impl === 'sorento' ? 'Sorento' : 'No delivery (logging only)';
}

export interface SinkTargetSectionProps {
  /** The persisted company - read mode renders from this. */
  company: AutocountCompany;
  /** The form's global Edit toggle. Read-only until true (AC-15-20). */
  editing: boolean;
  /** Working edit state (lifted to the parent so the form owns dirty + save). */
  sinkImpl: AutocountSinkImpl;
  connectionId: string | null;
  onSinkChange: (impl: AutocountSinkImpl) => void;
  onConnectionChange: (id: string | null) => void;
  /** Working Sorento company code (plan 22 S2, Appendix A6) - required with `sorento`. */
  companyCode: string;
  onCompanyCodeChange: (code: string) => void;
}

/**
 * Where a company pushes its synced masters (plan 14 hop 2), folded INTO the
 * company Overview Resource form (AC-15-20/21). Read mode = plain label/value
 * rows on the same grid as the identity fields; Edit mode = searchable
 * `SearchSelect`s saved through the form's single save, never a detached button.
 * `logging` is the no-op default; `sorento` needs a consumer connection AND a
 * Sorento company code (the anchor every Sorento call demands, Appendix A6) -
 * either missing is warned in place and blocked by the parent's save, and a
 * legacy company still missing its code shows that in read mode too, since it
 * is the prerequisite the task editor's Activate is withheld on.
 */
export function SinkTargetSection({
  company,
  editing,
  sinkImpl,
  connectionId,
  onSinkChange,
  onConnectionChange,
  companyCode,
  onCompanyCodeChange,
}: SinkTargetSectionProps) {
  const { options, isLoading, emptyReason } = useAutocountConsumerConnections();

  const noConnections = !isLoading && options.length === 0;
  const showConnection = editing
    ? sinkImpl === 'sorento'
    : company.sinkImpl === 'sorento';

  const readConnectionLabel = useMemo(() => {
    const match = options.find((o) => o.value === company.sinkConnectionId);
    return match?.label ?? company.sinkConnectionId ?? '-';
  }, [company.sinkConnectionId, options]);

  // Foolproof-UI: Sorento with no connection is a guaranteed sync failure - warn
  // in place (the parent's save also refuses it), never fail silently later.
  const missingConnection = editing && sinkImpl === 'sorento' && !connectionId;
  const missingCode = editing && sinkImpl === 'sorento' && !companyCode.trim();
  const persistedCode = (company.sorentoCompanyCode ?? '').trim();

  return (
    <>
      <DetailRow label="Delivery">
        {editing ? (
          <SearchSelect
            options={SINK_OPTIONS}
            value={sinkImpl}
            onChange={(value) => onSinkChange(value === 'sorento' ? 'sorento' : 'logging')}
            ariaLabel="Push delivery target"
          />
        ) : (
          sinkLabel(company.sinkImpl)
        )}
      </DetailRow>

      {showConnection && (
        <DetailRow label="Sorento connection">
          {editing ? (
            <div className="flex flex-col gap-2">
              <SearchSelect
                options={options}
                value={connectionId}
                onChange={(value) => onConnectionChange(value)}
                placeholder="Select a connection"
                disabled={isLoading || noConnections}
                ariaLabel="Sorento consumer connection"
              />
              {(emptyReason || missingConnection) && (
                <Alert variant="warning" appearance="light" data-testid="sink-connection-warning">
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>
                    {emptyReason ?? 'Choose a Sorento connection before saving.'}
                  </AlertTitle>
                </Alert>
              )}
            </div>
          ) : (
            readConnectionLabel
          )}
        </DetailRow>
      )}

      {showConnection && (
        <DetailRow label="Sorento company code">
          {editing ? (
            <div className="flex flex-col gap-2">
              <Input
                value={companyCode}
                onChange={(event) => onCompanyCodeChange(event.target.value)}
                aria-label="Sorento company code"
                aria-invalid={missingCode}
                className="sm:max-w-xs"
                data-testid="sink-company-code"
              />
              {missingCode && (
                <Alert variant="warning" appearance="light" data-testid="sink-company-code-warning">
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>Enter the Sorento company code before saving.</AlertTitle>
                </Alert>
              )}
            </div>
          ) : persistedCode ? (
            <code className="text-xs" data-testid="sink-company-code-value">
              {persistedCode}
            </code>
          ) : (
            <Badge variant="warning" appearance="light" size="sm" data-testid="sink-company-code-missing">
              Not set
            </Badge>
          )}
        </DetailRow>
      )}
    </>
  );
}
