'use client';

/**
 * Lazily fetch a message's stored media as an authed blob → object URL (plan 12
 * AC-12-07). An `<img src>`/`<a href>` can't carry the Bearer, so media rides
 * `apiFetchBlob` (forms BL-092 pattern). The object URL is revoked on unmount.
 */
import { useEffect, useRef, useState } from 'react';

import { apiFetchBlob } from '@/lib/api-client';

export interface UseMediaBlobResult {
  url: string | null;
  isLoading: boolean;
  error: boolean;
}

export function useMediaBlob(path: string | null | undefined): UseMediaBlobResult {
  const [url, setUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(false);
  const objectUrl = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (objectUrl.current) {
      URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    }
    setUrl(null);
    setError(false);
    if (!path) return;
    // Optimistic previews already hold a local object/data URL — use it directly
    // (the backend relative path is fetched with the Bearer; a blob: is not).
    if (path.startsWith('blob:') || path.startsWith('data:')) {
      setUrl(path);
      return;
    }
    setIsLoading(true);
    apiFetchBlob(path)
      .then((blob) => {
        if (cancelled) return;
        const made = URL.createObjectURL(blob);
        objectUrl.current = made;
        setUrl(made);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  useEffect(
    () => () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    },
    [],
  );

  return { url, isLoading, error };
}
