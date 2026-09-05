/**
 * Present-continuous form of a `ResourceAction.label` for a deferred
 * countdown's copy (sprint-4/23, T5, D2): "Delete permanently" -> "Deleting
 * permanently", so the countdown reads "Deleting in 10s" / "Deleting 3
 * users in 8s" rather than the bare imperative label. Only the FIRST word
 * (the verb) is conjugated; every registered action's label leads with one
 * (Delete/Trash/Archive/Disconnect/...).
 */
export function presentContinuous(label: string): string {
  const [first, ...rest] = label.trim().split(/\s+/);
  if (!first) return label;
  const verb = /e$/i.test(first) && !/ee$/i.test(first) ? `${first.slice(0, -1)}ing` : `${first}ing`;
  return [verb, ...rest].join(' ');
}

/**
 * Past-tense form of a `ResourceAction.label`'s leading verb (fix round 1,
 * item 13) - "Delete" -> "Deleted", "Trash" -> "Trashed" - for the commit
 * toast ("User trashed.", "Role deleted.") instead of a bare generic
 * "Done." that names neither what happened nor to what. A tiny irregular
 * set covers this app's own registered action labels (Set/Reset already
 * read as past tense unconjugated).
 */
const IRREGULAR_PAST: Record<string, string> = {
  set: 'Set',
  reset: 'Reset',
};

export function pastTense(label: string): string {
  const [first, ...rest] = label.trim().split(/\s+/);
  if (!first) return label;
  const irregular = IRREGULAR_PAST[first.toLowerCase()];
  const verb = irregular ?? (/e$/i.test(first) ? `${first}d` : `${first}ed`);
  return [verb, ...rest].join(' ');
}

/** Singular/plural display noun for a registered deferred action's
 * `entityType` - shared by the row, bulk and form surfaces so a commit
 * toast reads "User trashed." / "3 users trashed." rather than a bare
 * entity-type key. An unmapped type still gets a naive plural/bare
 * singular rather than nothing. */
// Exported (not just used internally) so `deferred-verb.entity-nouns.
// inventory.test.ts` can assert every registered `entityType` has a human
// noun without re-deriving this map from source text (T5 fix round 2, S6).
export const ENTITY_NOUNS: Record<string, { singular: string; plural: string }> = {
  user: { singular: 'user', plural: 'users' },
  role: { singular: 'role', plural: 'roles' },
  workflow: { singular: 'workflow', plural: 'workflows' },
  form: { singular: 'form', plural: 'forms' },
  template: { singular: 'template', plural: 'templates' },
  connection: { singular: 'connection', plural: 'connections' },
  ai_agent: { singular: 'AI agent', plural: 'AI agents' },
  ai_skill: { singular: 'AI skill', plural: 'AI skills' },
  document_file: { singular: 'file', plural: 'files' },
  document_share: { singular: 'link', plural: 'links' },
  product: { singular: 'product', plural: 'products' },
  tenant: { singular: 'tenant', plural: 'tenants' },
  // T5 fix round 2, S6: the remaining registered `entityType`s (core +
  // omnichannel + ideation + the app-store module type added by S2) - a
  // missing entry used to leak the raw registry key into a toast
  // ("Ideation_idea deleted.").
  document_type: { singular: 'document type', plural: 'document types' },
  background_job: { singular: 'job', plural: 'jobs' },
  email_outbox: { singular: 'email', plural: 'emails' },
  channel: { singular: 'channel', plural: 'channels' },
  workspace: { singular: 'workspace', plural: 'workspaces' },
  wa_template: { singular: 'WhatsApp template', plural: 'WhatsApp templates' },
  webhook_endpoint: { singular: 'webhook', plural: 'webhooks' },
  quick_reply: { singular: 'quick reply', plural: 'quick replies' },
  api_key: { singular: 'API key', plural: 'API keys' },
  ideation_idea: { singular: 'idea', plural: 'ideas' },
  ideation_business_requirement: {
    singular: 'business requirement',
    plural: 'business requirements',
  },
  ideation_br_idea_link: { singular: 'link', plural: 'links' },
  ideation_embed_connection: { singular: 'embed connection', plural: 'embed connections' },
  tenant_module: { singular: 'module', plural: 'modules' },
};

function capitalize(word: string): string {
  return word.length > 0 ? word[0].toUpperCase() + word.slice(1) : word;
}

export function entityNoun(entityType: string, count: number): string {
  const entry = ENTITY_NOUNS[entityType];
  if (count > 1) return entry ? entry.plural : `${entityType}s`;
  return entry ? entry.singular : entityType;
}

/**
 * The commit toast copy for a settled deferred action - "User trashed."
 * (single record) or "3 users trashed." (bulk). Composes from ONLY the
 * label's leading verb (never the rest of a multi-word label like "Delete
 * role"/"Reset to default") - the entity noun already supplies the object,
 * so keeping trailing words would double it up ("Role deleted role.").
 */
export function deferredDoneMessage(label: string, entityType: string, count: number): string {
  const [firstWord] = label.trim().split(/\s+/);
  const verb = (firstWord ? pastTense(firstWord) : label).toLowerCase();
  const noun = entityNoun(entityType, count);
  return count > 1 ? `${count} ${noun} ${verb}.` : `${capitalize(noun)} ${verb}.`;
}
