'use client';

/**
 * The lost-connection system banner (gap audit "connection lost", owner
 * choice: after 5 s). A live feed passes whether it is connected; after 5 s
 * without it the system banner says "Reconnecting. New messages may be
 * late." in the `warn` set with no close, and it leaves by itself once the
 * feed is back. Short drops that fix themselves never show it.
 *
 * Only while the Foundryx UIUX switch is on; off, it does nothing. Returns
 * whether the banner is showing (a feed may refetch what it missed when it
 * goes away).
 */
import { useEffect, useMemo, useState } from 'react';
import { useFx } from '@/hooks/use-fx';
import { useSystemBanner, type FxBanner } from './banner-store';

export const FX_CONNECTION_BANNER_DELAY_MS = 5000;
export const FX_CONNECTION_BANNER_TEXT =
  'Reconnecting. New messages may be late.';

export function useConnectionBanner(isConnected: boolean): boolean {
  const fx = useFx();
  const [showing, setShowing] = useState(false);

  useEffect(() => {
    if (!fx || isConnected) {
      setShowing(false);
      return;
    }
    const t = setTimeout(
      () => setShowing(true),
      FX_CONNECTION_BANNER_DELAY_MS,
    );
    return () => clearTimeout(t);
  }, [fx, isConnected]);

  const banner = useMemo<FxBanner | null>(
    () =>
      showing
        ? {
            id: 'connection',
            tone: 'warn',
            text: FX_CONNECTION_BANNER_TEXT,
          }
        : null,
    [showing],
  );
  useSystemBanner(banner);
  return showing;
}
