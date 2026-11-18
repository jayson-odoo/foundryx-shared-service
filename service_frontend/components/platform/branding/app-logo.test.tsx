/**
 * The shell logo used to point at `/media/app/*.svg`, template files never
 * committed to this repo: every environment answered 404 and every page
 * showed a broken image in the side panel, the phone top bar and the loader.
 * `AppLogo` draws its fallbacks inline, so nothing is left to 404, and keeps
 * the white-label rule (a branded tenant never sees the Foundryx mark).
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { PublicBranding } from '@/types/branding';
import { AppLogo } from './app-logo';

const UNBRANDED: PublicBranding = {
  isBranded: false,
  tenantName: null,
  appName: null,
  slogan: null,
  logoUrl: null,
  faviconUrl: null,
  illustrationUrl: null,
  tokens: null,
  version: 0,
};
const ACME: PublicBranding = { ...UNBRANDED, isBranded: true, tenantName: 'Acme Co' };

describe('AppLogo - unbranded host', () => {
  it('full: the inline wordmark, no image request', () => {
    const { container } = render(<AppLogo branding={UNBRANDED} />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByRole('img', { name: 'Foundryx' })).toBeInTheDocument();
    expect(container.innerHTML).not.toContain('/media/');
  });

  it('mini: the inline initial, no image request', () => {
    const { container } = render(<AppLogo branding={UNBRANDED} variant="mini" />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByRole('img', { name: 'Foundryx' })).toHaveTextContent('F');
  });
});

describe('AppLogo - branded tenant (white-label)', () => {
  it('shows the tenant logo, and its name when the logo fails to load', () => {
    render(<AppLogo branding={{ ...ACME, logoUrl: '/branding/acme.png' }} />);
    const img = screen.getByAltText('Acme Co');
    expect(img).toHaveAttribute('src', '/branding/acme.png');
    fireEvent.error(img);
    expect(screen.queryByAltText('Acme Co')).toBeNull();
    expect(screen.getByText('Acme Co')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Foundryx' })).toBeNull();
  });

  it('full without a logo: the tenant NAME, never the Foundryx wordmark', () => {
    render(<AppLogo branding={ACME} />);
    expect(screen.getByText('Acme Co')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Foundryx' })).toBeNull();
  });

  it('mini prefers the favicon, then the logo, then the initial', () => {
    const { rerender } = render(
      <AppLogo
        branding={{ ...ACME, faviconUrl: '/branding/fav.png', logoUrl: '/branding/acme.png' }}
        variant="mini"
      />,
    );
    expect(screen.getByAltText('Acme Co')).toHaveAttribute('src', '/branding/fav.png');
    rerender(<AppLogo branding={{ ...ACME, logoUrl: '/branding/acme.png' }} variant="mini" />);
    expect(screen.getByAltText('Acme Co')).toHaveAttribute('src', '/branding/acme.png');
    rerender(<AppLogo branding={ACME} variant="mini" />);
    expect(screen.getByRole('img', { name: 'Acme Co' })).toHaveTextContent('A');
  });
});

vi.mock('@/hooks/use-branding', () => ({
  useTenantBranding: () => ({ branding: UNBRANDED, isResolved: true }),
}));

describe('shell surfaces never request the missing /media/app files', () => {
  it('the auth-gate loader', async () => {
    const { ScreenLoader } = await import('@/components/common/screen-loader');
    const { container } = render(<ScreenLoader />);
    expect(container.innerHTML).not.toContain('/media/app/');
    expect(screen.getByRole('img', { name: 'Foundryx' })).toBeInTheDocument();
  });
});
