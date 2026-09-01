import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

// Mock clipboard globally
const mockClipboard = {
  writeText: vi.fn().mockResolvedValue(undefined),
};

Object.defineProperty(navigator, 'clipboard', {
  value: mockClipboard,
  writable: true,
  configurable: true,
});

// Test DataBlock component
function TestDataBlock({ label, value }: { label: string; value: unknown }) {
  const [copied, setCopied] = useState(false);

  const textToCopy = value == null ? '' : JSON.stringify(value, null, 2);

  const handleCopy = async () => {
    if (!textToCopy || typeof navigator === 'undefined' || !navigator.clipboard) {
      return;
    }

    try {
      await navigator.clipboard.writeText(textToCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Silently fail if clipboard write is not allowed
    }
  };

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        {value != null && (
          <button
            type="button"
            onClick={handleCopy}
            aria-label={`Copy ${label}`}
            className="hover:text-foreground text-muted-foreground transition-colors"
          >
            {copied ? (
              <Check className="size-3.5" />
            ) : (
              <Copy className="size-3.5" />
            )}
          </button>
        )}
      </div>
      <pre className="max-h-40 overflow-auto rounded-md bg-muted p-2 text-[11px] text-foreground">
        {value == null ? '-' : textToCopy}
      </pre>
    </div>
  );
}

// Test ErrorBlock component
function TestErrorBlock({ error }: { error: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      return;
    }

    try {
      await navigator.clipboard.writeText(error);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Silently fail if clipboard write is not allowed
    }
  };

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Error
        </span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label="Copy Error"
          className="hover:text-destructive text-muted-foreground transition-colors"
        >
          {copied ? (
            <Check className="size-3.5" />
          ) : (
            <Copy className="size-3.5" />
          )}
        </button>
      </div>
      <pre className="overflow-auto rounded-md bg-destructive/10 p-2 text-[11px] text-destructive">
        {error}
      </pre>
    </div>
  );
}

describe('DataBlock - copy to clipboard', () => {
  beforeEach(() => {
    mockClipboard.writeText.mockClear();
  });

  it('renders copy button when value is not null', () => {
    const testValue = { url: 'https://example.com', method: 'GET' };
    render(<TestDataBlock label="Input" value={testValue} />);

    const copyButton = screen.getByRole('button', { name: /copy input/i });
    expect(copyButton).toBeInTheDocument();
  });

  it('does not render copy button when value is null', () => {
    render(<TestDataBlock label="Input" value={null} />);

    const copyButton = screen.queryByRole('button', { name: /copy input/i });
    expect(copyButton).not.toBeInTheDocument();
  });

  it('copies formatted JSON on button click', async () => {
    const testValue = { url: 'https://example.com', method: 'GET' };
    render(<TestDataBlock label="Input" value={testValue} />);

    const copyButton = screen.getByRole('button', { name: /copy input/i });
    fireEvent.click(copyButton);

    await waitFor(() => {
      expect(mockClipboard.writeText).toHaveBeenCalledWith(
        JSON.stringify(testValue, null, 2),
      );
    });
  });

  it('has correct aria-label', () => {
    render(<TestDataBlock label="Output" value={{ result: 'ok' }} />);

    const copyButton = screen.getByRole('button', { name: /copy output/i });
    expect(copyButton).toHaveAttribute('aria-label', 'Copy Output');
  });

  it('silently fails when clipboard is unavailable', () => {
    const originalClipboard = navigator.clipboard;
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      writable: true,
      configurable: true,
    });

    render(<TestDataBlock label="Input" value={{ test: 'data' }} />);

    const copyButton = screen.getByRole('button', { name: /copy input/i });
    expect(() => {
      fireEvent.click(copyButton);
    }).not.toThrow();

    Object.defineProperty(navigator, 'clipboard', {
      value: originalClipboard,
      writable: true,
      configurable: true,
    });
  });
});

describe('ErrorBlock - copy to clipboard', () => {
  beforeEach(() => {
    mockClipboard.writeText.mockClear();
  });

  it('renders copy button', () => {
    render(<TestErrorBlock error="HTTP request failed: timeout" />);

    const copyButton = screen.getByRole('button', { name: /copy error/i });
    expect(copyButton).toBeInTheDocument();
  });

  it('copies error text on button click', async () => {
    const errorText = 'HTTP request failed: timeout';
    render(<TestErrorBlock error={errorText} />);

    const copyButton = screen.getByRole('button', { name: /copy error/i });
    fireEvent.click(copyButton);

    await waitFor(() => {
      expect(mockClipboard.writeText).toHaveBeenCalledWith(errorText);
    });
  });

  it('has correct aria-label', () => {
    render(<TestErrorBlock error="Test error" />);

    const copyButton = screen.getByRole('button', { name: /copy error/i });
    expect(copyButton).toHaveAttribute('aria-label', 'Copy Error');
  });
});
