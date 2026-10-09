import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ReportFilterBar } from './report-filter-bar';

const BASE_PROPS = {
  dateRange: { preset: 'last7' as const, from: '2026-03-01', to: '2026-03-07' },
  onDateRangeChange: vi.fn(),
  timeZone: 'Asia/Kuala_Lumpur',
  userId: null,
  onUserIdChange: vi.fn(),
  members: [{ id: 'u_ann', name: 'Ann Lee' }, { id: 'u_ben', name: 'Ben Ooi' }],
  channelId: null,
  onChannelIdChange: vi.fn(),
  channels: [{ id: 'chn-wa', name: 'WhatsApp Demo' }],
  granularity: null,
  onGranularityChange: vi.fn(),
  granularityOptions: ['hour', 'day', 'week', 'month'] as const,
};

describe('ReportFilterBar', () => {
  it('renders a User, Channel and Granularity SearchSelect plus the date range control', () => {
    render(<ReportFilterBar {...BASE_PROPS} granularityOptions={[...BASE_PROPS.granularityOptions]} />);
    expect(screen.getByRole('combobox', { name: 'User' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Channel' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Granularity' })).toHaveTextContent('Auto');
    expect(screen.getByRole('combobox', { name: 'Date range preset' })).toBeInTheDocument();
  });

  it('maps the "All users" / "All channels" sentinel back to null', () => {
    const onUserIdChange = vi.fn();
    render(
      <ReportFilterBar {...BASE_PROPS} userId="u_ann" onUserIdChange={onUserIdChange} granularityOptions={[...BASE_PROPS.granularityOptions]} />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: 'User' }));
    fireEvent.click(screen.getByText('All users'));
    expect(onUserIdChange).toHaveBeenCalledWith(null);
  });

  it('picks a real user through to onUserIdChange', () => {
    const onUserIdChange = vi.fn();
    render(
      <ReportFilterBar {...BASE_PROPS} onUserIdChange={onUserIdChange} granularityOptions={[...BASE_PROPS.granularityOptions]} />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: 'User' }));
    fireEvent.click(screen.getByText('Ben Ooi'));
    expect(onUserIdChange).toHaveBeenCalledWith('u_ben');
  });

  it('picks a real channel through to onChannelIdChange', () => {
    const onChannelIdChange = vi.fn();
    render(
      <ReportFilterBar {...BASE_PROPS} onChannelIdChange={onChannelIdChange} granularityOptions={[...BASE_PROPS.granularityOptions]} />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: 'Channel' }));
    fireEvent.click(screen.getByText('WhatsApp Demo'));
    expect(onChannelIdChange).toHaveBeenCalledWith('chn-wa');
  });

  it('offers only the meta-declared granularities plus Auto (foolproof-UI)', () => {
    const onGranularityChange = vi.fn();
    render(<ReportFilterBar {...BASE_PROPS} onGranularityChange={onGranularityChange} granularityOptions={['day']} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Granularity' }));
    const dailyOption = screen.getByRole('option', { name: 'Daily' });
    expect(dailyOption).toBeInTheDocument();
    expect(screen.queryByText('Weekly')).not.toBeInTheDocument();
    fireEvent.click(dailyOption);
    expect(onGranularityChange).toHaveBeenCalledWith('day');
  });
});
