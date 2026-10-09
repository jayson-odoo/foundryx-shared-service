# T8 evidence - guardrails and docs (plan 23)

## Fix round 1 (this session)

Worktree `.claude/worktrees/s23`, branch `sprint-4/23-T8-guardrails`, `agent-browser --session
t8fix1`. Real clicks from `/`, `demo@example.com` / `demo1234`, against a fresh `rm -rf .next &&
npm run build` + `npx next start -p 3002` build of this worktree. Full test-report section:
`documentation/plans/sprint-4/23-design-language-alignment-test-report.md` ## T8 - Fix round 1.

Run log (item 1, the `DropGap` blocker):

1. Logged in, expanded Settings, clicked into "Templates" - the sidebar's accordion-wrapped nav
   links did not respond to `agent-browser click <ref>` (URL never changed); switched to a native
   `el.click()` via `eval --stdin`, which navigated correctly every time thereafter.
2. Opened the "Password reset" template's Design tab, clicked Edit.
3. Screenshotted 1280px while hovering the "Hi {{recipient.firstName}}" text block - drag handle
   + up/down/delete controls visible, NORMAL tight spacing to the neighbouring blocks (no dead
   space): `fixround1-01-email-editor-1280.png`.
4. Set the viewport to 375px, screenshotted the same page (palette stacked above the canvas):
   `fixround1-02-email-editor-375.png`.
5. Attempted a mid-drag capture. The brief flagged `mouse down/up` as unable to produce `:active`
   - true for a bare down/up pair, but a `mouse down` → several `mouse move` steps → `screenshot`
   → `mouse up` sequence DID drive dnd-kit's `PointerSensor` (confirmed: the block order actually
   changed after the sequence completed). Captured mid-drag: `fixround1-03-drag-mid-frame.png`
   (dragged "Heading" chip following the cursor, dashed drop-gap outlines revealed between every
   block pair with none of them shifting position).
6. **Found a real regression while capturing #5, not by inspection**: the new drop-gap overlay
   (`h-6`, overflowing its `h-2` wrapper by 8px each side by design) was still in the pointer
   hit-test path while fully transparent - `elementFromPoint` over a neighbouring block's own
   content resolved to the overlay, silently swallowing that block's hover/click in the overlap
   band (its drag handle never appeared - `getBoundingClientRect()` on `block-handle-*` came back
   all-zero even after a real hover). Fixed with `pointer-events-none` on the overlay (a second
   commit on item 1, not folded into the first - see the test report). Re-verified:
   `elementFromPoint` now resolves to the block's own content, and hover reveals the handle with
   a real non-zero rect.
7. Any accidental reorders produced while proving the drag worked were undone (`Undo` button /
   `Cancel` → "Discard changes") before ending the session - no persisted change to the
   platform-tier "Password reset" template.

Evidence files:

- `fixround1-01-email-editor-1280.png` - 1280px, Design/Edit, hover state, normal spacing.
- `fixround1-02-email-editor-375.png` - 375px, same page, responsive stack.
- `fixround1-03-drag-mid-frame.png` - genuine mid-drag frame (see step 5).

## AC-DLA-66 artifact (original T8 slice)

`reviewer-rows.md` - proposed `.claude/agents/reviewer.md` rows (that directory is gitignored and
absent from this worktree per AC-DLA-66's own brief); the main session applies these to its own
gitignored copy. Fix round 1 item 6 corrected a typo in it (`lib.toast.ts` -> `lib/toast.ts`).
