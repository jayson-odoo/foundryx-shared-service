'use client';

import { useCallback, useEffect, useState } from 'react';
import { personaService } from '@/services/persona-service';
import type { PortalPermission } from '@/types/persona';

/**
 * Loads the grantable portal-permission catalog for the persona grant editor
 * (AC-06-26). Layering: UI → THIS hook → service → api-client → FastAPI.
 */
export interface UsePortalPermissionsResult {
  permissions: PortalPermission[];
  loading: boolean;
  error: string | null;
}

export function usePortalPermissions(): UsePortalPermissionsResult {
  const [permissions, setPermissions] = useState<PortalPermission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    personaService
      .portalPermissions()
      .then((data) => active && setPermissions(data))
      .catch(
        (e: unknown) =>
          active &&
          setError(e instanceof Error ? e.message : 'Could not load keys.'),
      )
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return { permissions, loading, error };
}

/** Loads + persists a persona's granted portal keys (grant editor state). */
export interface UsePersonaGrantsResult {
  keys: string[];
  setKeys: (keys: string[]) => void;
  loading: boolean;
  saving: boolean;
  error: string | null;
  save: () => Promise<boolean>;
}

export function usePersonaGrants(personaId: string): UsePersonaGrantsResult {
  const [keys, setKeys] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    personaService
      .getPermissions(personaId)
      .then((data) => active && setKeys(data))
      .catch(
        (e: unknown) =>
          active &&
          setError(e instanceof Error ? e.message : 'Could not load grants.'),
      )
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [personaId]);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const saved = await personaService.setPermissions(personaId, keys);
      setKeys(saved);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save grants.');
      return false;
    } finally {
      setSaving(false);
    }
  }, [personaId, keys]);

  return { keys, setKeys, loading, saving, error, save };
}
