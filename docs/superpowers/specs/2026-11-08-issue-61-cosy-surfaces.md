# Phase 3: cosy surfaces and calendar a11y

> Design spec for [issue #61](https://github.com/maciej-makowski/driftnote/issues/61).

Third PR of the driftnote web UI redesign (a six-phase plan; phase 1 is #57,
merged, phase 2 is #59, merged). This spec is self-contained: the section
numbers it cites belong to the redesign's design doc, which lives in Maciek's
private design repo and is not part of this repository.

## Goal

Apply the redesign's geometry and motion basics: one 8px radius token on the
rounded surfaces, a six-step spacing scale on the section paddings, eased
180ms colour transitions on hover and focus, and the `prefers-reduced-motion`
block that governs them. Plus the calendar accessibility items: full-date
`aria-label`s on every cell link and a one-line hint under the table when a
month has no entries at all. Colour values do not change in this phase (they
were phase 1), no class name changes, and nothing here needs JavaScript
(sections 3.2, 3.3, 3.5, 3.7, 3.8, 3.11).

## Scope

**In:**
- `src/driftnote/web/static/style.css`: the radius and spacing tokens, the
  motion tokens, radius on the six surface groups, borderless inputs, the
  spacing tokenisation pass, the hover/focus transition rule, the
  `prefers-reduced-motion` block, and the empty-month line's rule.
- `src/driftnote/web/templates/calendar.html.j2`: the `aria-label` on cell
  links and the empty-month conditional line.
- `src/driftnote/web/routes_browse.py`: one additive context boolean feeding
  that conditional; no other route change.
- `tests/integration/test_web_routes_browse.py`: two widened anchor regexes
  and four added tests (see Tests).
- This spec and the implementation plan in `docs/superpowers/plans/`.

**Out:**
- Every colour value: the `:root` colour block is byte-identical to master,
  so `scripts/check-contrast.py` still exits 0 on its unchanged 26-row pair
  set. Geometry changes no colours.
- Class names: unchanged everywhere, because integration tests pin them.
- Chip padding: stays `2px 8px` literal, because `cloud.py`'s bounding-box
  maths assume it (section 6).
- The banner entrance animation and the `--ease-soft`, `--dur-med`, and
  `--dur-slow` tokens: phase 5. This phase defines only `--ease-settle` and
  `--dur-fast`, the first tokens the reduced-motion block must govern
  (section 3.7).
- Font stacks, the serif body, and the vendored faces: phase 4.
- The admin partial, the live refresh, and the htmx include move: phase 6.
- `pyproject.toml` and `uv.lock`: zero new dependencies.

## Architecture

### Tokens, in a second `:root` block

The design doc puts the spacing scale, the radius token, and the motion
tokens in `:root` (section 3.3). The phase-1 contrast lock-in test
(`tests/unit/test_style_contrast.py`) parses the first `:root` block of the
stylesheet and pins its token set to exactly the 18 colour tokens, and the
standing rule for this redesign is that phase-1 unit tests stay green
unmodified. Phase 3 therefore adds a second, adjacent `:root` block holding
the new tokens, and the first block keeps its bytes:

```css
:root {
  --radius-m: 8px;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --ease-settle: cubic-bezier(0.22, 0.61, 0.36, 1);
  --dur-fast: 180ms;
}
```

CSS merges multiple `:root` blocks, and custom properties resolve the same
way either way, so this is purely a bookkeeping split. The stylesheet carries
a comment explaining it. `--radius-m` is the one radius token: every rounded
surface takes it (section 3.2, OD-5). `--space-5` already has a consumer
(test-controls `margin-top`); `--space-6` has none today because no current
padding equals 32px. The scale is defined whole now, as the doc lists it, and
later phases can consume `--space-6` without touching this file's token
block again.

### Radius placement, and rule 3

`--radius-m` goes on: `.tag-chip`, `button` (one rule covers plain and
`.entry-edit` buttons), the edit form's two input rules and its textarea, the
search input, `.job-cards .card`, `.calendar td`, and `.search-results li`
(sections 3.2, 3.5, 3.12). Every one of these is a filled surface with no
border, so issue-4's rule 3 (no combination of radius and visible border)
holds everywhere.

The inputs change shape: the `1px solid var(--border)` border becomes
`border: none`, keeping the raised background. That is the doc's borderless
and filled input. It is also why the borders that remain are all square: the
banner left stripes, the runs table's status stripes and row bottom borders,
the notice's left border, the entry page's 4px accent left border, the
topbar's bottom border, the test controls' 2px dashed border, and the preview
panel's 4px left border keep their borders and gain no radius. None pairs a
radius with a border.

The today cell keeps its 1px accent outline. An outline follows the
element's border-radius in current Chromium, Firefox, and Safari, so the
today outline rounds with the cell; on old engines it degrades to a square
outline. Cosmetic only, noted in the doc (section 3.2), not a rule violation.

### Spacing scale

The tokenisation rule is mechanical: every length in a `padding`, `margin`,
or `gap` declaration that equals a scale value (4, 8, 12, 16, 24, 32px) takes
the token; declarations carrying any off-scale length stay literal (the
banner strip's 6px gap, the results rows' 6px margin, the runs cells' `6px
10px`, the mobile cells' 2px, the headings' 6px, and the textarea's mixed
`8px 10px`). Every replaced value is identical to the token it replaces, so
the visual rhythm is unchanged; this is a tokenisation pass, not a re-layout
(section 3.12). The chip's `2px 8px` padding is untouched and now carries a
comment naming the constraint: `cloud.py`'s bounding-box estimates assume it,
and if padding ever changes, `_BBOX_MARGIN` is what gets revisited, not the
spiral (section 6).

### Motion basics

One utility rule gives the hover and focus colour changes their duration
(section 3.7's inventory row: links, nav, chips, buttons, calendar cells,
input focus):

```css
a,
.tag-chip,
button,
.calendar td,
.search-results li,
.entry-edit input[type="text"],
.entry-edit input:not([type]),
.entry-edit textarea,
.search-form input[type="search"] {
  transition:
    background-color var(--dur-fast) var(--ease-settle),
    color var(--dur-fast) var(--ease-settle);
}
```

Bare `a` covers the nav links, the entry links, and the brand; the calendar
cells transition their hover wash; the chips transition their existing hover
pair. Issue-4's rule 4 stands unchanged: hover changes background and colour
only, and the redesign adds a duration to the change, nothing else. No
transforms, no scaling, nothing moves more than 4px, no infinite loops.

Two selectors in that rule are declarative rather than active today. The
results rows have no hover rule in the shipped stylesheet, and the inputs'
only focus feedback is the global `:focus-visible` outline. The transition
sits on them so that a hover or focus surface a later phase adds inherits
the duration automatically. No hover rule was invented for rows in this
phase: a row hover background would be a new text/surface pair the contrast
gate's 26-row set does not carry, and the doc's motion inventory lists no
row hover. The focus outline also stays as it is: transitioning its colour
from the browser default would alter today's focus look, and no phase-3 item
asks for that.

### Reduced motion

The doc's standard block ships verbatim, in the same PR as the first motion
it governs (section 3.7):

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

Its three `!important` declarations are the invariant list's single recorded
exemption (section 3.3): the file's only `!important` occurrences are these
three lines inside this one block. It sits after the component and page
rules and before the shipped mobile media block, matching the doc's file
order (section 3.3, items 6 and 7).

### Calendar a11y and the empty-month line

Cell links carry `aria-label="{{ c.date.isoformat() }}"`, so the accessible
name of every cell link is the full date instead of a bare day number plus
an emoji (section 3.8). The grid is six rows of seven cells, all linked, pad
cells included, so every calendar page renders 42 labelled links.

The empty-month line needs one boolean in the route and one conditional in
the template (sections 3.5, 3.12; the boolean's exact shape was left to this
spec to pin):

```python
month_empty = not any(c.emoji for row in cells for c in row if c.in_month)
```

The boolean keys on in-month cells only: an entry sitting in the
prev/next-month pad tail is not an entry in the viewed month, and the hint
is about the viewed month. The template renders, under the table:

```html
<p class="calendar-empty">No entries this month. <a href="/admin/runs/imap_poll">Check the mail poll</a></p>
```

`/admin/runs/imap_poll` is the admin drill view for the mail poll job, the
likely cause of a silently empty month. The line is styled `.calendar-empty`
in `--fg-muted` at 13px, an existing gated pair (secondary text on the page
background), so the contrast checker's pair set stays at 26 rows. The
boolean is additive: no other route, no schema change, no moodboard change,
and the line renders without JavaScript (section 3.11).

## Files touched

| File | Change |
|---|---|
| `src/driftnote/web/static/style.css` | Second `:root` block with the radius, spacing, and motion tokens; radius on six surface groups; inputs borderless; spacing tokenisation; the transition rule; the reduced-motion block; the `.calendar-empty` rule |
| `src/driftnote/web/templates/calendar.html.j2` | `aria-label` on cell anchors; the empty-month conditional line |
| `src/driftnote/web/routes_browse.py` | One additive context boolean (`month_empty`) in the calendar handler and its `month_empty=` context key |
| `tests/integration/test_web_routes_browse.py` | Two anchor regexes widened for the `aria-label`; four added tests |
| `docs/superpowers/specs/2026-11-08-issue-61-cosy-surfaces.md` | This spec |
| `docs/superpowers/plans/2026-11-08-issue-61-cosy-surfaces.md` | Implementation plan |

## Tests

### Run first, patch what breaks

The integration suite ran against the staged template, stylesheet, and route
before anything in `tests/` was written, against the pristine master
baseline (22fa7e8: 236 passed, 2 skipped, 19 environmental errors). Result:
two assertions broke, both regexes pinning the cell anchor's exact markup in
ways the `aria-label` changes:

- `test_calendar_page_renders_pad_cell_day_numbers` matched
  `<a href="/entry/[^"]+">`; the closing `>` now follows `[^>]*>` so the
  attribute is tolerated.
- `test_calendar_pad_cell_with_entry_renders_mood` pinned the same anchor
  shape for the April 30 pad cell; same widening.

Nothing else broke. No assertion pins a class name, a colour, a padding, or
any stylesheet content: the phase-1 unit tests (the contrast lock-in pair
set, the invariants, the calendar-block no-opacity check) pass unmodified,
which is the standing rule this phase was built around.

### Added coverage

Four tests in the browse file's existing style, no new fixtures:

- `test_calendar_cell_links_carry_full_date_aria_labels`: all 42 cell links
  carry an `aria-label`, each label equals the cell's own ISO date, and the
  seeded entry's cell is among them.
- `test_calendar_empty_month_line_renders_for_empty_month`: an empty
  database renders the hint line with the `/admin/runs/imap_poll` link.
- `test_calendar_empty_month_line_absent_when_month_has_entries`: a month
  with one entry renders neither the line nor the class.
- `test_calendar_empty_month_line_ignores_pad_cell_entries`: an April 30
  entry viewed from the May grid still shows the hint, pinning the
  boolean's in-month scoping.

### Existing suites and gates

- `uv run pytest -m "not live"`: 240 passed, 2 skipped, 19 errors. The 19
  error node ids are byte-identical to the pristine master worktree's
  (testcontainers fixtures failing to reach a Docker socket this environment
  does not have; CI's runner has the socket). 236 of the passes are master's
  own; the four new tests account for the delta.
- `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  `uv run mypy`: clean.
- `uv run python scripts/check-contrast.py
  src/driftnote/web/static/style.css`: exit 0, 26 rows, no colour change.
- Invariant greps over the stylesheet: no `#` outside `:root`, no shadows,
  no gradients, no keyframes, no `opacity`, all three `!important`
  occurrences inside the reduced-motion block, no `transform` or animation
  properties (the word "transforms" appears once, in a comment saying they
  are absent), chip padding literal at `2px 8px`.

## Acceptance criteria

- [ ] The `:root` colour block is byte-identical to master, and the new
      tokens live in a second adjacent `:root` block: `--radius-m` 8px,
      `--space-1..6` 4/8/12/16/24/32px, `--ease-settle`
      cubic-bezier(0.22, 0.61, 0.36, 1), `--dur-fast` 180ms.
- [ ] `--radius-m` is applied to chips, buttons, inputs, admin cards,
      calendar cells, and search results rows; each is a filled surface
      with no border (rule 3).
- [ ] Inputs are borderless and filled; the seven square bordered elements
      keep their borders and gain no radius.
- [ ] The spacing scale replaces the on-scale section paddings, values
      identical; chip padding stays `2px 8px`.
- [ ] `--ease-settle` and `--dur-fast` are defined and applied to the
      hover/focus colour changes; nothing transforms, scales, or loops.
- [ ] The `prefers-reduced-motion` block is present and carries the file's
      only `!important` declarations.
- [ ] Every calendar cell link carries an `aria-label` with the full date.
- [ ] An empty month renders one quiet line under the table linking to
      `/admin/runs/imap_poll`, fed by the single additive context boolean;
      pad-cell entries do not suppress it.
- [ ] The phase-1 unit tests pass unmodified.
- [ ] The gate list above is green with the stated numbers.
- [ ] Templates other than `calendar.html.j2`, routes other than the one
      boolean, `pyproject.toml`, and `uv.lock` are untouched.

## Risks

**Risk:** Two `:root` blocks read as unusual CSS.
**Mitigation:** It is what keeps the phase-1 lock-in test green unmodified
while the doc still requires the tokens in `:root`; the trade is recorded
in the stylesheet comment and here. If Maciek prefers one block, the change
is moving ten lines and widening the phase-1 test's contract, a decision
for review, not for this PR to make silently.

**Risk:** The today cell's rounded outline degrades to square on old engines.
**Mitigation:** Cosmetic only, noted in the doc (section 3.2); current
Chromium, Firefox, and Safari all follow the radius.

**Risk:** The bare `a` selector puts a transition on every anchor, including
ones a later phase might not want animated.
**Mitigation:** The doc's inventory row is "links, nav" as a class, and
every anchor hover today is a colour change, which is what the duration is
for. A specific element can override the duration locally if one ever needs
to.

**Risk:** The empty-month boolean's in-month-only scoping could be read the
other way (pad entries suppressing the hint).
**Mitigation:** The scoping is stated in the route comment and pinned by
`test_calendar_empty_month_line_ignores_pad_cell_entries`.

**Risk:** A later phase edits the chip padding and silently breaks the tag
cloud's collision estimates.
**Mitigation:** The rule carries the constraint in a comment, and the doc's
risk list (section 6) names `_BBOX_MARGIN` as the thing to revisit if
padding ever changes.

## Out of scope

- The banner entrance animation, the preview and admin settle fades, and
  the `--ease-soft`, `--dur-med`, `--dur-slow` tokens: phase 5.
- The serif reading body, the weekday heading, the media grid, and the
  vendored Newsreader faces: phase 4.
- A hover background on search results rows: not in this phase's change
  list; if a later phase wants it, the row's transition is already in
  place and the new pair joins the contrast gate in that PR.
- The admin cards partial and the 30s refresh: phase 6.
- Any change to `cloud.py`, `banners.py`, auth, or the digest emails.
