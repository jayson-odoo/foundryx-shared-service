'use client';

/**
 * Loads the binding/candidate-actor option lists for the Review-process role
 * editor (plan sprint-4/06 slice 1) by reusing the existing entity services —
 * components reach data only via hooks→services. PERSONA/profile options are
 * EMS-side; the caller hides those sources when the `ems` module is inactive
 * (foolproof-UI), but loading is harmless (empty when not installed).
 */
import { useEffect, useState } from 'react';
import type { SearchSelectOption } from '@/components/platform/search-select';
import { emsService } from '@/services/ems-service';
import { personaService } from '@/services/persona-service';
import { rolesService } from '@/services/roles-service';
import { userService } from '@/services/user-service';

export interface ReviewActorOptions {
  /** Staff users (user-kind EXPLICIT/RULE candidate pool + STAFF_ROLE n/a). */
  users: SearchSelectOption[];
  /** Profiles (profile-kind candidate pool) — empty when ems is inactive. */
  profiles: SearchSelectOption[];
  /** Personas to bind a PERSONA role to — empty when ems is inactive. */
  personas: SearchSelectOption[];
  /** Staff roles to bind a STAFF_ROLE role to. */
  staffRoles: SearchSelectOption[];
  loading: boolean;
}

export function useReviewActorOptions(emsActive: boolean): ReviewActorOptions {
  const [users, setUsers] = useState<SearchSelectOption[]>([]);
  const [profiles, setProfiles] = useState<SearchSelectOption[]>([]);
  const [personas, setPersonas] = useState<SearchSelectOption[]>([]);
  const [staffRoles, setStaffRoles] = useState<SearchSelectOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);

    const tasks: Promise<void>[] = [
      userService
        .list({ page: 0, pageSize: 200 }) // list endpoints cap page_size at 200 — >200 → 422
        .then((r) => {
          if (active) {
            setUsers(r.data.map((u) => ({ value: u.id, label: u.name || u.email })));
          }
        })
        .catch(() => {
          if (active) setUsers([]);
        }),
      rolesService
        .list()
        .then((r) => {
          if (active) setStaffRoles(r.map((role) => ({ value: role.id, label: role.name })));
        })
        .catch(() => {
          if (active) setStaffRoles([]);
        }),
    ];

    if (emsActive) {
      tasks.push(
        emsService
          .listProfiles({ pageSize: 200 }) // caps at 200 — >200 → 422
          .then((r) => {
            if (active) {
              setProfiles(
                r.items.map((p) => ({ value: p.id, label: p.fullName || p.email })),
              );
            }
          })
          .catch(() => {
            if (active) setProfiles([]);
          }),
        personaService
          .list()
          .then((r) => {
            if (active) setPersonas(r.map((p) => ({ value: p.id, label: p.label })));
          })
          .catch(() => {
            if (active) setPersonas([]);
          }),
      );
    } else {
      setProfiles([]);
      setPersonas([]);
    }

    Promise.all(tasks).finally(() => {
      if (active) setLoading(false);
    });

    return () => {
      active = false;
    };
  }, [emsActive]);

  return { users, profiles, personas, staffRoles, loading };
}
