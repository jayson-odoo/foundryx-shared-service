/**
 * T3 fix round 1 finding 11 - `DrawerContent` gets the same
 * `hasDialogTitleInChildren` sr-only fallback `DialogContent` has
 * (dialog.tsx): a Radix `Content` with no `Title` descendant is an
 * accessibility gap this repo's own nav/mega-menu drawers (header.tsx)
 * shipped with. A caller that DOES render its own `DrawerTitle` keeps it -
 * the fallback never displaces a real heading.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Drawer, DrawerContent, DrawerTitle } from './drawer';

describe('DrawerContent sr-only title fallback (T3 fix round 1 finding 11)', () => {
  it('renders an sr-only fallback title when no DrawerTitle is provided', () => {
    render(
      <Drawer open>
        <DrawerContent>
          <p>Body content</p>
        </DrawerContent>
      </Drawer>,
    );

    const heading = screen.getByText('Panel');
    expect(heading).toHaveAttribute('data-slot', 'drawer-title');
    expect(heading).toHaveClass('sr-only');
  });

  it('does not add a second title when the caller renders its own DrawerTitle', () => {
    render(
      <Drawer open>
        <DrawerContent>
          <DrawerTitle>Navigation</DrawerTitle>
          <p>Body content</p>
        </DrawerContent>
      </Drawer>,
    );

    const titles = screen.getAllByText('Navigation');
    expect(titles).toHaveLength(1);
  });
});
