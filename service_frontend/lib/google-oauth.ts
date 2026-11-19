/**
 * Google sign-in for the Lead Capture wizard (plan 68). Google's OAuth 2.0
 * web server flow (https://developers.google.com/identity/protocols/oauth2/web-server):
 * the code comes back through the ONE OAuth popup + `/wa-callback` relay with
 * the same `state` check as Meta, and the backend exchanges it.
 */
import { launchOAuthPopup, type MetaOAuthResult } from './embedded-signup';

export const GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth';

export interface GoogleOAuthOptions {
  clientId: string;
  scopes: string[];
  windowName?: string;
}

/** The dialog URL: code flow, offline access + consent so a refresh token is issued. */
export function googleDialogUrl(opts: GoogleOAuthOptions, redirectUri: string, state: string): string {
  const params = new URLSearchParams({
    client_id: opts.clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: opts.scopes.join(' '),
    access_type: 'offline',
    prompt: 'consent',
    include_granted_scopes: 'true',
    state,
  });
  return `${GOOGLE_AUTH_URL}?${params.toString()}`;
}

export function launchGoogleOAuth(opts: GoogleOAuthOptions): Promise<MetaOAuthResult> {
  return launchOAuthPopup((redirectUri, state) => googleDialogUrl(opts, redirectUri, state), {
    windowName: opts.windowName ?? 'fx_google_oauth',
  });
}
