'use client';

import { useEffect } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';

/**
 * AC-DLA-50 - a render error inside any `app/(protected)` route is caught
 * HERE, one level below `app/(protected)/layout.tsx` (Next.js error
 * boundaries wrap a segment's own children, never the enclosing layout) -
 * so the sidebar/header/crumb chrome stays mounted and the user is never
 * dropped to a blank page. Reset re-renders the segment WITHOUT a full
 * reload; a genuinely broken page throws again and this boundary just
 * catches it a second time.
 */
export default function ProtectedError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <Container width="fluid">
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
        <span className="flex size-16 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <AlertTriangle className="size-8" />
        </span>
        <div className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold font-heading">Something went wrong</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            This page ran into a problem. You can try again, or head back to the dashboard.
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={() => reset()}>
          Reset
        </Button>
      </div>
    </Container>
  );
}
