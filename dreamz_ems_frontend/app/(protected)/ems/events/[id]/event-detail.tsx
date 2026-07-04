'use client';

/** Event (project) detail — Participants + the event's OWN eligibility flow
 * (AC-11-01/12/13). Participants carry a role + segment (from the template) and
 * move through the scoped eligibility graph via the Move action. The flow tab
 * is the scoped status canvas (scope = project_id), Edit-gated. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { ArrowRight, Banknote, Copy, ExternalLink, Info, LoaderCircleIcon, Receipt, ScanLine, Ticket, UserCheck, Users, Workflow } from 'lucide-react';
import { deriveTenantSlug } from '@/lib/tenant';
import { Container } from '@/components/common/container';
import { Form } from '@/components/ui/form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { SearchSelect } from '@/components/platform/search-select';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import type { ResourceAction } from '@/components/platform/resource-list';
import { ResourceList } from '@/components/platform/resource-list';
import { EntityFlow, type LayoutController } from '@/components/platform/status-engine';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useTerminology } from '@/hooks/use-terminology';
import { useCan } from '@/hooks/use-can';
import { emsService } from '@/services/ems-service';
import { integrationService } from '@/services/integration-service';
import type { Connection } from '@/types/integration';
import type { Profile, Project, TemplateChild, Ticket as TicketModel } from '@/types/ems';
import {
  useParticipantsListConfig,
  type ParticipantRow,
} from './use-participants-list-config';
import { OfferingsTab } from './offerings-tab';
import { RegistrationsTab } from './registrations-tab';
import { EventInvoicesTab } from './event-invoices-tab';
import { CheckpointsTab } from './checkpoints-tab';
import { SettlementTab } from './settlement-tab';
import type { CommercialMode, FeeType } from '@/types/ems';

const PARTICIPANT_ENTITY = 'project_participant';
const PROJECT_ENTITY = 'project';

interface DetailValues {
  title: string;
  brief: string;
  notes: string;
  domainName: string;
  startDate: string;
  endDate: string;
  eventValidityEnd: string;
  commercialMode: CommercialMode;
  feeType: FeeType | '';
  feeValue: string;
  paymentConnectionId: string; // '' = tenant default (resolve_for_type)
}

const EMPTY_DETAILS: DetailValues = {
  title: '',
  brief: '',
  notes: '',
  domainName: '',
  startDate: '',
  endDate: '',
  eventValidityEnd: '',
  commercialMode: 'SELF_RUN',
  feeType: '',
  feeValue: '',
  paymentConnectionId: '',
};

function detailsFrom(p: Project): DetailValues {
  return {
    title: p.title ?? '',
    brief: p.brief ?? '',
    notes: p.notes ?? '',
    domainName: p.domainName ?? '',
    startDate: p.startDate ?? '',
    endDate: p.endDate ?? '',
    eventValidityEnd: p.eventValidityEnd ?? '',
    commercialMode: p.commercialMode ?? 'SELF_RUN',
    feeType: p.feeType ?? '',
    feeValue: p.feeValue != null ? String(p.feeValue) : '',
    paymentConnectionId: p.paymentConnectionId ?? '',
  };
}

// Sentinel for "use the tenant default payment connection" (NULL on the wire).
const DEFAULT_CONN = '__default__';

const COMMERCIAL_OPTIONS = [
  { value: 'SELF_RUN', label: 'Self-run (no settlement)' },
  { value: 'AGENCY', label: 'Agency (give-back settlement)' },
];
const FEE_TYPE_OPTIONS = [
  { value: 'PERCENT', label: 'Percent of gross' },
  { value: 'FLAT', label: 'Flat amount' },
  { value: 'PER_TICKET', label: 'Per ticket' },
];

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

export function EventDetail({ projectId }: { projectId: string }) {
  const { label, labelPlural } = useTerminology();
  const { can } = useCan();
  const canCheckin = can('checkpoints.read');
  const engine = useStatusGraph(PARTICIPANT_ENTITY, projectId);
  // Event lifecycle graph (Draft/Planning/Active/…) — drives the header status
  // + the manual transition actions in the form "…".
  const lifecycle = useStatusGraph(PROJECT_ENTITY);
  // Tier-1 profile graph — its blocks_access statuses gate who may register.
  const profileEngine = useStatusGraph('profile');
  const blockedStatusIds = useMemo(
    () =>
      new Set(
        (profileEngine.graph?.statuses ?? []).filter((s) => s.blocksAccess).map((s) => s.id),
      ),
    [profileEngine.graph],
  );
  const form = useForm<DetailValues>({ defaultValues: EMPTY_DETAILS });
  const values = form.watch();

  const [project, setProject] = useState<Project | null>(null);
  const [roles, setRoles] = useState<TemplateChild[]>([]);
  const [segments, setSegments] = useState<TemplateChild[]>([]);
  // Payment-type connections → the per-event gateway picker (AC-07-25). Empty
  // when the user lacks integrations.read — the field then offers only "default".
  const [paymentConns, setPaymentConns] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [assignRow, setAssignRow] = useState<ParticipantRow | null>(null);
  const [nominateRow, setNominateRow] = useState<ParticipantRow | null>(null);
  const [nonce, setNonce] = useState(0);
  const layoutController = useRef<LayoutController | null>(null);
  const [layoutDirty, setLayoutDirty] = useState(false);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const reloadProject = useCallback(() => {
    emsService
      .getProject(projectId)
      .then((p) => {
        setProject(p);
        form.reset(detailsFrom(p));
      })
      .catch(() => {});
  }, [projectId, form]);

  useEffect(() => {
    let active = true;
    emsService
      .getProject(projectId)
      .then(async (p) => {
        if (!active) return;
        setProject(p);
        form.reset(detailsFrom(p));
        const [r, s] = await Promise.all([
          emsService.listRoles(p.templateId).catch(() => []),
          emsService.listSegments(p.templateId).catch(() => []),
        ]);
        if (!active) return;
        setRoles(r);
        setSegments(s);
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [projectId, form]);

  useEffect(() => {
    let active = true;
    integrationService
      .list({ page: 0, pageSize: 200 })
      .then((r) => active && setPaymentConns(r.data.filter((c) => c.type === 'payment')))
      .catch(() => active && setPaymentConns([]));
    return () => {
      active = false;
    };
  }, []);

  const onAdd = useCallback(() => setAdding(true), []);
  const onAssign = useCallback((row: ParticipantRow) => setAssignRow(row), []);
  const onNominate = useCallback((row: ParticipantRow) => setNominateRow(row), []);

  const participantsCtx = useMemo(
    () => ({
      projectId,
      statuses: engine.graph?.statuses ?? [],
      transitions: engine.graph?.transitions ?? [],
      roles,
      segments,
      onAdd,
      onAssign,
      onNominate,
    }),
    [projectId, engine.graph, roles, segments, onAdd, onAssign, onNominate],
  );
  const participantsConfig = useParticipantsListConfig(participantsCtx);

  const config = useMemo<ResourceFormConfig<Project> | null>(() => {
    if (!project) return null;
    // Event lifecycle status + manual transition actions (auto edges fire
    // themselves — never offered as a click), straight off the project graph.
    const statusLabel = new Map((lifecycle.graph?.statuses ?? []).map((s) => [s.id, s.label]));
    const currentStatus = project.statusId ? statusLabel.get(project.statusId) : null;
    const lifecycleActions: ResourceAction<Project>[] = (lifecycle.graph?.transitions ?? [])
      .filter((t) => t.triggerMode !== 'auto' && t.fromStatusId === project.statusId)
      .map((t) => ({
        id: `move-${t.toStatusId}`,
        label: statusLabel.get(t.toStatusId) || t.label, // bare target status name
        icon: ArrowRight,
        surfaces: { row: false, form: true, bulk: false },
        permission: 'projects.manage',
        run: async () => {
          try {
            await emsService.transitionProject(project.id, t.toStatusId);
            reloadProject();
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not change the status.');
          }
        },
      }));
    // Registration portal (public, anonymous) link for THIS event — slug derived
    // from the current host; the page itself is the slice-1 read-only portal.
    const registrationUrl = () => {
      const slug = deriveTenantSlug(window.location.host);
      return `${window.location.origin}/public/register/${slug}/${project.id}`;
    };
    const registrationActions: ResourceAction<Project>[] = [
      {
        id: 'copy-register-link',
        label: 'Copy registration link',
        icon: Copy,
        surfaces: { row: false, form: true, bulk: false },
        permission: 'projects.read',
        run: async () => {
          try {
            await navigator.clipboard.writeText(registrationUrl());
            toast.success('Registration link copied.');
          } catch {
            toast.error('Could not copy the link.');
          }
        },
      },
      {
        id: 'open-register-portal',
        label: 'Open registration portal',
        icon: ExternalLink,
        surfaces: { row: false, form: true, bulk: false },
        permission: 'projects.read',
        run: () => {
          window.open(registrationUrl(), '_blank', 'noopener');
        },
      },
    ];
    return {
      breadcrumb: [{ label: labelPlural('project'), href: '/ems/events' }, { label: project.title }],
      backHref: '/ems/events',
      backLabel: labelPlural('project'),
      title: project.title,
      subtitle: `${currentStatus ? `Status: ${currentStatus} · ` : ''}${labelPlural('project_participant')} + eligibility flow for this ${label('project').toLowerCase()}`,
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Info,
          render: ({ editing }) => (
            <div className="flex flex-col gap-5 py-2">
              <DetailRow label="Status">
                {currentStatus ? (
                  <Badge variant="primary" appearance="light" size="sm">{currentStatus}</Badge>
                ) : (
                  <span className="text-sm text-muted-foreground">—</span>
                )}
              </DetailRow>
              {(
                [
                  ['title', 'Title', 'text'],
                  ['startDate', 'Start date', 'date'],
                  ['endDate', 'End date', 'date'],
                  ['eventValidityEnd', 'Event validity end', 'date'],
                  ['brief', 'Brief', 'text'],
                  ['notes', 'Notes', 'text'],
                  ['domainName', 'Domain', 'text'],
                ] as [keyof DetailValues, string, string][]
              ).map(([key, lbl, type]) => (
                <DetailRow key={key} label={lbl}>
                  {editing ? (
                    <Input
                      type={type}
                      aria-label={lbl}
                      value={values[key] as string}
                      onChange={(e) => form.setValue(key, e.target.value, { shouldDirty: true })}
                    />
                  ) : (
                    // Date values render as the calendar string directly (no tz formatter).
                    <span className="text-sm">{(values[key] as string) || '—'}</span>
                  )}
                </DetailRow>
              ))}
              {/* Commercial mode + agency fee (AC-07-45) */}
              <DetailRow label="Commercial mode">
                {editing ? (
                  <SearchSelect
                    value={values.commercialMode}
                    onChange={(v) => form.setValue('commercialMode', v as CommercialMode, { shouldDirty: true })}
                    options={COMMERCIAL_OPTIONS}
                    ariaLabel="Commercial mode"
                  />
                ) : (
                  <span className="text-sm">
                    {COMMERCIAL_OPTIONS.find((o) => o.value === values.commercialMode)?.label ?? '—'}
                  </span>
                )}
              </DetailRow>
              {values.commercialMode === 'AGENCY' && (
                <>
                  <DetailRow label="Fee type">
                    {editing ? (
                      <SearchSelect
                        value={values.feeType || null}
                        onChange={(v) => form.setValue('feeType', (v as FeeType) ?? '', { shouldDirty: true })}
                        options={FEE_TYPE_OPTIONS}
                        ariaLabel="Fee type"
                      />
                    ) : (
                      <span className="text-sm">
                        {FEE_TYPE_OPTIONS.find((o) => o.value === values.feeType)?.label ?? '—'}
                      </span>
                    )}
                  </DetailRow>
                  <DetailRow label="Fee value">
                    {editing ? (
                      <Input
                        type="number"
                        step="0.01"
                        aria-label="Fee value"
                        value={values.feeValue}
                        onChange={(e) => form.setValue('feeValue', e.target.value, { shouldDirty: true })}
                      />
                    ) : (
                      <span className="text-sm">{values.feeValue || '—'}</span>
                    )}
                  </DetailRow>
                </>
              )}
              {/* Per-event payment gateway (AC-07-25). NULL/default → tenant
                  default connection (resolve_for_type) at checkout. */}
              <DetailRow label="Payment gateway">
                {editing ? (
                  <SearchSelect
                    value={values.paymentConnectionId || DEFAULT_CONN}
                    onChange={(v) =>
                      form.setValue('paymentConnectionId', v === DEFAULT_CONN ? '' : (v ?? ''), {
                        shouldDirty: true,
                      })
                    }
                    options={[
                      { value: DEFAULT_CONN, label: 'Tenant default' },
                      ...paymentConns.map((c) => ({
                        value: c.id,
                        label: c.status === 'ACTIVE' ? c.name : `${c.name} (${c.status.toLowerCase()})`,
                      })),
                    ]}
                    ariaLabel="Payment gateway"
                  />
                ) : (
                  <span className="text-sm">
                    {values.paymentConnectionId
                      ? (paymentConns.find((c) => c.id === values.paymentConnectionId)?.name ??
                        'Selected connection')
                      : 'Tenant default'}
                  </span>
                )}
              </DetailRow>
            </div>
          ),
        },
        {
          id: 'participants',
          label: labelPlural('project_participant'),
          icon: Users,
          render: () => <ResourceList key={nonce} config={participantsConfig} />,
        },
        {
          id: 'offerings',
          label: 'Offerings',
          icon: Ticket,
          render: () => <OfferingsTab projectId={projectId} roles={roles} segments={segments} />,
        },
        {
          id: 'tickets',
          label: 'Tickets',
          icon: UserCheck,
          render: () => <RegistrationsTab projectId={projectId} />,
        },
        {
          id: 'invoices',
          label: 'Invoices',
          icon: Receipt,
          render: () => <EventInvoicesTab projectId={projectId} />,
        },
        ...(project.commercialMode === 'AGENCY' && can('settlements.read')
          ? [
              {
                id: 'settlement',
                label: 'Settlement',
                icon: Banknote,
                render: () => <SettlementTab projectId={projectId} />,
              },
            ]
          : []),
        ...(canCheckin
          ? [
              {
                id: 'checkin',
                label: 'Check-in',
                icon: ScanLine,
                render: () => <CheckpointsTab projectId={projectId} segments={segments} />,
              },
            ]
          : []),
        {
          id: 'flow',
          label: 'Eligibility flow',
          icon: Workflow,
          render: ({ editing }) => (
            <EntityFlow
              entityType={PARTICIPANT_ENTITY}
              entityLabel={`${project.title} eligibility`}
              engine={engine}
              editing={editing}
              onDirtyChange={setLayoutDirty}
              layoutController={layoutController}
            />
          ),
        },
      ],
      actions: [...registrationActions, ...lifecycleActions],
      actionRows: [project],
      onReload: () => reloadProject(),
      editable: true,
      editPermission: 'projects.manage',
      // One Edit toggle covers BOTH the Details fields and the flow layout.
      isDirty: form.formState.isDirty || layoutDirty,
      onSave: async () => {
        // Each branch guarded by its own dirty flag (no no-op PATCH).
        if (form.formState.isDirty) {
          const updated = await emsService.updateProject(project.id, {
            title: values.title,
            brief: values.brief || null,
            notes: values.notes || null,
            domainName: values.domainName || null,
            startDate: values.startDate || null,
            endDate: values.endDate || null,
            eventValidityEnd: values.eventValidityEnd || null,
            commercialMode: values.commercialMode,
            feeType: values.commercialMode === 'AGENCY' ? (values.feeType || null) : null,
            feeValue:
              values.commercialMode === 'AGENCY' && values.feeValue !== ''
                ? Number(values.feeValue)
                : null,
            paymentConnectionId: values.paymentConnectionId || null,
          });
          setProject(updated);
          form.reset(detailsFrom(updated));
        }
        if (layoutDirty) layoutController.current?.save();
        return true;
      },
      onCancel: () => {
        form.reset(detailsFrom(project));
        layoutController.current?.discard();
      },
    };
  }, [project, engine, lifecycle.graph, reloadProject, participantsConfig, nonce, label, labelPlural, layoutDirty, form, values, projectId, roles, segments, canCheckin, can, paymentConns]);

  if (loading || engine.loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (!config) {
    return (
      <Container width="fluid">
        <div className="py-24 text-center text-sm font-medium">Event not found.</div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
      {adding && (
        <AddParticipantDialog
          projectId={projectId}
          roles={roles}
          segments={segments}
          blockedStatusIds={blockedStatusIds}
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            reload();
          }}
        />
      )}
      {assignRow && (
        <AssignDialog
          projectId={projectId}
          row={assignRow}
          roles={roles}
          segments={segments}
          onClose={() => setAssignRow(null)}
          onSaved={() => {
            setAssignRow(null);
            reload();
          }}
        />
      )}
      {nominateRow && (
        <NominateDialog
          projectId={projectId}
          row={nominateRow}
          blockedStatusIds={blockedStatusIds}
          onClose={() => setNominateRow(null)}
          onSaved={() => {
            setNominateRow(null);
            reload();
          }}
        />
      )}
    </Container>
  );
}

