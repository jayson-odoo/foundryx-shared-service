'use client';

import { useCallback, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Plug } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Form } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { SearchSelect } from '@/components/platform/search-select';
import {
  FormRow,
  ResourceForm,
  type ResourceFormConfig,
} from '@/components/platform/resource-form';
import { ApiError } from '@/lib/api-client';
import { autocountService } from '@/services/autocount-service';
import { useAutocountConnections } from '@/hooks/use-autocount-connections';
import type { AutocountCompany } from '@/types/autocount';
import { AC_COMPANIES_PATH, acCompanyHref } from '../../components/autocount-meta';

/**
 * Register an AutoCount company.
 *
 * The operator supplies ONLY a connection: the vendor API resolves the company
 * from the AppId header, so the company database name is DISCOVERED at sign-in
 * and never entered (AC-13-01). The picker lists only connections that can
 * actually succeed - already-registered ones are excluded (foolproof-UI).
 */
export function ConnectCompanyView() {
  const router = useRouter();
  const form = useForm();
  const { options, isLoading, emptyReason } = useAutocountConnections();
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [label, setLabel] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);

  const onSave = useCallback(async () => {
    if (!connectionId) {
      setFieldError('Select a connection.');
      return false;
    }
    setFieldError(null);
    setIsSaving(true);
    try {
      const company: AutocountCompany = await autocountService.createCompany({
        connectionId,
        name: label.trim(),
      });
      toast.success(`Connected ${company.databaseName}.`);
      router.push(acCompanyHref(company.id));
      return true;
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : 'That connection could not be registered.',
      );
      return false;
    } finally {
      setIsSaving(false);
    }
  }, [connectionId, label, router]);

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
              {emptyReason && (
                <Alert variant="warning" appearance="light" className="mb-4">
                  <AlertIcon>
                    <Plug className="size-4" />
                  </AlertIcon>
                  <AlertTitle>{emptyReason}</AlertTitle>
                </Alert>
              )}
              <FormRow label="AutoCount connection" required>
                <div className="flex flex-col gap-1">
                  <SearchSelect
                    options={options}
                    value={connectionId}
                    onChange={(value) => {
                      setConnectionId(value);
                      setFieldError(null);
                    }}
                    disabled={isLoading || isSaving || options.length === 0}
                    placeholder={isLoading ? 'Loading…' : 'Select a connection'}
                    ariaLabel="AutoCount connection"
                    className="max-w-sm"
                  />
                  {fieldError && (
                    <span className="text-xs text-destructive">{fieldError}</span>
                  )}
                </div>
              </FormRow>
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
      isDirty: Boolean(connectionId) || label.length > 0,
      onSave,
      onCancel: () => router.push(AC_COMPANIES_PATH),
    }),
    [connectionId, emptyReason, fieldError, isLoading, isSaving, label, onSave, options, router],
  );

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
