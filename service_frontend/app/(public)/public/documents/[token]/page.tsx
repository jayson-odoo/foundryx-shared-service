'use client';

/**
 * Public (anonymous) share page (plan sprint-3/05, Google model). Pre-auth,
 * branded by the public layout (white-label). Renders the SAME mini-Drive
 * (`ShareBrowser`) as the in-app scoped view — card/list, folder nav,
 * click-to-preview, download (+ upload on a public-edit folder). A workspace/
 * restricted link resolves to `sign_in_required`: a logged-in member is routed
 * into the in-app scoped view; everyone else gets a Sign-in CTA. Responsive ≤375px.
 */
import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { getSession } from 'next-auth/react';
import { AlertCircle, Loader2, Lock } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ShareScopedView } from '@/components/platform/document-drive/share-scoped-view';
import { usePublicShare } from '@/hooks/use-public-share';

export default function PublicSharePage() {
  const params = useParams();
  const router = useRouter();
  const token = String(params.token);
  const share = usePublicShare(token);

  // A workspace/restricted link → route a signed-in member into the scoped app
  // view; otherwise the Sign-in CTA below lets them authenticate.
  useEffect(() => {
    if (!share.signInRequired) return;
    let cancelled = false;
    getSession().then((s) => {
      if (!cancelled && s?.accessToken) router.replace(`/documents?shared=${token}`);
    });
    return () => {
      cancelled = true;
    };
  }, [share.signInRequired, token, router]);

  const shell = (body: React.ReactNode) => (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">{body}</div>
  );

  if (share.loading && !share.view) {
    return shell(
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" />
      </div>,
    );
  }

  if (share.notFound || !share.view) {
    return shell(
      <div className="flex flex-col items-center gap-3 py-24 text-center" data-testid="share-notfound">
        <AlertCircle className="size-10 text-muted-foreground" />
        <p className="text-base font-medium">This link isn’t available.</p>
      </div>,
    );
  }

  if (share.view.state === 'closed') {
    return shell(
      <div className="flex flex-col items-center gap-3 py-24 text-center" data-testid="share-closed">
        <Lock className="size-9 text-muted-foreground" />
        <p className="font-heading text-xl font-semibold">{share.view.tenantName ?? 'Shared link'}</p>
        <p className="text-sm text-muted-foreground">{share.view.message ?? 'This link is no longer available.'}</p>
      </div>,
    );
  }

  if (share.view.state === 'sign_in_required') {
    return shell(
      <div className="flex flex-col items-center gap-3 py-24 text-center" data-testid="share-signin">
        <Lock className="size-9 text-muted-foreground" />
        <p className="font-heading text-xl font-semibold">Sign in to access</p>
        <p className="text-sm text-muted-foreground">This link is shared with specific people in {share.view.tenantName ?? 'this workspace'}.</p>
        <Button
          onClick={() =>
            router.push(`/signin?callbackUrl=${encodeURIComponent(`/documents?shared=${token}`)}`)
          }
          data-testid="share-signin-cta"
        >
          Sign in
        </Button>
      </div>,
    );
  }

  if (share.view.state === 'password_required') {
    return shell(<PasswordGate share={share} />);
  }

  return shell(<ShareScopedView share={share} contextLabel="Shared" />);
}

function PasswordGate({ share }: { share: ReturnType<typeof usePublicShare> }) {
  const [pw, setPw] = useState('');
  return (
    <div className="mx-auto flex w-full max-w-sm flex-col items-center gap-4 py-20 text-center">
      <Lock className="size-9 text-muted-foreground" />
      <p className="font-heading text-lg font-semibold">This link is password protected</p>
      <form
        className="flex w-full flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void share.unlock(pw);
        }}
      >
        <Input
          type="password"
          autoFocus
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          placeholder="Password"
          aria-label="Password"
          data-testid="share-password"
        />
        {share.passwordError && (
          <Alert variant="destructive" appearance="light">
            <AlertIcon><AlertCircle /></AlertIcon>
            <AlertTitle>{share.passwordError}</AlertTitle>
          </Alert>
        )}
        <Button type="submit" disabled={!pw || share.unlocking} data-testid="share-unlock">
          {share.unlocking ? <Loader2 className="size-4 animate-spin" /> : null}
          Unlock
        </Button>
      </form>
    </div>
  );
}
