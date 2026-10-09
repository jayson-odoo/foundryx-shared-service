'use client';

/**
 * Contact form config (D-A2-2a, D-A2-4) - a clone of `use-user-form.tsx`.
 * CREATE renders one Details tab (`contact-form-fields.tsx`, an RHF form).
 * VIEWING an existing contact renders Details (reuses the A1 `ContactPanel`
 * via `contact-details-tab.tsx` - its own internal edit affordance, gated
 * `contacts.manage`) + Conversation (`<ConversationDrawer compact>`); the
 * outer shell stays read-only chrome (`editable:false`) so there is only ONE
 * edit affordance per field, not a duplicate outer toggle.
 */
import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { UserRound } from 'lucide-react';
import { toast } from '@/lib/toast';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import { ConversationDrawer } from '@/components/platform/conversation-drawer';
import { ApiError } from '@/lib/api-client';
import { contactService } from '@/services/contact-service';
import { useContactFields } from '@/hooks/use-contact-fields';
import { useContactTags } from '@/hooks/use-contact-tags';
import { useContactLifecycleStages } from '@/hooks/use-contact-lifecycle-stages';
import type { ContactListItem } from '@/types/omnichannel';
import { ContactDetailsTab } from './contact-details-tab';
import { ContactFormFields } from './contact-form-fields';
import { contactFormHref, contactFormPath, contactsListPath } from './paths';
import { contactCreateSchema, defaultContactCreateValues, type ContactCreateValues } from './contact-schema';

type CustomFieldValue = string | number | boolean | null;

export interface UseContactFormResult {
  config: ResourceFormConfig<ContactListItem> | null;
  /** Only meaningful in create mode (the view mode has no RHF form at the
   *  shell level - editing happens inside the reused A1 components). */
  form: UseFormReturn<ContactCreateValues>;
  isLoading: boolean;
  notFound: boolean;
}

/** `workspaceId` is resolved by the page BEFORE mounting this hook (mirrors
 *  the Inbox host) - always a real id here. */
