/**
 * Branding editor component tests (sprint-2/03 §TDD — frontend):
 * token editor renders groups · picker override marks the row + emits a diff ·
 * reset clears · template upload rejects bad files with named errors ·
 * read-only mode hides manage controls · asset card validates type/size.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BrandingTokens } from '@/types/branding';
import { AssetUploadCard } from './asset-upload-card';
import { ThemeTokenEditor } from './theme-token-editor';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ThemeTokenEditor', () => {
  it('renders all four groups', () => {
    render(<ThemeTokenEditor tokens={null} onChange={() => {}} canManage />);
    for (const label of ['Brand', 'Status colors', 'Grey scale', 'Surfaces']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('changing a hex value emits exactly that override', () => {
    const onChange = vi.fn();
    render(<ThemeTokenEditor tokens={null} onChange={onChange} canManage />);
    fireEvent.change(screen.getByLabelText('Primary hex value (light)'), {
      target: { value: '#0050ff' },
    });
    expect(onChange).toHaveBeenCalledWith({
      light: { primary: '#0050ff' },
      dark: {},
    });
  });

  it('typing the Dreamz default back clears the override (null document)', () => {
    const onChange = vi.fn();
    const tokens: BrandingTokens = { light: { primary: '#0050ff' }, dark: {} };
    render(<ThemeTokenEditor tokens={tokens} onChange={onChange} canManage />);
    fireEvent.change(screen.getByLabelText('Primary hex value (light)'), {
      target: { value: '#ff5a00' },
    });
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('Reset all clears every override', () => {
    const onChange = vi.fn();
    const tokens: BrandingTokens = {
      light: { primary: '#0050ff' },
      dark: { danger: '#ff0000' },
    };
    render(<ThemeTokenEditor tokens={tokens} onChange={onChange} canManage />);
    fireEvent.click(screen.getByRole('button', { name: /reset all/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('light and dark tabs edit independent values', () => {
    const onChange = vi.fn();
    render(<ThemeTokenEditor tokens={null} onChange={onChange} canManage />);
    fireEvent.click(screen.getByRole('button', { name: 'dark' }));
    fireEvent.change(screen.getByLabelText('Primary hex value (dark)'), {
      target: { value: '#4d82ff' },
    });
    expect(onChange).toHaveBeenCalledWith({
      light: {},
      dark: { primary: '#4d82ff' },
    });
  });

  it('rejects a template with unknown keys and reports them', async () => {
    const onChange = vi.fn();
    render(<ThemeTokenEditor tokens={null} onChange={onChange} canManage />);
    const file = new File(
      [JSON.stringify({ light: { bogus: '#fff' } })],
      'theme.json',
      {
        type: 'application/json',
      },
    );
    fireEvent.change(screen.getByLabelText('Upload theme template'), {
      target: { files: [file] },
    });
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onChange).not.toHaveBeenCalled();
  });

  it('applies a valid template as a draft', async () => {
    const onChange = vi.fn();
    render(<ThemeTokenEditor tokens={null} onChange={onChange} canManage />);
    const file = new File(
      [JSON.stringify({ light: { primary: '#0050ff' }, dark: {} })],
      'theme.json',
      { type: 'application/json' },
    );
    fireEvent.change(screen.getByLabelText('Upload theme template'), {
      target: { files: [file] },
    });
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        light: { primary: '#0050ff' },
        dark: {},
      }),
    );
  });

  it('read-only mode hides template + reset controls and disables inputs', () => {
    render(
      <ThemeTokenEditor
        tokens={{ light: { primary: '#0050ff' }, dark: {} }}
        onChange={() => {}}
        canManage={false}
      />,
    );
    expect(
      screen.queryByRole('button', { name: /download template/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /upload template/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /reset all/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText('Primary hex value (light)')).toBeDisabled();
  });
});

describe('AssetUploadCard', () => {
  it('rejects a wrong file type client-side', async () => {
    const onUpload = vi.fn();
    render(
      <AssetUploadCard
        kind="favicon"
        title="Browser-tab icon"
        url={null}
        canManage
        onUpload={onUpload}
        onRemove={async () => {}}
      />,
    );
    const file = new File(['x'], 'evil.svg', { type: 'image/svg+xml' }); // SVG not allowed for favicon
    fireEvent.change(screen.getByLabelText('Upload browser-tab icon'), {
      target: { files: [file] },
    });
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('Unsupported file type.'),
    );
    expect(onUpload).not.toHaveBeenCalled();
  });

  it('rejects an oversized file client-side', async () => {
    const onUpload = vi.fn();
    render(
      <AssetUploadCard
        kind="favicon"
        title="Browser-tab icon"
        url={null}
        canManage
        onUpload={onUpload}
        onRemove={async () => {}}
      />,
    );
    const big = new File([new Uint8Array(513 * 1024)], 'icon.png', {
      type: 'image/png',
    });
    fireEvent.change(screen.getByLabelText('Upload browser-tab icon'), {
      target: { files: [big] },
    });
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onUpload).not.toHaveBeenCalled();
  });

  it('uploads a valid file and shows Replace/Remove when set', async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <AssetUploadCard
        kind="logo"
        title="Logo"
        url={null}
        canManage
        onUpload={onUpload}
        onRemove={async () => {}}
      />,
    );
    const file = new File(['png'], 'logo.png', { type: 'image/png' });
    fireEvent.change(screen.getByLabelText('Upload logo'), {
      target: { files: [file] },
    });
    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file));

    rerender(
      <AssetUploadCard
        kind="logo"
        title="Logo"
        url="data:image/png;base64,x"
        canManage
        onUpload={onUpload}
        onRemove={async () => {}}
      />,
    );
    expect(
      screen.getByRole('button', { name: /replace/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument();
  });

  it('read-only mode renders no upload controls', () => {
    render(
      <AssetUploadCard
        kind="logo"
        title="Logo"
        url={null}
        canManage={false}
        onUpload={async () => {}}
        onRemove={async () => {}}
      />,
    );
    expect(
      screen.queryByRole('button', { name: /upload/i }),
    ).not.toBeInTheDocument();
  });
});
