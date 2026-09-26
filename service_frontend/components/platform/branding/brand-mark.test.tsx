import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { PublicBranding } from '@/types/branding';
import { BrandMark } from './brand-mark';

/**
 * Review fix B1 (issue #90 code review): `/media/foundryx/foundryx-logo.png`
 * is not committed to the repo - it 404s in every environment, so a
 * `next/image` pointed at it showed a broken-image icon to every visitor on
 * an unbranded host (including every WhatsApp visitor opening a public idea
 * link). The unbranded wordmark is now inline SVG text - no network request,
 * so it cannot 404.
 */

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

describe('BrandMark - unbranded wordmark does not depend on the missing PNG', () => {
  it('renders an inline SVG wordmark, never an <img> tag', () => {
    const { container } = render(<BrandMark branding={UNBRANDED} />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByRole('img', { name: 'Foundryx' })).toBeInTheDocument();
  });

  it('never references the missing PNG path anywhere in the rendered markup', () => {
    const { container } = render(<BrandMark branding={UNBRANDED} />);
    expect(container.innerHTML).not.toContain('/media/foundryx/foundryx-logo.png');
  });

  // Kill-test: reverting the fix (an `<Image src="/media/foundryx/...">`)
  // would fail BOTH assertions above - confirmed by hand against the prior
  // implementation before this fix landed.
});

describe('BrandMark - branded consumers unaffected (regression)', () => {
  it('shows the tenant logo image when branded with a logo URL', () => {
    const branding: PublicBranding = {
      ...UNBRANDED,
      isBranded: true,
      tenantName: 'Acme Co',
      logoUrl: '/branding/acme-logo.png',
    };
    render(<BrandMark branding={branding} />);
    expect(screen.getByAltText('Acme Co')).toBeInTheDocument();
  });

  it('falls back to the tenant NAME text when the logo image errors', () => {
    const branding: PublicBranding = {
      ...UNBRANDED,
      isBranded: true,
      tenantName: 'Acme Co',
      logoUrl: '/branding/acme-logo.png',
    };
    render(<BrandMark branding={branding} />);
    fireEvent.error(screen.getByAltText('Acme Co'));
    expect(screen.queryByAltText('Acme Co')).not.toBeInTheDocument();
    expect(screen.getByText('Acme Co')).toBeInTheDocument();
  });

  it('shows the tenant NAME text when branded with no logo URL', () => {
    const branding: PublicBranding = {
      ...UNBRANDED,
      isBranded: true,
      tenantName: 'Acme Co',
      logoUrl: null,
    };
    render(<BrandMark branding={branding} />);
    expect(screen.getByText('Acme Co')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Foundryx' })).not.toBeInTheDocument();
  });
});