/* ── dialogs ─────────────────────────────────────────────────────────────── */

const NONE = '__none__';

function AddParticipantDialog({
  projectId,
  roles,
  segments,
  blockedStatusIds,
  onClose,
  onSaved,
}: {
  projectId: string;
  roles: TemplateChild[];
  segments: TemplateChild[];
  blockedStatusIds: Set<string>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { label } = useTerminology();
  const [allProfiles, setAllProfiles] = useState<Profile[]>([]);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [roleId, setRoleId] = useState<string | null>(null);
  const [segmentId, setSegmentId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    emsService.listProfiles({ pageSize: 200 }).then((r) => setAllProfiles(r.items)).catch(() => setAllProfiles([]));
  }, []);

  // Foolproof-UI: only offer profiles the status engine allows to register —
  // suspended/blacklisted profiles are withheld (the backend enforces too).
  const profiles = allProfiles.filter((p) => !(p.statusId && blockedStatusIds.has(p.statusId)));

  const save = async () => {
    if (!profileId) return;
    setBusy(true);
    setError(null);
    try {
      await emsService.addParticipant(projectId, {
        profileId,
        roleId: roleId ?? undefined,
        segmentId: segmentId ?? undefined,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not register.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add {label('project_participant').toLowerCase()}</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {profiles.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {allProfiles.length === 0
                ? `Create a ${label('profile').toLowerCase()} first.`
                : 'Every profile is suspended or blacklisted — none can be registered.'}
            </p>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label>{label('profile')} *</Label>
                <SearchSelect
                  value={profileId}
                  onChange={setProfileId}
                  options={profiles.map((p) => ({ value: p.id, label: p.fullName || p.email }))}
                />
              </div>
              {roles.length > 0 && (
                <div className="space-y-1.5">
                  <Label>Role</Label>
                  <SearchSelect
                    value={roleId}
                    onChange={setRoleId}
                    options={roles.map((r) => ({ value: r.id, label: r.name }))}
                    placeholder="No role"
                  />
                </div>
              )}
              {segments.length > 0 && (
                <div className="space-y-1.5">
                  <Label>Segment</Label>
                  <SearchSelect
                    value={segmentId}
                    onChange={setSegmentId}
                    options={segments.map((s) => ({ value: s.id, label: s.name }))}
                    placeholder="No segment"
                  />
                </div>
              )}
            </>
          )}
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!profileId || busy}>
            {busy ? 'Saving…' : 'Add'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AssignDialog({
  projectId,
  row,
  roles,
  segments,
  onClose,
  onSaved,
}: {
  projectId: string;
  row: ParticipantRow;
  roles: TemplateChild[];
  segments: TemplateChild[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const initialRole = roles.find((r) => r.name === row.roleName)?.id ?? NONE;
  const initialSeg = segments.find((s) => s.name === row.segmentName)?.id ?? NONE;
  const [roleId, setRoleId] = useState<string | null>(initialRole);
  const [segmentId, setSegmentId] = useState<string | null>(initialSeg);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await emsService.updateParticipant(projectId, row.id, {
        roleId: roleId === NONE ? null : roleId,
        segmentId: segmentId === NONE ? null : segmentId,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Assign role / segment</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <p className="text-sm text-muted-foreground">{row.profileName}</p>
          <div className="space-y-1.5">
            <Label>Role</Label>
            <SearchSelect
              value={roleId}
              onChange={setRoleId}
              options={[{ value: NONE, label: 'No role' }, ...roles.map((r) => ({ value: r.id, label: r.name }))]}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Segment</Label>
            <SearchSelect
              value={segmentId}
              onChange={setSegmentId}
              options={[{ value: NONE, label: 'No segment' }, ...segments.map((s) => ({ value: s.id, label: s.name }))]}
            />
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Reassign a participant's ticket to a new attendee Profile (Cluster D slice 3).
 * Status → Transferred + QR rotated on the backend; the nominee can't re-transfer
 * (a transferred ticket is refused). Money untouched. Only transferable tickets
 * (not already transferred/void/refunded) are offered. */
function NominateDialog({
  projectId,
  row,
  blockedStatusIds,
  onClose,
  onSaved,
}: {
  projectId: string;
  row: ParticipantRow;
  blockedStatusIds: Set<string>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { label } = useTerminology();
  const [tickets, setTickets] = useState<TicketModel[] | null>(null);
  const [allProfiles, setAllProfiles] = useState<Profile[]>([]);
  const [ticketId, setTicketId] = useState<string | null>(null);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    emsService
      .listParticipantTickets(projectId, row.id)
      .then((ts) => {
        setTickets(ts);
        const transferable = ts.find((t) => !['transferred', 'void', 'refunded'].includes(t.status));
        setTicketId(transferable?.id ?? null);
      })
      .catch(() => setTickets([]));
    emsService.listProfiles({ pageSize: 200 }).then((r) => setAllProfiles(r.items)).catch(() => setAllProfiles([]));
  }, [projectId, row.id]);

  // Foolproof-UI: a transferable ticket only, a non-blocked + different nominee.
  const transferable = (tickets ?? []).filter((t) => !['transferred', 'void', 'refunded'].includes(t.status));
  const nominees = allProfiles.filter(
    (p) => p.id !== row.profileId && !(p.statusId && blockedStatusIds.has(p.statusId)),
  );

  const save = async () => {
    if (!ticketId || !profileId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await emsService.nominateTicket(projectId, ticketId, profileId);
      toast.success(res.qrRotated ? 'Ticket transferred — QR rotated.' : 'Ticket transferred.');
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not transfer the ticket.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Nominate / transfer ticket</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <p className="text-sm text-muted-foreground">{row.profileName}</p>
          {tickets === null ? (
            <p className="text-sm text-muted-foreground">Loading tickets…</p>
          ) : transferable.length === 0 ? (
            <p className="text-sm text-muted-foreground">This attendee has no transferable ticket.</p>
          ) : nominees.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No eligible {label('profile').toLowerCase()} to transfer to.
            </p>
          ) : (
            <>
              {transferable.length > 1 && (
                <div className="space-y-1.5">
                  <Label>Ticket *</Label>
                  <SearchSelect
                    value={ticketId}
                    onChange={setTicketId}
                    options={transferable.map((t) => ({ value: t.id, label: `Ticket ${t.id.slice(0, 8)}` }))}
                  />
                </div>
              )}
              <div className="space-y-1.5">
                <Label>New attendee *</Label>
                <SearchSelect
                  value={profileId}
                  onChange={setProfileId}
                  options={nominees.map((p) => ({ value: p.id, label: p.fullName || p.email }))}
                />
              </div>
            </>
          )}
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!ticketId || !profileId || busy}>
            {busy ? 'Transferring…' : 'Transfer'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

