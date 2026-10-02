import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { buildEvent, buildInfo } from './br-build-fixtures';
import { BrTraceTab } from './br-trace-tab';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => v ?? '',
    formatDateTime: (v: string) => `T(${v})`,
    formatTime: (v: string) => v ?? '',
  }),
}));

vi.mock('@/services/business-requirement-service', () => ({
  businessRequirementService: { getBuild: vi.fn() },
}));

const ISSUE = 'https://github.com/jayson-odoo/sorento-crm/issues/1402';

const sentBuild = () =>
  buildInfo({
    state: 'sent',
    canSend: false,
    issueUrl: ISSUE,
    issueNumber: 1402,
    events: [
      buildEvent({ id: 'e1', seq: 1, kind: 'sent', stage: 'sent', message: 'Sent to build' }),
      buildEvent({
        id: 'e2',
        seq: 2,
        stage: 'in_progress',
        message: 'Crew is building',
        prUrl: 'https://github.com/x/y/pull/9',
      }),
      buildEvent({
        id: 'e3',
        seq: 3,
        stage: 'handtest',
        message: 'Ready for hand test',
        handtestUrl: 'https://hand.test/abc',
      }),
      buildEvent({
        id: 'e4',
        seq: 4,
        stage: 'merged',
        message: 'PR merged',
        status: 'merged',
        statusMoved: true,
      }),
    ],
  });

describe('BrTraceTab (AC-STB-19)', () => {
  it('AC-STB-19 null build shows "Not sent to build yet."', () => {
    render(<BrTraceTab brId="br-1" build={null} reload={vi.fn()} />);
    expect(screen.getByText('Not sent to build yet.')).toBeInTheDocument();
  });

  it('AC-STB-19 state none shows "Not sent to build yet."', () => {
    render(<BrTraceTab brId="br-1" build={buildInfo({ state: 'none' })} reload={vi.fn()} />);
    expect(screen.getByText('Not sent to build yet.')).toBeInTheDocument();
    expect(document.querySelector('[data-slot="build-summary"]')).toBeNull();
  });

  it('AC-STB-19 summary card: issue link, latest stage, latest PR and hand-test links', () => {
    render(<BrTraceTab brId="br-1" build={sentBuild()} reload={vi.fn()} />);
    const summary = document.querySelector('[data-slot="build-summary"]') as HTMLElement;
    expect(summary).not.toBeNull();
    const issue = within(summary).getByRole('link', { name: /sorento-crm #1402/ });
    expect(issue).toHaveAttribute('href', ISSUE);
    // Latest event is "merged".
    expect(within(summary).getByText(/merged/i)).toBeInTheDocument();
    const links = within(summary).getAllByRole('link');
    expect(links.some((l) => l.getAttribute('href') === 'https://github.com/x/y/pull/9')).toBe(true);
    expect(links.some((l) => l.getAttribute('href') === 'https://hand.test/abc')).toBe(true);
  });

  it('AC-STB-19 timeline lists one item per event, oldest first, with message and formatted time', () => {
    render(<BrTraceTab brId="br-1" build={sentBuild()} reload={vi.fn()} />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent('Sent to build');
    expect(items[1]).toHaveTextContent('Crew is building');
    expect(items[2]).toHaveTextContent('Ready for hand test');
    expect(items[3]).toHaveTextContent('PR merged');
    expect(items[0]).toHaveTextContent('T(2026-09-30T08:00:00Z)');
  });

  it('AC-STB-19 merged/released events carry data-tone="success"; others do not', () => {
    render(<BrTraceTab brId="br-1" build={sentBuild()} reload={vi.fn()} />);
    const items = screen.getAllByRole('listitem');
    const tone = (el: HTMLElement) =>
      el.getAttribute('data-tone') ?? el.querySelector('[data-tone]')?.getAttribute('data-tone');
    expect(tone(items[3])).toBe('success');
    expect(tone(items[1])).not.toBe('success');
  });
});
