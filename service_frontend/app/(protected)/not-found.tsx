import Link from 'next/link';
import { SearchX } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';

/**
 * AC-DLA-50 - an unknown record id (or any route Next.js can't match)
 * inside `app/(protected)` renders THIS, one level below `layout.tsx`, so
 * the sidebar/header/crumb chrome stays mounted (same reasoning as
 * `error.tsx` alongside it).
 */
export default function ProtectedNotFound() {
  return (
    <Container width="fluid">
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
        <span className="flex size-16 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <SearchX className="size-8" />
        </span>
        <div className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold font-heading">Not found</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            This record or page doesn’t exist, or you no longer have access to it.
          </p>
        </div>
        <Button variant="primary" size="sm" asChild>
          <Link href="/">Back to dashboard</Link>
        </Button>
      </div>
    </Container>
  );
}
