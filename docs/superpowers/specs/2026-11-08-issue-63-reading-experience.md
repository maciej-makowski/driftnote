# Phase 4: reading experience and the vendored Newsreader serif

> Design spec for [issue #63](https://github.com/maciej-makowski/driftnote/issues/63).

Fourth PR of the driftnote web UI redesign (a six-phase plan; phases 1 to 3
are #57, #59, and #61, all merged). This spec is self-contained: the section
numbers it cites belong to the redesign's design doc, which lives in Maciek's
private design repo and is not part of this repository.

## Goal

Make the entry page a reading page. The markdown body gets the one vendored
serif the adoption decision (M3) picked, at 17px with 1.65 leading and a 62ch
measure; the heading names the weekday next to the ISO date; a quiet back
link sits above it; photos tile as a lazy-loaded grid; the edit link becomes
a quiet button. Search rows get the same scan-first structure (the date and
mood link becomes the row heading) and the search input names itself for
screen readers. The serif ships as four committed WOFF2 files plus the OFL
licence, authored once with fonttools from the Google Fonts sources. No
build step appears; no runtime dependency is added (sections 3.5, 3.6, 3.12
phase 4, M3).

## Scope

**In:**
- `src/driftnote/web/templates/entry.html.j2`: back link, weekday in the h1,
  the `.entry-body` wrapper, the media grid, thumb alt text, lazy loading,
  explicit thumb dimensions, and the quiet edit link.
- `src/driftnote/web/templates/base.html.j2`: an empty `head_extra` block in
  `<head>`, filled by the serif pages that need it.
- `src/driftnote/web/templates/entry_edit.html.j2`: no change this phase
  (the edit page renders no serif face yet; its preload joins in phase 5).
- `src/driftnote/web/templates/search.html.j2`: the input's `aria-label` and
  the heading structure on result rows. The em-dash separator stays verbatim.
- `src/driftnote/web/routes_browse.py`: the weekday Jinja filter, registered
  where the templates instance is built. No route change.
- `src/driftnote/web/static/style.css`: four `@font-face` rules, the
  `--font-serif` token, the `.entry-body` serif block, the media grid rules,
  and the entry page furniture the markup above needs (back link, quiet
  edit button).
- `src/driftnote/web/static/fonts/`: four WOFF2 files and `OFL.txt`, all
  committed as static assets.
- `scripts/check-contrast.py`: one added pair row (see Tests).
- `tests/integration/test_web_routes_browse.py` and
  `tests/integration/test_web_routes_edit.py`: eight added tests, no
  existing assertion changed.
- This spec and the implementation plan in `docs/superpowers/plans/`.

**Out:**
- The preview panel's serif styling and the rest of the entry-edit polish
  (min-height on `#preview`, the mood input's `aria-label`, the roman-face
  preload on the edit page): phase 5. The preload deliberately waits:
  nothing on the edit page consumes the face until the preview inherits
  the serif, so preloading now would fetch bytes no rule renders and log a
  preloaded-but-unused warning.
- The banner entrance animation, the preview and admin settle fades, and the
  `--ease-soft`, `--dur-med`, `--dur-slow` tokens: phase 5.
- The admin cards partial, the 30s refresh, and the htmx include move: phase
  6. The htmx script still loads on every page until then.
- The `--font-sans` and `--font-mono` tokens from section 3.6: they stay
  literal in `body` and the textarea because no rule this phase consumes
  them. `--font-serif` is the only stack token this phase adds, because
  `.entry-body` is its only consumer.
- `pyproject.toml` and `uv.lock`: byte-identical. fonttools and brotli ran
  from a scratch venv outside the repository.

## Architecture

### Font authoring: the recipe

One-off authoring, not a build step (section 3.6): the WOFF2 files are
committed; nothing in CI or the app regenerates them. Re-subsetting is a
manual step that runs only when the face or the subset changes.

Sources, fetched 2026-11-08 from `github.com/google/fonts` at
`ofl/newsreader/`:

- `Newsreader[opsz,wght].ttf` (451,664 B), the roman variable font.
- `Newsreader-Italic[opsz,wght].ttf` (495,684 B), the italic variable font.
- `OFL.txt` (4,394 B), vendored verbatim.

Both fonts carry two axes: `wght` 200 to 800 (default 400) and `opsz` 6 to
72 (default 18). The recipe pins both, then subsets:

1. Instance the variable font to a static cut: fonttools
   `varLib.instancer.instantiateVariableFont` with `wght=400` and
   `opsz=17`. The intermediates (118,224 B roman, 129,048 B italic) were
   kept only in the authoring workspace; they are not committed.
2. Subset each static cut twice with pyftsubset, once to the Google Fonts
   latin codepoints and once to latin-ext, `--flavor=woff2`,
   `--layout-features=*` (keeps kerning and the standard GSUB set).

The unicode ranges are copied verbatim from Google Fonts' own CSS for
Newsreader (ital 0 and 1, `opsz` 6..72, `wght` 400), which is what browsers
actually receive from fonts.googleapis.com:

- latin: `U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA,
  U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191,
  U+2193, U+2212, U+2215, U+FEFF, U+FFFD`
- latin-ext: `U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7,
  U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F,
  U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F,
  U+A720-A7FF`

The exact commands live in the authoring script (fonttools 4.68.0 plus
brotli 1.2.1 from the scratch venv; note fonttools 4.68 no longer names a
`woff2` extra, so brotli is installed explicitly).

Measured byte counts, replacing the design's 30 to 90 KB estimate
(section 7 records the estimate status):

| File | Bytes |
|---|---|
| `newsreader-400.woff2` | 23,200 |
| `newsreader-400-italic.woff2` | 25,268 |
| `newsreader-400-latin-ext.woff2` | 12,812 |
| `newsreader-400-italic-latin-ext.woff2` | 13,820 |
| `OFL.txt` | 4,394 |

The latin pair totals 48,468 B; all four faces total 75,100 B. The image
grows by the stylesheet delta (9,281 B to 12,504 B) plus the five committed
files (79,494 B).

### The opsz pin: 17

The opsz axis value is pinned at 17, not at the foundry default 18. Browsers
implement `font-optical-sizing: auto` (the default) by setting the opsz axis
close to the used font size; the CSS Fonts 4 note says user agents are
"expected to supply a value for the 'opsz' axis which is close to the used
value for font-size", and Google Fonts' own type documentation confirms
browsers match the axis to the CSS px size rather than to print points. The
body renders at 17px, so a browser holding the variable font would select
opsz of about 17. Pinning the static cut at 17 bakes exactly that optical
grade. The axis runs 6 (footnote-grade, loose spacing) to 72 (display
contrast); 17 keeps the text-grade cut. Because the static file carries no
fvar axis, `font-optical-sizing` becomes moot: what is committed is the
optical size.

### The latin-ext decision: include

Polish, Czech, and Hungarian diacritics are the risk the design names
(section 6), and Maciek's journal plausibly contains them, so the two
latin-ext files are vendored. The measured total of 75,100 B stays under the
90 KB worst-case budget the fonts row carries (section 3.10), whether that
budget is read as 90,000 B or 90 KiB, so the subset costs nothing to carry.
The files wire in through `unicode-range`, so a browser fetches one only
when one of its codepoints actually renders: an entry without diacritics
never downloads them. The request arithmetic below records the impact.

This is an interpretation call under M3 (the decision names "latin subset,
400 roman + 400 italic"; the ext files extend the same faces at the same
weight). It is vetoable: dropping the ext files means deleting two WOFF2
files and two `@font-face` rules, and the latin pair alone costs 48,468 B.
Latin-ext characters outside the vendored ranges fall back per glyph to the
system serif, exactly as the design's risk row describes.

### The `@font-face` wiring

Four top-level rules sit directly before the entry view section of
`style.css`, one per subset and style. Every rule carries:

- `font-family: "Newsreader"`, matching the consuming list on `.entry-body`.
- `font-weight: 400`.
- `font-display: swap`, so system-serif text shows while a file loads.
- `font-style: italic` on the two italic files, normal otherwise.
- `src: url("/static/fonts/...") format("woff2")`.
- The per-subset `unicode-range` listed above.

The fallback stack lives on the consuming list, not in the face rules
(section 3.6):

```css
.entry-body {
  font-family: "Newsreader", var(--font-serif);
  font-size: 17px;
  line-height: 1.65;
  max-width: 62ch;
}
```

`--font-serif` is `ui-serif, Georgia, "Iowan Old Style", "Times New Roman",
serif`, added to the second `:root` block (the first holds the 18 colour
tokens the phase-1 test pins exactly). A failed or blocked font file falls
back to the system serif at the same size and leading. The h1, the tags, the
back link, and the edit button stay in the system sans; only the reading
body carries the serif, and the italic file exists for the italic runs
inside it.

The stylesheet's invariant greps hold: no raw hex outside `:root`, no
shadows, no gradients, no keyframes, no transforms. `unicode-range` writes
`U+` ranges, not hex colours.

### Preload scoping

`base.html.j2` gains an empty `{% block head_extra %}{% endblock %}` inside
`<head>`, right after the stylesheet link. Nothing in the base template
references a font. `entry.html.j2` fills the block now; `entry_edit.html.j2`
joins in phase 5, when the preview panel gains the serif — preloading now
would fetch a face nothing on that page consumes and log a
preloaded-but-unused warning. The link both templates will carry:

```html
<link rel="preload" href="/static/fonts/newsreader-400.woff2" as="font" type="font/woff2" crossorigin>
```

Only the roman latin face preloads. The `crossorigin` attribute is required
even same-origin because font requests always run in CORS mode; without it
the preload would be discarded and the file would fetch twice. The italic
and the two latin-ext files are never preloaded; `unicode-range` fetches
them on demand. The other four page types fetch no font file, which the
calendar test pins.

### Per-page request arithmetic (section 3.10, updated)

Counts follow the design's row: a request is counted when the resource is
fetched; on a repeat visit a cached static asset does not re-request. Fonts
live under `/static/`, which is not `no-store`, so a face fetched once is
cached afterwards.

| Page | Steady state | With italic text | With latin-ext glyphs | Worst case |
|---|---|---|---|---|
| entry | 4 (HTML, CSS, htmx JS, roman) | 5 | +1 per ext file used | 7 (HTML, CSS, JS, four faces) |
| entry_edit | 3 (HTML, CSS, htmx JS; no face this phase) | 3 | 3 | 3 (faces join in phase 5) |
| calendar, search, tags | 3 (HTML, CSS, htmx JS) | 3 | 3 | 3 |
| admin | 3 (HTML, CSS, htmx JS) | 3 | 3 | 3 |
| favicon | 0 | 0 | 0 | 0 |

Every page still pays the global htmx include (counted above) until phase 6
scopes it to the two consumers; the design's section 3.10 row describes that
post-phase-6 end state, not this phase's.

### Entry page and search page markup

`entry.html.j2`, in order: the back link (`<p class="back"><a
href="/">Calendar</a></p>`), the h1 (`{{ entry.date|weekday }} {{ entry.date
}}` plus the mood span), the tags line, the body in `.entry-body`, the media
section, and the edit link as `<p class="entry-actions"><a
href="...">Edit</a></p>`. The weekday comes from the filter because
`entry.date` is a plain string. The filter maps `date.fromisoformat(...).weekday()`
through a static English name tuple; it is deterministic and not
locale-dependent, and an unparseable date renders an empty string rather
than a 500. The 4px accent left border on `.entry` stays, as the design
requires.

Photos wrap in `<div class="media-grid">`; each thumb anchor keeps its link
to the web-size copy, and the image carries `alt="photo from {{ entry.date
}}"`, `width="160"`, `height="160"`, and `loading="lazy"`. The explicit
dimensions plus `object-fit: cover` in CSS give every photo the same tile
shape with no layout shift; the crop is display-only and the anchor still
opens the full web-size photo. Videos keep `preload="none"`, controls, and
poster, and gain `border-radius: var(--radius-m)` in CSS; they stay outside
the grid in document flow. Thumbs are served at max-axis 320px JPEG, so a
160px tile downsamples them.

The stylesheet adds, in the entry section: `.entry .back` (muted 13px link),
`.entry-body`, `.media-grid` (auto-fill 160px columns, spacing-scale gap),
the 160px cover-cropped radius img, the video radius, and `.entry-actions`
(raised fill, radius, padding; hover moves to `--bg-hover` and keeps the
text colour). All use existing tokens; no new colour values.

`search.html.j2` adds `aria-label="Search query"` to the input and wraps
each result's date-plus-mood link in `<h2 class="result-heading">`, so the
scan pattern is date first and screen-reader heading navigation works per
row. The em-dash separator stays between the link and the excerpt, verbatim
repo content. The rows already carry the soft-card look from phase 3; this
phase changes their structure only.

## Files touched

| File | Change |
|---|---|
| `src/driftnote/web/templates/entry.html.j2` | Back link, weekday h1, `.entry-body`, media grid with lazy 160px thumbs and alt text, quiet edit link, preload block |
| `src/driftnote/web/templates/base.html.j2` | Empty `head_extra` block in `<head>` |
| `src/driftnote/web/templates/entry_edit.html.j2` | head_extra block left unfilled this phase; the preload joins in phase 5 with the preview serif |
| `src/driftnote/web/templates/search.html.j2` | Input `aria-label`; result heading structure; em-dash kept |
| `src/driftnote/web/routes_browse.py` | Static weekday name tuple, the `weekday` filter function, registration on the templates env |
| `src/driftnote/web/static/style.css` | `--font-serif` token; four `@font-face` rules; `.entry-body`; media grid; back-link, video-radius, and quiet-button rules |
| `src/driftnote/web/static/fonts/` | Four WOFF2 files and `OFL.txt` (new directory) |
| `scripts/check-contrast.py` | One added pair row |
| `tests/integration/test_web_routes_browse.py` | Seven added tests |
| `tests/integration/test_web_routes_edit.py` | One added test |
| `docs/superpowers/specs/2026-11-08-issue-63-reading-experience.md` | This spec |
| `docs/superpowers/plans/2026-11-08-issue-63-reading-experience.md` | Implementation plan |

## Tests

### Run first, patch what breaks

The full suite ran against the staged template, stylesheet, route, and font
changes before any test file was touched, against the pristine master
baseline (bbf09ea: 240 passed, 2 skipped, 19 environmental errors). Result:
nothing broke. No existing assertion pins the entry h1's contents, the body
wrapper, the media markup, the search row structure, or the head contents,
so no test needed patching. The 19 error node ids are byte-identical to the
pristine run (testcontainers fixtures failing to reach a Docker socket this
environment does not have; CI's runner has the socket).

### Added coverage

Eight tests, in the existing files' style, no new fixtures beyond one
local setup that seeds media rows:

- `test_entry_page_heading_carries_weekday`: the h1 reads "Wednesday
  2026-05-06" (the fixture date is a Wednesday) and the body renders inside
  `.entry-body`.
- `test_entry_page_has_quiet_back_link`: the Calendar link sits above the
  h1.
- `test_entry_page_media_grid_marks_thumbs`: with one photo and one video
  seeded, the thumb anchor targets the web-size copy, the img serves the
  thumb file with `alt="photo from 2026-05-06"`, `width="160"`
  `height="160"`, and `loading="lazy"`, photos sit in `.media-grid`, and
  videos keep `preload="none"`.
- `test_entry_page_preloads_roman_font_only`: the entry head preloads the
  roman face and references no italic or latin-ext file.
- `test_calendar_page_fetches_no_font_file`: the calendar head carries no
  preload link and no font reference.
- `test_search_input_has_aria_label`: the input names itself "Search
  query".
- `test_search_results_render_date_link_as_row_heading`: the hit's heading
  is the date and mood link, and the em-dash still separates link from
  excerpt.
- `test_edit_page_defers_roman_preload` (edit file): the edit page head
  carries no preload this phase; it joins in phase 5 with the preview serif.

### Existing suites and gates

- `uv run pytest -m "not live"`: 248 passed, 2 skipped, 19 errors. The 19
  error node ids match the pristine baseline run exactly. 240 of the passes
  are master's own; the eight new tests account for the delta.
- `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  `uv run mypy`: clean.
- `uv run python scripts/check-contrast.py
  src/driftnote/web/static/style.css`: exit 0.
- Each committed WOFF2 file starts with the `wOF2` magic bytes; the licence
  file is the SIL Open Font License 1.1 text with no HTML in it.
- Coverage spot checks ran during authoring: the latin files contain the
  basic latin and Latin-1 letters and no latin-ext diacritics; the ext
  files contain the diacritics and no basic latin letters.

## Acceptance criteria

- [ ] The entry h1 shows the weekday next to the ISO date, resolved by a
      static English mapping registered as the `weekday` filter where the
      templates instance is built; no route change.
- [ ] The entry body renders inside `.entry-body` with the vendored serif
      first and `--font-serif` behind it, 17px, 1.65 leading, 62ch measure.
- [ ] The entry page has the quiet Calendar back link above the h1 and the
      quiet raised-fill Edit link; the 4px accent left border stays.
- [ ] Photos render in a grid of 160px tiles with `loading="lazy"`,
      explicit width and height, and `alt="photo from {date}"`; videos keep
      `preload="none"` and gain the radius.
- [ ] Four WOFF2 files and the OFL licence are committed under
      `static/fonts/`, authored by the recipe in this spec, with the
      measured byte counts recorded (75,100 B total, latin pair 48,468 B).
- [ ] Every `@font-face` rule carries `font-display: swap`, the italic
      files carry `font-style: italic`, and each rule carries its subset's
      `unicode-range`.
- [ ] Only entry preloads the roman face this phase, via the `head_extra`
      block (the edit page joins in phase 5); base.html.j2 preloads nothing;
      the other five page types fetch no font file.
- [ ] The search input carries `aria-label="Search query"`; result rows
      carry the date-and-mood link as an h2 heading; the em-dash separator
      stays.
- [ ] The contrast checker exits 0; the quiet-button hover pair joins the
      gate and passes.
- [ ] The phase-1 unit tests pass unmodified; the phase-3 suite passes
      unmodified.
- [ ] `pyproject.toml` and `uv.lock` are byte-identical; no build step, no
      bundler, no package.json.

## Risks

**Risk:** The latin-ext inclusion is an M3 interpretation call.
**Mitigation:** The budget arithmetic is recorded (75,100 B total, under
the 90 KB worst case on either KB convention), the wiring costs nothing at
request time thanks to `unicode-range`, and the veto path is two file
deletions and two rule deletions. Flagged for review.

**Risk:** The static opsz pin fixes the optical grade at 17 while the
variable font would follow the CSS size.
**Mitigation:** The serif applies only to `.entry-body`, which is always
17px. If a later phase renders the serif at another size, the face needs a
second pinned cut or the variable file, and the spec then records that.

**Risk:** The quiet-button hover pair extends the contrast gate from 26 to
27 rows.
**Mitigation:** The repo's own convention adds new text/surface pairs to
the gate in the PR that introduces them; the new pair (fg on bg-hover,
10.51:1) passes. The phase-1 unit tests do not pin the row count and pass
unmodified. Flagged for review.

**Risk:** The search row headings inherit the global h2 margins inside the
row cards, so rows carry more vertical space than the old inline links.
**Mitigation:** The phase's stylesheet boundary excludes search CSS; if the
spacing reads too loose in review, a one-line `.search-results h2` margin
reset is the follow-up. No test pins row spacing.

**Risk:** The italic file (25.3 KB) is slightly larger than the roman
(23.2 KB) and both load on demand only.
**Mitigation:** `font-display: swap` keeps system-serif text visible while
a file loads, and the preload covers the roman face, the one every entry
page needs.

**Risk:** The Google Fonts repository moves the source files and the
documented raw URLs stop resolving.
**Mitigation:** The recipe names the exact paths and the fallback
(fontsource prebuilt WOFF2, licence re-verified) that was prepared but not
needed. The committed files do not depend on the URLs.

## Out of scope

- The preview panel's serif inheritance, the preview min-height, and the
  mood input's `aria-label`: phase 5, which owns entry_edit.html.j2's
  remaining items.
- The banner entrance animation and the remaining motion tokens: phase 5.
- The admin cards partial and the htmx include move: phase 6.
- The `--font-sans` and `--font-mono` tokens, until a rule consumes them.
- Calendar photo thumbnails, lightbox, emoji picker, tag autocomplete
  (other issues, per section 1.10).
- Any change to `cloud.py`, `banners.py`, auth, the digest emails, or the
  media pipeline.
