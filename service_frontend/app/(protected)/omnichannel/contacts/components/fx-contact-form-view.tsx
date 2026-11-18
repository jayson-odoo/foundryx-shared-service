'use client';

/**
 * Foundryx UIUX switch only (slice W1-CONTACT): the contact record and the
 * new-contact page under the new look, from the same `useContactForm` config
 * the switch-off view renders through `ResourceForm`.
 *
 * Page-local rather than the shared form shell, because the approved mock
 * needs what that shell does not take from a config today (findings FX-16,
 * FX-22): the record's More menu in the header, its own red action, and a
 * Details / Conversation toggle that keeps each side's state.
 *
 * Record (mock "Contact record", after):
 * - Header: avatar initials and the name (Hold to Copy), the phone under it
 *   (Hold to Copy), Back to contacts as a plain link, the record arrows
 *   ("3 of 137", greyed at the ends, hidden while Details is being edited)
 *   and More holding Erase contact. No red action: the record page has no
 *   main button today, and editing stays per section (Q-EDIT).
 * - Erase contact runs the contacts list's own action
 *   (`use-contact-erase-action.tsx`): typed confirm with the contact's name,
 *   no Undo.
 * - Details | Conversation is a sliding toggle. Each side mounts the first
 *   time it is shown and then stays mounted, so a half-typed reply or an
 *   open Details edit survives switching.
 *
 * New contact: the same fields, "Create contact" as the page's red action
 * (naming the contact on hover once one is typed), Cancel and Back to
 * contacts behind the single-click discard guard when something was typed.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { ChevronLeft } from 'lucide-react';
import type { UseFormReturn } from 'react-hook-form';
import type { ContactListItem } from '@/types/omnichannel';
import { buildListNav } from '@/lib/list-context';
import { cn } from '@/lib/utils';
import { useCan } from '@/hooks/use-can';
import { Button } from '@/components/ui/button';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Container } from '@/components/common/container';
import { FxDiscardDialog } from '@/components/fx/actions/confirm-dialog';
import { FxOtherActions } from '@/components/fx/actions/other-actions';
import {
  useRegisterMainAction,
  type FxMainActionSpec,
  type FxOtherActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { FxHoldToCopy } from '@/components/fx/copy/hold-to-copy';
import { ConversationDrawer } from '@/components/platform/conversation-drawer';
import { PageHeader } from '@/components/platform/page-header';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import { RecordNav } from '@/components/platform/resource-form/record-nav';
import type { ResourceAction } from '@/components/platform/resource-list';
import { ContactDetailsTab } from './contact-details-tab';
import { contactInitials, newContactName } from './contact-record-fx';
import type { ContactCreateValues } from './contact-schema';

type Side = 'details' | 'conversation';

function BackLink({
  href,
  label,
  onClick,
  className,
}: {
  href: string;
  label: string;
  onClick?: (e: React.MouseEvent<HTMLAnchorElement>) => void;
  className?: string;
}) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        className,
        'inline-flex min-h-9 items-center gap-1 text-sm font-semibold whitespace-nowrap text-(--fx-link) transition-[translate] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-px',
      )}
    >
      <ChevronLeft aria-hidden="true" className="size-4" />
      {label}
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Record
// ---------------------------------------------------------------------------

export function FxContactRecord({
  config,
}: {
  config: ResourceFormConfig<ContactListItem>;
}) {
  const record = config.actionRows[0];
  const pathname = usePathname() ?? '';
  const searchParams = useSearchParams();
  const { can } = useCan();
  const [side, setSide] = useState<Side>('details');
  const [mounted, setMounted] = useState<Record<Side, boolean>>({
    details: true,
    conversation: false,
  });
  const [editing, setEditing] = useState(false);
  const [erasing, setErasing] =
    useState<ResourceAction<ContactListItem> | null>(null);

  // Back keeps the list's place (ctx / i / from), as the switch-off shell does.
  const recordId = pathname.split('/').filter(Boolean).pop();
  const iParam = searchParams.get('i');
  const backHref = buildListNav(config.backHref, {
    ctx: searchParams.get('ctx'),
    i:
      iParam !== null && Number.isFinite(Number(iParam))
        ? Number(iParam)
        : null,
    from: recordId,
  });

  const erase = config.actions.find((a) => a.id === 'erase-contact');
  const canErase = Boolean(
    erase && (!erase.permission || can(erase.permission)),
  );
  const others = useMemo<FxOtherActionSpec[]>(
    () =>
      erase && canErase
        ? [
            {
              id: erase.id,
              label:
                typeof erase.label === 'function'
                  ? erase.label([record])
                  : erase.label,
              icon: 'trash',
              tone: 'delete',
              onClick: () => setErasing(erase),
            },
          ]
        : [],
    [erase, canErase, record],
  );

  const show = (next: string) => {
    if (next !== 'details' && next !== 'conversation') return;
    setSide(next);
    setMounted((m) => (m[next] ? m : { ...m, [next]: true }));
  };
  const onEditingChange = useCallback(
    (value: boolean) => setEditing(value),
    [],
  );

  const title = (
    <span className="flex min-w-0 items-center gap-3">
      <span
        aria-hidden="true"
        className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-(--fx-link-bg) text-sm font-bold text-(--fx-link)"
      >
        {contactInitials(record.name)}
      </span>
      <span className="min-w-0 break-words">
        <FxHoldToCopy>{record.name}</FxHoldToCopy>
      </span>
    </span>
  );

  return (
    <Container width="fluid">
      <div className="flex flex-col gap-4" data-fx-contact-record="">
        {/* Phones: Back to contacts on its own line above the header (mock). */}
        <BackLink
          href={backHref}
          label={config.backLabel ?? 'Back'}
          className="-mb-3 self-start sm:hidden"
        />
        <PageHeader
          crumbs={config.breadcrumb}
          title={title}
          description={
            record.phone ? (
              <span className="tabular-nums">
                <FxHoldToCopy>{record.phone}</FxHoldToCopy>
              </span>
            ) : undefined
          }
          actions={
            <div className="flex flex-wrap items-center justify-end gap-2">
              <BackLink
                href={backHref}
                label={config.backLabel ?? 'Back'}
                className="max-sm:hidden"
              />
              {config.recordNav && !editing && (
                <RecordNav
                  fetchAt={config.recordNav.fetchAt}
                  buildHref={config.recordNav.buildHref}
                />
              )}
              <FxOtherActions
                actions={others}
                moreIds={others.map((a) => a.id)}
              />
            </div>
          }
        />

        <div>
          <ToggleGroup
            type="single"
            value={side}
            onValueChange={show}
            aria-label="Contact record view"
            data-testid="fx-record-toggle"
          >
            <ToggleGroupItem value="details">Details</ToggleGroupItem>
            <ToggleGroupItem value="conversation">Conversation</ToggleGroupItem>
          </ToggleGroup>
        </div>

        {mounted.details && (
          <div
            role="region"
            aria-label="Details"
            hidden={side !== 'details'}
            data-fx-side="details"
            className="animate-in fade-in duration-(--fx-t-open) ease-(--fx-ease-out)"
          >
            <ContactDetailsTab
              contactId={record.id}
              onEditingChange={onEditingChange}
            />
          </div>
        )}
        {mounted.conversation && (
          <div
            role="region"
            aria-label="Conversation"
            hidden={side !== 'conversation'}
            data-fx-side="conversation"
            className="animate-in fade-in duration-(--fx-t-open) ease-(--fx-ease-out)"
          >
            <div className="h-[calc(100dvh-320px)] min-h-[420px] overflow-hidden rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface)">
              <ConversationDrawer contactId={record.id} compact />
            </div>
          </div>
        )}

        <ConfirmActionDialog
          pending={erasing}
          rows={[record]}
          onClose={() => setErasing(null)}
          onConfirm={(action) => {
            void action.run?.([record], {
              reload: config.onReload ?? (() => {}),
              backHref,
            });
          }}
        />
      </div>
    </Container>
  );
}

