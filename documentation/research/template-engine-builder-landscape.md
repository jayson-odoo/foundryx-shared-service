# Research: Template Engine & Design-Tool Landscape

> Researched 2026-06-07 (two parallel deep-research passes: OSS library landscape + EMS competitor analysis).
> Feeds the Template Engine plan (sprint-2) and the future Website Builder plan. Source links at the bottom of each section.

## 1. The headline conclusion

**One visual builder CANNOT serve email + webpage + badge/ticket.** Two independent research passes converged on this:

1. **Technically irreconcilable output models.** Email = table-based/MJML HTML with inline styles (Outlook still chokes on modern CSS). Webpage = responsive flow DOM rendered by real React components. Badge/ticket = absolute-positioned, mm-precise, fixed-dimension print canvas. Forcing one editor means email that breaks in Outlook, OR a canvas that can't do responsive flow, OR a flow builder that can't do print-precise placement.
2. **Every successful EMS product runs separate purpose-built editors.** Eventbrite, Cvent, Bizzabo, Hopin, Swoogo, Webex Events - all of them ship three distinct tools. None unified the canvas.

**What IS shared - the real reuse seam:**

- **The merge-field / data-tag system.** Cvent is the clearest example: 40+ data tags work identically in the Site Designer AND the email designer - different editors, one tag vocabulary. For Foundryx this maps directly onto the rule-engine **fact registry** (`actor.*`, `record:*` facts) - we already have the cross-surface data vocabulary built.
- **The brand asset library.** Splash's best-loved feature: upload colors/fonts/logos once, every surface auto-brands. For Foundryx this is `tenant_branding` (sprint-2/03) - also already built.
- **The render pipeline + JSON schema philosophy.** Store a portable JSON tree per surface; each surface has its own compiler (JSON→MJML→HTML for email, JSON→React for web, JSON→SVG→PDF for badges).

So the "Template Engine" is **one engine, several editors**: shared template store, shared merge fields, shared brand assets, shared render-dispatch - per-surface editor UIs and compilers.

## 2. Editor paradigm: structured blocks win, free-form loses

Strong market signal on how much design freedom event organizers actually use:

| Platform | Freedom level | Market verdict |
|---|---|---|
| **Luma (lu.ma)** | Locked themes + slots (40+ themes, curated fonts, NO custom HTML/CSS) | Most loved low-end product. Simplicity IS the product. |
| **Eventbrite** | Fixed sections, fill-in-the-slots (not even drag-drop) | Works; complaints target email send limits, not layout. |
| **Cvent / Swoogo / Hopin** | Structured widget/block editors + side panel | The enterprise mainstream. |
| **Splash** | True free-form WYSIWYG | Output praised ("beautiful") but builder called "limiting, clunky, dated"; $21.5K/yr Pro. Free-form raises the praise ceiling AND the complaint floor. |

**Implications:**

