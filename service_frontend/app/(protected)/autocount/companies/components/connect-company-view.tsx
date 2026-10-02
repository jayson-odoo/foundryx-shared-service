'use client';

import { useCallback, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Plug } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { toast } from '@/lib/toast';
import { Container } from '@/components/common/container';
import { Form } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { SearchSelect } from '@/components/platform/search-select';
import {
  FormRow,
  ResourceForm,
  type ResourceFormConfig,
} from '@/components/platform/resource-form';
import { ApiError } from '@/lib/api-client';
import { REF_PREFIX_RE, derivePrefix, readFieldErrors } from '@/lib/autocount-etl';
import { autocountService } from '@/services/autocount-service';
import {
  useAutocountSourceConnections,
  type SourceConnectionsState,
} from '@/hooks/use-autocount-connections';
import type { AutocountCompany } from '@/types/autocount';
import {
  AC_COMPANIES_PATH,
  AC_SOURCE_KIND_OPTIONS,
  acCompanyHref,
} from '../../components/autocount-meta';

type SourceKind = 'api' | 'db';

/** The shell's segmented-control styling (Active|Trashed) - selected = filled primary. */
const SEGMENT_CLASS =
  'data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary';

/** Why there is nothing to pick for a source, when there is nothing to pick. */
function emptyReason(kind: SourceKind, state: SourceConnectionsState) {
  if (state.isLoading || state.options.length > 0) return null;
  if (kind === 'api') {
    return state.hasAny
      ? 'Every AutoCount connection is already registered as a company.'
      : 'No AutoCount integration is connected yet.';
  }
  if (state.hasAny) return 'Every SQL database connection is already registered as a company.';
  return (
    <>
      No SQL database connection yet.{' '}
      <Link href="/settings/integrations/new" className="underline">
        Add one in Integrations
      </Link>
    </>
  );
}

/**
 * Register an AutoCount company from ONE connection (plan sprint-5/01).
 *
 * The operator picks the Source - the vendor API or a direct SQL database -
 * then a connection of that provider. The company's database name is
 * DISCOVERED either way (API sign-in, or the SQL connection's `database`
 * verified by a live probe) and never entered (AC-13-01, AC-01-02). Each
 * picker lists only connections that can actually succeed: already-registered
 * ones are excluded (foolproof-UI), and Create is withheld until one is picked.
 */
