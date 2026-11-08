# Phase 5: motion completion and the entry-edit deferrals

> Design spec for [issue #65](https://github.com/maciej-makowski/driftnote/issues/65).

Fifth PR of the driftnote web UI redesign (a six-phase plan; phases 1 to 4
are #57, #59, #61, and #63, all merged). This spec is self-contained: the
section numbers it cites belong to the redesign's design doc, which lives in
Maciek's private design repo and is not part of this repository.

## Goal

Finish the stylesheet's motion story. The second `:root` block gains the
three tokens phase 3 deferred (`--ease-soft`, `--dur-med`, `--dur-slow`), the
banner strip plays its one entrance on page load and then never moves again,
and content swapped in by htmx fades in over `--dur-med` instead of
repainting. The entry-edit items phase 4 deferred land in the same PR: the
preview panel inherits the reading serif, the panel reserves its first
lines, the mood input names itself for screen readers, and the edit page
preloads the roman face now that something on it renders the face. The
second `:root` block, which grew this phase, gets the exact-set pin the
phase-3 review asked for (sections 3.3, 3.5, 3.6, 3.7, 3.12 phase 5).

## Scope

**In:**
- `src/driftnote/web/static/style.css`: the three motion tokens in the
  second `:root` block; the banner entrance (the file's one `@keyframes`);
  the htmx settle-fade rules; `.preview` joining the `.entry-body` reading
  rule; the preview panel's `min-height`; comment updates where the motion
  story changed.
- `src/driftnote/web/templates/entry_edit.html.j2`: the `head_extra` fill
  (the roman-face preload, the same link entry uses) and the mood input's
  `aria-label="Mood, one emoji"`. Nothing else changes.
- `tests/unit/test_style_contrast.py`: seven added tests (the block-2
  exact-set pin and the motion invariants). No existing assertion changes.
- `tests/integration/test_web_routes_edit.py`: the phase-4 deferral test
  flips to assert the preload, and the mood `aria-label` gets a test.
- This spec and the implementation plan in `docs/superpowers/plans/`.

**Out:**
- The admin cards partial, the 30s refresh, and the htmx include move:
  phase 6. This phase pre-wires the cards fade hook in CSS (see the settle
  section), which the design's phase-5 row already owns ("preview/admin
  settle fades").
- Every colour value: the first `:root` block is byte-identical, so
  `scripts/check-contrast.py` exits 0 on the unchanged 27-row pair set.
  Motion adds no colours.
- The `prefers-reduced-motion` block: shipped in phase 3, untouched. Its
  `*` selector with `!important` governs the new animation and transitions.
- The unsaved-changes guard: OD-4's standing default, none in v1, keeps the
  zero-app-JS stance honest.
- The `--font-sans` and `--font-mono` tokens: still no rule consumes them.
- `pyproject.toml` and `uv.lock`: byte-identical. No dependency is added.

## Architecture

### The settle mechanics, verified against the vendored htmx 2.0.4

The class names and timings were read out of
`src/driftnote/web/static/htmx.min.js` (the vendored 2.0.4, 50,917 B), not
guessed. Its `config` block carries:

```
defaultSwapStyle:"innerHTML", defaultSwapDelay:0, defaultSettleDelay:20,
addedClass:"htmx-added", settlingClass:"htmx-settling",
swappingClass:"htmx-swapping",
attributesToSettle:["class","style","width","height"]
```

Two code paths in the minified source put them to work:

1. At swap time the target gets `htmx-swapping`, and each top-level node of
   the response fragment is inserted already carrying `htmx-added`, with a
   settle task queued per node. When the settle delay (20 ms) has passed,
   the task removes `htmx-added`, processes the node, and fires
   `htmx:load`.
2. After the swap the settled elements get `htmx-settling`; when the settle
   tasks have run, that class is removed and `htmx:afterSettle` fires.

So the standard settle fade needs exactly two CSS facts: the new content
starts at `opacity: 0` while `htmx-added` is present, and a transition on
`opacity` is present on the content in its settled state. Removing the
class then animates opacity from 0 back to 1. The class exists only for the
settle window, so the fade needs none of our JavaScript:

```css
.htmx-added {
  opacity: 0;
}
.preview > *,
.job-cards {
  transition: opacity var(--dur-med) var(--ease-soft);
}
```

Three points on the hooks:

- They are classes, not ids. The phase-1 invariant test
  (`test_no_raw_hex_outside_root`) asserts that no `#` appears anywhere
  outside the first `:root` block, and an id selector carries a `#`. The
  first staged version of this CSS used `#preview > *` and the phase-1 test
  caught it; the hooks moved to classes and no phase-1 test was touched.
  The markup keeps `id="preview"`, which `hx-target` needs; CSS does not
  reference it.
- `.preview > *` is the right grain for the preview: `POST /preview`
  returns bare rendered markdown with no wrapper (`routes_edit.py`'s
  preview handler), so the fragment roots are the panel's direct children.
  The panel's own chrome (background, left border) does not fade.
- `.job-cards` is the phase-6 admin target's fade hook, pre-wired here
  because the design's phase-5 row owns both fades. The partial renders
  cards-only markup whose root is the cards grid itself (the design's
  section 3.5 wrapper swaps `innerHTML`, so the grid element is the
  fragment root and carries `htmx-added`). Until phase 6 the selector
  matches the server-rendered grid, whose opacity never changes, so it is
  inert there.

The server-rendered initial preview carries no settle class and does not
fade on page load. Reduced-motion users get the instant appearance: the
phase-3 block zeroes `transition-duration` through its `*` selector.

### The banner entrance, once only

The strip is `.banners`, which `base.html.j2` renders only when at least
one banner exists, so nothing animates on a quiet page:

```css
.banners {
  animation: banner-enter var(--dur-slow) var(--ease-soft) forwards;
}

@keyframes banner-enter {
  from {
    opacity: 0;
    transform: translateY(2px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

The once-only behaviour is composed, not declared: the shorthand leaves
`animation-iteration-count` at its default 1 (no `infinite` anywhere in the
file, asserted by test), and `forwards` holds the settled state after the
one run. The settled state equals the element's natural state, so the strip
is static forever after the first 600 ms. The 2px rise is an entrance, not
a hover: the design's hard rules carve exactly this exception out of
issue-4's no-transform hover rule (section 3.7). `translateY` moves the
strip rigidly, so the banners' square left stripes keep their shape, and
the 2px travel stays under the 4px motion cap.

### The recorded keyframes exemption

The invariant list (section 3.3) says "no keyframes", and phase 3's review
swept the stylesheet clean of them. The banner entrance is the one
animation the design's motion inventory explicitly plans (section 3.7), so
this phase records a second exemption beside the reduced-motion block's
`!important` one: `banner-enter` is the stylesheet's only `@keyframes`
block and its only `animation` shorthand, and nothing else may add one
without amending the record. The exemption is stated here and in the PR
body, enforced by `test_banner_entrance_is_the_only_keyframes`, and the
stylesheet comment next to the keyframes carries it. The design doc's
invariant list gains the same line when the PR lands (the doc lives in
Maciek's design repo and is not edited from this PR).

### The entry-edit deferral resolution

The phase-4 deferral decision lives in PR 64's thread (round 1 declined
preloading a face nothing on the edit page consumed; the fix-up removed the
preload and flipped the test to `test_edit_page_defers_roman_preload`; the
approving round records "the edit page joins in phase 5 with the preview
serif") and in the phase-4 spec's Preload scoping and Out list. This PR
consumes that decision:

- The preview inherits the reading style by sharing the one rule:
  `.entry-body, .preview { font-family: "Newsreader", var(--font-serif);
  font-size: 17px; line-height: 1.65; max-width: 62ch; }`. The list is
  identical to the entry body's, so what you write is what you will read.
  The class hook is the markup's existing `class="preview"`.
- The panel reserves three preview lines: `min-height: 84px` on
  `.entry-edit .preview`, which is three lines at 17px/1.65 (28.05px per
  line). The design says 2 to 3 lines; three keeps the first keystroke
  from shifting the page even while the panel is empty.
- The mood input gets `aria-label="Mood, one emoji"`, verbatim from the
  design (sections 3.5, 3.8); the wrapped label stays for sighted users.
- The `head_extra` block fills with the same preload link entry carries,
  so the first visit has the roman face warming up while the page renders.

### The block-2 exact-set pin

PR 62's verdict carried the advisory on record: block 2 is the accumulation
point, nothing unit-pinned it, and when phase 5 grows it the PR should
"mirror the phase-1 pattern with an exact-set pin for the geometry/motion
tokens, or consolidate the blocks". This PR grows the block and pins it:
`test_second_root_block_holds_exactly_the_accumulated_tokens` asserts the
second `:root` block equals exactly 13 tokens, the phase-3 geometry set
(`--radius-m`, `--space-1` through `--space-6`), the phase-3 motion pair
(`--ease-settle`, `--dur-fast`), the phase-5 motion trio (`--ease-soft`,
`--dur-med`, `--dur-slow`), and `--font-serif`, which phase 4 placed in
this block. Nothing missing, nothing extra. `scripts/check-contrast.py`
keeps its documented contract (it parses the first block only), so the pin
parses the second block locally with the same token regex.

### Updated request arithmetic (section 3.10)

The table follows PR 64's convention: every page pays the global htmx
include until phase 6 scopes it to the two consumers.

| Page | Steady state | With italic text | With latin-ext glyphs | Worst case |
|---|---|---|---|---|
| entry | 4 (HTML, CSS, htmx JS, roman) | 5 | +1 per ext file used | 7 |
| entry_edit | 4 (HTML, CSS, htmx JS, roman) | 5 | +1 per ext file used | 7 |
| calendar, search, tags | 3 (HTML, CSS, htmx JS) | 3 | 3 | 3 |
| admin | 3 (HTML, CSS, htmx JS) | 3 | 3 | 3 |
| favicon | 0 | 0 | 0 | 0 |

entry_edit moves from 3 to 4: the serif preview gives the face a consumer,
so the preload is used and no preloaded-but-unused warning appears. The
phase-4 spec's entry_edit row said "faces join in phase 5"; this table is
that update.

## Files touched

| File | Change |
|---|---|
| `src/driftnote/web/static/style.css` | Three tokens in the second `:root` block; the settle-fade rules; the banner entrance and its keyframes; `.preview` in the reading rule; the preview `min-height`; comment updates |
| `src/driftnote/web/templates/entry_edit.html.j2` | `head_extra` fill (roman preload); mood `aria-label` |
| `tests/unit/test_style_contrast.py` | Seven added tests: the block-2 pin, the banner entrance's shape and once-only behaviour, the settle fades, the preview reading style, and the reduced-motion `!important` count |
| `tests/integration/test_web_routes_edit.py` | `test_edit_page_defers_roman_preload` replaced by `test_edit_page_preloads_roman_face`; `test_edit_page_mood_input_names_itself` added |
| `docs/superpowers/specs/2026-11-08-issue-65-motion-completion.md` | This spec |
| `docs/superpowers/plans/2026-11-08-issue-65-motion-completion.md` | Implementation plan |

## Tests

### Run first, patch what breaks

The full suite ran against the staged template, stylesheet, and test-state
changes against the pristine master baseline (1177d93: 248 passed, 2
skipped, 19 environmental errors). Two things broke, and both were this
phase's to fix:

- `test_edit_page_defers_roman_preload` failed by design: it is the
  phase-4 deferral's own guard, and its docstring scheduled this phase. It
  is replaced by `test_edit_page_preloads_roman_face`, which asserts the
  preload link and the roman-only scope (no italic, no latin-ext).
- `test_no_raw_hex_outside_root` caught the first staged CSS: the settle
  and serif hooks were id selectors, and the invariant greps any `#`
  outside the first `:root` block. The hooks moved to classes. No phase-1
  test was modified, which is the standing rule this phase was built
  around; the invariant shaped the implementation instead.

### Added coverage

Seven unit tests in `tests/unit/test_style_contrast.py`, the existing
file's style, no new fixtures:

- `test_second_root_block_holds_exactly_the_accumulated_tokens`: the
  block-2 exact-set pin (13 tokens).
- `test_banner_entrance_is_the_only_keyframes`: exactly one `@keyframes`
  (banner-enter) and exactly one animation shorthand, the recorded
  exemption.
- `test_banner_entrance_moves_two_pixels_and_fades_only`: opacity and a
  2px translateY only; no scale, rotate, skew, matrix, perspective, or
  infinite; the square stripes ride a rigid transform.
- `test_banner_entrance_runs_once_and_holds`: forwards fill on the
  `.banners` rule, default single iteration, no `infinite` in the file.
- `test_htmx_settle_fades_swap_content_in_over_dur_med`: the
  `.htmx-added { opacity: 0 }` opener and the `--dur-med`/`--ease-soft`
  transition on the class hooks.
- `test_preview_shares_the_entry_reading_style`: the serif list, size,
  leading on the grouped rule, and the 84px reserve on the panel.
- `test_reduced_motion_block_remains_the_only_important`: exactly 3
  `!important`, all inside the reduced-motion block, which carries the
  animation and transition duration zeroing that governs the new motion.

Two integration tests in `tests/integration/test_web_routes_edit.py`: the
replaced preload test (above) and `test_edit_page_mood_input_names_itself`,
which asserts the mood input's `aria-label` in the rendered page.

### Existing suites and gates

- `uv run pytest -m "not live"`: 256 passed, 2 skipped, 19 errors. The 19
  error node ids are byte-identical to the pristine master run
  (testcontainers fixtures failing to reach a Docker socket this
  environment does not have; CI's runner has the socket). 248 of the
  passes are master's own; 1 master test was replaced and 8 added, hence
  the delta.
- `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  `uv run mypy`: clean.
- `uv run python scripts/check-contrast.py
  src/driftnote/web/static/style.css`: exit 0, 27 rows, no colour change.
  The stylesheet measures 13,984 B raw, under the 14 KB budget row.
- Invariant greps over the stylesheet: no `#` outside the first `:root`
  block, no shadows, no gradients, exactly one `@keyframes` block
  (`banner-enter`) and one `animation` shorthand, `transform` declarations
  only inside the banner keyframes (the 2px rise), exactly 3 `!important`
  all inside the reduced-motion block, no `infinite`.

## Acceptance criteria

- [ ] The second `:root` block gains `--ease-soft`
      cubic-bezier(0.25, 0.1, 0.25, 1), `--dur-med` 300ms, and `--dur-slow`
      600ms, and is pinned by an exact-set test to 13 tokens; the first
      `:root` block is byte-identical to master.
- [ ] The banner strip runs one fade-plus-2px-rise entrance over
      `--dur-slow` on `--ease-soft` with `forwards`, runs once (default
      iteration, no `infinite`), and is static forever after; the square
      left stripes ride a rigid transform.
- [ ] `banner-enter` is the stylesheet's only `@keyframes` and only
      animation, recorded as the invariant list's second exemption in this
      spec, the PR body, the stylesheet comment, and a unit test.
- [ ] Content swapped into the preview panel enters at `opacity: 0` via
      `htmx-added` and fades in over `--dur-med` on `--ease-soft`; the
      hooks are classes; the server-rendered initial preview does not
      fade; the phase-6 cards grid fade is pre-wired.
- [ ] The settle-class names and the settle delay are verified against the
      vendored htmx 2.0.4, as recorded in this spec.
- [ ] The preview panel carries the reading serif (same list, size,
      leading, measure as `.entry-body`), reserves three lines
      (`min-height: 84px`), and the mood input carries
      `aria-label="Mood, one emoji"`.
- [ ] The edit page preloads the roman face via `head_extra`, the same
      link entry uses, with no italic or latin-ext preload.
- [ ] The reduced-motion block remains the stylesheet's only `!important`
      (3 declarations, one block) and governs the banner animation and the
      settle transitions through its `*` selector.
- [ ] The phase-1/3/4 unit tests pass unmodified; the one integration
      change is the deferral flip this phase was scheduled to make.
- [ ] The gate list above is green with the stated numbers, and
      `pyproject.toml` and `uv.lock` are byte-identical.

## Risks

**Risk:** The keyframes exemption could read as invariant drift.
**Mitigation:** The design's motion inventory plans the entrance
explicitly, the exemption is recorded in four places (spec, PR body,
stylesheet comment, unit test), and the test pins the count at one so a
second animation cannot appear silently.

**Risk:** The `.job-cards` fade hook pre-wires phase-6 markup.
**Mitigation:** The design pins the cards markup and the innerHTML swap;
the partial's root is the cards grid. If phase 6 lands differently, the
hook is a one-line edit and the generic `.htmx-added` opener already
applies to every swap. Flagged for the phase-6 PR.

**Risk:** The settle transition sits permanently on the preview's initial
children and the admin grid.
**Mitigation:** Nothing outside a swap changes opacity, so the transition
is inert until htmx adds the settle class; the phase-1 test's calendar
scoping already anticipated phase-5 fades outside the calendar block.

**Risk:** The 84px reserve is a fixed number against two different faces
(system serif fallback, vendored Newsreader).
**Mitigation:** Three lines at 17px/1.65 is 84.15px; the 0.15px difference
is under a pixel on either face, and the reserve only has to stop the
first keystroke from shifting the page.

**Risk:** A 300ms fade on every debounced keystroke-swap could feel busy
while typing.
**Mitigation:** The fade (300ms) is shorter than the trigger gap (400ms
debounce plus request time), the design's direction is settle-not-snap,
and reduced-motion users get the instant appearance.

## Out of scope

- The admin cards partial, the 30s refresh, and the htmx include move:
  phase 6.
- The unsaved-changes guard: OD-4's standing default, none in v1.
- The `--font-sans` and `--font-mono` tokens, until a rule consumes them.
- Any change to `banners.py`, `cloud.py`, auth, the digest emails, or the
  media pipeline; no route changes at all in this phase.
