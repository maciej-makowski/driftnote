# Dark-Mode UI Redesign + Complete Calendar Grid

> Design spec for [issue #4](https://github.com/maciej-makowski/driftnote/issues/4).

## Goal

Replace the utilitarian light theme on Driftnote's web UI with a flat dark theme using a coherent purple-accent palette, fix the calendar grid so it always renders six rows with prev/next-month pad cells visibly dimmed (day numbers shown), and give the monthly email digest a parallel light-theme polish pass.

## Scope

**In scope:**
- Full rewrite of `src/driftnote/web/static/style.css` from current 23 lines to a CSS-custom-property-driven dark theme.
- Calendar grid: always six rows, every cell carries `day_of_month`, pad cells dimmed but legible.
- Today's cell: 1px outline in accent color (no fill).
- Tag cloud, entry view, edit view, admin: re-themed per the palette below.
- Mobile (< 600px viewport): drop the weekday header row, shrink calendar cell padding/height. Calendar stays a 7-column grid.
- Email digest (`monthly.py`): coherent light-theme polish using a parallel light palette (typography hierarchy, accent color for "view in app" link, pad cells with day numbers).

**Out of scope:**
- Light/dark toggle. Single dark theme on web.
- Per-user theming.
- Visual regression snapshot tooling. PR includes manual screenshots.
- Tag-as-link wiring (issue #9 — separate PR).
- Calendar photo thumbnails (issue #11 — separate PR).
- Visual word cloud (issue #10 — separate PR).

## Palette

### Web (dark) — defined as CSS custom properties at the top of `style.css`

```css
:root {
  --bg:           #1e1e1e;   /* canvas */
  --bg-raised:    #252525;   /* cards, sections, raised surfaces */
  --bg-hover:     #2d2d2d;   /* calendar cell hover */
  --fg:           #e5e5e5;   /* primary text */
  --fg-muted:     #a0a0a0;   /* secondary, weekday labels, day-of-month numbers */
  --fg-dim:       #5a5a5a;   /* prev/next-month pad cells, very subdued text */
  --accent:       #bb9af7;   /* purple — links, focus, today's outline, accent stripe */
  --accent-hover: #d2b8ff;
  --border:       #333;
  --warn-bg:      #3b2a1a;
  --warn-fg:      #f5c542;
  --error-bg:     #3b1a1a;
  --error-fg:     #ff6b6b;
  --ok:           #6dbf6d;   /* status dots */
  --status-warn:  #f5c542;
  --status-error: #ff6b6b;
}
```

### Email digest (light) — inline-styled in `monthly.py`

```
bg              #ffffff
bg-raised       #f7f6fb   (subtle purple-tinted off-white for the calendar background)
fg              #1f1d2b
fg-muted        #6c6a78
fg-dim          #c4c2cc   (pad cells)
accent          #6c4fc4   (deeper purple, readable on white)
border          #e5e4ed
```

The two palettes are intentionally not shared via variables — the email is a self-contained HTML document with inline styles, where the web rewrites the global stylesheet. Visual coherence comes from the shared accent family (purple), not from shared tokens.

## Typography

- Font: keep `system-ui, sans-serif`.
- Hierarchy:
  - `h1`: 24px, weight 600
  - `h2`: 18px, weight 600
  - `body`: 15px, line-height 1.5
  - `.dom` (day-of-month label in calendar): 11px, `--fg-muted`
- No custom web fonts. No icon font.

## Theme rules (flat aesthetic)

1. **No box-shadows anywhere.** Remove the few inherited drop-shadows from htmx defaults if they appear.
2. **No gradients.**
3. **No combination of border-radius + visible border.** Use one or the other:
   - Cards: filled background, no border, no rounding.
   - Banners: filled background, single solid `border-left: 4px`, no rounding.
   - Buttons: filled background, no border, no rounding.
   - Inputs: subtle 1px border (`--border`), no rounding.
4. **Hover states**: change background only (`--bg-hover` for cells, `--accent-hover` for accent links). No transform, no shadow.
5. **Focus states**: 2px solid `--accent` outline with `outline-offset: 2px`. Replaces browser default ring.

## Components

### Top bar (`base.html.j2`)
- Background: `--bg`. Bottom border: 1px `--border`.
- Brand: `--fg`, weight 700.
- Nav links: `--fg-muted` default, `--accent` on hover.

### Banners (`base.html.j2`)
- Already has `.banner-warn` and `.banner-error`. Re-theme:
  - Warn: `background: --warn-bg`, `color: --warn-fg`, `border-left: 4px solid --warn-fg`.
  - Error: `background: --error-bg`, `color: --error-fg`, `border-left: 4px solid --error-fg`.
- No `border-radius`.

### Calendar (`calendar.html.j2` + `moodboard.py`)

**Backend (`moodboard.py`):**
- `MonthlyCell.day_of_month: int` — always populated (currently `int | None`, `None` for pad cells). This is a typed-API change.
- `MonthlyCell.emoji: str | None` — pad cells stay `None` (no mood data outside the month).
- `monthly_moodboard_grid(...)`: extend the loop until `len(rows) == 6`, even when the natural calendar layout fits in 5. Pad rows continue from the following month.
- The existing test `test_monthly_moodboard_returns_calendar_rows` asserts `len(rows) >= 5`; tighten to `len(rows) == 6` and add assertions that pad cells carry `day_of_month`.

**Template (`calendar.html.j2`):**
- Render `c.day_of_month` for every cell (pad and in-month alike).
- Pad cells: add `dim` class. In-month cells with no entry: still show `dom`, the emoji slot falls back to `·` in `--fg-muted`.
- Today's cell: add `today` class. CSS gives it a 1px solid `--accent` outline, no fill.
- Cell hover: `background: --bg-hover`. Cells stay clickable for in-month cells only (current behavior); pad cells are non-interactive.

**Mobile (`@media (max-width: 600px)`):**
- Hide `.calendar thead`.
- Reduce `td` height to 40px, padding to 2px.
- Reduce `.dom` font-size to 10px, `.emoji` to 16px.
- Layout stays a 7-column grid (no stacking).

### Tag cloud (`tags.html.j2`)
- Pills: `background: --bg-raised`, `color: --fg`, `padding: 2px 8px`. No `border-radius`. No border.
- Frequency-based font-size: keep current formula (`0.8 + count*0.1` rem).
- Inline-style on `<a>` is acceptable here (it's a generated dynamic value driven by tag frequency); other static inline styles in admin/search templates are removed per the rules in those sections.

### Entry view (`entry.html.j2`)
- Wrap content with a 4px `border-left: 4px solid --accent` on `<article class="entry">` plus 16px `padding-left`.
- Photo thumbnails: remove `border-radius: 8px`. Plain rectangles. Keep `max-width: 240px`.
- Video: remove `border-radius`.
- Tags: each tag rendered as a flat pill (consistent with tag cloud), no underline.
- Mood span: 26px (current).

### Edit view (`entry_edit.html.j2`)
- Textarea: `background: --bg-raised`, `color: --fg`, `font-family: ui-monospace, Menlo, monospace`, `font-size: 14px`, `border: 1px solid --border`, no `border-radius`. Width 100%.
- Live preview block: `background: --bg`, `border-left: 4px solid --accent`, `padding: 12px 16px`. Visually distinct from the textarea (different background, accent stripe).
- Save button: `background: --accent`, `color: --bg`, `padding: 8px 16px`, no border, no `border-radius`.
- Cancel link: `color: --fg-muted`, hover `--accent`.

### Admin (`admin.html.j2`)
- Job-cards: `display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px;`.
- Each card: `background: --bg-raised`, `padding: 12px 16px`. No border, no `border-radius`. h2 16px, body 14px.
- Status dot: 8px solid circle (`border-radius: 50%` is the one acceptable circle exception — required for the dot shape) inline before the status text. Color resolved from a class: `.dot-ok`, `.dot-warn`, `.dot-error`.
- "Last status" line: dot + text. No more text-only "ok"/"error"/"warn" labels (issue requirement).
- Test-controls block: keep dashed border but adopt dark-mode amber (`border: 2px dashed --warn-fg`, `background: --warn-bg`, `color: --fg`).
- Runs table: row backgrounds use the same status dot color as a 4px `border-left` accent. Otherwise the table is plain (`--bg-raised` background, 1px `--border` separators).
- Strip all inline `style=""` from `admin.html.j2` and route them through CSS classes. (Currently the template has 8 inline `style=""` attributes; these become CSS rules.)

### Search view (`search.html.j2`)
- Input: full-width, `background: --bg-raised`, `border: 1px solid --border`, padding 6px 10px.
- Search button: same as save button (accent fill).
- Results list: each item `background: --bg-raised`, padding 8px 12px, gap 6px between items.
- Strip the inline `style="padding:8px;border-radius:4px"` from the error banner — the global `.banner-warn` rule handles it.

### Email digest (`monthly.py`)
- Pull all inline color literals (`#222`, `#ccc`) into a module-level palette constant (`_DIGEST_PALETTE: dict[str, str]`) at the top of `monthly.py`. Function bodies reference this constant — no inline literals remain.
- Calendar grid: pad cells now show day-of-month (matching web). `--fg-dim`-equivalent (`#c4c2cc`) text.
- Add 1px `border-left: 4px solid <accent>` to the digest's intro section, mirroring the entry-view pattern in the web UI.
- Typography: h1/h2 sizes match the web's hierarchy.
- "View in app" links: use the email's accent color (`#6c4fc4`), no underline.

## Files touched

| File | Change |
|---|---|
| `src/driftnote/web/static/style.css` | Rewrite (current 23 lines → ~150 lines with CSS variables, mobile media query) |
| `src/driftnote/digest/moodboard.py` | `MonthlyCell.day_of_month: int` always set; grid pads to 6 rows |
| `src/driftnote/digest/monthly.py` | Light-theme polish; render pad-cell day numbers; palette constants |
| `src/driftnote/web/templates/base.html.j2` | Banner classes (no inline-style hooks needed) |
| `src/driftnote/web/templates/calendar.html.j2` | Render `day_of_month` for all cells; `today` class |
| `src/driftnote/web/templates/admin.html.j2` | Status-dot wrapper; remove inline styles |
| `src/driftnote/web/templates/entry.html.j2` | Accent-stripe wrapper |
| `src/driftnote/web/templates/entry_edit.html.j2` | Preview/textarea structural separation |
| `src/driftnote/web/templates/search.html.j2` | Remove inline styles |
| `src/driftnote/web/templates/tags.html.j2` | Flat pill markup (drop dynamic inline `style=` if class-based sizing reads cleaner — see decision below) |
| `tests/unit/test_digest_moodboard.py` | Assert `len(rows) == 6` always; pad cells carry `day_of_month` |
| `tests/integration/test_web_routes_browse.py` | Assert calendar HTML contains 6 weeks; pad-cell day numbers present |
| `tests/integration/test_web_routes_media_and_admin.py` | Adjust if assertions check for old text-only status labels |
| `tests/unit/test_digest_monthly_render.py` (new) | In-test substring assertions: digest HTML contains the palette accent (`#6c4fc4`), the muted pad-cell color (`#c4c2cc`), and pad-cell day numbers. Not a committed `.html` snapshot — palette tweaks should not require fixture refreshes |

### Decision: tag size — class vs inline style

Current template uses `style="font-size: {{ 0.8 + (count*0.1) }}rem"`. For a generated, per-tag scalar it's defensible to keep inline. The redesign keeps this inline style but moves all *static* admin/search inline styles into CSS classes. Rationale: a per-element scalar that's a function of dynamic data is the canonical case for inline `style=`; converting to a class would require either pre-computed class buckets (adds rendering complexity for no gain) or a `<style>` block per page (worse). Keep as-is.

## Acceptance criteria

- [ ] CSS custom properties block is the first rule in `style.css`. All themed colors reference variables, no raw hex values outside `:root`.
- [ ] Calendar grid is always 6 rows. Pad cells are visibly dimmed (`--fg-dim`) but their day-of-month number is legible.
- [ ] Today's cell is outlined in `--accent`. No fill.
- [ ] Mobile viewport (< 600px): weekday header is hidden, cells fit on screen without horizontal scroll on a 360px-wide viewport.
- [ ] Admin status indicators are colored dots, not text labels.
- [ ] All existing tests pass (browse, edit, admin, moodboard).
- [ ] New tests cover: 6-row guarantee, pad-cell day numbers, digest light-palette presence.
- [ ] PR description contains screenshots: calendar (desktop + mobile), entry view, edit view, admin, monthly digest email render.
- [ ] No `border-radius` in the codebase except status dots (`50%`) — verified by grep on the final stylesheet.

## Risks and mitigations

**Risk:** Email digest dark-on-light renders poorly in Gmail's automatic dark-mode adjustments.
**Mitigation:** Test with a real Gmail send during development. Use light-friendly colors with sufficient contrast that Gmail's dark-mode transform doesn't mangle them. Avoid pure white backgrounds (use `#ffffff` for canvas but `#f7f6fb` for raised areas — Gmail's transform handles slightly tinted whites better than `#ffffff` against gray text).

**Risk:** `MonthlyCell.day_of_month` becoming non-optional is a breaking API change for any callers outside `monthly.py` and `calendar.html.j2`.
**Mitigation:** A repo-wide grep already confirms only those two callers exist. Test suite catches regressions.

**Risk:** Always-6-rows changes the visual rhythm of months that naturally fit 5. Existing snapshots (if any) of 5-row months would need updating.
**Mitigation:** Confirmed via test inventory: only one moodboard test asserts on row count, and it's loose (`>= 5`). Tightening to `== 6` is the intended fix.

## Implementation strategy

A single PR. The work is largely confined to `style.css` plus a small backend tweak; splitting wouldn't reduce risk.

Order of work in the implementation plan:
1. Backend: `MonthlyCell` + `monthly_moodboard_grid` always-6-rows change with tests.
2. Template: `calendar.html.j2` updated to render pad-cell day numbers.
3. CSS: full rewrite of `style.css` with the dark palette + flat rules + mobile media query.
4. Templates: structural tweaks for admin status dots, entry accent stripe, edit-view preview separation.
5. Email digest: `monthly.py` light-theme polish.
6. Tests: update existing assertions, add the digest-render snapshot.
7. Manual verification: run the dev server, exercise each view at desktop and mobile widths, send a test digest to confirm the light theme renders cleanly in Gmail.
