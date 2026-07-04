import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { StoreModule } from '@/types/app-store';
import { ModuleCard } from './module-card';

const base: StoreModule = {
  name: 'omnichannel',
  title: 'Omnichannel',
  description: 'WhatsApp messaging for events.',
  icon: 'message-square',
  version: '0.1.0',
  status: 'ACTIVE',
  installedVersion: '0.1.0',
  updateAvailable: false,
  installedAt: '2026-05-01T00:00:00Z',
};

const noop = async () => true;
const allowAll = () => true;
const denyAll = () => false;

describe('ModuleCard', () => {
  it('not installed → Install button + "Not installed" badge', () => {
    render(
      <ModuleCard
        module={{ ...base, status: null, installedVersion: null, installedAt: null }}
        canAct={allowAll}
        busy={false}
        onAction={noop}
        onUninstall={noop}
      />,
    );
    expect(screen.getByText('Not installed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Install' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Uninstall' })).not.toBeInTheDocument();
  });

  it('active → Deactivate + Uninstall, no Install', () => {
    render(
      <ModuleCard module={base} canAct={allowAll} busy={false} onAction={noop} onUninstall={noop} />,
    );
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Deactivate' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Uninstall' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Install' })).not.toBeInTheDocument();
  });

  it('update available → Update button + version transition text', () => {
    render(
      <ModuleCard
        module={{ ...base, version: '1.1.0', installedVersion: '1.0.0', updateAvailable: true }}
        canAct={allowAll}
        busy={false}
        onAction={noop}
        onUninstall={noop}
      />,
    );
    expect(screen.getByText('Update available')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument();
    expect(screen.getByText('v1.0.0 → v1.1.0')).toBeInTheDocument();
  });

  it('inactive → Reactivate, badge Inactive', () => {
    render(
      <ModuleCard
        module={{ ...base, status: 'INACTIVE' }}
        canAct={allowAll}
        busy={false}
        onAction={noop}
        onUninstall={noop}
      />,
    );
    expect(screen.getByText('Inactive')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reactivate' })).toBeInTheDocument();
  });

  it('permission-gated: no buttons without app_store.* keys', () => {
    render(
      <ModuleCard module={base} canAct={denyAll} busy={false} onAction={noop} onUninstall={noop} />,
    );
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('deactivate routes through a confirm dialog', async () => {
    const onAction = vi.fn().mockResolvedValue(true);
    render(
      <ModuleCard module={base} canAct={allowAll} busy={false} onAction={onAction} onUninstall={noop} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Deactivate' }));
    expect(await screen.findByText('Deactivate Omnichannel?')).toBeInTheDocument();
    expect(onAction).not.toHaveBeenCalled(); // nothing until confirmed
    fireEvent.click(screen.getAllByRole('button', { name: 'Deactivate' }).at(-1)!);
    await waitFor(() => expect(onAction).toHaveBeenCalledWith('omnichannel', 'deactivate'));
  });

  it('uninstall confirm stays disabled until the exact module name is typed', async () => {
    const onUninstall = vi.fn().mockResolvedValue(true);
    render(
      <ModuleCard
        module={base}
        canAct={allowAll}
        busy={false}
        onAction={noop}
        onUninstall={onUninstall}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Uninstall' }));
    expect(await screen.findByText('Uninstall Omnichannel?')).toBeInTheDocument();

    const input = screen.getByLabelText('Confirm module name');
    const confirm = screen.getAllByRole('button', { name: 'Uninstall' }).at(-1)!;
    expect(confirm).toBeDisabled();

    fireEvent.change(input, { target: { value: 'omni' } });
    expect(confirm).toBeDisabled();

    fireEvent.change(input, { target: { value: 'omnichannel' } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(onUninstall).toHaveBeenCalledWith('omnichannel', 'omnichannel'));
  });
});
