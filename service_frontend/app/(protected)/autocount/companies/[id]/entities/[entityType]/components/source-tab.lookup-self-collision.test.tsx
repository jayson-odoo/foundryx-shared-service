import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type {
  AutocountApiConnection,
  AutocountEtlSourceConfig,
  AutocountEtlTask,
  AutocountFormulaTestResult,
} from '@/types/autocount';
import type { UseHttpPreviewResult, UseSqlPreviewResult } from '@/hooks/use-autocount-etl';
import { SourceTab } from './source-tab';

/**
 * Browser round 1 defect (AC-10-09): a COMBINED preview's `columns` is RAW
 * main-endpoint columns UNION every attached lookup's own alias (so the grid
 * can show enriched values) - passing that straight through as the alias
 * editor's "source columns" made a pre-filled lookup's OWN, already-tested
 * alias falsely collide with itself. Fixed in `source-tab.tsx` by deriving
 * the collision check's raw-column set from the backend-echoed
 * `preview.task.sourceConfig.lookups` (the EXACT aliases baked into the
 * current merged columns) rather than the live, possibly freshly-typed
 * `config.lookups`.
 */

function httpConfig(over: Partial<AutocountEtlSourceConfig> = {}): AutocountEtlSourceConfig {
  return {
    connectionId: 'conn-api-sorento',
    query: '',
    lineQuery: null,
    keyColumns: [],
    watermarkColumn: null,
    comparedColumns: [],
    fromDate: null,
    docDateColumn: null,
    filterFormula: null,
    incrementalMinutes: 15,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
    path: '/itembypage',
    keyFields: ['ItemCode'],
    watermarkField: 'LastModified',
    comparedFields: [],
    lookups: [
      {
        path: '/itemuombypage',
        as: 'uom',
        on: [{ local: 'ItemCode', remote: 'ItemCode' }],
        fields: [{ remote: 'Price', as: 'BaseUOMPrice' }],
      },
    ],
    ...over,
  };
}

function idlePreview(): UseSqlPreviewResult {
  return { state: { status: 'idle' }, run: vi.fn(), reset: vi.fn() };
}

function passThroughServer(formula: string, value: unknown): Promise<AutocountFormulaTestResult> {
  return Promise.resolve({ ok: true, output: value, error: null });
}

const API_CONNECTIONS: AutocountApiConnection[] = [
  { id: 'conn-api-sorento', name: 'Sorento REST', baseUrl: 'https://hapi.sorento.cc.cd/api/db1', auth: 'none' },
];

function echoedTask(lookups: AutocountEtlSourceConfig['lookups']): AutocountEtlTask {
  return {
    companyId: 'company-1',
    entityType: 'product',
    etlStatus: 'draft',
    activatedAt: null,
    sourceImpl: 'autocount_http',
    sourceConfig: httpConfig({ lookups }),
    resultColumns: ['ItemCode', 'Description', 'LastModified'],
    lastPreviewAt: '2026-09-20T00:00:00Z',
    lastPreviewFailedCount: 0,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
  };
}

/** A COMBINED preview response, both lookups' aliases echoed in `columns`
 * (backend design) AND `task.sourceConfig.lookups` naming exactly what was
 * tested. */
function combinedHttpPreview(over: { taskLookups?: AutocountEtlSourceConfig['lookups'] } = {}): UseHttpPreviewResult {
  const testedLookups =
    over.taskLookups ??
    ([
      {
        path: '/itemuombypage',
        as: 'uom',
        on: [{ local: 'ItemCode', remote: 'ItemCode' }],
        fields: [{ remote: 'Price', as: 'BaseUOMPrice' }],
      },
      {
        path: '/itemuombypage',
        as: 'uom2',
        on: [{ local: 'ItemCode', remote: 'ItemCode' }],
        fields: [{ remote: 'Rate', as: 'BaseUOMRate' }],
      },
    ] as AutocountEtlSourceConfig['lookups']);
  return {
    state: {
      status: 'success',
      preview: {
        envelope: 'paged',
        totalCount: 11826,
        columns: [
          { name: 'ItemCode', sample: 'SRT-01' },
          { name: 'Description', sample: 'Sorento bathtub waste' },
          { name: 'LastModified', sample: '2026-08-01T00:00:00' },
          { name: 'BaseUOMPrice', sample: '63.00' },
          { name: 'BaseUOMRate', sample: '1.2' },
        ],
        rows: [],
        durationMs: 220,
        lookups: [
          { alias: 'uom', matched: 50, missed: 0 },
          { alias: 'uom2', matched: 50, missed: 0 },
        ],
        task: echoedTask(testedLookups),
      },
    },
    run: vi.fn(),
    fieldErrors: {},
    reset: vi.fn(),
  };
}

