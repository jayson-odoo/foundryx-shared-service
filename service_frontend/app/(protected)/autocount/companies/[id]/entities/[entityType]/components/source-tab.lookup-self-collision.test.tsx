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
 * Browser round 1 defect (AC-10-09): a preview's `columns` is RAW
 * main-endpoint columns UNION every alias the REQUEST's lookups carried (so
 * the grid can show enriched values) - passing that straight through as the
 * alias editor's "source columns" made a pre-filled lookup's OWN alias
 * falsely collide with itself.
 *
 * Confirm round 2 (B1): fixed at the WIRE, not by subtraction. The response
 * now carries `rawColumns` - the walked endpoint's own columns, never an
 * alias, never a combine computed alias - and `source-tab.tsx` hands exactly
 * that to the Lookups editor. Every fixture below therefore mirrors the REAL
 * backend response: the request's aliases ARE in `columns`, and `rawColumns`
 * is raw only.
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

/** The three RAW columns of `/itembypage` - what `rawColumns` reports and the
 * ONLY names the alias editor may call taken. */
const RAW_COLUMNS = ['ItemCode', 'Description', 'LastModified'];

/** A COMBINED preview response, both lookups' aliases echoed in `columns`
 * (backend design) AND `task.sourceConfig.lookups` naming exactly what was
 * tested. `extraColumns` widens the MERGED set the way a request carrying a
 * freshly-typed draft alias really does. */
function combinedHttpPreview(
  over: { taskLookups?: AutocountEtlSourceConfig['lookups']; extraColumns?: string[] } = {},
): UseHttpPreviewResult {
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
          ...(over.extraColumns ?? []).map((name) => ({ name, sample: null })),
        ],
        rawColumns: RAW_COLUMNS,
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

  // Confirm round 2, repro B (AC-10-01/AC-10-05) - the REAL response shape:
  // the Test posts the DRAFT's lookups, so the merged `columns` comes back
  // carrying `FreshAlias` even though the STORED (echoed) task predates it.
  // Only `rawColumns` can tell the editor that name is still free.
  it('a second field on an already-tested lookup, given a brand-new alias, keeps NO inline error (a merged alias is not a raw column)', () => {
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
        // The stored task still names only the FIRST field...
        taskLookups: [
          {
            path: '/itemuombypage',
            as: 'uom',
            on: [{ local: 'ItemCode', remote: 'ItemCode' }],
            fields: [{ remote: 'Price', as: 'BaseUOMPrice' }],
          },
        ],
        // ...while the Test itself posted the draft, so the server merged
        // `FreshAlias` into `columns`.
        extraColumns: ['FreshAlias'],
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
    // all - `preview.task` is `undefined`. The REQUEST still carried the
    // preset's lookups, so all three aliases come back INSIDE `columns`;
    // `rawColumns` is the only raw list.
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
            { name: 'ItemBaseUOM', sample: 'UNIT' },
            { name: 'ItemDescription', sample: 'Widget' },
            { name: 'UomRate', sample: '1' },
          ],
          rawColumns: ['ItemCode', 'Location', 'BalQty'],
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
    expect(screen.getByDisplayValue('ItemDescription')).toHaveAttribute('aria-invalid', 'false');
    expect(screen.getByDisplayValue('UomRate')).toHaveAttribute('aria-invalid', 'false');
    expect(screen.queryByText('"ItemBaseUOM" is already a source column.')).not.toBeInTheDocument();
    expect(screen.queryByText('"ItemDescription" is already a source column.')).not.toBeInTheDocument();
    expect(screen.queryByText('"UomRate" is already a source column.')).not.toBeInTheDocument();
  });

  // Confirm round 2, item 4 (AC-10-01) - a combine's COMPUTED alias is not a
  // source column: the backend keys that clash to
  // `combine.computed[i].alias`, so the Lookups editor must not duplicate it
  // as "already a source column". Falls straight out of `rawColumns` never
  // carrying a computed alias.
  it('a lookup alias equal to a combine COMPUTED alias is never reported as a source column', () => {
    const cfg = httpConfig({
      lookups: [
        {
          path: '/itemuombypage',
          as: 'uom',
          on: [{ local: 'ItemCode', remote: 'ItemCode' }],
          fields: [{ remote: 'Rate', as: 'item_code' }],
        },
      ],
    });
    renderApiBranch({
      cfg,
      httpPreview: combinedHttpPreview({
        taskLookups: [],
        // A combine-carrying Test echoes the computed alias in the merged
        // `columns` (and in `preCombineColumns`), never in `rawColumns`.
        extraColumns: ['item_code'],
      }),
    });
    expect(screen.queryByText('"item_code" is already a source column.')).not.toBeInTheDocument();
  });
});
