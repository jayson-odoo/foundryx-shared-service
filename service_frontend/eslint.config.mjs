// eslint.config.mjs
import { FlatCompat } from '@eslint/eslintrc';

// Create a FlatCompat instance to support legacy "extends" syntax.
const compat = new FlatCompat({
  baseDirectory: import.meta.dirname,
});

// Plan 23 T8 (AC-DLA-63) guardrail: bans arbitrary `text-[Npx]` font-size
// utilities in className strings. Ported from `sorento_crm`
// `eslint.config.mjs`'s `no-px-text-class` rule (same shape, same reasoning
// - the type scale in `css/config.reui.css` already covers every step a
// design needs, so a literal px size is always a step someone skipped, not
// a gap in the scale). A tiny inline rule is the simplest thing that works
// here - no published package exists for this project-specific string
// shape, and `no-restricted-syntax` with a regex selector can't be scoped to
// `text-[`+digits+`px]` without also matching unrelated bracket classes.
const PX_TEXT_RE = /text-\[\d+(?:\.\d+)?px\]/g;
const noPxTextClassRule = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Disallow arbitrary text-[Npx] utility classes; use the type scale from css/config.reui.css instead.',
    },
    schema: [],
    messages: {
      noPxText:
        'Do not use "{{match}}" in className. Use the type scale (text-2xs/xs/sm/base/lg/xl/2xl) from css/config.reui.css - see docs/reference/design-language.md section 2.',
    },
  },
  create(context) {
    function check(node, raw) {
      if (typeof raw !== 'string') return;
      for (const match of raw.matchAll(PX_TEXT_RE)) {
        context.report({ node, messageId: 'noPxText', data: { match: match[0] } });
      }
    }
    return {
      Literal(node) {
        check(node, node.value);
      },
      TemplateElement(node) {
        check(node, node.value.raw);
      },
    };
  },
};

// Plan 23 T8 fix round 1 (item 4) - each `no-restricted-imports` path entry
// is declared ONCE here so an override block can re-declare the rule with
// only the entries it still needs, instead of turning the whole rule `off`
// (which let `lib/toast.ts` - exempted only for `sonner` - also import a
// bare `@/components/ui/select`/`@/components/ui/table` unnoticed).
const SELECT_RESTRICTION = {
  name: '@/components/ui/select',
  message:
    'Radix Select is not searchable. Use SearchSelect (or MultiSelect for multi-value) from @/components/platform/search-select.',
};
const TABLE_RESTRICTION = {
  name: '@/components/ui/table',
  // Reworded (T8 fix round 1, item 5): the prior message said the primitive
  // was "reserved for" table-field.tsx/block-view.tsx, but neither file
  // actually imports it (measured 6 Sep 2026 - both render plain `<table>`
  // markup directly, no import of the primitive) - so the message states
  // the rule plainly instead of pointing at a non-existent allowlist.
  message:
    'Raw <table> markup is reserved for content renderers (a form table FIELD, a rendered email block) - every product table is a DataGrid (AC-DLA-56).',
};
const SONNER_RESTRICTION = {
  name: 'sonner',
  message:
    "Import { toast } from '@/lib/toast' instead - it wraps sonner with the house success/error duration + close-button defaults. Only lib/toast.ts, components/ui/sonner.tsx and components/platform/resource-actions/deferred-toast.tsx may import sonner directly.",
};

