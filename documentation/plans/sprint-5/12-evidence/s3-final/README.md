# sprint-5/12 S3 (final build) - agent-browser run log

Recorded 2026-09-22 by the lane tester at HEAD `e1857aac` - the commit that moved the
post-apply hydration to `applyView`. This re-runs **AC-12-24** on the FINAL build, because the
`s2-real` shots were taken one commit earlier. Tool: `agent-browser` CLI, `--session s50t`,
headless Chrome. NO Playwright. Widths 1280x900 and 375x812.

## Stack under test

| Piece | Value |
|---|---|
| Frontend | :3012, prod build of `e1857aac` (`lsof` cwd = `.claude/worktrees/s50/service_frontend`) |
| Backend | :8012, uvicorn without `--reload`, lane env, DB `foundryx_service_s50` |
| Auth | real login `demo@example.com` at `localhost:3012`, tenant `default` |
| Entity | company `Mocha s50` (`autocount_http`), entity `product` |

Starting state: the product mapping was bent back (SQL, fixture only - the same device the
`s2-real` run used) to the production `SRT` baseline of UAC section 0: `ItemCode -> name`, plain
`Description -> description` with no formula, `ListPrice -> list_price`, `uom_code` ENABLED.

## Navigation - real clicks only

Sidebar `AutoCount` -> `Companies` -> row `Mocha s50` -> tab `Entities` -> the Product row's
`Actions` menu -> `Configure mapping` -> page `Actions` -> `Reset to preset`.

(The entities grid scrolls horizontally at 1280; the row `Actions` button is reached through
that existing container scroll, not a relocated control.)

## Shots

| File | What it proves | AC |
|---|---|---|
| `01-1280-action-menu-reset-to-preset.png` | The mapping page's `ActionMenu`: exactly one item, `Reset to preset` (server-derived `hasPreset`) | AC-12-21 |
| `02-1280-reset-dialog-diff.png` | The REAL `dryRun:true` diff: `Code` unchanged, **`Name` changed**, **`Description` changed** (the Desc2 join as a `ClampedText` chip), `Category code` / `Brand code` unchanged, **`Uom code` changed + "Disabled - withheld by the preset"**, `Is active` unchanged, **`List price` changed** (the `<= 0` clamp). `Required` badges on Code / Name / Is active | AC-12-12, AC-12-22 |
| `03-1280-after-apply-toast-no-reload.png` | `dryRun:false`: toast "Mapping reset to preset.", dialog closed, table showing the preset rows - `Description` with the join formula, `BaseUOM` dimmed with a `Disabled` badge, `BaseUOMPrice` with the clamp | AC-12-13, AC-12-23, AC-12-25 |
| `04-1280-after-save-already-matches.png` | `Edit` -> `Save mapping` -> re-open: "This mapping already matches the preset.", `Reset mapping` **disabled**. `uom_code` is still `is_enabled=false` in the DB after that Save | AC-12-22, AC-12-26 |
| `05-375-after-save-already-matches.png` | Same at 375, non-clipped (`scrollWidth === innerWidth === 375`) | AC-12-33 |
| `06-375-reset-dialog-diff.png` | A non-empty diff at 375: row cards stack, the formula clamps, the row list scrolls INSIDE the dialog (`dialog.scrollWidth <= clientWidth`), page does not overflow | AC-12-22, AC-12-33 |

## AC-12-23 "re-renders from the returned view" - measured, not assumed

`agent-browser network requests`, tail, across the open-dialog + apply:

```
POST .../entities/product/mapping/reset-preset (Fetch) 200      <- the dry run
GET  http://localhost:3012/api/auth/session    (Fetch) 200
POST .../entities/product/mapping/reset-preset (Fetch) 200      <- the apply
```

**No `GET .../entities/product/mapping` after the apply POST** (the last one in the log precedes
the dialog opening) and no document navigation. The table on screen after the apply is rendered
from the `MappingViewResponse` the POST returned - `applyView`, `e1857aac`.

## DB after the run

```
ItemCode     | code          | enabled
Description  | name          | enabled
Description  | description   | enabled   formula = the Desc2 join
ItemGroup    | category_code | enabled
ItemBrand    | brand_code    | enabled
BaseUOM      | uom_code      | DISABLED  (withheld by the preset)
IsActive     | is_active     | enabled
BaseUOMPrice | list_price    | enabled   formula = the <= 0 clamp
```

8 rows - no `is_discontinued` (AC-12-06, ruling R4). The lane is left in this state.

## Console

Zero errors across the run. Only the codebase-wide Radix
`Missing Description or aria-describedby for {DialogContent}` warnings (3), which pre-date this
plan.
