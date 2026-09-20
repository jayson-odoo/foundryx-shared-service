'use client';

import { useCallback, useMemo, useState } from 'react';
import Link from 'next/link';
import { Info, Lock, Play, TriangleAlert, Wand2 } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { AutocountFormulaBuilder } from '@/components/platform/autocount/formula-builder';
import { ColumnChips, ColumnPickers } from '@/components/platform/autocount/column-pickers';
import { SqlEditor } from '@/components/platform/autocount/sql-editor';
import { SqlPreviewGrid } from '@/components/platform/autocount/sql-preview-grid';
import { SqlSchemaTree } from '@/components/platform/autocount/sql-schema-tree';
import type {
  UseAutocountSqlSchemaResult,
  UseHttpPreviewResult,
  UseSqlPreviewResult,
} from '@/hooks/use-autocount-etl';
import type { UsePreviewColumnsMapResult } from '@/hooks/use-autocount-pull';
import {
  AC_API_CAPABLE_ENTITY_TYPES,
  entityLabel,
} from '../../../../../components/autocount-meta';
import {
  httpPreviewAsSqlPreview,
  httpPreviewBadgeText,
  isDocumentEntity,
  pickerColumnOptions,
  previewBadgeText,
  starterQuery,
} from '@/lib/autocount-etl';
import type {
  AutocountApiConnection,
  AutocountCombinePreviewResult,
  AutocountConnectionAuth,
  AutocountEtlSourceConfig,
  AutocountEtlTask,
  AutocountFormulaTestResult,
  AutocountMappingPreset,
  AutocountSqlConnection,
} from '@/types/autocount';
import { CombineEditor } from './combine-editor';
import { LookupsEditor } from './lookups-editor';

/**
 * The company connection a DB company's task is locked to (AC-01-19): shown
 * as a read-only row where a free-picking company has a picker. The editor
 * seeds it into the config BASELINE (never a post-mount patch, which would
 * dirty an untouched editor), so the save never has to guess.
 */
export interface LockedConnection {
  id: string;
  /** `name · database` when the connection is loaded; the company database until then. */
  label: string;
}

/** The API branch's locked connection (sprint-5/08, AC-08-19) - an http/api
 * company's task reads through its OWN connection, never a free picker. */
export interface LockedApiConnection {
  id: string;
  label: string;
  auth: AutocountConnectionAuth;
}

/** The task's Source (sprint-5/08, D13) - the ONE place API vs Database is chosen. */
export type SourceKind = 'db' | 'api';

const SOURCE_KIND_OPTIONS: { value: SourceKind; label: string }[] = [
  { value: 'api', label: 'API' },
  { value: 'db', label: 'Database' },
];

/** The shell's segmented-control styling (selected = filled primary). */
const SEGMENT_CLASS =
  'data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary';

export interface SourceTabProps {
  editing: boolean;
  entityType: string;
  sourceKind: SourceKind;
  onSourceKindChange: (kind: SourceKind) => void;
  config: AutocountEtlSourceConfig;
  onChange: (patch: Partial<AutocountEtlSourceConfig>) => void;
  connections: AutocountSqlConnection[];
  connectionsLoading: boolean;
  /** Set on a DB company - replaces the Database Connection picker with a read-only row. */
  lockedConnection?: LockedConnection | null;
  schema: UseAutocountSqlSchemaResult;
  preview: UseSqlPreviewResult;
  /** Documents only (plan 22 S5) - a SEPARATE preview instance for the line
   * query, so testing it never clobbers the header preview's state. */
  linePreview: UseSqlPreviewResult;
  /** Per-field 422 errors from the last save (AC-22-11/AC-08-13). */
  fieldErrors: Record<string, string>;
  /**
   * Document entities only (sprint-5/02, AC-02-16/17) - the AutoCount
   * SQL-pack preset for THIS entity, already substituted for the company's
   * database. Empty/undefined = "Use preset" is not offered (foolproof-UI -
   * never show a picker with nothing that would work).
   */
  presets?: AutocountMappingPreset[];
  onUsePreset?: (preset: AutocountMappingPreset) => void;
  /** Server-authoritative single-formula eval, backing the Filter field's
   * `AutocountFormulaBuilder` Testing tab (AC-02-11/20). */
  onServerTest: (formula: string, value: unknown) => Promise<AutocountFormulaTestResult>;
  // ── API branch (sprint-5/08) ──────────────────────────────────────────────
  /** Every `autocount` connection of the tenant, badged by auth (AC-08-15). */
  apiConnections: AutocountApiConnection[];
  apiConnectionsLoading: boolean;
  /** Set on an http/api company - locks the picker to the company's own
   * connection (AC-08-19). A `db` company keeps the free picker (AC-08-13:
   * "an HTTP task on a DB company may reference ANY open connection"). */
  lockedApiConnection?: LockedApiConnection | null;
  httpPreview: UseHttpPreviewResult;
  /** The task's owning company (sprint-5/08 review round 1, B3) - passed to
   * `httpPreview.run` so a clean Test ALSO stamps `resultColumns`/
   * `lastPreviewAt` on this exact task (AC-08-14), the same way the SQL
   * tab's Test Query already does implicitly by saving through the task
   * route. Without it, the activate-once gate could only ever be satisfied
   * by Review & Activate's own "Preview" ceremony, never the Source tab's
   * own Test button. */
  companyId: string;
  /**
   * A Test succeeded for exactly this `connectionId`/`path` pair (AC-08-20) -
   * `TaskEditorView` tracks it to withhold Save until it happens for the
   * CURRENT config (an edit to either field invalidates the previous
   * success by comparing against it, never a separate reset call). Omitted
   * only in tests that render the tab standalone with no save gate to feed.
   *
   * `task` (sprint-5/08 review round 7) is the response's own stamped task
   * (`HttpPreview.task`) when the backend echoed one - `TaskEditorView`
   * `apply()`s it directly, replacing the round-6 `reload()` that raced a
   * concurrent Save. `undefined` for a mocked `httpPreview.run` that still
   * resolves a bare `true` (kept tolerant on purpose, see `onTestHttp`).
   */
  onHttpPreviewSuccess?: (
    target: { connectionId: string; path: string },
    task?: AutocountEtlTask,
  ) => void;
  /**
   * The Lookups editor's own per-row remote-column probe (sprint-5/10,
   * AC-10-05/09) - owned by the caller so it survives a Source-tab re-render
   * (it tracks state per lookup row).
   */
  columnsProbe: UsePreviewColumnsMapResult;
  /** Server-authoritative formula eval for the Combine editor's builder. */
  onCombineFormulaTest: (formula: string, value: unknown) => Promise<AutocountFormulaTestResult>;
}

