import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type {
  WorkflowNode,
  WorkflowOmnichannelTestSource,
  WorkflowRunRequest,
} from '@/types/workflows';
import { RunDialog } from './run-dialog';

const SOURCES: WorkflowOmnichannelTestSource[] = [
  {
    channelId: 'chn-support',
    channelName: 'Support sandbox',
    contactId: 'cnt-alice',
    contactName: 'Alice Tan',
    contactPhone: '+60 12-300 4000',
  },
  {
    channelId: 'chn-support',
    channelName: 'Support sandbox',
    contactId: 'cnt-amy',
    contactName: 'Amy Lee',
    contactPhone: '+60 12-500 6000',
  },
  {
    channelId: 'chn-sales',
    channelName: 'Sales sandbox',
    contactId: 'cnt-bob',
    contactName: 'Bob Lim',
    contactPhone: '+60 17-700 8000',
  },
];

function trigger(
  type: string,
  config: WorkflowNode['config'] = {},
): WorkflowNode {
  return {
    id: 'trigger-1',
    kind: 'trigger',
    type,
    config,
    position: { x: 0, y: 0 },
  };
}

function renderDialog(
  node: WorkflowNode,
  onRun = vi.fn<(request: WorkflowRunRequest) => void>(),
  testSources: WorkflowOmnichannelTestSource[] = SOURCES,
  sideEffects = { callsAi: false, sendsMessage: false },
) {
  render(
    <RunDialog
      open
      onOpenChange={vi.fn()}
      trigger={node}
      testSources={testSources}
      testOptionsLoading={false}
      testOptionsError={false}
      sideEffects={sideEffects}
      busy={false}
      onRun={onRun}
    />,
  );
  return onRun;
}

