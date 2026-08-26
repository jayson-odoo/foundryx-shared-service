import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { WebhookEndpointDialog } from './webhook-endpoint-dialog';

const create = vi.fn();
const update = vi.fn();

vi.mock('@/services/whatsapp-webhook-service', () => ({
  whatsappWebhookService: {
    create: (...a: unknown[]) => create(...a),
    update: (...a: unknown[]) => update(...a),
    rotate: vi.fn(),
    enable: vi.fn(),
    disable: vi.fn(),
    remove: vi.fn(),
    list: vi.fn(),
    deliveries: vi.fn(),
  },
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// Stub the MultiSelect popover with a flat set of toggle buttons - the popover
// internals aren't under test here, the dialog's validation + reveal are.
vi.mock('@/components/platform/multi-select', () => ({
  MultiSelect: ({
    options,
    value,
    onChange,
  }: {
    options: { label: string; value: string }[];
    value: string[];
    onChange: (v: string[]) => void;
  }) => (
    <div>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() =>
            onChange(
              value.includes(o.value)
                ? value.filter((x) => x !== o.value)
                : [...value, o.value],
            )
          }
        >
          {`toggle ${o.label}`}
        </button>
      ))}
    </div>
  ),
}));

const SECRET = 'whsec_ABCDEF1234567890thisisasigningsecret';

beforeEach(() => {
  vi.clearAllMocks();
  create.mockResolvedValue({
    endpoint: {
      id: 'wh-new-001',
      tenantId: 'tnt-001',
      workspaceId: 'wsp-001',
      channelId: 'chn-001',
      name: 'CRM sync',
      url: 'https://hooks.example.com/whatsapp',
      events: ['message.inbound'],
      status: 'ACTIVE',
      consecutiveFailures: 0,
      lastSuccessAt: null,
      disabledAt: null,
      disabledReason: null,
      createdAt: '2026-07-04T00:00:00Z',
      updatedAt: '2026-07-04T00:00:00Z',
    },
    signingSecret: SECRET,
  });
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <WebhookEndpointDialog
      channelId="chn-001"
      endpoint={null}
      open={open}
      onOpenChange={setOpen}
      onSaved={() => {}}
    />
  );
}

async function fillValidForm() {
  fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'CRM sync' } });
  fireEvent.change(screen.getByLabelText(/endpoint url/i), {
    target: { value: 'https://hooks.example.com/whatsapp' },
  });
  fireEvent.click(screen.getByRole('button', { name: /toggle inbound messages/i }));
}

describe('WebhookEndpointDialog (omnichannel Slice 4)', () => {
  it('requires at least one event and a valid https url before creating', async () => {
    render(<Harness />);
    // Name + url set, but NO event selected → submit is blocked with errors.
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'CRM sync' } });
    fireEvent.change(screen.getByLabelText(/endpoint url/i), {
      target: { value: 'https://hooks.example.com/whatsapp' },
    });
    fireEvent.click(screen.getByRole('button', { name: /add endpoint/i }));

    await waitFor(() => {
      expect(screen.getByText(/select at least one event/i)).toBeInTheDocument();
    });
    expect(create).not.toHaveBeenCalled();
  });

  it('rejects a non-https url', async () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'CRM sync' } });
    fireEvent.change(screen.getByLabelText(/endpoint url/i), {
      target: { value: 'http://insecure.example.com/hook' },
    });
    fireEvent.click(screen.getByRole('button', { name: /toggle inbound messages/i }));
    fireEvent.click(screen.getByRole('button', { name: /add endpoint/i }));

    await waitFor(() => {
      expect(screen.getByText(/valid https:\/\/ url/i)).toBeInTheDocument();
    });
    expect(create).not.toHaveBeenCalled();
  });

  it('creates with the entered values and reveals the signing secret ONCE', async () => {
    render(<Harness />);
    await fillValidForm();
    fireEvent.click(screen.getByRole('button', { name: /add endpoint/i }));

    await waitFor(() => {
      expect(screen.getByDisplayValue(SECRET)).toBeInTheDocument();
    });
    expect(create).toHaveBeenCalledWith('chn-001', {
      name: 'CRM sync',
      url: 'https://hooks.example.com/whatsapp',
      events: ['message.inbound'],
    });
    expect(screen.getByText(/won.t be shown again/i)).toBeInTheDocument();
    expect(screen.getByText(/X-Fx-Signature/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /copy signing secret/i })).toBeInTheDocument();
  });

  it('copy writes the secret to the clipboard', async () => {
    render(<Harness />);
    await fillValidForm();
    fireEvent.click(screen.getByRole('button', { name: /add endpoint/i }));
    await waitFor(() => screen.getByDisplayValue(SECRET));

    fireEvent.click(screen.getByRole('button', { name: /copy signing secret/i }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(SECRET);
    });
  });
});
