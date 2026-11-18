/**
 * Lane META-LEADS-GUIDE-PAGE: the public guide renders with NO session (no
 * SessionProvider, no login), shows both audiences, and its labels come from
 * the same registries the wizard and the app use.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WIZARD_STEPS } from '@/lib/lead-capture-wizard';
import { SOURCE_STATUS_REGISTRY } from '@/app/(protected)/lead-capture/sources/components/source-status';
import { LeadCaptureGuide } from './lead-capture-guide';

const writeText = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  writeText.mockClear();
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
});

function renderGuide(partnerName: string | null = 'Partner CRM') {
  return render(<LeadCaptureGuide partnerName={partnerName} apiBase="https://ss.example/be/api/v1/lead-capture" />);
}

describe('LeadCaptureGuide', () => {
  it('renders without any session provider (no login)', () => {
    renderGuide();
    expect(screen.getByRole('heading', { level: 1, name: 'Receive Facebook leads in Partner CRM' })).toBeInTheDocument();
  });

  it('falls back to a generic name on an unbranded host', () => {
    renderGuide(null);
    expect(screen.getByRole('heading', { level: 1, name: 'Receive Facebook leads in your app' })).toBeInTheDocument();
  });

  it('shows the developer part first: connect button, lead pull, optional push', () => {
    renderGuide();
    expect(screen.getByRole('tab', { name: 'For developers' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { name: 'A. A "Connect Facebook Page" button' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'B. One scheduled job that collects leads' })).toBeInTheDocument();
    expect(screen.getByText(/connect-sessions/)).toBeInTheDocument();
    for (const meta of Object.values(SOURCE_STATUS_REGISTRY)) {
      expect(screen.getAllByText(meta.label).length).toBeGreaterThan(0);
    }
  });

  it('copies a code sample with its Copy button', () => {
    renderGuide();
    const block = screen.getByTestId('code-connect-session');
    fireEvent.click(within(block).getByRole('button', { name: 'Copy' }));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('/connect-sessions'));
  });

  it('shows one card per wizard step on the customer tab', () => {
    renderGuide();
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'For your customer' }));
    fireEvent.click(screen.getByRole('tab', { name: 'For your customer' }));
    const panel = screen.getByRole('tabpanel');
    for (const def of WIZARD_STEPS) {
      expect(within(panel).getByRole('heading', { name: new RegExp(`^\\d+\\. ${def.label}$`) })).toBeInTheDocument();
    }
    expect(within(panel).getByRole('heading', { name: /\. Finish$/ })).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { name: /\. Done$/ })).toBeInTheDocument();
    expect(within(panel).getByText('Facebook did not give permission to read leads.', { exact: false })).toBeInTheDocument();
  });
});

describe('guide route', () => {
  const dir = __dirname;
  it('lives in the public group with no auth guard', () => {
    expect(dir).toMatch(/app[\\/]\(public\)[\\/]public[\\/]lead-capture[\\/]guide$/);
    const src = ['page.tsx', 'lead-capture-guide.tsx']
      .map((f) => fs.readFileSync(path.join(dir, f), 'utf8'))
      .join('\n');
    expect(src).not.toMatch(/useSession|getServerSession|RequirePermission|apiFetch\(/);
  });
});
