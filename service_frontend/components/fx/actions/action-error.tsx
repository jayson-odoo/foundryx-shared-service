'use client';

/**
 * An action's error sits next to the action (playbook 0.71.0 "Fields"): when
 * a click cannot go ahead, the reason appears right under that button in the
 * "why" style, never as a toast, says what to do, pulses the place to fix it
 * when that is elsewhere on the page, and stays until the next click or
 * change. Toasts stay for things that did happen.
 *
 *   const why = useFxActionError();
 *   <div className="relative">
 *     <Button onClick={() => why.show('Get the signature first.', 'signature')} />
 *     <FxActionError message={why.message} />
 *   </div>
 */
import { useCallback, useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { pulseFxTarget } from './pulse';

export function useFxActionError(): {
  message: string | null;
  show: (message: string, pulseTarget?: string) => void;
  clear: () => void;
} {
  const [message, setMessage] = useState<string | null>(null);

  const clear = useCallback(() => setMessage(null), []);
  const show = useCallback((next: string, pulseTarget?: string) => {
    setMessage(next);
    if (pulseTarget) pulseFxTarget(pulseTarget);
  }, []);

  // The next click or change anywhere clears it. Listening starts on the
  // frame after it shows, so the click that raised it does not clear it.
  useEffect(() => {
    if (!message) return;
    let armed = false;
    const arm = setTimeout(() => {
      armed = true;
    }, 0);
    const off = () => {
      if (armed) setMessage(null);
    };
    document.addEventListener('pointerdown', off, true);
    document.addEventListener('input', off, true);
    return () => {
      clearTimeout(arm);
      document.removeEventListener('pointerdown', off, true);
      document.removeEventListener('input', off, true);
    };
  }, [message]);

  return { message, show, clear };
}

/** The "why" under the button. Place it in the button's positioned wrapper;
 *  it takes no layout space on wider screens, its own line on phones. */
export function FxActionError({
  message,
  className,
}: {
  message: string | null;
  className?: string;
}) {
  if (!message) return null;
  return (
    <p
      role="alert"
      data-fx-why=""
      className={cn(
        'absolute end-0 top-full mt-1 w-max max-w-64 text-end text-sm font-semibold text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-surface))] max-sm:static max-sm:max-w-56',
        className,
      )}
    >
      {message}
    </p>
  );
}
