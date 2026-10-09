/**
 * Text-node-only rendering (AC-WEB-48, D-A7B-26) - the panel's only
 * untrusted-content renderer. No `dangerouslySetInnerHTML` anywhere in this
 * component; a `<script>`/`javascript:` payload must render as literal,
 * inert text.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MessageText } from './message-text';

describe('MessageText', () => {
  it('renders a <script> payload as literal text, never as markup', () => {
    const payload = '<script>alert(1)</script>';
    render(<MessageText text={payload} />);
    expect(screen.getByText(payload)).toBeInTheDocument();
    expect(document.querySelector('script')).not.toBeInTheDocument();
  });

  it('renders an <img onerror> payload as literal text (stored-XSS guard)', () => {
    const payload = '<img src=x onerror=alert(1)>';
    render(<MessageText text={payload} />);
    expect(screen.getByText(payload)).toBeInTheDocument();
    expect(document.querySelector('img')).not.toBeInTheDocument();
  });

  it('a javascript: payload never becomes a link', () => {
    render(<MessageText text="click javascript:alert(1) now" />);
    expect(document.querySelector('a')).not.toBeInTheDocument();
  });

  it('a real http(s) URL renders as an anchor with the matching href', () => {
    render(<MessageText text="See https://example.com/x for details" />);
    const link = screen.getByRole('link', { name: 'https://example.com/x' });
    expect(link).toHaveAttribute('href', 'https://example.com/x');
  });
});
