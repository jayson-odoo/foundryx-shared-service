'use client';

import Link from 'next/link';
import { ShieldAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';

export interface NoPermissionProps {
  /** What the user was trying to access (for a friendly, specific message). */
  title?: string;
  description?: string;
}

/**
 * Friendly "you don't have access" page — shown instead of a raw 403/technical
 * error when a user lacks the permission for a route (plan 03 §3.4).
 */
export function NoPermission({
  title = 'You don’t have access to this page',
  description = 'Your role doesn’t include permission for this area. If you think this is a mistake, ask an administrator to grant you access.',
}: NoPermissionProps) {
  return (
    <Container width="fluid">
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
        <span className="flex size-16 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <ShieldAlert className="size-8" />
        </span>
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold font-heading">{title}</h1>
          <p className="max-w-md text-sm text-muted-foreground">{description}</p>
        </div>
        <Button variant="primary" size="sm" asChild>
          <Link href="/">Back to dashboard</Link>
        </Button>
      </div>
    </Container>
  );
}