const eslintConfig = [
  ...compat.config({
    extends: ['next/core-web-vitals', 'next/typescript', 'prettier'],
    // Plugins in legacy format must be an array of plugin names.
    plugins: ['react-hooks'],
    rules: {
      // Disable react-in-jsx-scope (not needed in React 17+)
      'react/react-in-jsx-scope': 'off',
      'react/no-unescaped-entities': 'off',
      // React Hooks rules
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      '@next/next/no-img-element': 'off',
      // Plan 23 T8 (AC-DLA-63) a11y guardrail: 'warn' so a future click
      // handler on a div or an icon button that loses its label is a
      // code-review catch, not a silent regression - not 'error' because a
      // per-file/per-element audit of every pre-existing site is
      // `a11y-guardrails.inventory.test.ts`'s job (targeted, zero-allowlist
      // assertions), not this blanket rule's. `jsx-a11y` is already
      // registered by `next/core-web-vitals` (pulled in via the `extends`
      // above), so no new plugin registration is needed here.
      'jsx-a11y/click-events-have-key-events': 'warn',
      'jsx-a11y/no-static-element-interactions': 'warn',
      'jsx-a11y/control-has-associated-label': 'warn',
      // Plan 23 T8 (AC-DLA-63) - the three guardrails backing the design
      // language's "one door" rules (docs/reference/design-language.md
      // section 4): every dropdown is searchable, every product table is a
      // DataGrid, every toast goes through the house wrapper. 'error' - a
      // NEW violation of any of these three is a defect, not a style nit.
      // Per-file exemptions for the small number of legitimate/pre-existing
      // importers are declared in the override blocks below (never widen
      // these lists without a comment naming why).
      'no-restricted-imports': ['error', { paths: [SELECT_RESTRICTION, TABLE_RESTRICTION, SONNER_RESTRICTION] }],
    },
  }),
  {
    // The three sanctioned direct `sonner` importers (lib/toast.inventory.
    // test.ts is the runtime-enforced version of this same allowlist;
    // `branding.test.tsx` additionally mocks-and-reimports sonner to assert
    // against the mock directly - see that inventory test's own comment).
    // T8 fix round 1 (item 4): re-declares the rule with `sonner` REMOVED
    // from the path list (not `off`) - these files are exempt from the
    // sonner restriction only, and still can't import a bare Select/table.
    files: [
      'lib/toast.ts',
      'components/ui/sonner.tsx',
      'components/platform/resource-actions/deferred-toast.tsx',
      'components/platform/branding/branding.test.tsx',
    ],
    rules: { 'no-restricted-imports': ['error', { paths: [SELECT_RESTRICTION, TABLE_RESTRICTION] }] },
  },
  {
    // Pre-existing bare-Select debt (measured 5 Sep 2026), tracked and OPEN
    // in documentation/backlogs/backlog.md - BL-062 (searchable dropdowns
    // everywhere, sweep of pre-existing plain Selects) and BL-SS-043
    // (connections form's provider `select` fields specifically). This
    // guardrail's job is to stop the count growing, not to burn it down in
    // a guardrails-only slice (plan 23 T8) - a file leaves this list the day
    // it migrates to SearchSelect/MultiSelect. T8 fix round 1 (item 4):
    // re-declares the rule with `select` REMOVED from the path list (not
    // `off`) - these files are exempt from the select restriction only, and
    // still can't import a bare table/sonner.
    files: [
      'app/(protected)/ideation/ideas/components/idea-form-fields.tsx',
      'app/(protected)/settings/integrations/components/connection-form-fields.tsx',
      'app/(protected)/components/demo1/light-sidebar/components/earnings-chart.tsx',
      'app/(protected)/omnichannel/settings/workspaces/components/workspace-form-fields.tsx',
      'app/(protected)/omnichannel/inbox/components/thread-list.tsx',
      'app/(protected)/user-management/users/components/user-form-fields.tsx',
      'components/ui/data-grid-pagination.tsx',
      'components/platform/resource-list/filter-builder.tsx',
      'components/platform/channel-connect-wizard/channel-connect-wizard.tsx',
    ],
    rules: { 'no-restricted-imports': ['error', { paths: [TABLE_RESTRICTION, SONNER_RESTRICTION] }] },
  },
  {
    // Plan 23 T8 (AC-DLA-63): text-[Npx] is an error everywhere in feature
    // code except the vendor-derived demo1 layout (Metronic's own markup)
    // and non-ts/tsx vendor CSS (ESLint only lints ts/tsx, so the CSS half
    // of this exemption is descriptive, not enforced by a file pattern
    // here). Measured 5 Sep 2026: zero files anywhere in the tree currently
    // use the banned pattern, demo1 included - the ignore is a forward
    // allowance for Metronic-derived markup, not a live debt list (unlike
    // Sorento's, which ported a real 82-file backlog).
    files: ['**/*.{ts,tsx}'],
    ignores: [
      'app/components/layouts/demo1/**',
      // Test fixtures that deliberately contain the banned string as an
      // example of what the rule catches (this rule's own "the rule fires"
      // proof).
      'eslint.config.text-px-rule.test.ts',
    ],
    plugins: {
      local: { rules: { 'no-px-text-class': noPxTextClassRule } },
    },
    rules: { 'local/no-px-text-class': 'error' },
  },
  {
    ignores: ['.next/**', 'node_modules/**', 'prisma/**'],
  },
];

// Exported (in addition to the default config) so
// `eslint.config.text-px-rule.test.ts` can drive the rule directly through
// ESLint's own `Linter` class - see AC-DLA-63.
export { noPxTextClassRule };
export default eslintConfig;
