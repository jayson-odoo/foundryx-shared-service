/** AC-IVE-18/22/48 - save-view dialog: name required, Shared switch gated. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { InboxViewDialog } from './inbox-view-dialog';

describe('InboxViewDialog', () => {
  it('Save is disabled until a name is entered', () => {
    render(
      <InboxViewDialog open view={null} canShare={false} onOpenChange={vi.fn()} onCreate={vi.fn()} onUpdate={vi.fn()} />,
    );
    expect(screen.getByTestId('inbox-view-submit')).toBeDisabled();
  });

  it('hides the Shared switch entirely without inbox_views.manage (D-A3-11)', () => {
    render(
      <InboxViewDialog open view={null} canShare={false} onOpenChange={vi.fn()} onCreate={vi.fn()} onUpdate={vi.fn()} />,
    );
    expect(screen.queryByTestId('inbox-view-shared')).not.toBeInTheDocument();
  });

  it('shows the Shared switch with inbox_views.manage', () => {
    render(
      <InboxViewDialog open view={null} canShare onOpenChange={vi.fn()} onCreate={vi.fn()} onUpdate={vi.fn()} />,
    );
    expect(screen.getByTestId('inbox-view-shared')).toBeInTheDocument();
  });

  it('submits the typed name via onCreate', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <InboxViewDialog open view={null} canShare={false} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />,
    );
    await user.type(screen.getByTestId('inbox-view-name'), 'Waiting on me');
    await user.click(screen.getByTestId('inbox-view-submit'));
    expect(onCreate).toHaveBeenCalledWith({ name: 'Waiting on me', isShared: false });
  });

  it('rename (editing an existing view) pre-fills its name and isShared', () => {
    render(
      <InboxViewDialog
        open
        canShare
        view={{
          id: 'v1', workspaceId: 'wsp-001', name: 'Hot leads', ownerUserId: 'usr-demo', ownerName: 'Demo User',
          isShared: true, filter: {}, sortOrder: 0, createdAt: '2026-01-01T00:00:00Z',
        }}
        onOpenChange={vi.fn()}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
      />,
    );
    expect(screen.getByTestId('inbox-view-name')).toHaveValue('Hot leads');
    expect(screen.getByTestId('inbox-view-shared')).toBeChecked();
  });
});
