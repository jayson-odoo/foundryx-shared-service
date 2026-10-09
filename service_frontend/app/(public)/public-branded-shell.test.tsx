import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PublicBranding } from '@/types/branding';
import { PublicBrandedShell, usePublicPageBranding } from './public-branded-shell';

/**
 * Issue #90 W1 (AC-90-1xx): the public idea-status page owns its own header
 * and footer (a real product/brand header + a footer BrandMark, per the #90
 * page design) - it must NOT also get the shell's `AuthFooter` (Terms/Plans/
 * Contact Us stub links, `href="#"`) the way a plain public form page does.
 * Mirrors the existing `isChromelessPanelPath` carve-out for
 * `/public/webchat/`, widened to also cover `/public/ideas/`.
 */

const usePathname = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ usePathname: () => usePathname() }));

const useTenantBranding = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-branding', () => ({
  useTenantBranding: () => useTenantBranding(),
}));

beforeEach(() => {
  usePathname.mockReset();
  useTenantBranding.mockReset();
  useTenantBranding.mockReturnValue({
    branding: {
      isBranded: false,
      tenantName: null,
      appName: null,
      slogan: null,
      logoUrl: null,
      faviconUrl: null,
      illustrationUrl: null,
      tokens: null,
      version: 0,
    },
    isResolved: true,
  });
});

describe('PublicBrandedShell - the public idea page owns its own chrome', () => {
  it('renders no AuthFooter on /public/ideas/:token', () => {
    usePathname.mockReturnValue('/public/ideas/tok_abc123def456');
    render(
      <PublicBrandedShell>
        <div>idea body</div>
      </PublicBrandedShell>,
    );
    expect(screen.getByText('idea body')).toBeInTheDocument();
    expect(screen.queryByText('Terms')).not.toBeInTheDocument();
    expect(screen.queryByText('Plans')).not.toBeInTheDocument();
    expect(screen.queryByText('Contact Us')).not.toBeInTheDocument();
  });

  it('still renders the AuthFooter on an ordinary public form page (regression)', () => {
    usePathname.mockReturnValue('/public/forms/some-tenant/some-form');
    render(
      <PublicBrandedShell>
        <div>form body</div>
      </PublicBrandedShell>,
    );
    expect(screen.getByText('Terms')).toBeInTheDocument();
  });
});

// ── review fix S2 - a chromeless child gets the SSR-resolved branding, no flash ──

function BrandingProbe() {
  const branding = usePublicPageBranding();
  return <span data-testid="probe">{branding?.tenantName ?? 'UNBRANDED'}</span>;
}

const UNBRANDED_FIXTURE: PublicBranding = {
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

describe('PublicBrandedShell - S2 chromeless children read the SSR-resolved branding', () => {
  it('serves the SSR initialBranding to a chromeless child before the client fetch resolves (no flash)', () => {
    usePathname.mockReturnValue('/public/ideas/tok_abc123def456');
    // The client-side store has not resolved yet - `useTenantBranding()`
    // alone would give a chromeless child the Foundryx default here.
    useTenantBranding.mockReturnValue({ branding: UNBRANDED_FIXTURE, isResolved: false });
    render(
      <PublicBrandedShell
        initialBranding={{ ...UNBRANDED_FIXTURE, isBranded: true, tenantName: 'Acme Co' }}
      >
        <BrandingProbe />
      </PublicBrandedShell>,
    );
    expect(screen.getByTestId('probe')).toHaveTextContent('Acme Co');
  });

  it('serves the live branding to a chromeless child once the client fetch resolves', () => {
    usePathname.mockReturnValue('/public/ideas/tok_abc123def456');
    useTenantBranding.mockReturnValue({
      branding: { ...UNBRANDED_FIXTURE, isBranded: true, tenantName: 'Beta Co' },
      isResolved: true,
    });
    render(
      <PublicBrandedShell initialBranding={null}>
        <BrandingProbe />
      </PublicBrandedShell>,
    );
    expect(screen.getByTestId('probe')).toHaveTextContent('Beta Co');
  });

  it('a chromeless child sees UNBRANDED when neither SSR nor the client resolved anything branded', () => {
    usePathname.mockReturnValue('/public/ideas/tok_abc123def456');
    useTenantBranding.mockReturnValue({ branding: UNBRANDED_FIXTURE, isResolved: false });
    render(
      <PublicBrandedShell initialBranding={null}>
        <BrandingProbe />
      </PublicBrandedShell>,
    );
    expect(screen.getByTestId('probe')).toHaveTextContent('UNBRANDED');
  });
});
