'use client';

import { useCallback, useMemo } from 'react';
import Link from 'next/link';
import { Info, LoaderCircleIcon } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm, type ResourceFormConfig } from '@/components/platform/resource-form';
import { useCan } from '@/hooks/use-can';
import { useAutocountCompany } from '@/hooks/use-autocount-company';
import { useAutocountMapping } from '@/hooks/use-autocount-mapping';
import type { AutocountMappingRow } from '@/types/autocount';
import {
  AC_COMPANIES_MANAGE,
  AC_COMPANIES_PATH,
  acCompanyHref,
  entityLabel,
} from '../../../../../../components/autocount-meta';
import { MappingEditorBody } from './mapping-editor-body';
import { useMappingDraft } from './use-mapping-draft';

export interface MappingEditorViewProps {
  companyId: string;
  entityType: string;
}

/**
 * The per-(company, entity) field-mapping editor (AC-15-40..44) on the Resource
 * form shell: read-only by default, editable under the global Edit toggle, saved
 * through the form's single dirty-guarded save. Presents AutoCount source →
 * Sorento field directly (G1); the Sorento picker offers only accepted targets.
 * The editor body itself is shared with the DB task editor's Mapping tab.
 */
export function MappingEditorView({ companyId, entityType }: MappingEditorViewProps) {
  const { can } = useCan();
  const form = useForm();
  const { detail } = useAutocountCompany(companyId);
  const { view, isLoading, notFound, saveError, save, testFormula, simulate } =
    useAutocountMapping(companyId, entityType);
  const draft = useMappingDraft(view);

  const onSave = useCallback(async (): Promise<boolean> => {
    const problem = draft.validate();
    if (problem) {
      toast.error(problem);
      return false;
    }
    const ok = await save(draft.writeRows());
    if (ok) toast.success('Field mapping saved.');
    return ok;
  }, [draft, save]);

  const config = useMemo<ResourceFormConfig<AutocountMappingRow> | null>(() => {
    if (!view) return null;
    const companyName = detail?.company.name;
    return {
      breadcrumb: [
        { label: 'AutoCount' },
        { label: 'Companies', href: AC_COMPANIES_PATH },
        ...(companyName
          ? [{ label: companyName, href: acCompanyHref(companyId) }]
          : []),
        { label: `${entityLabel(entityType)} mapping` },
      ],
      backHref: acCompanyHref(companyId),
      title: `${entityLabel(entityType)} field mapping`,
      subtitle: companyName ?? undefined,
      tabs: [
        {
          id: 'mapping',
          label: 'Mapping',
          icon: Info,
          render: ({ editing }) => (
            <div className="py-2">
              <MappingEditorBody
                editing={editing && can(AC_COMPANIES_MANAGE)}
                draft={draft}
                saveError={saveError}
                onServerTest={testFormula}
                onSimulate={simulate}
                entityLabel={entityLabel(entityType)}
              />
            </div>
          ),
        },
      ],
      initialTabId: 'mapping',
      actions: [],
      actionRows: [],
      editable: true,
      editPermission: AC_COMPANIES_MANAGE,
      isDirty: draft.dirty,
      onSave,
      onCancel: draft.reset,
    };
  }, [can, companyId, detail, draft, entityType, onSave, saveError, simulate, testFormula, view]);

  if (isLoading && !view) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (notFound || !config) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Mapping not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={acCompanyHref(companyId)}>Back to company</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
