# Phase 1: tokens and contrast lock-in

> Design spec for [issue #57](https://github.com/maciej-makowski/driftnote/issues/57).

First PR of the driftnote web UI redesign (a six-phase plan; phases 2 to 6
follow in their own issues). This spec is self-contained: the section
numbers it cites belong to the redesign's design doc, which lives in
Maciek's private design repo and is not part of this repository.

## Goal

Swap the stylesheet's :root colour values for the W10 target set, remove the
opacity hack that dimmed calendar pad cells below AA, and add the tooling
that keeps every pair at AA from then on: a checker script and a unit test
CI runs on every PR. The visible change is colour only. No template, route,
radius, motion, or spacing change belongs to this phase.

## Scope

**In:**
- `src/driftnote/web/static/style.css`: the 18 :root values (section 3.4),
  the opacity rule deleted, one scoped override added in its place.
- `scripts/check-contrast.py`: new, standard library only.
- `tests/unit/test_style_contrast.py`: new.
- This spec.

**Out:**
- Every other style.css line. The remaining 228 lines are byte-identical to
  master at 34360a4; the full diff is 19 changed lines.
- Radius, spacing scale, motion tokens, typography (phases 3 to 5).
- Templates, routes, auth, the email digest palette.
- `pyproject.toml` and `uv.lock`: zero new dependencies.
- The `docs/superpowers/plans/` implementation plan ships in this PR
  (`2026-11-08-issue-57-tokens-and-contrast.md`); the GitHub issue (#57) is
  already filed.

## Architecture

### Tokens change value, not name

All 18 tokens keep their names and their order in the :root block, so every
`var()` reference keeps working and no template needs a colour edit
(section 3.3). Values come from the W10 final set:

```css
:root {
  --bg:           #201b26;
  --bg-raised:    #2a2432;
  --bg-hover:     #352e40;
  --fg:           #eae5f2;
  --fg-muted:     #b6adca;
  --fg-dim:       #a49ac0;
  --accent:       #c5a8f5;
  --accent-hover: #d9c4fa;
  --border:       #3a3145;
  --warn-bg:      #3a2e1f;
  --warn-fg:      #f4cf70;
  --error-bg:     #3c222a;
  --error-fg:     #f2989e;
  --ok:           #9fcf9f;
  --status-warn:  #f4cf70;
  --status-error: #f2989e;
  --cal-entry:        #283428;
  --cal-today-empty:  #3a2e1f;
}
```

### Pad cells: opacity out, --fg-dim in

The shipped dimming is `.calendar td.dim { opacity: 0.5; }` (style.css:80).
It composites everything inside a pad cell to effective 2.51:1 (day number,
raised wash) and 2.48:1 (day number, entry wash), below AA for 11px text
(section 1.9). Phase 1 deletes that rule and puts this override in its
place:

```css
.calendar td.dim a, .calendar td.dim .dom { color: var(--fg-dim); }
```

A bare `.calendar td.dim` colour rule would change nothing visible. The
pad-cell text is owned by the anchor rule (style.css:79) and the `.dom`
rule (style.css:87), and both out-rank a plain cell rule. The override's
two selectors out-rank them in turn (`.calendar td.dim a` beats
`.calendar td a`; `.calendar td.dim .dom` beats `.calendar .dom`), so the
pad-cell day numbers and middots take --fg-dim directly. --fg-dim keeps
its name and gains #a49ac0, the value that clears 4.5:1 on the raised
wash (5.70), the entry wash (4.94), and the hover wash (4.93), per the W10
tuning note.

### The checker script

`scripts/check-contrast.py`, standard library only. It takes a stylesheet
path, parses the first :root block, evaluates a 24-row pair set, prints the
table, and exits 1 on any gated failure. Thresholds: 4.5:1 for the 19 text
pairs, 3:1 for the 3 non-text pairs (ok dot, error stripe, focus outline),
and no gate for the 2 decorative border rows, which carry no required
information so WCAG 1.4.11 does not apply. The pad-cell pairs are encoded
on their real surfaces: --bg-raised for td.empty, --cal-entry for
td.has-entry, --bg-hover for hover. The `blend` helper implements the W10
compositing step, banker's rounding per channel, for any future pair that
carries alpha; no phase-1 pair needs it.

### The unit test

`tests/unit/test_style_contrast.py` loads the checker by path (its
filename contains a hyphen) and pins, against
`src/driftnote/web/static/style.css`:

- the :root block equals the 18 target tokens exactly, nothing missing or
  extra;
- every gated pair in the full set clears its threshold;
- the three pad-cell rows exist in the pair set;
- `blend` reproduces the W10 banker's-rounding reference (#a0a0a0 at 0.5
  over #252525 is #626262);
- the hierarchy order dim < muted < fg on the page background (W10 tuning
  note);
- two section 3.3 invariant greps as tests: the calendar block holds no
  opacity, and no raw hex outside :root.

## Files touched

| File | Change |
|---|---|
| `src/driftnote/web/static/style.css` | 18 :root values swapped to the W10 set; opacity rule (line 80) replaced by the scoped pad-cell override; all other lines byte-identical |
| `scripts/check-contrast.py` | New. Parses :root, prints the pair table, exits 1 on any gated AA failure |
| `tests/unit/test_style_contrast.py` | New. Locks the token values, the AA pair set, and the section 3.3 invariants against the shipped stylesheet |
| `docs/superpowers/specs/2026-11-08-issue-57-tokens-and-contrast.md` | This spec |

## Tests

### Unit (`tests/unit/test_style_contrast.py`)

1. `test_root_block_holds_exactly_the_phase1_tokens`: the :root mapping
   equals the 18-entry target dict exactly.
2. `test_every_gated_pair_passes_aa`: no gated pair in `evaluate()` falls
   below its threshold; the failure message names pair, ratio, and values.
3. `test_pad_cell_pairs_are_encoded_on_their_washes`: the three pad-cell
   labels exist in the pair set.
4. `test_blend_composites_with_bankers_rounding`: W10's shipped-table
   reference row for the blend helper.
5. `test_three_digit_hex_expands_like_css`: #333 expands to #333333, the
   W10 shipped border row (1.32 on #1e1e1e).
6. `test_hierarchy_stays_ordered_dim_muted_fg`: dim < muted < fg on --bg.
7. `test_calendar_block_carries_no_opacity`: the calendar section holds
   no opacity, scoped to that section (see Risks).
8. `test_fg_dim_token_is_used_by_the_pad_cell_override`: var(--fg-dim)
   appears in the stylesheet.
9. `test_no_raw_hex_outside_root`: issue-9 invariant from section 3.3.

### Checker on the command line

```
uv run python scripts/check-contrast.py src/driftnote/web/static/style.css
```

Exits 0 against the phase-1 stylesheet and prints the 24-row table. Exits
1 against the shipped palette at 34360a4, where the three pad-cell pairs
resolve --fg-dim #5a5a5a directly on their washes and sit at 2.00:1 to
2.22:1. (The shipped opacity hack's own effective ratios, 2.51:1 to
4.03:1 with alpha compositing, belong to W10's shipped table; the phase-1
pair set models the replacement mechanism, not the removed hack.) The
asymmetry between the two runs is the proof the gate bites.

### CI and existing suites

`ci.yml` runs ruff check, ruff format --check, mypy (files: src, tests),
and `pytest -m "not live"` on every PR. The new unit test rides the
existing pytest step and the pre-commit fast hook (`pytest -q -m "not live
and not slow" tests/unit`). It reads one 6.7 KB file and does arithmetic,
so it adds nothing noticeable to suite time. Zero new dependencies;
`pyproject.toml` stays byte-identical.

`scripts/` sits outside mypy's `files` config (src, tests) and outside
CI's ruff targets (src, tests), so the unit test is the enforcement point
for the script's behaviour. The pre-commit ruff hook still lints the
script file itself on commit.

No integration test changes: phase 1 touches no markup, and the browse,
edit, media, and admin suites must pass untouched. That is also the
regression proof that the phase is colour-only.

## Acceptance criteria

- [ ] The style.css diff touches exactly 19 lines: the 18 :root value
      lines and the opacity rule's line.
- [ ] The :root block holds exactly the 18 W10 tokens with the values in
      section 3.4, no extra or missing tokens.
- [ ] No opacity in the calendar block; pad-cell text takes var(--fg-dim)
      through the scoped override.
- [ ] No raw hex outside :root.
- [ ] `uv run pytest tests/unit/test_style_contrast.py -v` passes.
- [ ] `uv run pytest -m "not live"` passes with no edits to existing tests.
- [ ] The browse, edit, media, and admin integration suites pass untouched.
- [ ] `uv run python scripts/check-contrast.py
      src/driftnote/web/static/style.css` exits 0 and prints the table.
- [ ] The checker exits 1 against the shipped 34360a4 stylesheet.
- [ ] ruff check, ruff format --check, and mypy are green with the new
      files staged.
- [ ] Templates, routes, pyproject.toml, uv.lock: untouched.

## Risks

**Risk:** The checker's pair set models the stylesheet; it does not parse
the rules. If a later phase restyles a surface (hover wash, chip colours),
a stale pair set would pass a stylesheet that no longer matches reality.
**Mitigation:** Every pair label names the selector it models. Phases 3 to
5 run the suite first and update the pair set in the same PR, the same
standing rule the design doc sets for markup-pinning tests. The section
3.3 greps are now unit tests, so drift fails CI instead of waiting for
review.

**Risk:** A ratio sitting exactly on a threshold could flip with a
rounding change.
**Mitigation:** No target pair is within 0.4 of its threshold; the
closest are 4.93 and 4.94. Ratios use the W10 method, double precision,
one rounding step, and the W10 table is the pinned reference.

**Risk:** The no-opacity assertion could collide with phase 5's motion
fades, which bring opacity in for `.htmx-added` content.
**Mitigation:** The assertion is scoped to the `/* Calendar */` section,
which no planned phase animates. Any phase that needs opacity elsewhere
amends the test in its own PR.

**Risk:** --fg-dim at 4.93:1 on the hover wash is the thinnest margin in
the set. A future --bg-hover lightening could break pad-cell hover
contrast.
**Mitigation:** The unit test fails the build, not a user. The W10 tuning
note records why the value was picked.

## Out of scope

- Radius, spacing scale, motion tokens, typography, and every other
  style.css region (phases 3 to 5; phase 2 covers base chrome and the
  skip link).
- Template and route changes: phase 1 needs none.
- The email digest's inline light palette: separate by design (issue-4).
- The `docs/superpowers/plans/` implementation plan: included in this PR
  (not deferred).