describe('RunDialog', () => {
  it('preserves manual-trigger inputs and submits the existing request shape', async () => {
    const user = userEvent.setup();
    const onRun = renderDialog(
      trigger('manual', {
        inputs: [{ key: 'email', label: 'Email', type: 'string' }],
      }),
    );

    expect(
      screen.getByRole('heading', { name: 'Run workflow' }),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText('Email'), 'alice@example.com');
    await user.click(screen.getByTestId('run-dialog-submit'));

    expect(onRun).toHaveBeenCalledWith({
      inputs: { email: 'alice@example.com' },
    });
  });

  it('preselects a configured channel and offers only its paired contacts', async () => {
    const user = userEvent.setup();
    renderDialog(
      trigger('omnichannel.message_received', { channelId: 'chn-support' }),
    );

    expect(
      screen.getByRole('heading', { name: 'Test workflow' }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Channel')).toHaveTextContent(
      'Support sandbox',
    );
    await user.click(screen.getByLabelText('Contact'));
    expect(screen.getByText('Alice Tan · +60 12-300 4000')).toBeInTheDocument();
    expect(screen.getByText('Amy Lee · +60 12-500 6000')).toBeInTheDocument();
    expect(
      screen.queryByText('Bob Lim · +60 17-700 8000'),
    ).not.toBeInTheDocument();
  });

  it('does not auto-select all-channel test data and submits the typed test trigger', async () => {
    const user = userEvent.setup();
    const onRun = renderDialog(
      trigger('omnichannel.message_received', { channelId: null }),
    );

    expect(screen.getByLabelText('Channel')).toHaveTextContent(
      'Choose a channel',
    );
    expect(screen.getByLabelText('Contact')).toBeDisabled();
    expect(screen.getByTestId('run-dialog-submit')).toBeDisabled();

    await user.click(screen.getByLabelText('Channel'));
    await user.click(screen.getByText('Sales sandbox'));
    await user.click(screen.getByLabelText('Contact'));
    await user.click(screen.getByText('Bob Lim · +60 17-700 8000'));
    await user.type(
      screen.getByLabelText('Message'),
      '  Please move my booking  ',
    );
    await user.click(screen.getByTestId('run-dialog-submit'));

    expect(onRun).toHaveBeenCalledWith({
      inputs: {},
      isTest: true,
      testTrigger: {
        type: 'omnichannel.message_received',
        channelId: 'chn-sales',
        contactId: 'cnt-bob',
        messageText: 'Please move my booking',
      },
    });
  });

  it('clears a selected contact when the channel changes', async () => {
    const user = userEvent.setup();
    renderDialog(trigger('omnichannel.message_received', { channelId: null }));

    await user.click(screen.getByLabelText('Channel'));
    await user.click(screen.getByText('Support sandbox'));
    await user.click(screen.getByLabelText('Contact'));
    await user.click(screen.getByText('Alice Tan · +60 12-300 4000'));
    expect(screen.getByLabelText('Contact')).toHaveTextContent('Alice Tan');

    await user.click(screen.getByLabelText('Channel'));
    await user.click(screen.getByText('Sales sandbox'));
    expect(screen.getByLabelText('Contact')).toHaveTextContent(
      'Choose a contact',
    );
    expect(screen.getByTestId('run-dialog-submit')).toBeDisabled();
  });

  it('blocks the run when no safe source exists and warns about real side effects', () => {
    renderDialog(
      trigger('omnichannel.message_received', { channelId: null }),
      vi.fn(),
      [],
      { callsAi: true, sendsMessage: true },
    );

    expect(screen.getByTestId('test-source-warning')).toHaveTextContent(
      'No sandbox contacts are available for this trigger.',
    );
    expect(screen.getByTestId('test-side-effects-warning')).toHaveTextContent(
      'Testing will call the configured AI model and send a message through the selected sandbox channel.',
    );
    expect(screen.getByTestId('run-dialog-submit')).toBeDisabled();
  });

  it('clears ephemeral values when the dialog closes and reopens', async () => {
    const user = userEvent.setup();
    const node = trigger('omnichannel.message_received', { channelId: null });
    const onRun = vi.fn<(request: WorkflowRunRequest) => void>();
    const props = {
      onOpenChange: vi.fn(),
      trigger: node,
      testSources: SOURCES,
      testOptionsLoading: false,
      testOptionsError: false,
      sideEffects: { callsAi: false, sendsMessage: false },
      busy: false,
      onRun,
    };
    const { rerender } = render(<RunDialog {...props} open />);

    await user.click(screen.getByLabelText('Channel'));
    await user.click(screen.getByText('Sales sandbox'));
    await user.click(screen.getByLabelText('Contact'));
    await user.click(screen.getByText('Bob Lim · +60 17-700 8000'));
    await user.type(screen.getByLabelText('Message'), 'Temporary message');

    rerender(<RunDialog {...props} open={false} />);
    rerender(<RunDialog {...props} open />);

    expect(screen.getByLabelText('Channel')).toHaveTextContent(
      'Choose a channel',
    );
    expect(screen.getByLabelText('Contact')).toBeDisabled();
    expect(screen.getByLabelText('Message')).toHaveValue('');
  });

  it('requires confirmation for a mutating Redis run even with no inputs', async () => {
    const user = userEvent.setup();
    const onRun = renderDialog(trigger('manual'), vi.fn(), SOURCES, {
      callsAi: false,
      sendsMessage: false,
      mutatesRedis: true,
    });

    await user.click(screen.getByTestId('run-dialog-submit'));
    expect(onRun).not.toHaveBeenCalled();
    expect(screen.getByRole('alertdialog')).toHaveTextContent(
      'This run will change Redis data.',
    );
    await user.click(screen.getByTestId('redis-confirm-run'));
    expect(onRun).toHaveBeenCalledWith({ inputs: {} });
  });

  it('blocks manual Code execution when the runner is unavailable', async () => {
    const user = userEvent.setup();
    const onRun = vi.fn<(request: WorkflowRunRequest) => void>();
    render(
      <RunDialog
        open
        onOpenChange={vi.fn()}
        trigger={trigger('manual')}
        testSources={[]}
        testOptionsLoading={false}
        testOptionsError={false}
        sideEffects={{ callsAi: false, sendsMessage: false, runsCode: true }}
        codeRunnerAvailable={false}
        busy={false}
        onRun={onRun}
      />,
    );

    expect(screen.getByTestId('code-runner-blocked')).toHaveTextContent(
      'Manual execution is blocked.',
    );
    await user.click(screen.getByTestId('run-dialog-submit'));
    expect(onRun).not.toHaveBeenCalled();
  });
});