export function ConnectCompanyView() {
  const router = useRouter();
  const form = useForm({ mode: 'onTouched' });
  const sources = useAutocountSourceConnections();
  const [pickedKind, setPickedKind] = useState<SourceKind | null>(null);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [label, setLabel] = useState('');
  // Reference prefix (AC-08-06/07/09) - only meaningful for a No-auth (open)
  // API connection; `touched` tracks whether the operator has edited the
  // auto-derived default so a later connection change doesn't clobber it.
  const [refPrefix, setRefPrefix] = useState('');
  const [refPrefixTouched, setRefPrefixTouched] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [refPrefixError, setRefPrefixError] = useState<string | null>(null);

  // The operator's pick wins; until they pick, the default follows the data
  // (AC-01-12) - nothing is selected yet, so the default flipping after load
  // never has to clear a connection.
  const kind: SourceKind = pickedKind ?? sources.defaultKind;
  const source = kind === 'db' ? sources.db : sources.api;
  const banner = emptyReason(kind, source);

  const pickedApiConnection = connectionId ? sources.apiConnectionsById[connectionId] : undefined;
  const isOpenConnection = kind === 'api' && pickedApiConnection?.auth === 'none';

  const onKindChange = useCallback((value: string) => {
    if (value !== 'api' && value !== 'db') return;
    setPickedKind(value);
    // A connection belongs to its source - switching clears it.
    setConnectionId(null);
    setFieldError(null);
    setRefPrefix('');
    setRefPrefixTouched(false);
    setRefPrefixError(null);
  }, []);

  const onConnectionChange = useCallback(
    (value: string) => {
      setConnectionId(value);
      setFieldError(null);
      setRefPrefixError(null);
      // A fresh No-auth pick seeds the prefix from the connection's own name
      // (AC-08-09) UNLESS the operator already typed something of their own.
      const picked = sources.apiConnectionsById[value];
      if (picked?.auth === 'none' && !refPrefixTouched) {
        setRefPrefix(derivePrefix(picked.name));
      }
    },
    [refPrefixTouched, sources.apiConnectionsById],
  );

  const onRefPrefixChange = useCallback((value: string) => {
    setRefPrefix(value);
    setRefPrefixTouched(true);
    setRefPrefixError(null);
  }, []);

  const onSave = useCallback(async () => {
    if (!connectionId) {
      setFieldError('Select a connection.');
      return false;
    }
    if (isOpenConnection && !REF_PREFIX_RE.test(refPrefix.trim())) {
      setRefPrefixError('Enter a reference prefix (letters, digits, underscore).');
      return false;
    }
    setFieldError(null);
    setRefPrefixError(null);
    setIsSaving(true);
    try {
      const company: AutocountCompany = await autocountService.createCompany({
        connectionId,
        name: label.trim(),
        ...(isOpenConnection ? { refPrefix: refPrefix.trim() } : {}),
      });
      toast.success(`Connected ${company.databaseName}.`);
      router.push(acCompanyHref(company.id));
      return true;
    } catch (error) {
      if (error instanceof ApiError && (error.status === 422 || error.status === 409)) {
        const fieldErrors = readFieldErrors(error.detail);
        // A probe mismatch / connect failure lands on the field (422); a 409
        // names the company already holding the database - both belong under
        // the picker the operator is looking at, not in a toast (AC-01-14).
        if (fieldErrors.refPrefix) {
          setRefPrefixError(fieldErrors.refPrefix);
          return false;
        }
        setFieldError(fieldErrors.connectionId ?? error.message);
        return false;
      }
      toast.error(
        error instanceof ApiError ? error.message : 'That connection could not be registered.',
      );
      return false;
    } finally {
      setIsSaving(false);
    }
  }, [connectionId, isOpenConnection, label, refPrefix, router]);

  const config = useMemo<ResourceFormConfig<AutocountCompany>>(
    () => ({
      breadcrumb: [
        { label: 'AutoCount' },
        { label: 'Companies', href: AC_COMPANIES_PATH },
        { label: 'Connect company' },
      ],
      backHref: AC_COMPANIES_PATH,
      backLabel: 'Companies',
      title: 'Connect company',
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Plug,
          render: () => (
            <div className="flex flex-col py-2">
              {banner && (
                <Alert
                  variant="warning"
                  appearance="light"
                  className="mb-4"
                  data-testid="connect-company-banner"
                >
                  <AlertIcon>
                    <Plug className="size-4" />
                  </AlertIcon>
                  <AlertTitle>{banner}</AlertTitle>
                </Alert>
              )}
              <FormRow label="Source" required>
                <ToggleGroup
                  type="single"
                  size="sm"
                  variant="outline"
                  value={kind}
                  onValueChange={onKindChange}
                  disabled={isSaving}
                  aria-label="Source"
                  className="w-fit max-w-full flex-wrap"
                >
                  {AC_SOURCE_KIND_OPTIONS.map((option) => (
                    <ToggleGroupItem
                      key={option.value}
                      value={option.value}
                      className={SEGMENT_CLASS}
                    >
                      {option.label}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </FormRow>
              <FormRow
                label={kind === 'db' ? 'SQL database connection' : 'AutoCount connection'}
                required
              >
                <div className="flex flex-col gap-1">
                  <SearchSelect
                    options={source.options}
                    value={connectionId}
                    onChange={onConnectionChange}
                    disabled={source.isLoading || isSaving || source.options.length === 0}
                    placeholder="Select a connection"
                    ariaLabel={kind === 'db' ? 'SQL database connection' : 'AutoCount connection'}
                    className="max-w-sm"
                  />
                  {fieldError && (
                    <span className="text-xs text-destructive" data-testid="connection-error">
                      {fieldError}
                    </span>
                  )}
                </div>
              </FormRow>
              {isOpenConnection && (
                <FormRow label="Reference prefix" required>
                  <div className="flex flex-col gap-1">
                    <Input
                      value={refPrefix}
                      onChange={(e) => onRefPrefixChange(e.target.value)}
                      disabled={isSaving}
                      aria-label="Reference prefix"
                      className="max-w-sm font-mono"
                    />
                    <span className="text-xs text-muted-foreground">
                      Prefixes every record reference sent to the consumer. Cannot be changed
                      later.
                    </span>
                    {refPrefixError && (
                      <span className="text-xs text-destructive" data-testid="ref-prefix-error">
                        {refPrefixError}
                      </span>
                    )}
                  </div>
                </FormRow>
              )}
              <FormRow label="Label">
                <Input
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  disabled={isSaving}
                  placeholder="Company name"
                  aria-label="Label"
                  className="max-w-sm"
                />
              </FormRow>
            </div>
          ),
        },
      ],
      actions: [],
      actionRows: [],
      editable: false,
      initialEditing: true,
      isDirty: Boolean(connectionId) || label.length > 0 || refPrefix.length > 0,
      // Create cannot succeed without a connection - and, for a No-auth pick,
      // without a valid reference prefix - withheld, not offered-then-failed.
      saveDisabled:
        !connectionId || (isOpenConnection && !REF_PREFIX_RE.test(refPrefix.trim())),
      onSave,
      onCancel: () => router.push(AC_COMPANIES_PATH),
    }),
    [
      banner,
      connectionId,
      fieldError,
      isOpenConnection,
      isSaving,
      kind,
      label,
      onConnectionChange,
      onKindChange,
      onRefPrefixChange,
      onSave,
      refPrefix,
      refPrefixError,
      router,
      source,
    ],
  );

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
