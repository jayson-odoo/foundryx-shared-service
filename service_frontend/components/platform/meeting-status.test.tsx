import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StatusBadge } from '@/components/platform/status-badge';
import { MEETING_STATUS_REGISTRY } from './meeting-status';

// AC-S3-11: `transcribed` reads distinctly from `ready` - `ready` stays
// reserved for minutes (S4), never faked by the transcript hop.
describe('MEETING_STATUS_REGISTRY', () => {
  it('renders "Transcript ready" for a transcribed meeting', () => {
    render(<StatusBadge status="transcribed" registry={MEETING_STATUS_REGISTRY} />);
    expect(screen.getByText('Transcript ready')).toBeInTheDocument();
  });

  it('renders a different label than ready', () => {
    expect(MEETING_STATUS_REGISTRY.transcribed.label).not.toBe(
      MEETING_STATUS_REGISTRY.ready.label
    );
  });
});
