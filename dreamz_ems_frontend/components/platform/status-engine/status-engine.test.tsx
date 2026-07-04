/**
 * Status-engine component tests (sprint-2/01 §TDD — frontend):
 * canvas renders nodes/edges · terminal node has no outgoing handle ·
 * drawer validation · edge-create writes a transition · permission gating
 * hides manage controls.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// The transition drawer reads the acting user for template previews.
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Demo User' } }, status: 'authenticated' }),
}));
import { FlowCanvas } from '@/components/platform/flow-canvas';
import type { StatusNodeData } from '@/types/status-engine';
import { StatusDrawer } from './status-drawer';
import { StatusFlowNode } from './status-node';
import { StatusTable } from './status-table';
import { TransitionDrawer } from './transition-drawer';

// ---- jsdom shims @xyflow/react needs beyond the global setup ----
class DOMMatrixReadOnlyStub {
  m22 = 1;
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).DOMMatrixReadOnly =
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).DOMMatrixReadOnly ?? DOMMatrixReadOnlyStub;
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
  configurable: true,
  get() {
    return 600;
  },
});
Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
  configurable: true,
  get() {
    return 800;
  },
});
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(SVGElement.prototype as any).getBBox = () => ({ x: 0, y: 0, width: 0, height: 0 });

const NODE_TYPES = { status: StatusFlowNode };

function makeStatus(overrides: Partial<StatusNodeData>): StatusNodeData {
  return {
    id: 'status-1',
    entityType: 'ticket',
    key: 'pending',
    label: 'Pending',
    color: 'blue',
    sortOrder: 1,
    isInitial: false,
    isTerminal: false,
    isActive: true,
    blocksAccess: false,
    isArchived: false,
    isDefault: false,
    positionX: 0,
    positionY: 0,
    isSystem: false,
    recordCount: 0,
    ...overrides,
  };
}

const pending = makeStatus({ id: 's-pending', key: 'pending', label: 'Pending', isInitial: true });
const approved = makeStatus({
  id: 's-approved',
  key: 'approved',
  label: 'Approved',
  isTerminal: true,
});

function canvasNodes() {
  return [
    { id: pending.id, type: 'status', position: { x: 0, y: 0 }, data: { status: pending } },
    { id: approved.id, type: 'status', position: { x: 300, y: 0 }, data: { status: approved } },
  ];
}

describe('FlowCanvas + StatusFlowNode', () => {
  it('renders status nodes from graph data', async () => {
    // Edge SVG paths need real layout measurement (inert ResizeObserver in
    // jsdom) — edge rendering is asserted by the Playwright E2E instead.
    const { container } = render(
      <FlowCanvas
        nodes={canvasNodes()}
        edges={[{ id: 'e-1', source: pending.id, target: approved.id, label: 'Approve' }]}
        nodeTypes={NODE_TYPES}
      />,
    );
    expect(await screen.findByTestId('status-node-pending')).toBeInTheDocument();
    expect(screen.getByTestId('status-node-approved')).toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(container.querySelector('.react-flow')).not.toBeNull();
  });

  it('terminal statuses render no outgoing (source) handle', async () => {
    render(<FlowCanvas nodes={canvasNodes()} edges={[]} nodeTypes={NODE_TYPES} />);
    const pendingNode = await screen.findByTestId('status-node-pending');
    const approvedNode = screen.getByTestId('status-node-approved');
    expect(pendingNode.querySelector('[data-testid="source-handle"]')).not.toBeNull();
    expect(approvedNode.querySelector('[data-testid="source-handle"]')).toBeNull();
    // Trait badges surface the machine semantics.
    expect(approvedNode).toHaveTextContent('Terminal');
    expect(pendingNode).toHaveTextContent('Initial');
  });
});

describe('StatusDrawer', () => {
  const baseProps = {
    open: true,
    onOpenChange: vi.fn(),
    statuses: [pending, approved],
    onCreate: vi.fn().mockResolvedValue(true),
    onUpdate: vi.fn().mockResolvedValue(true),
    onDelete: vi.fn().mockResolvedValue(true),
    onSetActive: vi.fn().mockResolvedValue(true),
    onMigrate: vi.fn().mockResolvedValue(true),
  };

  it('blocks create when the label is empty', async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(
      <StatusDrawer {...baseProps} status={null} canManage onCreate={onCreate} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(await screen.findByText('Label is required.')).toBeInTheDocument();
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('creates a status with label, color and flags', async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(
      <StatusDrawer {...baseProps} status={null} canManage onCreate={onCreate} />,
    );
    fireEvent.change(screen.getByLabelText(/Label/), { target: { value: 'On Hold' } });
    fireEvent.click(screen.getByRole('switch', { name: 'Blocks access' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    // The picker works in hex (default = the gray token swatch).
    expect(onCreate).toHaveBeenCalledWith('On Hold', '#6B7280', expect.objectContaining({
      blocksAccess: true,
    }));
  });

  it('locks behavior flags on system statuses and hides delete', () => {
    render(
      <StatusDrawer
        {...baseProps}
        status={makeStatus({ id: 's-system', label: 'Active', isSystem: true })}
        canManage
      />,
    );
    expect(screen.getByRole('switch', { name: 'Blocks access' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('hides ALL manage controls without statuses.manage', () => {
    render(<StatusDrawer {...baseProps} status={pending} canManage={false} />);
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Label/)).toBeDisabled();
  });
});

describe('TransitionDrawer', () => {
  const baseProps = {
    open: true,
    onOpenChange: vi.fn(),
    statuses: [pending, approved],
    roleOptions: [{ value: 'role-1', label: 'Admin' }],
    userOptions: [{ value: 'user-1', label: 'Demo User' }],
    templateOptions: [],
    facts: [],
    onCreate: vi.fn().mockResolvedValue(true),
    onUpdate: vi.fn().mockResolvedValue(true),
    onDelete: vi.fn().mockResolvedValue(true),
  };

  it('edge-create writes the transition with the typed label', async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(
      <TransitionDrawer
        {...baseProps}
        transition={null}
        pending={{ fromStatusId: pending.id, toStatusId: approved.id }}
        canManage
        onCreate={onCreate}
      />,
    );
    // The pending edge names both endpoints.
    expect(screen.getByText(/Pending → Approved/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Action label/), { target: { value: 'Approve' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create transition' }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    expect(onCreate).toHaveBeenCalledWith(
      { fromStatusId: pending.id, toStatusId: approved.id },
      'Approve',
      [],
      [],
      null,
      'manual',
    );
  });

  it('validates label and notification subject/body before saving', async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(
      <TransitionDrawer
        {...baseProps}
        transition={null}
        pending={{ fromStatusId: pending.id, toStatusId: approved.id }}
        canManage
        onCreate={onCreate}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Create transition' }));
    expect(await screen.findByText('Label is required.')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Action label/), { target: { value: 'Approve' } });
    fireEvent.click(screen.getByRole('button', { name: /Add notification/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Create transition' }));
    expect(
      await screen.findByText('Notification subject and body are required.'),
    ).toBeInTheDocument();
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('hides manage footer without statuses.manage', () => {
    render(
      <TransitionDrawer
        {...baseProps}
        transition={{
          id: 't-1',
          entityType: 'ticket',
          fromStatusId: pending.id,
          toStatusId: approved.id,
          label: 'Approve',
          sortOrder: 1,
          roles: [],
          notifications: [],
        }}
        pending={null}
        canManage={false}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Delete transition' }),
    ).not.toBeInTheDocument();
    // Read-only view must not allow editing the role gate either.
    expect(screen.getAllByRole('combobox')[0]).toBeDisabled();
  });

  it('an automatic edge hides the role gate (system-fired)', () => {
    render(
      <TransitionDrawer
        {...baseProps}
        transition={{
          id: 't-auto',
          entityType: 'ticket',
          fromStatusId: pending.id,
          toStatusId: approved.id,
          label: 'Auto-approve',
          sortOrder: 1,
          roles: [],
          notifications: [],
          conditionsJson: null,
          triggerMode: 'auto',
        }}
        pending={null}
        canManage
      />,
    );
    // Trigger control present; roles gate hidden for auto edges.
    expect(screen.getByText('Trigger')).toBeInTheDocument();
    expect(screen.queryByText('Who can perform it')).not.toBeInTheDocument();
    expect(screen.getByText('Conditions')).toBeInTheDocument();
  });

  it('blocks saving an automatic edge with no conditions', async () => {
    const onUpdate = vi.fn().mockResolvedValue(true);
    render(
      <TransitionDrawer
        {...baseProps}
        transition={{
          id: 't-auto2',
          entityType: 'ticket',
          fromStatusId: pending.id,
          toStatusId: approved.id,
          label: 'Auto-approve',
          sortOrder: 1,
          roles: [],
          notifications: [],
          conditionsJson: null,
          triggerMode: 'auto',
        }}
        pending={null}
        canManage
        onUpdate={onUpdate}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(
      await screen.findByText('An automatic transition needs at least one condition.'),
    ).toBeInTheDocument();
    expect(onUpdate).not.toHaveBeenCalled();
  });
});

describe('StatusTable', () => {
  it('lists statuses and hides reorder handles without manage', () => {
    render(
      <StatusTable
        statuses={[pending, approved]}
        canManage={false}
        entityLabel="Ticket"
        onReorder={vi.fn().mockResolvedValue(true)}
        onRowClick={vi.fn()}
      />,
    );
    expect(screen.getByTestId('status-row-pending')).toBeInTheDocument();
    expect(screen.getByTestId('status-row-approved')).toBeInTheDocument();
    expect(screen.queryByLabelText(/Reorder/)).not.toBeInTheDocument();
  });

  it('shows reorder handles with manage', () => {
    render(
      <StatusTable
        statuses={[pending, approved]}
        canManage
        entityLabel="Ticket"
        onReorder={vi.fn().mockResolvedValue(true)}
        onRowClick={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('Reorder Pending')).toBeInTheDocument();
  });
});
