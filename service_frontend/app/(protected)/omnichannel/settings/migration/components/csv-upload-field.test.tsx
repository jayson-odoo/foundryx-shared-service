/**
 * CSV upload field (S6, AC-MIG-46/47) - the migration setup form's upload
 * primitive: click-or-drop a file, POST it through `uploadCsv`, surface the
 * result (or a toast on failure); the "uploaded" state offers Remove only
 * while editing.
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CsvUploadField } from './csv-upload-field';

const uploadCsvMock = vi.fn();
vi.mock('@/services/respondio-migration-service', () => ({
  respondioMigrationService: { uploadCsv: (...args: unknown[]) => uploadCsvMock(...args) },
}));
vi.mock('@/lib/toast', () => ({ toast: { error: vi.fn() } }));

function file(name = 'contacts.csv') {
  return new File(['First Name\nAda'], name, { type: 'text/csv' });
}

describe('CsvUploadField', () => {
  it('uploads the chosen file and reports the result back', async () => {
    uploadCsvMock.mockResolvedValueOnce({ key: 'conn:1:a.csv', rowCount: 1, headers: ['First Name'] });
    const onUploaded = vi.fn();
    render(
      <CsvUploadField
        kind="contacts"
        label="Contacts CSV *"
        editing
        fileName={null}
        rowCount={null}
        onUploaded={onUploaded}
        onClear={vi.fn()}
      />,
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { files: [file()] } });
    });
    await vi.waitFor(() => expect(onUploaded).toHaveBeenCalledWith({ key: 'conn:1:a.csv', rowCount: 1, headers: ['First Name'] }, 'contacts.csv'));
    expect(uploadCsvMock).toHaveBeenCalledWith('contacts', expect.any(File));
  });

  it('toasts on a rejected upload and never calls onUploaded', async () => {
    const { toast } = await import('@/lib/toast');
    uploadCsvMock.mockRejectedValueOnce(new Error('Unsupported file - upload a CSV.'));
    const onUploaded = vi.fn();
    render(
      <CsvUploadField
        kind="contacts"
        label="Contacts CSV *"
        editing
        fileName={null}
        rowCount={null}
        onUploaded={onUploaded}
        onClear={vi.fn()}
      />,
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { files: [file()] } });
    });
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledWith('Unsupported file - upload a CSV.'));
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it('renders the uploaded file name + row count, with Remove offered only while editing', () => {
    const onClear = vi.fn();
    const { rerender } = render(
      <CsvUploadField
        kind="contacts"
        label="Contacts CSV *"
        editing
        fileName="contacts.csv"
        rowCount={3}
        onUploaded={vi.fn()}
        onClear={onClear}
      />,
    );
    expect(screen.getByText('contacts.csv')).toBeInTheDocument();
    expect(screen.getByText('3 rows')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /remove contacts csv/i }));
    expect(onClear).toHaveBeenCalled();

    rerender(
      <CsvUploadField
        kind="contacts"
        label="Contacts CSV *"
        editing={false}
        fileName="contacts.csv"
        rowCount={3}
        onUploaded={vi.fn()}
        onClear={onClear}
      />,
    );
    expect(screen.queryByRole('button', { name: /remove contacts csv/i })).not.toBeInTheDocument();
  });

  it('shows the field-level error text when provided', () => {
    render(
      <CsvUploadField
        kind="contacts"
        label="Contacts CSV *"
        editing
        fileName={null}
        rowCount={null}
        onUploaded={vi.fn()}
        onClear={vi.fn()}
        error="Upload a contacts CSV."
      />,
    );
    expect(screen.getByText('Upload a contacts CSV.')).toBeInTheDocument();
  });
});