function renderApiBranch(over: { cfg?: AutocountEtlSourceConfig; httpPreview?: UseHttpPreviewResult } = {}) {
  render(
    <SourceTab
      editing
      entityType="product"
      sourceKind="api"
      onSourceKindChange={vi.fn()}
      config={over.cfg ?? httpConfig()}
      onChange={vi.fn()}
      connections={[]}
      connectionsLoading={false}
      lockedConnection={null}
      schema={{ schemas: [], isLoading: false, error: null, refresh: vi.fn() }}
      preview={idlePreview()}
      linePreview={idlePreview()}
      fieldErrors={{}}
      onServerTest={passThroughServer}
      apiConnections={API_CONNECTIONS}
      apiConnectionsLoading={false}
      lockedApiConnection={null}
      httpPreview={over.httpPreview ?? { state: { status: 'idle' }, run: vi.fn(), fieldErrors: {}, reset: vi.fn() }}
      companyId="company-1"
      columnsProbe={{ columnsByKey: {}, loadingKeys: {}, errorsByKey: {}, run: vi.fn() }}
      onCombineFormulaTest={passThroughServer}
    />,
  );
}

describe('SourceTab Lookups editor - self-collision false positive (browser round 1, AC-10-09)', () => {
  it('a pre-filled lookup field keeps NO inline error after a combined Test echoes its own alias back', () => {
    renderApiBranch({ cfg: httpConfig(), httpPreview: combinedHttpPreview() });
    // Lookup #1's own field alias input carries `BaseUOMPrice` - no inline
    // 422-style error, even though the merged preview columns now literally
    // contain that string.
    const aliasInput = screen.getByDisplayValue('BaseUOMPrice');
    expect(aliasInput).toHaveAttribute('aria-invalid', 'false');
    expect(screen.queryByText('"BaseUOMPrice" is already a source column.')).not.toBeInTheDocument();
  });

  it('an alias that genuinely equals a real (untested) raw column still 422s inline', () => {
    // The second lookup's field is typed to `Description` - a REAL raw
    // column - but has never itself been tested (the echoed task only
    // named the FIRST lookup's `BaseUOMPrice`), so it must still collide.
    const cfg = httpConfig({
      lookups: [
        {
          path: '/itemuombypage',
          as: 'uom',
          on: [{ local: 'ItemCode', remote: 'ItemCode' }],
          fields: [{ remote: 'Price', as: 'BaseUOMPrice' }],
        },
        {
          path: '/itemuombypage',
          as: 'uom2',
          on: [{ local: 'ItemCode', remote: 'ItemCode' }],
          fields: [{ remote: 'Rate', as: 'Description' }],
        },
      ],
    });
    renderApiBranch({
      cfg,
      httpPreview: combinedHttpPreview({
        taskLookups: [
          {
            path: '/itemuombypage',
            as: 'uom',
            on: [{ local: 'ItemCode', remote: 'ItemCode' }],
            fields: [{ remote: 'Price', as: 'BaseUOMPrice' }],
          },
        ],
      }),
    });
    expect(screen.getByText('"Description" is already a source column.')).toBeInTheDocument();
  });

  it('an alias equal to an EARLIER lookup\'s alias still 422s inline (untouched by this fix)', () => {
    const cfg = httpConfig({
      lookups: [
        {
          path: '/itemuombypage',
          as: 'uom',
          on: [{ local: 'ItemCode', remote: 'ItemCode' }],
          fields: [{ remote: 'Price', as: 'BaseUOMPrice' }],
        },
        {
          path: '/itemuombypage',
          as: 'uom2',
          on: [{ local: 'ItemCode', remote: 'ItemCode' }],
          fields: [{ remote: 'Rate', as: 'BaseUOMPrice' }],
        },
      ],
    });
    renderApiBranch({ cfg, httpPreview: combinedHttpPreview() });
    expect(screen.getByText('"BaseUOMPrice" is already used by another lookup field.')).toBeInTheDocument();
  });

  it('a brand-new, never-tested alias is checked fresh - even when it matches the LAST tested value of a DIFFERENT field', () => {
    const cfg = httpConfig({
      lookups: [
        {
          path: '/itemuombypage',
          as: 'uom',
          on: [{ local: 'ItemCode', remote: 'ItemCode' }],
          // Just typed, not yet re-tested with THIS alias.
          fields: [{ remote: 'Price', as: 'ItemCode' }],
        },
      ],
    });
    renderApiBranch({
      cfg,
      // The LAST successful test ran with a DIFFERENT alias for this same
      // field - `ItemCode` has never itself been round-tripped as an alias,
      // so it must still collide with the genuine raw column of that name.
      httpPreview: combinedHttpPreview({
        taskLookups: [
          {
            path: '/itemuombypage',
            as: 'uom',
            on: [{ local: 'ItemCode', remote: 'ItemCode' }],
            fields: [{ remote: 'Price', as: 'SomeOtherName' }],
          },
        ],
      }),
    });
    expect(screen.getByText('"ItemCode" is already a source column.')).toBeInTheDocument();
  });

  // S5b-FE browser defect 3 (AC-10-01/AC-10-05) - `rawSourceColumns` must
  // never be widened by the DRAFT's own (untested, or freshly-typed but not
  // yet re-Tested) lookup aliases; only the SERVER's own base, minus the
  // aliases the echoed task proves are already baked in.
  it('a second field on an already-tested lookup, given a brand-new alias, keeps NO inline error (draft alias never widens the raw set)', () => {
    const cfg = httpConfig({
      lookups: [
        {
          path: '/itemuombypage',
          as: 'uom',
          on: [{ local: 'ItemCode', remote: 'ItemCode' }],
          // Second field just added to the already-tested lookup - a brand
          // new alias, never itself tested, and not a real raw column.
          fields: [
            { remote: 'Price', as: 'BaseUOMPrice' },
            { remote: 'Rate', as: 'FreshAlias' },
          ],
        },
      ],
    });
    renderApiBranch({
      cfg,
      httpPreview: combinedHttpPreview({
        taskLookups: [
          {
            path: '/itemuombypage',
            as: 'uom',
            on: [{ local: 'ItemCode', remote: 'ItemCode' }],
            // The echo only proves the FIRST field - `FreshAlias` was added
            // to the draft after that Test landed.
            fields: [{ remote: 'Price', as: 'BaseUOMPrice' }],
          },
        ],
      }),
    });
    const aliasInput = screen.getByDisplayValue('FreshAlias');
    expect(aliasInput).toHaveAttribute('aria-invalid', 'false');
    expect(screen.queryByText('"FreshAlias" is already a source column.')).not.toBeInTheDocument();
  });

  it('a preset\'s pre-filled-but-never-tested lookup aliases keep NO inline error on the entity\'s FIRST Test (no echo yet)', () => {
    const cfg = httpConfig({
      lookups: [
        {
          path: '/itembypage',
          as: 'item',
          on: [{ local: 'ItemCode', remote: 'ItemCode' }],
          fields: [
            { remote: 'BaseUOM', as: 'ItemBaseUOM' },
            { remote: 'Description', as: 'ItemDescription' },
          ],
        },
        {
          path: '/itemuombypage',
          as: 'uom',
          on: [{ local: 'ItemCode', remote: 'ItemCode' }],
          fields: [{ remote: 'Rate', as: 'UomRate' }],
        },
      ],
    });
    // A brand-new entity's first-ever Test: the backend has no
    // `ac_entity_config` row yet, so the response carries no `task` echo at
    // all - `preview.task` is `undefined`.
    const httpPreview: UseHttpPreviewResult = {
      state: {
        status: 'success',
        preview: {
          envelope: 'paged',
          totalCount: 100,
          columns: [
            { name: 'ItemCode', sample: 'SRT-01' },
            { name: 'Location', sample: 'MAIN' },
            { name: 'BalQty', sample: '10' },
          ],
          rows: [],
          durationMs: 180,
          lookups: [
            { alias: 'item', matched: 10, missed: 0 },
            { alias: 'uom', matched: 10, missed: 0 },
          ],
          task: undefined,
        },
      },
      run: vi.fn(),
      fieldErrors: {},
      reset: vi.fn(),
    };
    renderApiBranch({ cfg, httpPreview });
    expect(screen.getByDisplayValue('ItemBaseUOM')).toHaveAttribute('aria-invalid', 'false');
    expect(screen.getByDisplayValue('UomRate')).toHaveAttribute('aria-invalid', 'false');
    expect(screen.queryByText('"ItemBaseUOM" is already a source column.')).not.toBeInTheDocument();
    expect(screen.queryByText('"UomRate" is already a source column.')).not.toBeInTheDocument();
  });
});