- Default UX = **themes/templates with slots** - organizers start from a gallery, not a blank canvas.
- Editor model = **two-level structure**: **Section** (layout row: columns/widths/background) → **Block** (content: text, image, button, divider, spacer, social). This is Brevo's model - the cleanest documented block grammar in the industry.
- The escape hatch for the ~10% power users = a **custom-HTML block** (sanitized), NOT pixel freedom. Every structured platform ships one (Swoogo, Bizzabo, Brevo).
- Industry UX trend: moving from side-panel editing → **inline on-canvas editing** (Mailchimp's new builder). Prefer click-text-edit-in-place over click-then-edit-in-sidebar where feasible.
- **Conditional logic is the single most-demanded "advanced" feature** across email AND badges (show section/element by attendee type, registration field, payment status). Cvent's rebuilt badge designer leads with it; Webex badges have per-element visibility rules. For Foundryx: **the rule engine plugs in as block/section visibility conditions** - a `conditions_json` on a block, evaluated against the same facts that drive transitions. Design the block schema for this from day one.

## 3. The block schema is a forever-contract

Mailchimp's cautionary tale: their classic builder and new builder have **non-portable content** - templates built in one cannot open in the other. A hard migration wall stranding years of customer content.

Rules for Foundryx:

- The JSON block schema gets a **`schemaVersion`** from day one and a written upgrade policy (migrate-on-read or migrate-on-write).
- Keep the schema **editor-agnostic**: it describes content + layout intent, not editor internals. If we swap editor libraries later, content survives.
- Never store compiled HTML as the source of truth - always the JSON tree; compiled output is a cache/derivative.

## 4. OSS library landscape (React 19 / Next 15 embeddable)

### 4.1 Email builders

| Lib | License | Verdict |
|---|---|---|
| **GrapesJS + grapesjs-mjml** | BSD-3 / MIT | Most mature embeddable email DnD editor. MJML source → server-compiled Outlook-safe HTML. React 19 via `@grapesjs/react`. Pain: imperative API, heavy, its own CSS layer (clashes with our no-global-CSS rule - needs containment). Fully self-hostable, no fees. |
| **Maily.to** | MIT | Modern TipTap/shadcn block-style email composer. Clean React stack, active. Block-stack paradigm (Notion-ish), not table-canvas. Less Outlook-battle-tested than MJML. |
| **Unlayer (react-email-editor)** | wrapper MIT, **editor = hosted SaaS** | **REJECT.** Open-core trap: actual editor loads from Unlayer cloud, custom tools/white-label paid ($250+/mo), not self-hostable. Unacceptable for a resold PaaS. |
| **easy-email (zalify)** | MIT core, **frozen** | **REJECT.** Free core stale since ~Sep 2024; effort moved to paid client-ID-gated `Easy-Email-Pro`. React 18-era MUI deps. |
| **react-email** | MIT | Code-first (devs write React → email HTML). Not a tenant-facing visual builder; JS-only renderer (awkward for Python backend). Good reference for email-safe component patterns. |

**Email render path recommendation:** JSON block tree → **MJML** document → `mjml` compile (server-side, Node CLI or sidecar) → email-safe HTML → merge-field render → `email_outbox`. MJML solves the Outlook/Gmail/Apple-Mail matrix once; we never hand-write `<table>` soup. Alternative if we avoid the Node dependency: hand-rolled table-HTML compiler for our limited block set (Brevo-style block grammar is small enough to compile ourselves - text/image/button/divider/columns each have known-good table patterns).

### 4.2 Webpage builders (future plan - recorded for then)

| Lib | License | Verdict |
|---|---|---|
| **Puck** (`@measured/puck`) | MIT | **Front-runner for the website builder.** JSON tree mapped to OUR OWN React components (fits the Resource-shell/design-system ethos perfectly), clean SSR `<Render>` separate from editor, active (~13k★), AI-gen in 0.21. Risks: pre-1.0 API churn; **React 19 peer-dep must be verified at install**. |
| **GrapesJS** | BSD-3 | Could double as web builder (one editor codebase email+web) but blocks are HTML-strings, not React components - loses design-system integration. |
| **Craft.js** | MIT | Plan §2.4 named it, but: bus-factor 1, sporadic maintenance, you build the entire editor UI yourself, React 19 unconfirmed. **Downgrade from the plan's suggestion.** |
| **react-page** | MIT | Stagnant, single maintainer, React 18-era. **REJECT.** |
| **Builder.io / Plasmic** | open-core | Editor + backend are proprietary SaaS - embedding a competitor's hosted surface in our PaaS, per-MAU pricing, lock-in. **REJECT.** |
| **BlockNote** | MPL-2.0 | Notion-style document editor - wrong shape for page layout. (Possible fit for a rich-text BLOCK inside other editors.) |

### 4.3 Badge/ticket canvas (backlogged - recorded for then)

Fixed-dimension absolute-position editor - genuinely different from flow builders:

| Lib | License | Verdict |
|---|---|---|
| **Konva / react-konva** | MIT | Build-your-own canvas editor. Full control, free; high effort. |
| **Fabric.js** | MIT | Same class; richer built-in object editing + JSON serialization. |
| **Polotno SDK** | **Commercial** | Canva-grade badge UX out of the box (Konva-based). Paid license - budget if we want the shortcut. |
| **tldraw** | revenue-gated | Overkill + licensing caveat. |

**Badge reference implementation = Webex Events badge designer:** fixed-size canvas (multiple badge sizes, single/double-sided), text/image/shape elements, **User-Info dynamic fields** (per-element data binding), **visibility rules per element by attendee type**, drag + arrow-key nudge + smart alignment guides, Zebra direct-print. Cvent's rebuilt Badge Designer adds batch PDF (sync auto-PDF; async batch of 200).

**Canva Bulk Create = the data-merge model:** placeholder elements bound to data columns, one row → one rendered artifact, batch render. Identical in spirit to binding canvas elements to fact-registry fields.

**PDF generation:**

| Engine | License | Verdict |
|---|---|---|
| **WeasyPrint** (Python) | BSD | **Native FastAPI fit.** Smallest PDFs (8-21KB), no headless browser, no JS execution (fine - badges are static). CSS `@page { size: 54mm 86mm }` for fixed dims. ~230-630ms/doc cold. |
| **Puppeteer print-to-PDF (headless Chromium)** | Apache | Only if templates need JS or CSS Grid; ~300MB Chromium + process babysitting. |

Path: canvas JSON → SVG/PNG → fixed-size HTML → WeasyPrint.

## 5. Merge-field syntax survey

| Platform | Syntax |
|---|---|
| Brevo | `{{ contact.FIRSTNAME }}` (Jinja-like "Brevo Template Language") |
| RSVPify | `{first_name}` |
| Cvent | named data tags (dropdown-inserted) |
| Mailchimp | `*\|FNAME\|*` merge tags + dynamic content |
| Plan §1.2.4 | Handlebars/Mustache `{{user.name}}`, partials `{{> event_header}}` |

`{{ dotted.path }}` double-curly is the modern norm and matches both the plan and Jinja2 (already our email templating). Foundryx already has the **merge-field-editor** component (status-engine notifications, chips + in-place preview - CLAUDE.md says "the standard template-builder input, BL-024 adopts") and the **fact registry** as the field vocabulary. One canonical token grammar across all surfaces.

## 6. What this means for Foundryx product quality

1. **We're building the Cvent architecture with better seams.** Their data-tag system is bolted across products; ours is a first-class engine (rule-engine facts) that emails, badges, web pages, AND workflow conditions all share. That's a genuine differentiator, not just parity.
2. **Don't chase Splash.** Free-form looks impressive in demos and bleeds usability complaints in production. Structured blocks + great themes + brand-asset auto-styling = the loved experience (Luma proof).
3. **Conditional content is the premium feature to nail** - "show this section only to VIP ticket holders", "badge shows speaker ribbon if role=speaker". Competitors gate this behind enterprise tiers; our rule engine makes it nearly free to offer everywhere. Schema must carry per-block/element `conditions_json` from v1 (even if UI lands later).
4. **Brand assets must flow automatically.** A new template should open pre-branded from `tenant_branding` (logo, colors, fonts) - Splash's killer feature, and we already store the assets.
5. **Schema versioning is product insurance.** Mailchimp's migration wall is a warning: tenants will build hundreds of templates; the JSON contract outlives any editor library we pick.
6. **Editor-library churn is expected - isolate it.** Pre-1.0 Puck, GrapesJS API style, TipTap majors: the editor must live behind our own component boundary (like FlowCanvas wraps react-flow), with the JSON schema as the only contract.

## 7. Engineering-blog signal

No public architecture write-ups from Eventbrite/Cvent/Splash on their editors. The de-facto engineering documentation is vendor help-centers/release notes (Cvent release notes, Webex KB, Brevo block docs, Mailchimp classic-vs-new). The existence of the embeddable-builder licensing market (Unlayer, BEE, Polotno) is itself signal: a robust visual editor is hard enough that most platforms license rather than build - which is why the OSS-clean picks (GrapesJS/MJML, Puck, Konva, WeasyPrint) matter for our COGS.

## Sources

**Libraries:** [Puck](https://github.com/puckeditor/puck) · [Craft.js](https://github.com/prevwong/craft.js/) · [GrapesJS](https://github.com/GrapesJS/grapesjs) · [grapesjs-mjml](https://github.com/GrapesJS/mjml) · [Unlayer pricing](https://unlayer.com/pricing) · [easy-email](https://github.com/zalify/easy-email-editor) · [Maily.to](https://github.com/arikchakma/maily.to) · [react-email](https://react.email) · [Builder.io self-host thread](https://forum.builder.io/t/is-builder-io-open-source-software-can-we-self-host/2634) · [Plasmic codegen](https://docs.plasmic.app/learn/codegen-guide/) · [BlockNote](https://github.com/TypeCellOS/BlockNote) · [react-page](https://react-page.github.io/) · [MJML vs React Email](https://www.htmlemailbuilders.com/compare/mjml-vs-react-email) · [HTML→PDF benchmark 2026](https://pdf4.dev/blog/html-to-pdf-benchmark-2026) · [Konva vs Fabric](https://dev.to/lico/react-comparison-of-js-canvas-libraries-konvajs-vs-fabricjs-1dan)

**Competitors:** [Luma themes](https://help.luma.com/p/event-themes-and-customization) · [Cvent Badge Designer](https://release.cvent.com/eventmanagement/announcements/spotlight-badge-designer) · [Cvent Site Designer](https://support.cvent.com/s/communityarticle/Using-the-Site-Designer) · [Cvent data tags](https://support.cvent.com/s/communityarticle/Data-Tag-Cheat-Sheet) · [Eventbrite email FAQ](https://docs-eb.toneden.io/send-an-email-campaign/email-campaigns-faq) · [Swoogo builder series](https://swoogo.events/video-series/website-builder/) · [RSVPify merge tags](https://help.rsvpify.com/en/articles/4944901-what-are-merge-tags-how-do-i-use-them) · [Webex Events badge designer](https://help.socio.events/en/articles/5558077-design-onsite-badges) · [Whova badge templates](https://whova.com/blog/name-badge-templates-customizations/) · [Splash design](https://splashthat.com/platform/design) · [Splash G2](https://www.g2.com/products/splash/reviews) · [Mailchimp builders](https://mailchimp.com/help/about-mailchimps-email-builders/) · [Brevo editor](https://help.brevo.com/hc/en-us/articles/360016831820-Overview-of-the-Drag-Drop-email-editor) · [Brevo template language](https://help.brevo.com/hc/en-us/articles/360000946299-Personalize-your-messages-with-dynamic-content-Brevo-Template-Language) · [Canva Bulk Create](https://www.canva.com/help/bulk-create/)
