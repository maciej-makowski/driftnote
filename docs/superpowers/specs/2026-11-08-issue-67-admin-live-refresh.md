# Phase 6: admin live refresh and htmx scoping

> Design spec for [issue #67](https://github.com/maciej-makowski/driftnote/issues/67).

Last PR of the driftnote web UI redesign (a six-phase plan; phases 1 to 5 are
#57, #59, #61, #63, and #65, all merged). This spec is self-contained: the
section numbers it cites belong to the redesign's design doc, which lives in
Maciek's private design repo and is not part of this repository.

## Goal

The admin tab shows job state that changes while the tab sits open, and until
now the only way to see a run land was a manual reload. Phase 6 lets the
cards refresh themselves: /admin embeds the cards grid inside an hx wrapper
that polls a new partial endpoint every 30s. In the same PR the htmx include
moves off base.html.j2 onto the two pages that use htmx, so the other four
page types stop downloading the 50,917 B file they never call (sections 3.5,
3.10, 3.12 phase 6; M4 records the include move as decided).

## Scope

**In:**
- `src/driftnote/web/routes_admin.py`: one new read-only endpoint,
  GET /admin/cards, rendering the partial with the no-store header. No new
  auth code: the JWT middleware is global.
- `src/driftnote/web/templates/_admin_cards.html.j2`: new partial,
  cards-only markup, extracted from admin.html.j2's cards section. Its root
  keeps the `.job-cards` class.
- `src/driftnote/web/templates/admin.html.j2`: the cards section becomes the
  hx wrapper with the include inside; `head_extra` gains the htmx script.
- `src/driftnote/web/templates/base.html.j2`: the global htmx script line is
  removed.
- `src/driftnote/web/templates/entry_edit.html.j2`: `head_extra` gains the
  htmx script beside the phase-5 roman preload.
- Tests: five added in `tests/integration/test_web_routes_media_and_admin.py`,
  one in `tests/integration/test_web_routes_edit.py`, one in
  `tests/integration/test_web_routes_browse.py`. No existing test changed.
- This spec and the implementation plan in `docs/superpowers/plans/`.

**Out:**
- The unsaved-changes guard: OD-4's standing default, none in v1.
- htmx itself: 2.0.4 unchanged, `.htmx-version` untouched, no new dependency.
- `auth.py`, `cloud.py`, `banners.py`: untouched. The middleware is installed
  once in `app.py` and wraps every route, including the new one.
- `style.css`: untouched. The settle-fade hooks landed in phase 5 and the
  partial keeps them valid.
- `pyproject.toml` and `uv.lock`: byte-identical.

## Architecture

### The cards endpoint

GET /admin/cards renders `_admin_cards.html.j2` from the same `_build_cards()`
data /admin uses, so the partial shows exactly what the full page shows. It
carries `Cache-Control: no-store`, the same header admin_index and admin_drill
set because their HTML reflects DB state that mutates as jobs run (see #23);
the poll swaps this response into the page, so a stale one would be as wrong
as a stale /admin. Auth is inherited, not added: Cloudflare Access fronts
every path at the edge, and behind it `_CFAccessMiddleware` (installed once in
`app.py`, over the whole app) verifies the `Cf-Access-Jwt-Assertion` JWT for
every route and answers 403 without it (auth.py; bypassed in dev,
auth.py:88-89). A route carries no auth code of its own because none exists
to add; the endpoint is one handler that renders a template.

### The wrapper and the re-arm, verified against the vendored htmx 2.0.4

The wrapper, verbatim from the design (section 3.5):

```html
<div id="job-cards"
     hx-get="/admin/cards"
     hx-trigger="every 30s"
     hx-target="this"
     hx-swap="innerHTML">
  <!-- the partial include renders here -->
</div>
```

`hx-swap` is innerHTML, not outerHTML, and that choice is what keeps the
refresh alive. The mechanics were read out of
`src/driftnote/web/static/htmx.min.js` (the vendored 2.0.4, 50,917 B), the
same source the phase-3 review and the phase-5 spec used for the settle
classes, not guessed:

1. Parsing. The trigger-spec parser maps `every <interval>` to a spec object
   carrying `pollInterval` in milliseconds: `if (c === "every") { const u =
   {trigger: "every"}; ... u.pollInterval = d(...) }`.
2. Start. At trigger init, htmx runs `else if (e.pollInterval > 0) {
   t.polling = true; ct(ue(r), n, e) }`. A poller therefore exists only on an
   element whose parsed specs carry a pollInterval, which is an element
   carrying the hx-* attributes.
3. The poller. `function ct(e, t, n) { const r = ie(e); r.timeout =
   setTimeout(function () { if (le(e) && r.cancelled !== true) { ...
   t(e) ...; ct(e, t, n) } }, n.pollInterval) }`. It captures the element
   reference and reschedules itself on that same element each tick. The gate
   is `le(e)`, which is `e.getRootNode({composed: true}) === document`: the
   tick fires only while that element is still in the document.
4. Under outerHTML, the swap replaces the wrapper element itself with the
   response fragment. The response is cards-only markup with no hx-*
   attributes, so when htmx processes the new content it parses no trigger
   specs and starts no poller. The old poller's element is now detached,
   `le(e)` is false, and the chain stops at the first tick. The refresh dies
   after one cycle, silently.
5. Under innerHTML, the wrapper survives the swap with its attributes
   intact. Its poller keeps firing against an element that stays in the
   document, and the swapped-in section carries no hx-* attributes, so htmx
   creates no second poller for it. The refresh continues for the life of
   the tab.

The config block confirms the settle side that follows:
`defaultSwapStyle:"innerHTML", defaultSwapDelay:0, defaultSettleDelay:20,
addedClass:"htmx-added"`. The swapped-in root is the partial's
`<section class="job-cards">` element. htmx inserts it carrying `htmx-added`
and removes the class after the 20 ms settle delay, which is exactly the
phase-5 settle fade: `.htmx-added { opacity: 0 }` plus the `opacity`
transition on `.job-cards` (style.css:393-399). The phase-5 spec pre-wired
that hook on the stated assumption that the partial's root would be the cards
grid itself, and flagged it for this PR; the partial keeps the assumption
true, so no CSS changed and no class moved.

### No-JS and the inert attributes

With JavaScript off, the hx-* attributes are inert data attributes: the page
renders once, exactly as before this phase (section 3.11). The cards are
server-rendered inside the wrapper on first load, the ack and ack-all flows
stay plain form POSTs, the filter stays a GET form, and the poll is additive
comfort on top of a page that already works, like the live preview.

### The include, moved

base.html.j2's `<script src="/static/htmx.min.js" defer></script>` line is
removed. The same line, byte for byte (same src, same defer, no cache
buster; base never carried a `?v`), lands in the `head_extra` block of
entry_edit.html.j2 and admin.html.j2, the two consumers after this phase.
entry_edit's block already carried the phase-5 roman preload; the script
sits after it. The four page types that carry no hx-* attribute (calendar,
tags, search, entry) render no script tag at all.

### Request arithmetic, end state (section 3.10)

The design's budget row, now true:

| Page | Requests | Notes |
|---|---|---|
| entry | 3 (HTML, CSS, font) | 4 when italic body text loads the second face |
| entry_edit | 4 (adds JS) | 5 likewise with italic |
| admin | 3 (adds JS) | |
| calendar, search, tags | 2 each | HTML + CSS only |
| favicon | 0 | data URI |

The phase-5 spec's table recorded the pre-phase-6 state, in which every page
paid the include. The JS total is unchanged (50,917 B, one file); only its
reach shrinks to the two consumers.

## Files touched

| File | Change |
|---|---|
| `src/driftnote/web/routes_admin.py` | GET /admin/cards after admin_index; no-store; reuses `_build_cards` |
| `src/driftnote/web/templates/_admin_cards.html.j2` | New partial: the cards grid, root `.job-cards` |
| `src/driftnote/web/templates/admin.html.j2` | Cards section becomes the hx wrapper with the include; `head_extra` gains the script |
| `src/driftnote/web/templates/base.html.j2` | The global htmx script line removed |
| `src/driftnote/web/templates/entry_edit.html.j2` | `head_extra` gains the script after the preload |
| `tests/integration/test_web_routes_media_and_admin.py` | Five tests added |
| `tests/integration/test_web_routes_edit.py` | `test_edit_page_carries_the_htmx_script` added |
| `tests/integration/test_web_routes_browse.py` | `test_no_js_page_types_carry_no_htmx_script` added |
| `docs/superpowers/specs/2026-11-08-issue-67-admin-live-refresh.md` | This spec |
| `docs/superpowers/plans/2026-11-08-issue-67-admin-live-refresh.md` | Implementation plan |

## Tests

### Run first, patch what breaks

The suite ran against the staged changes against the pristine master baseline
(f596fb4: 256 passed, 2 skipped, 19 environmental errors, identical node ids).
Nothing broke: no test pinned base.html.j2's script tag, and the admin tests
survived the markup extraction because the include renders the same card
markup into /admin that the inline loop used to.

### Added coverage

Five integration tests in `tests/integration/test_web_routes_media_and_admin.py`:

- `test_admin_cards_partial_renders_the_cards`: 200, the grid section as
  root, card content and dot class present, and cards-only shape (no page
  chrome, no wrapper, no hx attributes).
- `test_admin_cards_partial_carries_no_store`: cache-control is exactly
  `no-store`.
- `test_admin_cards_endpoint_auth_gated_like_its_parent`: with the
  middleware installed in prod mode (the HS256 signing-key pattern
  `tests/unit/test_web_auth.py` established), /admin and /admin/cards both
  answer 403 without the Access header and 200 with a valid token.
- `test_admin_page_embeds_the_cards_wrapper`: the four hx attributes
  verbatim, the seven cards server-rendered inside the wrapper, and the
  drill view polling the same partial (it shares the template).
- `test_admin_page_carries_the_htmx_script`: the script in base's exact
  form in admin's head.

One in `tests/integration/test_web_routes_edit.py`:
`test_edit_page_carries_the_htmx_script`, which also asserts the phase-5
preload is still there. One in `tests/integration/test_web_routes_browse.py`:
`test_no_js_page_types_carry_no_htmx_script`, which asserts the calendar,
search, tags, and entry heads carry no script tag.

### Existing suites and gates

- `uv run pytest -m "not live"`: 263 passed, 2 skipped, 19 errors. The 19
  error node ids are byte-identical to the pristine f596fb4 run
  (testcontainers fixtures that need a Docker socket this environment does
  not have; CI's runner has one).
- `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  `uv run mypy`: clean.
- `uv run python scripts/check-contrast.py src/driftnote/web/static/style.css`:
  exit 0, 27 rows, no colour change in this phase.

## Acceptance criteria

- [ ] GET /admin/cards renders the cards-only partial, carries no-store,
      and passes through the global JWT middleware with no new auth code.
- [ ] admin.html.j2 embeds the partial inside the wrapper with the exact
      attribute set (`id="job-cards"`, `hx-get="/admin/cards"`,
      `hx-trigger="every 30s"`, `hx-target="this"`, `hx-swap="innerHTML"`),
      and the cards render server-side without JS.
- [ ] The innerHTML re-arm rationale is verified against the vendored htmx
      2.0.4 and recorded in this spec.
- [ ] base.html.j2 carries no htmx script; entry_edit and admin carry it in
      base's exact form (same src, same defer, no cache buster).
- [ ] The partial's root keeps `.job-cards`, so the phase-5 settle fade
      applies unchanged and no CSS changes.
- [ ] The four no-JS page types render no script tag; the request
      arithmetic matches the design's 3.10 end-state row.
- [ ] The gates are green with the stated numbers; `pyproject.toml` and
      `uv.lock` are byte-identical; htmx and `.htmx-version` untouched.

## Risks

**Risk:** A 30s poll adds background traffic for every open admin tab.
**Mitigation:** One small render over seven jobs per tab per 30s, behind
Access where only the admin can reach it. The poll also stops itself when
the page goes away: the wrapper leaves the document, `le(e)` fails, and the
rescheduling chain ends.

**Risk:** A future edit swaps outerHTML back in and kills the refresh after
the first cycle, which is silent.
**Mitigation:** The template comment beside the wrapper states the re-arm
rationale, and `test_admin_page_embeds_the_cards_wrapper` pins
`hx-swap="innerHTML"`.

**Risk:** The partial drifts from the page's card markup.
**Mitigation:** There is no copy to drift: admin.html.j2 includes the
partial, so the drill view and the index render through the same markup.
The partial is the only card-grid source.

**Risk:** Polling could resurrect cached HTML between cycles.
**Mitigation:** The response carries `no-store`, the directive #23 added to
the DB-derived admin views; the browser cannot reuse a stored response for
the next poll.

## Out of scope

- The unsaved-changes guard: OD-4's standing default, none in v1.
- htmx version bumps: Implementation.md's manual procedure, untouched.
- Auth changes: F1 keeps Cloudflare Access and the JWT middleware as they
  are.
- Deployment: this phase rides the second batched deploy (M2, Maciek-gated),
  which per section 4.4 also verifies /admin/cards renders the cards and
  302s when unauthenticated through the edge. Revert of this phase removes
  one read-only GET endpoint.
