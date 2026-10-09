/**
 * Mock contact-field registry (S0, plan 25). In-memory store, seeded with a
 * field per type family so every input renderer + validation state is
 * tunable with no backend. Mirrors the backend rules the real service will
 * enforce (AC-CDM-01..05): reserved keys, key regex + uniqueness
 * (case-insensitive) per workspace, `list` requires >= 1 option, 100-field cap.
 *
 * Single-workspace mock (same reasoning as conversation-service.mock's thread
 * list): `workspace-service` is REAL and returns a real UUID, so `workspaceId`
 * is accepted + stamped on created rows for realism but NOT used to filter -
 * every call sees the one seeded set regardless of which real workspace is
 * open. A real per-workspace registry lands with the S1 backend.
 */
import { ApiError } from '@/lib/api-client';
import type {
  ContactField,
  CreateContactFieldInput,
  UpdateContactFieldInput,
} from '@/types/omnichannel';
import { RESERVED_CONTACT_FIELD_KEYS } from '@/types/omnichannel';
import type { ContactFieldService } from './contact-field-service';
import { delay } from './mock-query';

/** Throws the SAME 422 shape the real backend sends (`ApiError.detail.fieldErrors`)
 *  so dialogs map errors identically against mock or real (S4 swap parity). */
function fieldErrorsError(message: string, fieldErrors: Record<string, string>): ApiError {
  return new ApiError(message, 422, null, { fieldErrors });
}

const KEY_RE = /^[a-z][a-zA-Z0-9_]{0,39}$/;
const MAX_FIELDS = 100;
const SEED_WORKSPACE_ID = 'wsp-001'; // cosmetic default; never filtered on

let idSeq = 1;
const nextId = () => `cf-${idSeq++}`;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString();

function seed(): ContactField[] {
  idSeq = 1;
  return [
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      key: 'leadSource',
      label: 'Lead Source',
      description: 'Where this contact first came from.',
      type: 'list',
      options: ['Referral', 'Website', 'Trade show', 'Cold outreach'],
      visibility: 'always',
      sortOrder: 0,
      valuesCount: 2,
      createdAt: iso(30),
    },
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      key: 'company',
      label: 'Company',
      description: null,
      type: 'text',
      options: null,
      visibility: 'always',
      sortOrder: 1,
      valuesCount: 1,
      createdAt: iso(29),
    },
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      key: 'dealValue',
      label: 'Deal Value',
      description: 'Estimated deal size (MYR).',
      type: 'number',
      options: null,
      visibility: 'always',
      sortOrder: 2,
      valuesCount: 0,
      createdAt: iso(20),
    },
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      key: 'newsletterOptIn',
      label: 'Newsletter Opt-in',
      description: null,
      type: 'checkbox',
      options: null,
      visibility: 'hidden',
      sortOrder: 3,
      valuesCount: 0,
      createdAt: iso(10),
    },
  ];
}

let fields: ContactField[] = seed();

/** Reset mock state between tests / a fresh browser session. */
export function __mockResetContactFields(): void {
  fields = seed();
}

/** Cross-mock read used by conversation-service.mock.ts to validate a contact
 *  PATCH's `customFields` (S0 only - the real backend validates against the
 *  same workspace-scoped table server-side). `workspaceId` is accepted for a
 *  parity-shaped call signature but not filtered on (single-workspace mock). */
export function __mockAllContactFields(_workspaceId: string): ContactField[] {
  void _workspaceId;
  return [...fields];
}

function validate(
  input: { key?: string; label: string; type?: ContactField['type']; options?: string[] },
  excludingId?: string,
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!input.label.trim()) errors.label = 'Label is required.';
  if (input.key !== undefined) {
    if (RESERVED_CONTACT_FIELD_KEYS.includes(input.key)) {
      errors.key = 'This key is reserved for a system field.';
    } else if (!KEY_RE.test(input.key)) {
      errors.key = 'Use letters, numbers and underscore, starting with a lowercase letter.';
    } else if (
      fields.some((f) => f.id !== excludingId && f.key.toLowerCase() === input.key!.toLowerCase())
    ) {
      errors.key = 'A field with this key already exists.';
    }
  }
  if (input.type === 'list' && !(input.options ?? []).some((o) => o.trim())) {
    errors.options = 'Add at least one option.';
  }
  return errors;
}

export const mockContactFieldService: ContactFieldService = {
  async list(_workspaceId) {
    void _workspaceId;
    const rows = [...fields].sort((a, b) => a.sortOrder - b.sortOrder);
    return delay(rows, 200);
  },

  async create(workspaceId, input: CreateContactFieldInput) {
    if (fields.length >= MAX_FIELDS) {
      throw fieldErrorsError('This workspace has reached the 100-field limit.', {
        key: 'This workspace has reached the 100-field limit.',
      });
    }
    const errors = validate(input);
    if (Object.keys(errors).length) {
      throw fieldErrorsError('Please fix the highlighted fields.', errors);
    }
    const maxOrder = Math.max(-1, ...fields.map((f) => f.sortOrder));
    const created: ContactField = {
      id: nextId(),
      workspaceId,
      key: input.key,
      label: input.label.trim(),
      description: input.description?.trim() || null,
      type: input.type,
      options: input.type === 'list' ? (input.options ?? []).filter((o) => o.trim()) : null,
      visibility: input.visibility ?? 'always',
      sortOrder: maxOrder + 1,
      valuesCount: 0,
      createdAt: new Date().toISOString(),
    };
    fields = [...fields, created];
    return delay(created, 250);
  },

  async update(_workspaceId, fieldId, input: UpdateContactFieldInput) {
    void _workspaceId;
    const existing = fields.find((f) => f.id === fieldId);
    if (!existing) throw new Error('Field not found.');
    const errors = validate(
      { label: input.label ?? existing.label, type: existing.type, options: input.options },
      fieldId,
    );
    if (Object.keys(errors).length) {
      throw fieldErrorsError('Please fix the highlighted fields.', errors);
    }
    const updated: ContactField = {
      ...existing,
      label: input.label !== undefined ? input.label.trim() : existing.label,
      description:
        input.description !== undefined ? input.description?.trim() || null : existing.description,
      options:
        existing.type === 'list' && input.options !== undefined
          ? input.options.filter((o) => o.trim())
          : existing.options,
      visibility: input.visibility ?? existing.visibility,
      sortOrder: input.sortOrder ?? existing.sortOrder,
    };
    fields = fields.map((f) => (f.id === fieldId ? updated : f));
    return delay(updated, 250);
  },

  async remove(_workspaceId, fieldId) {
    void _workspaceId;
    fields = fields.filter((f) => f.id !== fieldId);
    return delay(undefined, 200);
  },
};
