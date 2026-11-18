/**
 * Switch-off parity: PageHeader (see parity-utils.ts).
 */
import type { ReactElement } from 'react';
import { act, render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/platform/page-header';
import { parityHtml } from './parity-utils';

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

const { usePathname, useRouter } = vi.hoisted(() => ({
  usePathname: vi.fn(() => '/user-management/users'),
  useRouter: vi.fn(() => ({ push: vi.fn(), back: vi.fn(), prefetch: vi.fn() })),
}));
vi.mock('next/navigation', () => ({ usePathname, useRouter }));

beforeEach(() => {
  usePathname.mockReturnValue('/user-management/users');
});

/** Renders and lets the async terminology lookup settle before the snapshot. */
async function settle(ui: ReactElement): Promise<HTMLElement> {
  let container!: HTMLElement;
  await act(async () => {
    ({ container } = render(ui));
  });
  return container;
}

describe('parity (switch off): PageHeader', () => {
  it('menu-derived title and crumbs with an action', async () => {
    const container = await settle(
      <PageHeader actions={<Button>Add user</Button>} />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('explicit title, eyebrow, crumbs and description', async () => {
    const container = await settle(
      <PageHeader
        title="Admin User"
        eyebrow="User"
        crumbs={[
          { label: 'Users', href: '/user-management/users' },
          { label: 'Admin User' },
        ]}
        description="Created 14 Nov 2026"
      />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
