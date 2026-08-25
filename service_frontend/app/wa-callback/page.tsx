'use client';

import { useEffect, useState } from 'react';

/**
 * WhatsApp Embedded Signup OAuth callback (self-hosted redirect flow).
 *
 * Meta's OAuth dialog redirects here with `?code=…` after the tenant finishes.
 * This page runs in the popup opened by `launchEmbeddedSignup`: it relays the
 * code back to the opener via postMessage, then closes. No auth needed - the
 * opener does the authenticated exchange. Registered as a Valid OAuth Redirect
 * URI in the Meta app.
 */
export default function WaCallbackPage() {
  const [message, setMessage] = useState('Completing your WhatsApp connection…');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const error = params.get('error_description') || params.get('error');
    const payload = code
      ? { type: 'FX_WA_OAUTH', code }
      : { type: 'FX_WA_OAUTH', error: error || 'Signup cancelled.' };

    if (window.opener) {
      window.opener.postMessage(payload, window.location.origin);
      setMessage('Done - you can close this window.');
      // Give the message a tick to flush before the window disappears.
      window.setTimeout(() => window.close(), 300);
    } else {
      // Full-page fallback (popup was blocked / opened as a redirect): stash the
      // code so the channels page can pick it up, then send the user back.
      if (code) {
        sessionStorage.setItem('fx_wa_code', code);
        window.location.replace('/omnichannel/settings/channels?wa_connected=1');
      } else {
        setMessage(error || 'Signup cancelled. You can close this window.');
      }
    }
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
