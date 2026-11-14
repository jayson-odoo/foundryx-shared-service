/**
 * Binding editor (plan 29 S4, D-A4-4/D-A4-5) - renders EXACTLY the slot count
 * the caller derives from the template shape (one row per header/body/button
 * variable, never more/fewer), and a slot switched to "Contact field" always
 * starts with an EMPTY fallback the author must fill in (the save-time
 * required-fallback rule this editor feeds).
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { TemplateBinding, WhatsAppTemplate } from '@/types/omnichannel';
import { BindingEditor } from './binding-editor';

vi.mock('@/services/whatsapp-template-service', () => ({
  whatsappTemplateService: {
    get: vi.fn().mockResolvedValue({ doc: null }),
  },
}));

const TEMPLATE: WhatsAppTemplate = {
  id: 'tpl-1',
  channelId: 'chn-1',
  name: 'booking_update',
  language: 'en_US',
  category: 'UTILITY',
  status: 'APPROVED',
  headerFormat: null,
  headerVariableCount: 0,
  variableCount: 2,
  buttonVariableCount: 0,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
} as WhatsAppTemplate;

const staticBinding = (text = ''): TemplateBinding => ({ source: 'static', text });
const fieldBinding = (field = 'firstName', fallback = ''): TemplateBinding => ({
  source: 'contactField',
  field,
  fallback,
});

describe('BindingEditor - slot count', () => {
  it('renders exactly one row per header + body + button slot passed in', () => {
    render(
      <BindingEditor
        channelId="chn-1"
        template={TEMPLATE}
        editing
        header={[staticBinding()]}
        body={[fieldBinding(), staticBinding()]}
        buttons={[fieldBinding()]}
        onChangeHeader={vi.fn()}
        onChangeBody={vi.fn()}
        onChangeButtons={vi.fn()}
      />,
    );
    expect(screen.getByText('Header {{1}}')).toBeInTheDocument();
    expect(screen.getByText('Body {{1}}')).toBeInTheDocument();
    expect(screen.getByText('Body {{2}}')).toBeInTheDocument();
    expect(screen.getByText('Button URL {{1}}')).toBeInTheDocument();
    expect(screen.queryByText('Body {{3}}')).not.toBeInTheDocument();
  });

  it('renders zero rows for a template with no variables at all', () => {
    render(
      <BindingEditor
        channelId="chn-1"
        template={TEMPLATE}
        editing
        header={[]}
        body={[]}
        buttons={[]}
        onChangeHeader={vi.fn()}
        onChangeBody={vi.fn()}
        onChangeButtons={vi.fn()}
      />,
    );
    expect(screen.queryByText(/\{\{1\}\}/)).not.toBeInTheDocument();
  });
});

describe('BindingEditor - fallback rule (D-A4-5)', () => {
  it('typing a fallback value calls onChangeBody with the updated slot', () => {
    const onChangeBody = vi.fn();
    render(
      <BindingEditor
        channelId="chn-1"
        template={TEMPLATE}
        editing
        header={[]}
        body={[fieldBinding('firstName', '')]}
        buttons={[]}
        onChangeHeader={vi.fn()}
        onChangeBody={onChangeBody}
        onChangeButtons={vi.fn()}
      />,
    );
    const fallbackInput = screen.getByTestId('broadcast-binding-body-0-fallback');
    fireEvent.change(fallbackInput, { target: { value: 'there' } });
    expect(onChangeBody).toHaveBeenCalledWith([{ source: 'contactField', field: 'firstName', fallback: 'there' }]);
  });

  it('post-approval O-4: renders a per-slot server 422 message when passed', () => {
    render(
      <BindingEditor
        channelId="chn-1"
        template={TEMPLATE}
        editing
        header={[]}
        body={[staticBinding(''), staticBinding('ok')]}
        buttons={[]}
        onChangeHeader={vi.fn()}
        onChangeBody={vi.fn()}
        onChangeButtons={vi.fn()}
        bodyErrors={['Static text is required.', undefined]}
      />,
    );
    expect(screen.getByText('Static text is required.')).toBeInTheDocument();
  });

  it('a disabled (read-only) row never fires a change on input', () => {
    const onChangeBody = vi.fn();
    render(
      <BindingEditor
        channelId="chn-1"
        template={TEMPLATE}
        editing={false}
        header={[]}
        body={[fieldBinding('firstName', 'there')]}
        buttons={[]}
        onChangeHeader={vi.fn()}
        onChangeBody={onChangeBody}
        onChangeButtons={vi.fn()}
      />,
    );
    expect(screen.getByTestId('broadcast-binding-body-0-fallback')).toBeDisabled();
  });
});
