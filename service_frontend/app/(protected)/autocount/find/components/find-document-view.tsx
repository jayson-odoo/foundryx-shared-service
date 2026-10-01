'use client';

import { useState } from 'react';
import { Database, Search, TriangleAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { JobProgress } from '@/components/platform/autocount/job-progress';
import { useAutocountCompanies } from '@/hooks/use-autocount-pull';
import { useDocLookup, useDocLookupTypes, type UseDocLookupOptions } from '@/hooks/use-autocount-doc-lookup';
import { formatVendorDay, stepsDone } from '@/lib/autocount-doc-lookup';
import type { DocLookupStartInput } from '@/types/autocount-doc-lookup';
import { DocResult } from './doc-result';
import { DocSearchForm } from './doc-search-form';
import { SearchSteps } from './search-steps';

export interface FindDocumentViewProps {
  /** Test seam - the service + poll cadence the search hook uses. */
  lookupOptions?: UseDocLookupOptions;
}

/**
 * `/autocount/find` (sprint-5/17) - search by number; stored sightings show
 * first, then the live AutoCount search fills in the current record.
 */
export function FindDocumentView({ lookupOptions }: FindDocumentViewProps) {
  const { companies } = useAutocountCompanies();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const { types } = useDocLookupTypes(companyId, lookupOptions?.service);
  const lookup = useDocLookup(lookupOptions);
  const [lastInput, setLastInput] = useState<DocLookupStartInput | null>(null);
  const [aroundDay, setAroundDay] = useState('');

  const job = lookup.job;
  const result = job?.result ?? null;
  const steps = result?.steps ?? [];
  const searching = lookup.phase === 'stored' || lookup.phase === 'searching';
  const typeLabel =
    types.find((t) => t.key === (result?.docType ?? lastInput?.docType))?.label ?? 'Document';
  const storedEmpty =
    lookup.stored !== null && lookup.stored.snapshots.length === 0 && lookup.stored.ledger === null;

  const search = (input: DocLookupStartInput) => {
    setLastInput(input);
    void lookup.search(input);
  };

  return (
    <Container width="fluid">
      <PageHeader title="Find document" crumbs={[{ label: 'AutoCount' }, { label: 'Find document' }]} />

      <div className="flex flex-col gap-4">
        <Card>
          <CardContent>
            <DocSearchForm
              companies={companies}
              types={types}
              companyId={companyId}
              onCompanyChange={(id) => {
                setCompanyId(id);
                lookup.reset();
              }}
              busy={searching}
              onSearch={search}
            />
          </CardContent>
        </Card>

        {lookup.phase === 'error' && lookup.error && (
          <Alert variant="destructive" appearance="light" data-testid="ac-find-error">
            <AlertIcon>
              <TriangleAlert />
            </AlertIcon>
            <AlertTitle>{lookup.error}</AlertTitle>
          </Alert>
        )}

        {searching && storedEmpty && (
          <Alert variant="info" appearance="light" data-testid="ac-find-stored-empty">
            <AlertIcon>
              <Database />
            </AlertIcon>
            <div className="flex flex-col gap-0.5">
              <AlertTitle>Not in any stored snapshot</AlertTitle>
              <AlertDescription>The feed never pushed it either.</AlertDescription>
            </div>
          </Alert>
        )}

        {searching && (
          <Card data-testid="ac-find-searching">
            <CardHeader>
              <CardHeading>
                <CardTitle>Searching AutoCount</CardTitle>
              </CardHeading>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <JobProgress
                status={lookup.stopping ? 'cancelling' : job ? 'running' : 'queued'}
                stage={null}
                pagesDone={job ? stepsDone(steps) : null}
                pagesTotal={job ? steps.length || null : null}
                unit="days"
                onCancel={job ? () => void lookup.stop() : undefined}
                cancelLabel="Stop"
              />
              {steps.length > 0 && <SearchSteps steps={steps} running />}
            </CardContent>
          </Card>
        )}

        {lookup.phase === 'done' && job && result?.found && (
          <DocResult result={result} stored={lookup.stored} typeLabel={typeLabel} />
        )}

        {lookup.phase === 'done' && job && result && !result.found && job.status !== 'failed' && (
          <Card data-testid="ac-find-not-found">
            <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
              <p className="font-heading text-base font-semibold">
                {job.status === 'aborted' ? `Search for ${result.docNo} stopped` : `${result.docNo} was not found`}
              </p>
              <p className="max-w-2xl text-sm text-muted-foreground">
                Searched snapshots, the document feed
                {result.searched.lastModifiedFrom
                  ? `, modified-on ${formatVendorDay(result.searched.lastModifiedFrom)} – ${formatVendorDay(result.searched.lastModifiedTo)}`
                  : ''}
                {` and DocDate ${formatVendorDay(result.searched.docDateFrom)} – ${formatVendorDay(result.searched.docDateTo)}`} (
                {stepsDone(steps)} AutoCount reads).
              </p>
              {lastInput && (
                <form
                  className="mt-3 flex flex-wrap items-center justify-center gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (aroundDay) search({ ...lastInput, aroundDay });
                  }}
                >
                  <Input
                    type="date"
                    aria-label="Around date"
                    className="w-44"
                    value={aroundDay}
                    onChange={(e) => setAroundDay(e.target.value)}
                  />
                  <Button type="submit" variant="outline" disabled={!aroundDay}>
                    <Search className="size-4" />
                    Search around date
                  </Button>
                </form>
              )}
              {steps.length > 0 && (
                <div className="mt-4 w-full text-left">
                  <SearchSteps steps={steps} />
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {lookup.phase === 'done' && job?.status === 'failed' && (
          <Alert variant="destructive" appearance="light" data-testid="ac-find-failed">
            <AlertIcon>
              <TriangleAlert />
            </AlertIcon>
            <AlertTitle>{job.error ?? 'The search failed.'}</AlertTitle>
          </Alert>
        )}
      </div>
    </Container>
  );
}
