/**
 * Cluster E (AC-06-64) scenario builder - operator-API setup so the FLOW under
 * test stays real clicks. Builds, against the live backend at :8002 as the demo
 * admin:
 *   - a published submission form (event) + its scoped status graph
 *     (Draft → Submitted[review_start] → Accepted/Rejected/Revisions; Revisions
 *     is_active=false so the revise-clone loop works);
 *   - a published rubric form with a numeric `score` field;
 *   - a persona-bound review configuration (Author/Reviewer/Decision-maker) with
 *     required_review_count=2 + an open window + status map (the seeded
 *     review.allocate workflow auto-creates);
 *   - 1 author + 2 reviewers + 1 decision-maker Profile, persona-granted.
 *
 * Everything is timestamped (never a fixed literal) so reruns don't collide.
 */

import { execFileSync } from 'node:child_process';

const API = process.env.CLUSTER_E_API ?? 'http://localhost:8002';
const TENANT_SLUG = 'default';
const DB_URL =
  process.env.CLUSTER_E_DB ??
  'postgresql://foundryx:foundryx@localhost:5432/foundryx_service_clustere';

/**
 * E2E residue cleanup (the documented failure class). The persona-bound reviewer
 * pool draws EVERY Profile holding the reviewer/decider persona tenant-wide,
 * ordered by id and trimmed to required_review_count - so prior runs' reviewer
 * profiles (lower ids) would be allocated instead of THIS run's. Soft-delete all
 * prior E2E reviewer/decider profiles (the resolver filters is_deleted=False) so
 * the pool contains only the run we are about to build. Historical FK refs (old
 * assignments) are untouched.
 */
function cleanupResidueProfiles(): void {
  execFileSync(
    'psql',
    [
      DB_URL,
      '-c',
      "UPDATE app_ems.profiles SET is_deleted = true WHERE is_deleted = false AND (email LIKE 'e2e-reviewer%' OR email LIKE 'e2e-decider%' OR email LIKE 'ce-rev%' OR email LIKE 'ce-dec%');",
    ],
    { encoding: 'utf8' },
  );
}

export interface Actor {
  profileId: string;
  email: string;
  fullName: string;
}

export interface ClusterEScenario {
  stamp: string;
  submissionFormId: string;
  reviewFormId: string;
  configId: string;
  scoreKey: string;
  titleKey: string;
  reviewScoreKey: string;
  statuses: Record<string, string>; // key -> status id
  author: Actor;
  reviewers: Actor[];
  decisionMaker: Actor;
  adminToken: string;
}

async function api(
  token: string | null,
  method: string,
  path: string,
  body?: unknown,
): Promise<any> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`${method} ${path} → ${res.status}: ${text}`);
  }
  return text ? JSON.parse(text) : null;
}

export async function adminLogin(): Promise<string> {
  const data = await api(null, 'POST', '/auth/login', {
    email: 'demo@example.com',
    password: 'demo1234',
    tenantSlug: TENANT_SLUG,
  });
  return data.access_token;
}

function textField(key: string, label: string) {
  return { id: `f_${key}`, type: 'text', key, label, required: true };
}
function numberField(key: string, label: string) {
  return { id: `f_${key}`, type: 'number', key, label, required: true };
}

async function createPublishedForm(
  token: string,
  name: string,
  fields: Array<Record<string, unknown>>,
  opts: { allowRevisions?: boolean } = {},
): Promise<string> {
  const form = await api(token, 'POST', '/forms', { name, access: 'internal' });
  const formId = form.id;
  const doc = {
    schemaVersion: 1,
    pages: [{ id: 'p1', title: 'Details', sections: [{ id: 's1', fields }] }],
  };
  // allowRevisions must be ON for the submission form so a "Request revisions"
  // decision lets the author clone a new Draft revision (revise loop, AC-06-09).
  await api(token, 'PATCH', `/forms/${formId}`, {
    draftDefinition: doc,
    ...(opts.allowRevisions ? { allowRevisions: true } : {}),
  });
  await api(token, 'POST', `/forms/${formId}/publish`, {});
  return formId;
}

async function createScopedStatus(
  token: string,
  formId: string,
  key: string,
  label: string,
  color: string,
  flags: Record<string, boolean>,
): Promise<string> {
  const row = await api(token, 'POST', '/statuses', {
    entityType: 'form_submission',
    scopeId: formId,
    key,
    label,
    color,
    flags,
  });
  return row.id;
}

async function createScopedEdge(
  token: string,
  formId: string,
  fromId: string,
  toId: string,
  label: string,
): Promise<void> {
  await api(token, 'POST', '/statuses/transitions', {
    entityType: 'form_submission',
    scopeId: formId,
    fromStatusId: fromId,
    toStatusId: toId,
    label,
  });
}

