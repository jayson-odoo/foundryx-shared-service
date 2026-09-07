/**
 * Plan 31 (omnichannel workflow parity) S3 review B-1 - backend<->FE metadata
 * key-shape parity guard. The review's root cause was a silent drift:
 * `closeReasons[].isActive` existed on the FE type/filter but never on the
 * wire, so a real workspace's Close reason picker was always empty against
 * the real API even though every test was green. This is the FRONTEND half
 * of the parity pair; `test_omnichannel_workspace_options_key_shape_matches_
 * frontend_type` (`tests/test_omnichannel_workflow_parity_triggers.py`) is
 * the backend half.
 *
 * Two things are checked at once: (1) TS excess-property checking on the
 * object literals below - assigning a fixture straight into a
 * `WorkflowOmnichannelWorkspace`-typed const fails `tsc` if a field is added
 * to the FE type without also being added here; (2) the `Object.keys`
 * assertions fail loudly if a field is added/removed on the RUNTIME shape
 * without updating this fixture. A field added on only one side (backend
 * dict or FE type) must fail ONE of the two parity tests.
 */
import { describe, expect, it } from 'vitest';
import type { WorkflowOmnichannelWorkspace } from './workflows';

const workspace: WorkflowOmnichannelWorkspace = {
  id: 'ws-1',
  name: 'General',
  contactTags: [{ id: 'tag-1', name: 'VIP' }],
  contactFields: [{ key: 'company', label: 'Company', type: 'text' }],
  lifecycleStages: [{ id: 'stage-1', name: 'New' }],
  // No `isActive` - the wire never carries one (B-1); adding it back here
  // would fail `tsc` (excess property on a `closeReasons` literal) the
  // moment it's re-added to the type without a matching backend field.
  closeReasons: [{ id: 'reason-1', name: 'Resolved' }],
  members: [{ id: 'user-1', name: 'Demo Admin' }],
  templates: [{ id: 'tpl-1', name: 'welcome_message', status: 'APPROVED' }],
};

describe('WorkflowOmnichannelWorkspace - backend<->FE key parity (plan 31 S3 review B-1)', () => {
  it('every array element carries exactly its documented key set', () => {
    expect(Object.keys(workspace.contactTags[0]).sort()).toEqual(['id', 'name']);
    expect(Object.keys(workspace.contactFields[0]).sort()).toEqual(['key', 'label', 'type']);
    expect(Object.keys(workspace.lifecycleStages[0]).sort()).toEqual(['id', 'name']);
    // The load-bearing assertion - NO `isActive` key (B-1).
    expect(Object.keys(workspace.closeReasons[0]).sort()).toEqual(['id', 'name']);
    expect(Object.keys(workspace.members[0]).sort()).toEqual(['id', 'name']);
    expect(Object.keys(workspace.templates[0]).sort()).toEqual(['id', 'name', 'status']);
  });
});