// ---------------------------------------------------------------------------
// New contact
// ---------------------------------------------------------------------------

export function FxNewContact({
  config,
  form,
}: {
  config: ResourceFormConfig<ContactListItem>;
  form: UseFormReturn<ContactCreateValues>;
}) {
  const router = useRouter();
  const [working, setWorking] = useState(false);
  const [pending, setPending] = useState<(() => void) | null>(null);
  const dirty = config.isDirty;

  const firstName = form.watch('firstName');
  const lastName = form.watch('lastName');
  const typedName = newContactName({
    firstName: firstName ?? '',
    lastName: lastName ?? '',
    phone: '',
  });

  // Leaving with typed values asks once (single-click Discard), as the
  // switch-off shell does; a browser-level leave gets the browser's prompt.
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  const guard = useCallback(
    (proceed: () => void) => {
      if (!dirty) {
        proceed();
        return;
      }
      setPending(() => proceed);
    },
    [dirty],
  );

  const { onSave } = config;
  const create = useCallback(async () => {
    setWorking(true);
    try {
      await onSave();
    } finally {
      setWorking(false);
    }
  }, [onSave]);

  const main = useMemo<FxMainActionSpec>(
    () => ({
      id: 'create-contact',
      label: 'Create contact',
      fullLabel: typedName ? `Create ${typedName}` : undefined,
      onClick: () => void create(),
      working,
    }),
    [typedName, create, working],
  );
  useRegisterMainAction(main);

  const details = config.tabs[0];
  const leaveBack = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (!dirty) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    guard(() => router.push(config.backHref));
  };

  return (
    <Container width="fluid">
      <div className="flex flex-col gap-4" data-fx-new-contact="">
        <BackLink
          href={config.backHref}
          label={config.backLabel ?? 'Back'}
          onClick={leaveBack}
          className="-mb-3 self-start sm:hidden"
        />
        <PageHeader
          crumbs={config.breadcrumb}
          title={typeof config.title === 'string' ? config.title : undefined}
          description={config.subtitle}
          guardNav={dirty ? guard : undefined}
          actions={
            <div className="flex items-center gap-2">
              <BackLink
                href={config.backHref}
                label={config.backLabel ?? 'Back'}
                onClick={leaveBack}
                className="max-sm:hidden"
              />
              <Button
                type="button"
                variant="fx-text"
                size="sm"
                onClick={() => guard(config.onCancel)}
                disabled={working}
              >
                Cancel
              </Button>
            </div>
          }
        />

        <section
          aria-label="Details"
          className={cn(
            'flex flex-col gap-4 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 text-(--fx-ink) sm:p-5',
          )}
        >
          <h2 className="text-base font-semibold">Details</h2>
          {details?.render({ editing: true })}
        </section>

        <FxDiscardDialog
          open={pending !== null}
          name={typedName || 'the new contact'}
          onKeep={() => setPending(null)}
          onDiscard={() => {
            pending?.();
            setPending(null);
          }}
        />
      </div>
    </Container>
  );
}