const NO_WATERMARK = '';

/**
 * The task editor's Source tab (sprint-5/08 D13, formerly "Query"): an
 * API | Database toggle. Database renders today's schema tree + SQL editor +
 * Test Query + preview grid unchanged; API renders a connection picker +
 * endpoint path + Test + preview grid (`SqlPreviewGrid` reused via the
 * `httpPreviewAsSqlPreview` adapter). Both branches feed the SAME
 * `ColumnPickers` (key/watermark/compared - dropdowns, never free text).
 */
export function SourceTab({
  editing,
  entityType,
  sourceKind,
  onSourceKindChange,
  config,
  onChange,
  connections,
  connectionsLoading,
  lockedConnection = null,
  schema,
  preview,
  linePreview,
  fieldErrors,
  presets = [],
  onUsePreset,
  onServerTest,
  apiConnections,
  apiConnectionsLoading,
  lockedApiConnection = null,
  httpPreview,
  companyId,
  onHttpPreviewSuccess,
  columnsProbe,
  onCombineFormulaTest,
}: SourceTabProps) {
  const isDocument = isDocumentEntity(entityType);
  const connection = connections.find((c) => c.id === config.connectionId) ?? null;
  const [filterBuilderOpen, setFilterBuilderOpen] = useState(false);

  const previewColumns = useMemo(
    () => (preview.state.status === 'success' ? preview.state.preview.columns.map((c) => c.name) : []),
    [preview.state],
  );
  // The Filter builder's Variables panel (AC-02-11/20) - the header columns
  // known so far, plus whatever the saved formula already references (a
  // stale-but-visible variable, same discoverability as `pickerColumnOptions`).
  const filterKnownColumns = useMemo(
    () => pickerColumnOptions(previewColumns, config.keyColumns),
    [config.keyColumns, previewColumns],
  );
  const filterVariables = useMemo(
    () =>
      filterKnownColumns.length > 0
        ? [{ label: 'Header columns', items: filterKnownColumns.map((c) => ({ label: c, token: c })) }]
        : [],
    [filterKnownColumns],
  );
  const docDateOptions = useMemo(
    () => previewColumns.map((c) => ({ label: c, value: c })),
    [previewColumns],
  );

  const savedPicks = useMemo(
    () => [
      ...config.keyColumns,
      ...(config.watermarkColumn ? [config.watermarkColumn] : []),
      ...config.comparedColumns,
    ],
    [config.comparedColumns, config.keyColumns, config.watermarkColumn],
  );
  const columnOptions = useMemo(
    () => pickerColumnOptions(previewColumns, savedPicks).map((c) => ({ label: c, value: c })),
    [previewColumns, savedPicks],
  );
  // Compared columns never include a key column (keys are identity, not change).
  const comparedOptions = useMemo(
    () => columnOptions.filter((o) => !config.keyColumns.includes(o.value)),
    [columnOptions, config.keyColumns],
  );
  // BL-SS-087 (foolproof-UI half) - the watermark column is GUARANTEED to
  // change on every update, so it can never also be a key column (a
  // reconcile would mint a "new" ref for the same real-world record every
  // time). Withhold the chosen watermark from the key-columns picker...
  // SF3 (final reviewer pass): only an UNSELECTED value is ever excluded -
  // a LEGACY config saved before this guard existed can have the watermark
  // column sitting INSIDE keyColumns already; filtering that value out of
  // the options entirely would silently hide the already-selected pill/
  // label (both derive from `options`, not `value`), leaving the operator
  // unable to even see what's wrong, let alone fix it by deselecting.
  const keyColumnOptions = useMemo(
    () =>
      columnOptions.filter(
        (o) => o.value !== config.watermarkColumn || config.keyColumns.includes(o.value),
      ),
    [columnOptions, config.keyColumns, config.watermarkColumn],
  );
  const watermarkOptions = useMemo(() => {
    // ...and withhold the chosen key columns from the watermark picker,
    // the same rule (and the same legacy-value exception) from the other
    // picker's side.
    const base = columnOptions.filter(
      (o) => !config.keyColumns.includes(o.value) || o.value === config.watermarkColumn,
    );
    // A document task REQUIRES a watermark column (AutoCount stamps a
    // header's LastModified on any line edit - the S5 line-change-detection
    // decision), so "None" is never a valid choice for one (foolproof-UI -
    // only offer options that can actually work).
    return isDocument ? base : [{ label: 'None', value: NO_WATERMARK }, ...base];
  }, [columnOptions, config.keyColumns, config.watermarkColumn, isDocument]);
  const pickersEnabled = editing && columnOptions.length > 0;

  const canTest = Boolean(config.connectionId) && config.query.trim().length > 0 &&
    preview.state.status !== 'loading';
  const canTestLine = Boolean(config.connectionId) && Boolean(config.lineQuery?.trim()) &&
    linePreview.state.status !== 'loading';

  const onTest = useCallback(() => {
    if (!config.connectionId) return;
    void preview.run(config.connectionId, config.query);
  }, [config.connectionId, config.query, preview]);

  const onTestLine = useCallback(() => {
    if (!config.connectionId || !config.lineQuery) return;
    // A harmless NULL bind (never real filtered data at picker-config time)
    // - just enough for the query to execute so its columns populate the
    // line-column pickers below.
    void linePreview.run(config.connectionId, config.lineQuery, { bindDocKey: true, docKey: null });
  }, [config.connectionId, config.lineQuery, linePreview]);

  const onInsertStarter = useCallback(
    (schemaName: string, tableName: string) => {
      onChange({ query: starterQuery(schemaName, tableName) });
    },
    [onChange],
  );

  const onConnectionChange = useCallback(
    (id: string) => {
      onChange({ connectionId: id });
      preview.reset();
      linePreview.reset();
    },
    [onChange, preview, linePreview],
  );

  const onKeyColumnsChange = useCallback(
    (keys: string[]) => {
      onChange({
        keyColumns: keys,
        comparedColumns: config.comparedColumns.filter((c) => !keys.includes(c)),
      });
    },
    [config.comparedColumns, onChange],
  );

  const connectionOptions = connections.map((c) => ({
    label: `${c.name} · ${c.database}`,
    value: c.id,
  }));

  // ── API branch derived state (sprint-5/08) ────────────────────────────────

  const apiConnection = apiConnections.find((c) => c.id === config.connectionId) ?? null;
  const apiConnectionAuth = lockedApiConnection?.auth ?? apiConnection?.auth ?? null;
  const apiCapable = AC_API_CAPABLE_ENTITY_TYPES.includes(entityType);
  // Foolproof-UI (AC-08-19 simplification, see the task-editor-view PHASE 1
  // MOCK contract note): a Basic-auth connection is not even OFFERED for an
  // entity that has no confirmed vendor route, rather than shown disabled
  // with a reason - the picker never lets an operator select a combination
  // the server would reject.
  const apiConnectionOptions = apiConnections
    .filter((c) => c.auth === 'none' || apiCapable)
    .map((c) => ({
      label: `${c.name} (${c.auth === 'none' ? 'No auth' : 'Basic auth'})`,
      value: c.id,
    }));
  const isBasicAuth = apiConnectionAuth === 'basic';

  // sprint-5/10 (AC-10-01, D23) - a lookup alias may never be a key or
  // watermark field (a miss leaves it absent); it IS offered in the
  // compared-fields picker, the Combine editor's column options, and the
  // Mapping source picker. Declared ahead of `httpPreviewColumns` below -
  // both need it.
  const lookupAliases = useMemo(
    () => new Set((config.lookups ?? []).flatMap((l) => l.fields.map((f) => f.as.trim()).filter(Boolean))),
    [config.lookups],
  );
  // Review round 1 B1 (AC-10-82/AC-10-40/41) - NEVER keyed off the echoed
  // `task`: a brand-new entity carries no `ac_entity_config` row yet, so
  // the backend withholds `task` on its very FIRST Test - and a stock task's
  // first Test sends `combine` from its preset, so falling back to the bare
  // (then COMBINED) `columns` leaked post-group names like `qty` into the
  // watermark/compared/Lookups/Combine pickers. The SERVER's own
  // `preCombineColumns` (sent exactly when the request carried `combine`)
  // IS the pre-combine, alias-inclusive set (raw + lookup aliases +
  // computed aliases); for a plain (no-combine) Test the bare `columns`
  // already IS pre-combine (the combine stage never ran). This is the
  // PICKER base only - the Lookups editor's alias self-collision check reads
  // the server's own `rawColumns` instead (`rawSourceColumns` below).
  const previewBaseColumns = useMemo(() => {
    if (httpPreview.state.status !== 'success') return [];
    const preview = httpPreview.state.preview;
    return preview.preCombineColumns ?? preview.columns.map((c) => c.name);
  }, [httpPreview.state]);
  // Unioned with every alias the DRAFT's lookups currently name (S2 - an
  // added-but-not-yet-re-Tested lookup's alias must not vanish from the
  // watermark/compared/Combine pickers, which read THIS, never the bare
  // server base).
  const httpPreviewColumns = useMemo(
    () => Array.from(new Set([...previewBaseColumns, ...Array.from(lookupAliases)])),
    [previewBaseColumns, lookupAliases],
  );
  // The Combine editor's own funnel (AC-10-82) - the SAME six server counts
  // the Source tab's Test just landed, present only when that Test's
  // request carried `combine` (`rowsIn` is the funnel's own presence
  // signal - a plain lookup preview never sets it).
  const combineFunnel = useMemo<AutocountCombinePreviewResult | null>(() => {
    if (httpPreview.state.status !== 'success') return null;
    const preview = httpPreview.state.preview;
    if (preview.rowsIn == null) return null;
    return {
      rowsIn: preview.rowsIn,
      excludedCount: preview.excludedCount ?? 0,
      groups: preview.groups ?? 0,
      droppedByRule: preview.droppedByRule ?? {},
      rowsOut: preview.rowsOut ?? 0,
      roundedCount: preview.roundedCount ?? 0,
    };
  }, [httpPreview.state]);
  // Browser round 1 fix (AC-10-09), closed for good in confirm round 2 (B1):
  // the Lookups editor's alias collision check runs against the SERVER's own
  // `rawColumns` and nothing else. Every other set on this tab is merged by
  // design - `preview.columns` is raw UNION every alias the REQUEST's lookups
  // carried, and `preCombineColumns` folds in the combine's computed aliases
  // on top - so each one makes an alias collide with itself the moment the
  // Test that introduced it lands. No subtraction, no echo: an absent
  // `rawColumns` (no Test yet, or a pre-`rawColumns` backend) means "nothing
  // is known to be taken", never "everything in `columns` is taken".
  // `lib/autocount-lookups.ts` still owns the EARLIER-alias half of the rule,
  // and a clash with a combine computed alias stays the combine's own 422
  // (`combine.computed[i].alias`), never reported here.
  const rawSourceColumns = useMemo(() => {
    if (httpPreview.state.status !== 'success') return [];
    return httpPreview.state.preview.rawColumns ?? [];
  }, [httpPreview.state]);
  // sprint-5/10 browser round S6 defect D1 - each picker's saved-value
  // carry-over (the "stale but visible" half of `pickerColumnOptions`) is
  // now scoped to ITS OWN stored value, never a shared pool: a saved
  // combine task's `comparedFields` (which MAY legitimately hold a combine
  // measure alias like `qty` - AC-10-80 constrains only the key fields,
  // nothing forbids a measure in compared) was previously unioned with
  // `keyFields`/`watermarkField` into ONE `httpSavedPicks` list feeding
  // every picker, so a saved `qty` compared pick leaked into the watermark
  // (and key) picker's own options too.
  const httpKeyFields = useMemo(() => config.keyFields ?? [], [config.keyFields]);
  const httpComparedFields = useMemo(() => config.comparedFields ?? [], [config.comparedFields]);
  const httpKeyPickerOptions = useMemo(
    () => pickerColumnOptions(httpPreviewColumns, httpKeyFields).map((c) => ({ label: c, value: c })),
    [httpPreviewColumns, httpKeyFields],
  );
  const httpWatermarkPickerOptions = useMemo(
    () =>
      pickerColumnOptions(httpPreviewColumns, config.watermarkField ? [config.watermarkField] : []).map(
        (c) => ({ label: c, value: c }),
      ),
    [httpPreviewColumns, config.watermarkField],
  );
  const httpComparedPickerOptions = useMemo(
    () => pickerColumnOptions(httpPreviewColumns, httpComparedFields).map((c) => ({ label: c, value: c })),
    [httpPreviewColumns, httpComparedFields],
  );
  // Belt and braces (S6 defect D1) - a combine `measures[].alias` is a
  // POST-group output column, computed AFTER `groupBy` runs: it can never be
  // a key or watermark (both are pre-group row identity) no matter which
  // picker's own saved-value carry-over might otherwise surface it. The
  // compared picker is deliberately NOT filtered by this set - see above.
  const measureAliases = useMemo(
    () => new Set((config.combine?.measures ?? []).map((m) => m.alias)),
    [config.combine],
  );
  // sprint-5/10 (AC-10-80) - a combine-carrying task's key fields are the
  // combine's OWN `groupBy` columns, derived, never separately typed: the
  // Key fields picker becomes read-only chips of `groupBy` the moment one is
  // set (the server derives the saved `keyFields` the SAME way at save
  // time, `EtlService._update_http_task`).
  const combineGroupBy = useMemo(() => config.combine?.groupBy ?? [], [config.combine]);
  const combineKeyLocked = combineGroupBy.length > 0;
  const httpKeyFieldsDisplay = combineKeyLocked ? combineGroupBy : httpKeyFields;
  const httpComparedOptions = useMemo(
    () => httpComparedPickerOptions.filter((o) => !httpKeyFields.includes(o.value)),
    [httpComparedPickerOptions, httpKeyFields],
  );
  const httpKeyOptions = useMemo(
    () =>
      httpKeyPickerOptions.filter(
        (o) =>
          !lookupAliases.has(o.value) &&
          !measureAliases.has(o.value) &&
          (o.value !== config.watermarkField || httpKeyFields.includes(o.value)),
      ),
    [httpKeyPickerOptions, httpKeyFields, config.watermarkField, lookupAliases, measureAliases],
  );
  const httpWatermarkOptions = useMemo(() => {
    const base = httpWatermarkPickerOptions.filter(
      (o) =>
        !lookupAliases.has(o.value) &&
        !measureAliases.has(o.value) &&
        (!httpKeyFields.includes(o.value) || o.value === config.watermarkField),
    );
    return [{ label: 'None', value: NO_WATERMARK }, ...base];
  }, [httpWatermarkPickerOptions, httpKeyFields, config.watermarkField, lookupAliases, measureAliases]);
  const httpPickersEnabled =
    editing &&
    (httpPreviewColumns.length > 0 ||
      httpKeyFields.length > 0 ||
      Boolean(config.watermarkField) ||
      httpComparedFields.length > 0);

  const canTestHttp =
    Boolean(config.connectionId) &&
    Boolean(config.path?.trim()) &&
    !isBasicAuth &&
    httpPreview.state.status !== 'loading';

  const onTestHttp = useCallback(() => {
    if (!config.connectionId || !config.path) return;
    const target = { connectionId: config.connectionId, path: config.path };
    // `Promise.resolve(...)` tolerates a test double whose mocked `run`
    // returns a plain boolean rather than the real `HttpPreview | false` -
    // any truthy result (this exact connectionId/path pair proved) reports
    // success upward (AC-08-20); `result.task` (sprint-5/08 review round 7,
    // absent on a plain-boolean test double) is forwarded so the editor can
    // `apply()` it without a second fetch.
    void Promise.resolve(
      httpPreview.run(config.connectionId, config.path, config.distinctOf ?? undefined, {
        companyId,
        entityType,
        lookups: config.lookups,
        // sprint-5/10 S5b-FE (AC-10-82) - the SAME Test proves the combine
        // step too: sent only when the task carries one, so a plain
        // lookup-only task's response is unaffected.
        combine: config.combine,
      }),
    ).then((result) => {
      if (result) onHttpPreviewSuccess?.(target, typeof result === 'object' ? result.task : undefined);
    });
  }, [
    companyId,
    config.combine,
    config.connectionId,
    config.distinctOf,
    config.lookups,
    config.path,
    entityType,
    httpPreview,
    onHttpPreviewSuccess,
  ]);

  const onApiConnectionChange = useCallback(
    (id: string) => {
      onChange({ connectionId: id });
      httpPreview.reset();
    },
    [onChange, httpPreview],
  );

  const onHttpKeyFieldsChange = useCallback(
    (keys: string[]) => {
      onChange({
        keyFields: keys,
        comparedFields: (config.comparedFields ?? []).filter((c) => !keys.includes(c)),
      });
    },
    [config.comparedFields, onChange],
  );

  // An OPEN (no-auth) company has no database connection at all - offering
  // "Database" as a toggle segment would be a guaranteed dead end
  // (foolproof-UI: only valid options). A vendor/basic-auth `api` company
  // keeps both (it may still carry `sql_db` tasks, AC-08-13); a `db`
  // company (`lockedApiConnection` unset here) keeps both too.
  const sourceKindOptions =
    lockedApiConnection?.auth === 'none'
      ? SOURCE_KIND_OPTIONS.filter((option) => option.value !== 'db')
      : SOURCE_KIND_OPTIONS;

  return (
    <div className="flex flex-col gap-4">
      <ToggleGroup
        type="single"
        size="sm"
        variant="outline"
        value={sourceKind}
        onValueChange={(value) => {
          if (value === 'db' || value === 'api') onSourceKindChange(value);
        }}
        disabled={!editing}
        aria-label="Source"
        className="w-fit max-w-full flex-wrap"
      >
        {sourceKindOptions.map((option) => (
          <ToggleGroupItem key={option.value} value={option.value} className={SEGMENT_CLASS}>
            {option.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {sourceKind === 'db' ? (
        <>
          {!lockedConnection && !connectionsLoading && connections.length === 0 && (
            <Alert variant="warning" appearance="light" data-testid="no-sql-connection">
              <AlertIcon>
                <TriangleAlert />
              </AlertIcon>
              <AlertTitle>
                No SQL database connection yet.{' '}
                <Link href="/settings/integrations/new" className="underline">
                  Add one in Integrations
                </Link>
              </AlertTitle>
            </Alert>
          )}

          <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
            {/* Schema tree - scrolls within the editor's height on desktop, stacks
                above the editor on mobile (side panels never stretch the page). */}
            <aside className="rounded-lg border border-border bg-muted/30 p-3 lg:max-h-[calc(100vh-18rem)] lg:overflow-y-auto">
              <SqlSchemaTree
                schema={schema.schema}
                isLoading={schema.isLoading}
                error={schema.error}
                noConnection={!config.connectionId}
                onRefresh={schema.refresh}
                onInsertQuery={onInsertStarter}
                canInsert={editing}
              />
            </aside>

            <div className="flex min-w-0 flex-col gap-4">
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:max-w-sm">
                  <Label htmlFor="etl-connection">Connection</Label>
                  {lockedConnection ? (
                    <span
                      className="flex min-h-8.5 items-center gap-1.5 text-sm text-foreground"
                      data-testid="locked-connection"
                    >
                      <Lock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      {lockedConnection.label}
                    </span>
                  ) : (
                    <SearchSelect
                      options={connectionOptions}
                      value={config.connectionId}
                      onChange={onConnectionChange}
                      placeholder="Select a connection"
                      disabled={!editing || connectionsLoading || connections.length === 0}
                      ariaLabel="Connection"
                    />
                  )}
                </div>
                {isDocument && presets.length > 0 && (
                  <div className="flex min-w-0 flex-col gap-1.5 sm:max-w-xs">
                    <Label htmlFor="etl-preset">Use preset</Label>
                    <SearchSelect
                      options={presets.map((p) => ({ label: p.label, value: p.entityType }))}
                      value=""
                      onChange={(entityKey) => {
                        const p = presets.find((preset) => preset.entityType === entityKey);
                        if (p) onUsePreset?.(p);
                      }}
                      placeholder="Choose a preset"
                      disabled={!editing}
                      ariaLabel="Use preset"
                    />
                  </div>
                )}
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={onTest}
                  disabled={!canTest}
                  data-testid="sql-test-query"
                >
                  <Play className="size-3.5" />
                  Test query
                </Button>
                {preview.state.status === 'success' && (
                  <Badge
                    variant={preview.state.preview.rowCount === 0 ? 'secondary' : 'success'}
                    appearance="light"
                    data-testid="sql-preview-badge"
                  >
                    {previewBadgeText(preview.state.preview)}
                  </Badge>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>{isDocument ? 'Header query' : 'Query'}</Label>
                <SqlEditor
                  value={config.query}
                  onChange={(query) => onChange({ query })}
                  editing={editing}
                  schema={schema.schema}
                  dialect={connection?.dialect ?? schema.schema?.dialect ?? null}
                  ariaLabel={isDocument ? 'Header query' : 'Query'}
                />
                {fieldErrors.query && (
                  <p className="text-xs text-destructive">{fieldErrors.query}</p>
                )}
              </div>

              {isDocument && (
                <div className="flex flex-col gap-4 rounded-lg border border-border p-4">
                  <div className="flex flex-wrap items-end gap-3">
                    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                      <Label>Line query</Label>
                      <SqlEditor
                        value={config.lineQuery ?? ''}
                        onChange={(lineQuery) => onChange({ lineQuery })}
                        editing={editing}
                        schema={schema.schema}
                        dialect={connection?.dialect ?? schema.schema?.dialect ?? null}
                        ariaLabel="Line query"
                        testId="sql-line-editor"
                      />
                      {fieldErrors.lineQuery && (
                        <p className="text-xs text-destructive">{fieldErrors.lineQuery}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Button
                      type="button"
                      variant="primary"
                      size="sm"
                      onClick={onTestLine}
                      disabled={!canTestLine}
                      data-testid="sql-test-line-query"
                    >
                      <Play className="size-3.5" />
                      Test line query
                    </Button>
                    {linePreview.state.status === 'success' && (
                      <Badge
                        variant={linePreview.state.preview.rowCount === 0 ? 'secondary' : 'success'}
                        appearance="light"
                        data-testid="sql-line-preview-badge"
                      >
                        {previewBadgeText(linePreview.state.preview)}
                      </Badge>
                    )}
                  </div>
                  <SqlPreviewGrid state={linePreview.state} />

                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="flex min-w-0 flex-col gap-1.5">
                      <Label htmlFor="etl-from-date">
                        From date <span className="text-destructive">*</span>
                      </Label>
                      {editing ? (
                        <Input
                          id="etl-from-date"
                          type="date"
                          value={config.fromDate ?? ''}
                          onChange={(e) => onChange({ fromDate: e.target.value || null })}
                          aria-invalid={Boolean(fieldErrors.fromDate)}
                        />
                      ) : (
                        <span className="text-sm">{config.fromDate ?? '-'}</span>
                      )}
                      {fieldErrors.fromDate && (
                        <p className="text-xs text-destructive">{fieldErrors.fromDate}</p>
                      )}
                    </div>
                    <div className="flex min-w-0 flex-col gap-1.5">
                      <Label>
                        Document date column <span className="text-destructive">*</span>
                      </Label>
                      {editing ? (
                        <SearchSelect
                          options={docDateOptions}
                          value={config.docDateColumn ?? ''}
                          onChange={(v) => onChange({ docDateColumn: v || null })}
                          placeholder={pickersEnabled ? 'Pick a column' : 'Run Test query first'}
                          disabled={!pickersEnabled}
                          ariaLabel="Document date column"
                        />
                      ) : (
                        <ColumnChips values={config.docDateColumn ? [config.docDateColumn] : []} empty="-" />
                      )}
                      {fieldErrors.docDateColumn && (
                        <p className="text-xs text-destructive">{fieldErrors.docDateColumn}</p>
                      )}
                    </div>
                  </div>

                  {/* The family filter (AC-02-11/19/20) - authored ONLY through the
                      formula builder, same dialog masters' Transform column uses
                      (Q16); the field itself shows the formula read-only. */}
                  <div className="flex min-w-0 flex-col gap-1.5">
                    <Label>Filter</Label>
                    <div className="flex items-center gap-2">
                      {config.filterFormula ? (
                        <ClampedText
                          text={config.filterFormula}
                          lines={2}
                          className="flex-1 rounded-md border border-border bg-muted/30 px-3 py-2 font-mono text-xs"
                        />
                      ) : (
                        <span className="flex-1 rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                          Every header is staged (no filter).
                        </span>
                      )}
                      {editing && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          mode="icon"
                          onClick={() => setFilterBuilderOpen(true)}
                          aria-label="Build the filter formula"
                          title="Edit as a formula"
                        >
                          <Wand2 className="size-4" />
                        </Button>
                      )}
                    </div>
                    {fieldErrors.filterFormula && (
                      <p className="text-xs text-destructive">{fieldErrors.filterFormula}</p>
                    )}
                  </div>
                </div>
              )}

              {isDocument && (
                <AutocountFormulaBuilder
                  open={filterBuilderOpen}
                  onOpenChange={setFilterBuilderOpen}
                  value={config.filterFormula ?? ''}
                  onApply={(formula) => onChange({ filterFormula: formula.trim() ? formula.trim() : null })}
                  onServerTest={onServerTest}
                  variables={filterVariables}
                  fieldLabel="Filter"
                />
              )}

              <SqlPreviewGrid state={preview.state} />

              <ColumnPickers
                editing={editing}
                keyOptions={keyColumnOptions}
                watermarkOptions={watermarkOptions}
                comparedOptions={comparedOptions}
                keyValue={config.keyColumns}
                onKeyChange={onKeyColumnsChange}
                watermarkValue={config.watermarkColumn ?? NO_WATERMARK}
                onWatermarkChange={(v) => onChange({ watermarkColumn: v === NO_WATERMARK ? null : v })}
                comparedValue={config.comparedColumns}
                onComparedChange={(comparedColumns) => onChange({ comparedColumns })}
                pickersEnabled={pickersEnabled}
                fieldErrors={fieldErrors}
              />
            </div>
          </div>
        </>
      ) : (
        <div className="flex flex-col gap-4">
          {!lockedApiConnection && !apiConnectionsLoading && apiConnections.length === 0 && (
            <Alert variant="warning" appearance="light" data-testid="no-api-connection">
              <AlertIcon>
                <TriangleAlert />
              </AlertIcon>
              <AlertTitle>
                Add an AutoCount API connection in{' '}
                <Link href="/settings/integrations/new" className="underline">
                  Settings -&gt; Integrations
                </Link>
                .
              </AlertTitle>
            </Alert>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:max-w-sm">
              <Label htmlFor="etl-api-connection">Connection</Label>
              {lockedApiConnection ? (
                <span
                  className="flex min-h-8.5 items-center gap-1.5 text-sm text-foreground"
                  data-testid="locked-api-connection"
                >
                  <Lock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  {lockedApiConnection.label}
                  <Badge variant="secondary" appearance="light" size="sm">
                    {lockedApiConnection.auth === 'none' ? 'No auth' : 'Basic auth'}
                  </Badge>
                </span>
              ) : (
                <SearchSelect
                  options={apiConnectionOptions}
                  value={config.connectionId}
                  onChange={onApiConnectionChange}
                  placeholder="Select a connection"
                  disabled={!editing || apiConnectionsLoading || apiConnectionOptions.length === 0}
                  ariaLabel="Connection"
                />
              )}
              {fieldErrors.connectionId && (
                <p className="text-xs text-destructive">{fieldErrors.connectionId}</p>
              )}
            </div>
          </div>

          {isBasicAuth ? (
            <Alert variant="info" appearance="light" data-testid="basic-auth-source">
              <AlertIcon>
                <Info />
              </AlertIcon>
              <AlertTitle>
                {entityLabel(entityType)} reads through the AutoCount API login - no endpoint to
                configure here.
              </AlertTitle>
            </Alert>
          ) : (
            <>
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:max-w-md">
                  <Label htmlFor="etl-path">Endpoint path</Label>
                  <Input
                    id="etl-path"
                    value={config.path ?? ''}
                    onChange={(e) => onChange({ path: e.target.value })}
                    disabled={!editing}
                    placeholder="/itembypage"
                    className="font-mono"
                    aria-invalid={Boolean(fieldErrors.path)}
                  />
                  {fieldErrors.path && <p className="text-xs text-destructive">{fieldErrors.path}</p>}
                </div>
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={onTestHttp}
                  disabled={!canTestHttp}
                  data-testid="http-test-path"
                >
                  <Play className="size-3.5" />
                  Test
                </Button>
                {httpPreview.state.status === 'success' && (
                  <Badge variant="success" appearance="light" data-testid="http-preview-badge">
                    {httpPreviewBadgeText(httpPreview.state.preview)}
                  </Badge>
                )}
              </div>

              {config.distinctOf && config.distinctOf.length > 0 && (
                <div className="flex min-w-0 flex-col gap-1.5">
                  <Label>Derived from distinct values of</Label>
                  <ColumnChips values={config.distinctOf} empty="-" />
                </div>
              )}

              {/* Lookups + Combine rows (sprint-5/10, R9/R11, AC-10-09/82) -
                  operator-configurable cross-endpoint joins and row
                  collapsing, ANY API task. Below the path, above the
                  key/watermark/compared pickers. */}
              <LookupsEditor
                editing={editing}
                lookups={config.lookups ?? []}
                onChange={(lookups) => onChange({ lookups })}
                sourceColumns={rawSourceColumns}
                connectionId={config.connectionId}
                columnsProbe={columnsProbe}
                lookupResults={httpPreview.state.status === 'success' ? httpPreview.state.preview.lookups : []}
              />

              <CombineEditor
                editing={editing}
                combine={config.combine}
                onChange={(combine) => onChange({ combine })}
                columnOptions={httpPreviewColumns}
                funnel={combineFunnel}
                onServerTest={onCombineFormulaTest}
              />

              <SqlPreviewGrid
                state={
                  httpPreview.state.status === 'success'
                    ? { status: 'success', preview: httpPreviewAsSqlPreview(httpPreview.state.preview) }
                    : httpPreview.state
                }
              />

              <ColumnPickers
                editing={editing}
                keyOptions={httpKeyOptions}
                watermarkOptions={httpWatermarkOptions}
                comparedOptions={httpComparedOptions}
                keyValue={httpKeyFieldsDisplay}
                onKeyChange={onHttpKeyFieldsChange}
                keyReadOnly={combineKeyLocked}
                watermarkValue={config.watermarkField ?? NO_WATERMARK}
                onWatermarkChange={(v) => {
                  const next = v === NO_WATERMARK ? null : v;
                  // Schedule tab's incremental-floor check reads the SQL
                  // field name (`watermarkColumn`) unconditionally (AC-08-19:
                  // Schedule stays "the existing component, untouched") -
                  // mirror the HTTP pick onto it so that ONE shared signal
                  // keeps working for both branches without a second copy.
                  onChange({ watermarkField: next, watermarkColumn: next });
                }}
                comparedValue={config.comparedFields ?? []}
                onComparedChange={(comparedFields) => onChange({ comparedFields })}
                pickersEnabled={httpPickersEnabled}
                fieldErrors={{
                  keyColumns: fieldErrors.keyFields,
                  watermarkColumn: fieldErrors.watermarkField,
                  comparedColumns: fieldErrors.comparedFields,
                }}
              />
            </>
          )}
        </div>
      )}
    </div>
  );
}
