'use client';

import { useEffect, useState } from 'react';
import { useRef } from 'react';
import { Button } from '@/components/ui/button';
import { SearchSelect } from '@/components/platform/search-select';
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
 *
 * A partner Page connect (Messenger + Instagram) answers the callback with a
 * `pagePicker` instead of a redirect: the page lists the Pages the person can
 * manage (only those that would connect something), and the choice or a
 * cancel is posted with the single-use pick token; that answer carries the
 * redirect. A pick that ends the session instead (too many Page ids that
 * were not on the list: `status=failed`) answers a redirect too and is
 * followed the same way; any refusal shows the neutral message.
 */

interface PageOption {
  id: string;
  name: string;
  igUsername?: string | null;
  connected: boolean;
}

interface CallbackAnswer {
  redirect?: string;
  pagePicker?: { pickToken: string; pages: PageOption[] };
}

const FAILED_MESSAGE =
  'We could not complete the connection. You can close this window and try again.';

function pageLabel(p: PageOption): string {
  return p.igUsername ? `${p.name} (Instagram @${p.igUsername})` : p.name;
}

function followRedirect(res: CallbackAnswer | undefined) {
  if (!res || typeof res.redirect !== 'string' || !res.redirect) throw new Error('bad');
  window.location.replace(res.redirect);
}
export default function WaCallbackPage() {
  // Foundryx UIUX: this page stays outside the switch's components (global
  // look only), so only its words follow the switch; the message posted to
  // the opener never changes.
  const fx = Boolean(useFxControls()?.on);
  const [message, setMessage] = useState(fx ? 'Finishing your sign-in.' : 'Completing your sign-in…');
  const partnerLoad = useRef(false);
  const [picker, setPicker] = useState<{ pickToken: string; pages: PageOption[] } | null>(null);
  const [pageId, setPageId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const sendPick = (chosen: string | null) => {
    if (!picker || sending) return;
    setSending(true);
    const body: { pickToken: string; pageId?: string } = { pickToken: picker.pickToken };
    if (chosen) body.pageId = chosen;
    publicFetch<CallbackAnswer>('/api/v1/omnichannel/connect/page-select', {
      method: 'POST',
      body: JSON.stringify(body),
    })
      .then(followRedirect)
      .catch(() => {
        setPicker(null);
        setMessage(FAILED_MESSAGE);
      });
  };

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
      publicFetch<CallbackAnswer>(
        '/api/v1/omnichannel/connect/wa-callback',
        {
          method: 'POST',
          body: JSON.stringify(body),
        },
      )
        .then((res) => {
          const pick = res?.pagePicker;
          if (pick && typeof pick.pickToken === 'string' && Array.isArray(pick.pages)) {
            setPicker(pick);
            return;
          }
          followRedirect(res);
        })
        .catch(() => {
          setMessage(FAILED_MESSAGE);
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

  if (picker) {
    const options = picker.pages
      .filter((p) => !p.connected)
      .map((p) => ({ label: pageLabel(p), value: p.id }));
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <div className="flex w-full max-w-sm flex-col gap-4">
          <h1 className="text-base font-semibold text-foreground">Choose a Facebook Page</h1>
          {options.length ? (
            <SearchSelect
              options={options}
              value={pageId}
              onChange={(v) => setPageId(v)}
              placeholder="Pick a Page"
              searchPlaceholder="Search Pages"
              ariaLabel="Facebook Page"
              disabled={sending}
              className="w-full"
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              Every Page you manage is already connected.
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" onClick={() => sendPick(null)} disabled={sending}>
              Cancel connection
            </Button>
            {options.length ? (
              <Button onClick={() => sendPick(pageId)} disabled={sending || !pageId}>
                Connect Page
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
