'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import {
  connectionFormSchema,
  defaultsForProvider,
  requiredFieldErrors,
  toConnectionInput,
  type ConnectionFormValues,
} from '@/app/(protected)/settings/integrations/components/connection-schema';
import { integrationService } from '@/services/integration-service';
import { storageMigrationService } from '@/services/storage-migration-service';
import type { IntegrationProvider } from '@/types/integration';
import type { Job, StorageMigrationTestResult } from '@/types/jobs';

const BLANK: ConnectionFormValues = { provider: '', name: '', config: {}, credentials: {} };

/** Wizard step: configure the new bucket → test it → typed-confirm + start. */
export type MigrationStep = 'configure' | 'test' | 'confirm';

export interface UseStorageMigrationResult {
  step: MigrationStep;
  form: UseFormReturn<ConnectionFormValues>;
  /** Storage providers only (the migration target is always storage). */
  providers: IntegrationProvider[];
  provider: IntegrationProvider | null;
  onProviderChange: (key: string) => void;
  /** Live probe of the candidate bucket; Start stays gated until it passes. */
  testResult: StorageMigrationTestResult | null;
  testing: boolean;
  runTest: () => Promise<void>;
  starting: boolean;
  /** Typed-confirm value (must equal the target bucket name to enable Start). */
  confirmValue: string;
  setConfirmValue: (v: string) => void;
  /** The bucket name the user must retype to confirm. */
  targetName: string;
  next: () => void;
  back: () => void;
  canAdvanceFromConfigure: boolean;
  /** Full per-provider validation of the config step (surfaces field errors). */
  validateConfigure: () => Promise<boolean>;
  canStart: boolean;
  start: () => Promise<Job | null>;
}

/**
 * Storage-migration wizard state (sprint-4/10). Reuses the connect wizard's
 * `fields()`-driven RHF form + schema helpers (no reinvention) for the config
 * step; the Test step is non-destructive and MUST pass before Start; the
 * confirm step is a typed-confirm on the target bucket name. Any config edit
 * invalidates a prior passing test (foolproof-UI - can't launch stale).
 */
export function useStorageMigration(active: boolean): UseStorageMigrationResult {
  const [step, setStep] = useState<MigrationStep>('configure');
  const [providers, setProviders] = useState<IntegrationProvider[]>([]);
  const [testResult, setTestResult] = useState<StorageMigrationTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [confirmValue, setConfirmValue] = useState('');

  const form = useForm<ConnectionFormValues>({
    resolver: zodResolver(connectionFormSchema),
    defaultValues: BLANK,
  });

  const providerKey = form.watch('provider');
  const provider = useMemo(
    () => providers.find((p) => p.provider === providerKey) ?? null,
    [providers, providerKey],
  );

  // Reset the whole wizard whenever it (re)opens.
  useEffect(() => {
    if (!active) return;
    setStep('configure');
    setTestResult(null);
    setTesting(false);
    setStarting(false);
    setConfirmValue('');
    form.reset(BLANK);
    integrationService
      .providers()
      .then((all) => setProviders(all.filter((p) => p.type === 'storage')))
      .catch(() => setProviders([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  // A field edit invalidates a prior passing test (can't launch a stale probe).
  useEffect(() => {
    const sub = form.watch(() => setTestResult(null));
    return () => sub.unsubscribe();
  }, [form]);

  const onProviderChange = useCallback(
    (key: string) => {
      const p = providers.find((x) => x.provider === key);
      if (!p) return;
      form.reset(defaultsForProvider(p));
      setTestResult(null);
    },
    [providers, form],
  );

  const validateConfig = useCallback(async (): Promise<boolean> => {
    const ok = await form.trigger();
    if (!ok) return false;
    if (!provider) {
      form.setError('provider', { message: 'Pick a provider.' });
      return false;
    }
    const errors = requiredFieldErrors(provider, form.getValues(), true);
    if (errors.length) {
      for (const e of errors) form.setError(e.path, { message: e.message });
      return false;
    }
    return true;
  }, [form, provider]);

  const runTest = useCallback(async () => {
    if (!(await validateConfig())) return;
    setTesting(true);
    try {
      const values = toConnectionInput(form.getValues());
      const res = await storageMigrationService.testBucket({
        provider: values.provider,
        config: values.config,
        credentials: values.credentials,
      });
      setTestResult(res);
    } catch (e) {
      setTestResult({
        ok: false,
        message: e instanceof Error ? e.message : 'The bucket could not be verified.',
      });
    } finally {
      setTesting(false);
    }
  }, [form, validateConfig]);

  const targetName = form.watch('name') || '';

  const canAdvanceFromConfigure = !!provider;
  const canStart = !!testResult?.ok && confirmValue.trim() === targetName.trim() && !!targetName.trim();

  const next = useCallback(() => {
    setStep((s) => {
      if (s === 'configure') return 'test';
      if (s === 'test') return 'confirm';
      return s;
    });
  }, []);

  const back = useCallback(() => {
    setStep((s) => {
      if (s === 'confirm') return 'test';
      if (s === 'test') return 'configure';
      return s;
    });
  }, []);

  const start = useCallback(async (): Promise<Job | null> => {
    if (!canStart) return null;
    setStarting(true);
    try {
      const values = toConnectionInput(form.getValues());
      return await storageMigrationService.startMigration({
        provider: values.provider,
        name: values.name,
        config: values.config,
        credentials: values.credentials,
      });
    } finally {
      setStarting(false);
    }
  }, [canStart, form]);

  return {
    step,
    form,
    providers,
    provider,
    onProviderChange,
    testResult,
    testing,
    runTest,
    starting,
    confirmValue,
    setConfirmValue,
    targetName,
    next,
    back,
    canAdvanceFromConfigure,
    validateConfigure: validateConfig,
    canStart,
    start,
  };
}
