'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { LoaderCircleIcon, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { PortalInviteButton } from '@/components/platform/portal-invite-button';
import { useCan } from '@/hooks/use-can';
import { personaService } from '@/services/persona-service';
import { emsService } from '@/services/ems-service';
import type { Persona, PersonaMembership } from '@/types/persona';
import type { Project } from '@/types/ems';

/**
 * Profile "Personas" section (AC-06-22/26 — the STAFF acquisition path). Lists
 * the Profile's scoped memberships with a scoped add (persona SearchSelect +
 * scope picker: Tenant-wide or a specific event) and revoke. Every dropdown is a
 * SearchSelect (foolproof-UI). Read-only unless the user holds personas.manage.
 */
const SCOPE_TENANT = 'tenant';
const SCOPE_PROJECT = 'project';

export function ProfilePersonasTab({
  profileId,
  profileEmail,
}: {
  profileId: string;
  profileEmail?: string | null;
}) {
  const { can } = useCan();
  const canManage = can('personas.manage');

  const [memberships, setMemberships] = useState<PersonaMembership[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  const [personaId, setPersonaId] = useState<string | null>(null);
  const [scopeType, setScopeType] = useState<string>(SCOPE_TENANT);
  const [scopeId, setScopeId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    const ms = await personaService.listProfileMemberships(profileId);
    setMemberships(ms);
  }, [profileId]);

  useEffect(() => {
    let active = true;
    Promise.all([
      personaService.listProfileMemberships(profileId),
      personaService.list(),
      emsService.listProjects({ pageSize: 200 }),
    ])
      .then(([ms, ps, prj]) => {
        if (!active) return;
        setMemberships(ms);
        setPersonas(ps);
        setProjects(prj.items);
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [profileId]);

  const personaName = useMemo(() => {
    const map = new Map(personas.map((p) => [p.id, p.label]));
    return (id: string) => map.get(id) ?? id;
  }, [personas]);

  const projectName = useMemo(() => {
    const map = new Map(projects.map((p) => [p.id, p.title]));
    return (id: string) => map.get(id) ?? id;
  }, [projects]);

  const scopeLabel = (m: PersonaMembership) =>
    m.scopeType === SCOPE_PROJECT && m.scopeId
      ? projectName(m.scopeId)
      : 'Tenant-wide';

  const canSubmit =
    Boolean(personaId) &&
    (scopeType === SCOPE_TENANT || Boolean(scopeId));

  const add = async () => {
    if (!personaId) return;
    setAdding(true);
    try {
      await personaService.assignMembership(profileId, {
        personaId,
        scopeType,
        scopeId: scopeType === SCOPE_PROJECT ? scopeId ?? undefined : undefined,
      });
      setPersonaId(null);
      setScopeType(SCOPE_TENANT);
      setScopeId(null);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not assign the persona.');
    } finally {
      setAdding(false);
    }
  };

  const revoke = async (membershipId: string) => {
    try {
      await personaService.revokeMembership(profileId, membershipId);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not revoke the persona.');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <LoaderCircleIcon className="size-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 py-2">
      {canManage && (
        <div className="flex items-center justify-end">
          <PortalInviteButton profileId={profileId} email={profileEmail} />
        </div>
      )}

      {/* Existing memberships. */}
      <div className="flex flex-col gap-2">
        {memberships.length === 0 ? (
          <p className="text-sm text-muted-foreground">No personas assigned.</p>
        ) : (
          memberships.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2"
            >
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="font-medium">{personaName(m.personaId)}</span>
                <Badge variant="secondary" appearance="light" size="sm">
                  {scopeLabel(m)}
                </Badge>
                <Badge variant="outline" appearance="light" size="sm">
                  {m.grantedVia}
                </Badge>
              </div>
              {canManage && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Revoke persona"
                  onClick={() => void revoke(m.id)}
                >
                  <Trash2 className="size-4 text-destructive" />
                </Button>
              )}
            </div>
          ))
        )}
      </div>

      {/* Scoped add. */}
      {canManage && (
        <div className="flex flex-col gap-3 rounded-lg border border-dashed border-border p-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label>Persona</Label>
              <SearchSelect
                ariaLabel="Persona"
                placeholder="Select persona"
                options={personas.map((p) => ({ label: p.label, value: p.id }))}
                value={personaId}
                onChange={(v) => setPersonaId(v)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Scope</Label>
              <SearchSelect
                ariaLabel="Scope"
                options={[
                  { label: 'Tenant-wide', value: SCOPE_TENANT },
                  { label: 'Specific event', value: SCOPE_PROJECT },
                ]}
                value={scopeType}
                onChange={(v) => {
                  setScopeType(v);
                  if (v === SCOPE_TENANT) setScopeId(null);
                }}
              />
            </div>
            {scopeType === SCOPE_PROJECT && (
              <div className="space-y-1.5">
                <Label>Event</Label>
                <SearchSelect
                  ariaLabel="Event"
                  placeholder="Select event"
                  searchPlaceholder="Search events…"
                  options={projects.map((p) => ({ label: p.title, value: p.id }))}
                  value={scopeId}
                  onChange={(v) => setScopeId(v)}
                />
              </div>
            )}
          </div>
          <div className="flex justify-end">
            <Button onClick={() => void add()} disabled={!canSubmit || adding}>
              <Plus className="size-3.5" /> {adding ? 'Assigning…' : 'Assign persona'}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
