'use client';

import { useEffect, useState } from 'react';
import { useRef } from 'react';
import { publicFetch } from '@/lib/api-client';
import { isPopupOAuthState } from '@/lib/embedded-signup';
import { useFxControls } from '@/hooks/use-fx';

/**
 * WhatsApp Embedded Signup OAuth callback (self-hosted redirect flow).
 *
 * Meta's OAuth dialog redirects here with `?code=…` after the tenant finishes.
 * This page runs in the popup opened by `launchEmbeddedSignup`: it relays the
 * code back to the opener via postMessage, then closes. No auth needed - the
 * opener does the authenticated exchange. Registered as a Valid OAuth Redirect
 * URI in the Meta app.
 *
 * Two flows come back here with a `?state=...`, told apart by its shape:
 * - The ONE OAuth popup (`launchOAuthPopup`: WhatsApp Embedded Signup, Lead
 *   Capture's Facebook and Google sign-in) sends its own random state
 *   (`isPopupOAuthState`). It is relayed to the opener with the code, and the
 *   opener takes only the answer carrying its own state (login CSRF).
 * - A partner connect session (hosted sign-up for a client app) carries the
 *   server-issued state: that branch strips the query, hands the code to the
 *   backend and follows the stored return URL.
 * Without `state` the popup relay runs as it always did.
 */
export default function WaCallbackPage() {
  // Foundryx UIUX: this page stays outside the switch's components (global
  // look only), so only its words follow the switch; the message posted to
  // the opener never changes.
  const fx = Boolean(useFxControls()?.on);
  const [message, setMessage] = useState(fx ? 'Finishing your sign-in.' : 'Completing your sign-in…');
  const partnerLoad = useRef(false);

  useEffect(() => {
    if (partnerLoad.current) return;
    const params = new URLSearchParams(window.location.search);

    // The ONE OAuth popup's own state: relayed to the opener below, never
    // sent to the partner connect endpoint.
    const popupState = isPopupOAuthState(params.get('state'))
      ? params.get('state')
      : null;

    // Partner connect session: the single-use `state` is the credential.
    if (params.has('state') && !popupState) {
      partnerLoad.current = true;
      const state = params.get('state');
      const partnerCode = params.get('code');
      const partnerError =
        params.get('error_description') || params.get('error');
      // Drop the code from the address bar and history before anything else.
      window.history.replaceState(null, '', window.location.pathname);
      const body: { state: string | null; code?: string; error?: string } = {
        state,
      };
      if (partnerCode) body.code = partnerCode;
      if (partnerError) body.error = partnerError.slice(0, 512);
      publicFetch<{ redirect: string }>(
        '/api/v1/omnichannel/connect/wa-callback',
        {
          method: 'POST',
          body: JSON.stringify(body),
        },
      )
        .then((res) => {
          if (!res || typeof res.redirect !== 'string' || !res.redirect)
            throw new Error('bad');
          window.location.replace(res.redirect);
        })
        .catch(() => {
          setMessage(
            'We could not complete the connection. You can close this window and try again.',
          );
        });
      return;
    }

    const code = params.get('code');
    const error = params.get('error_description') || params.get('error');
    // The popup's state rides along so the opener can match the answer to its
    // own dialog; a callback without one posts the same message as before.
    const relayState = popupState ? { state: popupState } : {};
    const payload = code
      ? { type: 'FX_WA_OAUTH', code, ...relayState }
      : { type: 'FX_WA_OAUTH', error: error || 'Signup cancelled.', ...relayState };

    if (window.opener) {
      window.opener.postMessage(payload, window.location.origin);
      setMessage(fx ? 'Done. You can close this window.' : 'Done - you can close this window.');
      // Give the message a tick to flush before the window disappears.
      window.setTimeout(() => window.close(), 300);
    } else {
      // Full-page fallback (popup was blocked / opened as a redirect): stash the
      // code so the channels page can pick it up, then send the user back.
      if (code) {
        sessionStorage.setItem('fx_wa_code', code);
        window.location.replace('/omnichannel/settings/channels?wa_connected=1');
      } else {
        setMessage(
          fx
            ? error
              ? `${error} You can close this window.`
              : 'Connection cancelled. You can close this window.'
            : error || 'Signup cancelled. You can close this window.',
        );
      }
    }
    // Runs once, when the window opens; the switch cannot change meanwhile.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