async function createProfile(
  token: string,
  email: string,
  fullName: string,
): Promise<string> {
  const p = await api(token, 'POST', '/ems/profiles', { email, fullName });
  return p.id;
}

async function grantPersona(
  token: string,
  profileId: string,
  personaId: string,
): Promise<void> {
  await api(token, 'POST', `/ems/profiles/${profileId}/personas`, {
    personaId,
    scopeType: 'tenant',
  });
}

export interface StaffVariant {
  configId: string;
  submissionFormId: string;
  adminToken: string;
}

/**
 * AC-06-10/46/47 staff-actor variant. A SEPARATE config whose can_review role is
 * STAFF_ROLE-sourced (bound to the demo admin's own role) → allocation produces
 * an `actor_kind=user` assignment that the staff app surfaces and the portal does
 * not. Submission is authored by `author` (a profile) so the author-exclusion
 * leaves the admin user as the sole reviewer.
 */
export async function buildStaffVariant(
  adminToken: string,
  scenario: ClusterEScenario,
): Promise<StaffVariant> {
  const stamp = `${Date.now()}-staff`;
  // The admin's own role id (login returns roles[]).
  const me = await api(adminToken, 'POST', '/auth/login', {
    email: 'demo@example.com',
    password: 'demo1234',
    tenantSlug: TENANT_SLUG,
  });
  const adminRoleId = me.user.roles[0].id;

  const submissionFormId = await createPublishedForm(
    adminToken,
    `E2E Staff Submission ${stamp}`,
    [textField('title', 'Title')],
  );
  const reviewFormId = await createPublishedForm(
    adminToken,
    `E2E Staff Rubric ${stamp}`,
    [numberField('score', 'Score')],
  );
  // Graph: review_start = submitted (default Draft→Submitted edge).
  const graph = await api(
    adminToken,
    'GET',
    `/statuses?entityType=form_submission&scopeId=${submissionFormId}`,
  );
  const submittedId = graph.statuses.find((s: any) => s.key === 'submitted').id;

  const personas = await api(adminToken, 'GET', '/ems/personas');
  const participantPersonaId = personas.find((p: any) => p.key === 'participant').id;

  const config = await api(adminToken, 'POST', '/reviews/configurations', {
    name: `E2E Staff Reviews ${stamp}`,
    formId: submissionFormId,
    reviewFormId,
    requiredReviewCount: 1,
    scoreFieldKey: 'score',
    reviewStartStatusId: submittedId,
    windowStart: new Date(Date.now() - 3600_000).toISOString(),
    windowEnd: new Date(Date.now() + 30 * 24 * 3600_000).toISOString(),
    roles: [
      {
        key: 'author',
        label: 'Author',
        canSubmit: true,
        actorSource: 'PERSONA',
        actorIdentityKind: 'profile',
        boundPersonaId: participantPersonaId,
        sortOrder: 0,
      },
      {
        key: 'reviewer',
        label: 'Reviewer',
        canReview: true,
        actorSource: 'STAFF_ROLE',
        actorIdentityKind: 'user',
        boundStaffRoleId: adminRoleId,
        sortOrder: 1,
      },
    ],
  });

  // The author profile (scenario.author) holds the participant persona already,
  // so it may submit to THIS config too - the spec submits via the portal API
  // (subject=profile) so allocation excludes the author and assigns the admin
  // user (the STAFF_ROLE reviewer). configId returned for that submit.
  void scenario;
  return { configId: config.id, submissionFormId, adminToken };
}

