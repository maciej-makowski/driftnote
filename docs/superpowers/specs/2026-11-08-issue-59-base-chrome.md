# Phase 2: base chrome and structural a11y

> Design spec for [issue #59](https://github.com/maciej-makowski/driftnote/issues/59).

Second PR of the driftnote web UI redesign (a six-phase plan; phase 1 is
#57, merged). This spec is self-contained: the section numbers it cites
belong to the redesign's design doc, which lives in Maciek's private design
repo and is not part of this repository.

## Goal

Give every page the base chrome the redesign's structural accessibility
pass calls for: a skip link as the first focusable element, a named target
on `main`, the dark colour-scheme and theme-colour metas, and an inline SVG
moon favicon that ends the browser's repeated requests for /favicon.ico,
which the app has never served (sections 3.5, 3.8, 1.8). The change is
chrome only. No page content, route, colour token, or motion token moves in
this phase.

## Scope

**In:**
- `src/driftnote/web/templates/base.html.j2`: the skip link, `id="content"`
  on main, two head metas, the favicon link.
- `src/driftnote/web/static/style.css`: the skip-link rules and the
  skip-target scroll handling, in the chrome region.
- `tests/integration/test_web_routes_browse.py`: one added smoke test; no
  existing assertion needed patching (see Tests).
- This spec and the implementation plan in `docs/superpowers/plans/`.

**Out:**
- Every other stylesheet line. The :root block is byte-identical to master;
  phase 2 adds no colours, so the phase-1 contrast gate needs no pair set
  change.
- Every other template, every route, auth, the email digest palette.
- `pyproject.toml` and `uv.lock`: zero new dependencies.
- A tabindex on main: the design doc's template change list is "give main
  id=content" and nothing more.

## Architecture

### Skip link and target

The first element in `<body>` is the doc's verbatim markup:

```html
<a class="skip-link" href="#content">Skip to content</a>
```

It sits before the topbar, so it is the first tab stop on every page
(section 3.5, 3.8). `<main>` gains `id="content"` and everything else in
the template keeps its current bytes: the per-page title block, the
stylesheet link, the htmx include, the topbar, and the banner strip
(section 3.5's "keep exactly where they are").

The link is hidden with positioning, not `display: none`, so it stays in
the accessibility tree at all times and a screen reader can reach it
without tabbing. On `:focus` it appears over the topbar:

```css
.skip-link {
  position: fixed;
  top: 12px;
  left: -9999px;
  z-index: 10;
  padding: 8px 12px;
  background: var(--bg-raised);
  color: var(--accent);
}
.skip-link:focus { left: 16px; }
```

The accent text on the raised surface clears the AA text gate with margin
(7.37:1 at rest, 9.47:1 on hover through the global `a:hover` colour;
checker method, design doc section 3.4). The focus outline needs no new
rule: the existing global `:focus-visible` treatment (2px accent outline,
2px offset) already applies. Hover colour comes from the existing global
`a:hover`. Phase 2 adds no opacity, transform, or transition, so the
motion inventory (section 3.7) and the phase-1 invariants are untouched.

### Skip-target scroll handling

```css
main { scroll-margin-top: 12px; }
```

When the browser jumps to the fragment, the main landmark lands 12px below
the viewport's top edge instead of flush against it. The rule keys on the
main element's type selector rather than the id: the phase-1 invariant
test greps the stylesheet for any # outside :root, and an id selector
would trip that grep on a character that is not a colour. main is the
only element of its kind on every page, so the selectors are equivalent.
No tabindex is added: modern browsers set the sequential focus navigation
starting point from the fragment target, so tabbing continues from main
after the jump. If a later phase ever makes the topbar sticky, this gap
needs revisiting; the topbar is static today.

### Placement in the stylesheet

The block sits in the chrome region, directly after the banner rules and
before the calendar block, matching the design doc's chrome order of
topbar, banners, skip link (section 3.3). That section also mentions the
skip-link rule under "reset and base"; this spec resolves the double
listing in favour of the chrome position, where the feature's two rules
read as one block next to the other chrome rules.

### Head additions, in the doc's order

After the viewport meta, in order: `<meta name="color-scheme"
content="dark">`, then `<meta name="theme-color" content="#201b26">`. The
first tells the browser the app's single theme is dark (issue-4 settled
single-theme; the design doc does not reopen it), so native form controls
and scrollbars render dark instead of white-flashing. The second paints
the browser UI chrome in the canvas colour on mobile. The favicon link
sits directly above the stylesheet link, grouping the two `link rel` lines:

```html
<link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2032%2032'%3E%3Crect%20width='32'%20height='32'%20rx='7'%20fill='%23201b26'/%3E%3Ccircle%20cx='16'%20cy='16'%20r='9'%20fill='%23c5a8f5'/%3E%3Ccircle%20cx='20'%20cy='12'%20r='8'%20fill='%23201b26'/%3E%3C/svg%3E">
```

The SVG is a 210-byte crescent moon authored for this phase: a rounded
square in the canvas colour, a full circle in the accent colour, and an
offset circle in the canvas colour carving the crescent. Two-circle
geometry renders identically in every engine; no path maths. It is the
OD-6 standing default (inline SVG moon as a data URI), which Maciek can
still veto at the PR diff; the swap is one href value. The data URI makes
the favicon request count zero (section 3.10), so the browser stops
asking for /favicon.ico on every page load.

## Files touched

| File | Change |
|---|---|
| `src/driftnote/web/templates/base.html.j2` | Skip link first in body; main gains `id="content"`; head gains the two metas and the favicon link; all other lines byte-identical |
| `src/driftnote/web/static/style.css` | 16 added lines after the banner block: the skip-link rules and the skip-target scroll handling; :root and everything else unchanged |
| `tests/integration/test_web_routes_browse.py` | One added smoke test pinning the phase-2 chrome |
| `docs/superpowers/specs/2026-11-08-issue-59-base-chrome.md` | This spec |
| `docs/superpowers/plans/2026-11-08-issue-59-base-chrome.md` | Implementation plan |

## Tests

### Run first, patch what breaks

Section 3.12's phase-2 bullet orders the suite run before any test edit,
and this phase followed it: the integration suite ran against the staged
template and stylesheet before anything in `tests/` was written. Result:
nothing broke. No existing assertion pins head markup anywhere in the
test tree; the browse suite's assertions all target body content
(calendar cells, chips, results), and a grep across `tests/` finds no
reference to the head, the stylesheet link, htmx, or main. No assertion
was patched, and none needed to be.

### Added coverage

One test in the existing smoke-test style of the browse file,
`test_base_chrome_skip_link_head_and_landmark`, which pins:

- the colour-scheme and theme-color metas, verbatim;
- the favicon link is a data URI under 1 KB;
- the skip link is the first focusable element: no anchor, button,
  input, textarea, or select sits between `<body>` and the link;
- main carries `id="content"`.

No new fixtures, no new test architecture: it uses the file's existing
`app_with_data` fixture and plain string assertions.

### Existing suites and gates

- `uv run pytest -m "not live"`: 236 passed, 2 skipped, 19 errors. The 19
  errors are the pre-existing testcontainers fixtures failing to reach a
  Docker socket this environment does not have; the pristine master
  worktree produces the same 19 error node ids. CI's runner has the
  socket, so they are expected green there.
- `uv run pytest tests/integration/test_web_routes_browse.py
  tests/integration/test_web_routes_edit.py
  tests/integration/test_web_routes_media_and_admin.py`: 38 passed.
- `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  `uv run mypy`: clean.
- `uv run python scripts/check-contrast.py
  src/driftnote/web/static/style.css`: still exits 0 and prints the same
  24-row table. Phase 2 adds no colours; the phase-1 pair set needs no
  change.

## Acceptance criteria

- [ ] The base.html.j2 diff adds exactly five things in the doc's order:
      skip link first in body, main id, colour-scheme meta, theme-color
      meta, favicon link; all other lines byte-identical.
- [ ] The style.css diff adds only the skip-link block and the skip-target
      rule, in the chrome region; :root is byte-identical.
- [ ] The skip link is the first tab stop and appears on focus, in the
      accent colour, with the existing focus-visible outline.
- [ ] No raw hex outside :root in the stylesheet, and no opacity outside
      the exemption the phase-1 tests already allow.
- [ ] The integration suite passed before any test edit, and the only test
      change is the added smoke test.
- [ ] `uv run pytest -m "not live"` passes apart from the environmental
      testcontainers errors that the pristine master run reproduces.
- [ ] ruff check, ruff format --check, mypy, and the contrast checker are
      green.
- [ ] Templates other than base.html.j2, routes, pyproject.toml, uv.lock:
      untouched.

## Risks

**Risk:** The focused skip link overlays the topbar's brand row.
**Mitigation:** It is a transient keyboard-only overlay that vanishes on
blur, on a raised surface so it reads as floating above the page. This is
the standard skip-link presentation; no layout shift is possible because
the element is fixed.

**Risk:** The favicon's crescent is hand-authored two-circle geometry, and
Maciek has not seen it yet (OD-6 is decided by standing default, not by
him).
**Mitigation:** The moon uses the app's own two palette values on the
canvas colour, and the whole icon is one href value: a veto is a one-line
swap with no test change beyond the length bound.

**Risk:** The doc lists the skip-link rule under both "reset and base" and
the chrome list in section 3.3.
**Mitigation:** Recorded in Architecture: this phase places the block in
the chrome region after the banners, matching the chrome order line.
Moving it later is a pure cut and paste.

**Risk:** A future phase pins or moves the markup this phase adds.
**Mitigation:** The added smoke test names the phase-2 chrome explicitly,
so the PR that moves the skip link or the id fails visibly and updates the
assertion in the same PR, per section 6's standing rule.

## Out of scope

- Colour tokens, radius, spacing, motion, typography: phases 3 to 5.
- The admin partial, the live refresh, and the htmx include move: phase 6.
- A light theme or any colour-scheme switching: issue-4 settled
  single-theme; the meta declares dark, it does not toggle.
- Serving /favicon.ico from the app: the data URI removes the request, so
  the route never needs to exist.
