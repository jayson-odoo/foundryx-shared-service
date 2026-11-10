import { AlertCircle, Loader2 } from 'lucide-react';

export function PortalLoading() {
  return (
    <div className="flex grow items-center justify-center py-24 text-muted-foreground" data-testid="portal-loading">
      <Loader2 className="size-6 animate-spin" aria-label="Loading" />
    </div>
  );
}

export function PortalMessage({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-24 text-center" data-testid="portal-message">
      <AlertCircle className="size-10 text-muted-foreground" aria-hidden />
      <p className="text-base font-medium">{text}</p>
    </div>
  );
}