export async function buildScenario(): Promise<ClusterEScenario> {
  const token = await adminLogin();
  // Soft-delete prior runs' reviewer/decider profiles so the persona pool is
  // exactly this run's reviewers (residue otherwise crowds the first-N pick).
  cleanupResidueProfiles();
  const stamp = `${Date.now()}`;

  const titleKey = 'title';
  const submissionFormId = await createPublishedForm(
    token,
    `E2E Submission ${stamp}`,
    [textField(titleKey, 'Title'), { id: 'f_abstract', type: 'textarea', key: 'abstract', label: 'Abstract', required: true }],
    { allowRevisions: true },
  );

  const reviewScoreKey = 'score';
  const reviewFormId = await createPublishedForm(
    token,
    `E2E Rubric ${stamp}`,
    [numberField(reviewScoreKey, 'Score'), { id: 'f_comments', type: 'textarea', key: 'comments', label: 'Comments' }],
  );

  // Scoped status graph. Draft→Submitted already exists from materialize_scope.
  // We add In-Review path statuses. review_start = "submitted" (submit drives
  // Draft→Submitted, which fires review.allocate).
  const submittedRow = (
    await api(
      token,
      'GET',
      `/statuses?entityType=form_submission&scopeId=${submissionFormId}`,
    )
  ).statuses.find((s: any) => s.key === 'submitted');
  const draftRow = (
    await api(
      token,
      'GET',
      `/statuses?entityType=form_submission&scopeId=${submissionFormId}`,
    )
  ).statuses.find((s: any) => s.key === 'draft');

  const acceptedId = await createScopedStatus(token, submissionFormId, 'accepted', 'Accepted', 'green', {
    isTerminal: true,
  });
  const rejectedId = await createScopedStatus(token, submissionFormId, 'rejected', 'Rejected', 'red', {
    isTerminal: true,
  });
  const revisionsId = await createScopedStatus(token, submissionFormId, 'revisions', 'Revisions', 'amber', {
    isActive: false,
  });

  await createScopedEdge(token, submissionFormId, submittedRow.id, acceptedId, 'Accept');
  await createScopedEdge(token, submissionFormId, submittedRow.id, rejectedId, 'Reject');
  await createScopedEdge(token, submissionFormId, submittedRow.id, revisionsId, 'Request revisions');

  const statuses: Record<string, string> = {
    draft: draftRow.id,
    submitted: submittedRow.id,
    accepted: acceptedId,
    rejected: rejectedId,
    revisions: revisionsId,
  };

  // Personas (seeded by EMS install). Look them up.
  const personas = await api(token, 'GET', '/ems/personas');
  const personaId = (key: string) => {
    const p = personas.find((x: any) => x.key === key);
    if (!p) throw new Error(`persona ${key} not seeded`);
    return p.id;
  };

  // Profiles.
  const authorEmail = `e2e-author-${stamp}@example.com`;
  const author: Actor = {
    profileId: await createProfile(token, authorEmail, `E2E Author ${stamp}`),
    email: authorEmail,
    fullName: `E2E Author ${stamp}`,
  };
  const reviewers: Actor[] = [];
  for (let i = 1; i <= 2; i++) {
    const email = `e2e-reviewer${i}-${stamp}@example.com`;
    const profileId = await createProfile(token, email, `E2E Reviewer ${i} ${stamp}`);
    await grantPersona(token, profileId, personaId('reviewer'));
    reviewers.push({ profileId, email, fullName: `E2E Reviewer ${i} ${stamp}` });
  }
  const dmEmail = `e2e-decider-${stamp}@example.com`;
  const decisionMaker: Actor = {
    profileId: await createProfile(token, dmEmail, `E2E Decider ${stamp}`),
    email: dmEmail,
    fullName: `E2E Decider ${stamp}`,
  };
  await grantPersona(token, decisionMaker.profileId, personaId('decision_maker'));
  // Author holds the participant persona (the can_submit role binds to it).
  await grantPersona(token, author.profileId, personaId('participant'));

  // Review configuration - persona-bound roles + status map + open window.
  const now = Date.now();
  const config = await api(token, 'POST', '/reviews/configurations', {
    name: `E2E Event Reviews ${stamp}`,
    formId: submissionFormId,
    reviewFormId,
    requiredReviewCount: 2,
    scoreFieldKey: reviewScoreKey,
    windowStart: new Date(now - 3600_000).toISOString(),
    windowEnd: new Date(now + 30 * 24 * 3600_000).toISOString(),
    reviewStartStatusId: statuses.submitted,
    acceptedStatusId: statuses.accepted,
    rejectedStatusId: statuses.rejected,
    revisionsStatusId: statuses.revisions,
    roles: [
      {
        key: 'author',
        label: 'Author',
        canSubmit: true,
        actorSource: 'PERSONA',
        actorIdentityKind: 'profile',
        boundPersonaId: personaId('participant'),
        sortOrder: 0,
      },
      {
        key: 'reviewer',
        label: 'Reviewer',
        canReview: true,
        actorSource: 'PERSONA',
        actorIdentityKind: 'profile',
        boundPersonaId: personaId('reviewer'),
        sortOrder: 1,
      },
      {
        key: 'decision_maker',
        label: 'Decision Maker',
        canDecide: true,
        actorSource: 'PERSONA',
        actorIdentityKind: 'profile',
        boundPersonaId: personaId('decision_maker'),
        sortOrder: 2,
      },
    ],
  });

  return {
    stamp,
    submissionFormId,
    reviewFormId,
    configId: config.id,
    scoreKey: reviewScoreKey,
    titleKey,
    reviewScoreKey,
    statuses,
    author,
    reviewers,
    decisionMaker,
    adminToken: token,
  };
}