export function useContactForm(contactId: string | undefined, workspaceId: string): UseContactFormResult {
  const router = useRouter();
  const creating = !contactId;

  const { fields } = useContactFields(workspaceId);
  const { tags } = useContactTags(workspaceId);
  const { stages } = useContactLifecycleStages(workspaceId);

  const [record, setRecord] = useState<ContactListItem | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const createForm = useForm<ContactCreateValues>({
    mode: 'onTouched',
    resolver: zodResolver(contactCreateSchema),
    defaultValues: defaultContactCreateValues(),
  });
  const [customValues, setCustomValues] = useState<Record<string, CustomFieldValue>>({});
  const [customErrors, setCustomErrors] = useState<Record<string, string>>({});

  // Default the Lifecycle stage field to the workspace's initial stage once
  // it loads (AC-CTM-08) - only while the field is still untouched.
  useEffect(() => {
    if (!creating || stages.length === 0) return;
    if (createForm.getValues('lifecycleStatusId')) return;
    const initial = stages.find((s) => s.isInitial) ?? stages[0];
    if (initial) createForm.setValue('lifecycleStatusId', initial.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [creating, stages]);

  useEffect(() => {
    let active = true;
    if (creating) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    contactService
      .get(workspaceId, contactId)
      .then((c) => {
        if (!active) return;
        setRecord(c);
        setNotFound(false);
      })
      .catch(() => active && setNotFound(true))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
  }, [creating, workspaceId, contactId]);

  const config = useMemo<ResourceFormConfig<ContactListItem> | null>(() => {
    if (isLoading || (!creating && notFound)) return null;

    if (creating) {
      const onSave = async (): Promise<boolean> => {
        let ok = false;
        setCustomErrors({});
        await createForm.handleSubmit(async (values) => {
          try {
            const created = await contactService.create(workspaceId, {
              firstName: values.firstName || null,
              lastName: values.lastName || null,
              phone: values.phone,
              email: values.email || null,
              language: values.language || null,
              countryCode: values.countryCode || null,
              lifecycleStatusId: values.lifecycleStatusId,
              tagIds: values.tagIds,
              customFields: customValues,
            });
            toast.success('Contact created.');
            router.push(contactFormPath(created.id));
            ok = true;
          } catch (error) {
            if (error instanceof ApiError && error.status === 422) {
              const fieldErrors =
                (error.detail as { fieldErrors?: Record<string, string> } | undefined)?.fieldErrors ?? {};
              const KNOWN = new Set(['phone', 'email', 'language', 'countryCode', 'tagIds']);
              const nextCustomErrors: Record<string, string> = {};
              for (const [key, message] of Object.entries(fieldErrors)) {
                if (KNOWN.has(key)) {
                  createForm.setError(key as keyof ContactCreateValues, { message });
                } else if (key.startsWith('customFields.')) {
                  nextCustomErrors[key.slice('customFields.'.length)] = message;
                } else {
                  toast.error(message);
                }
              }
              if (Object.keys(nextCustomErrors).length) setCustomErrors(nextCustomErrors);
            } else {
              toast.error(error instanceof Error ? error.message : 'Could not create the contact.');
            }
          }
        })();
        return ok;
      };

      return {
        breadcrumb: [
          { label: 'Home', href: '/' },
          { label: 'Contacts', href: contactsListPath },
          { label: 'New contact' },
        ],
        backHref: contactsListPath,
        backLabel: 'Back to contacts',
        title: 'New contact',
        subtitle: 'Add a contact to this workspace',
        avatar: <UserRound className="size-5" />,
        tabs: [
          {
            id: 'details',
            label: 'Details',
            render: () => (
              <ContactFormFields
                form={createForm}
                stages={stages}
                tags={tags}
                fields={fields}
                customValues={customValues}
                onCustomChange={(key, value) => setCustomValues((prev) => ({ ...prev, [key]: value }))}
                customErrors={customErrors}
              />
            ),
          },
        ],
        actions: [],
        actionRows: [],
        editable: false,
        initialEditing: true,
        isDirty: createForm.formState.isDirty,
        onSave,
        onCancel: () => router.push(contactsListPath),
      } satisfies ResourceFormConfig<ContactListItem>;
    }

    if (!record) return null;

    return {
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'Contacts', href: contactsListPath },
        { label: record.name },
      ],
      backHref: contactsListPath,
      backLabel: 'Back to contacts',
      title: record.name,
      subtitle: record.phone ?? undefined,
      avatar: <UserRound className="size-5" />,
      tabs: [
        { id: 'details', label: 'Details', render: () => <ContactDetailsTab contactId={record.id} /> },
        {
          id: 'conversation',
          label: 'Conversation',
          render: () => (
            <div className="h-[calc(100vh-320px)] min-h-[420px] overflow-hidden rounded-lg border">
              <ConversationDrawer contactId={record.id} compact />
            </div>
          ),
        },
      ],
      actions: [],
      actionRows: [record],
      // The reused A1 panel components (`ContactPanel` -> `ContactDetailsForm`
      // / `LifecycleMove` / `TagChips`) each own their own field-level edit
      // affordance (gated `contacts.manage`) - a second, outer Edit toggle
      // here would be a redundant/confusing SECOND way to enter edit mode.
      editable: false,
      isDirty: false,
      onSave: async () => true,
      onCancel: () => {},
      recordNav: {
        fetchAt: (query, index) =>
          contactService.getAt(workspaceId, query, index).then((r) => ({
            recordId: r.contact?.id ?? null,
            total: r.total,
          })),
        buildHref: (recordId, ctx, index) => contactFormHref(recordId, { ctx, index }),
      },
    } satisfies ResourceFormConfig<ContactListItem>;
  }, [
    isLoading,
    creating,
    notFound,
    record,
    workspaceId,
    createForm,
    stages,
    tags,
    fields,
    customValues,
    customErrors,
    router,
  ]);

  return { config, form: createForm, isLoading, notFound };
}
