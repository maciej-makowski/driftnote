# Issue #7 — Robust quote-stripping for non-Gmail clients

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replies sent from Outlook (web/desktop), Apple Mail (mac/iOS), iPhone Gmail app, and locale-translated clients should not bleed quoted prompt text into the journal entry body.

**Architecture:** `_strip_quoted` in `src/driftnote/ingest/parse.py` currently has only two patterns (`On … wrote:` and `From: …`). Expand to cover the common attribution/separator forms used by major clients, plus a defensive fallback that trims everything after a recognised separator line. No new dependencies — pure regex addition.

**Tech Stack:** stdlib `re`, existing `email` parser. No new deps (option (c) from the issue).

**Issue:** https://github.com/maciej-makowski/driftnote/issues/7

---

## Chunk 1: Expand patterns + per-client fixtures

### Task 1: Add fixture .eml files for non-Gmail clients

**Files:**
- Create: `tests/fixtures/emails/reply_outlook_web.eml`
- Create: `tests/fixtures/emails/reply_apple_mail_macos.eml`
- Create: `tests/fixtures/emails/reply_iphone_gmail_app.eml`
- Create: `tests/fixtures/emails/reply_french_locale.eml`
- Create: `tests/fixtures/emails/reply_outlook_separator_line.eml`

Each fixture is a plain `.eml` file that includes representative reply formatting from that client. Use the templates below verbatim — the bodies are crafted to verify both that the new content is preserved AND that the quoted prompt is stripped.

- [ ] **Step 1: Create `tests/fixtures/emails/reply_outlook_web.eml`**

```
From: you@example.com
To: you+driftnote@example.com
Subject: Re: [Driftnote] How was 2026-05-09?
Message-ID: <reply-outlook-web@example.com>
In-Reply-To: <prompt-2026-05-09@driftnote>
Date: Sat, 09 May 2026 21:30:00 +0000
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 7bit

Mood: 💪

Outlook web reply body. Coffee with Anna in the morning. #social

________________________________
From: Driftnote <you@example.com>
Sent: Saturday, May 9, 2026 9:00:00 PM
To: you+driftnote@example.com
Subject: [Driftnote] How was 2026-05-09?

Hi,

How was 2026-05-09?
```

- [ ] **Step 2: Create `tests/fixtures/emails/reply_apple_mail_macos.eml`**

```
From: you@example.com
To: you+driftnote@example.com
Subject: Re: [Driftnote] How was 2026-05-09?
Message-ID: <reply-apple-macos@example.com>
In-Reply-To: <prompt-2026-05-09@driftnote>
Date: Sat, 09 May 2026 21:30:00 +0000
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 7bit

Mood: 🌧️

Apple Mail macOS reply body. Long walk after lunch. #outdoor

> On May 9, 2026, at 9:00 PM, Driftnote <you@example.com> wrote:
>
> Hi,
> How was 2026-05-09?
```

- [ ] **Step 3: Create `tests/fixtures/emails/reply_iphone_gmail_app.eml`**

```
From: you@example.com
To: you+driftnote@example.com
Subject: Re: [Driftnote] How was 2026-05-09?
Message-ID: <reply-iphone-gmail@example.com>
In-Reply-To: <prompt-2026-05-09@driftnote>
Date: Sat, 09 May 2026 21:30:00 +0000
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 7bit

Mood: 🎉

iPhone Gmail body. Birthday dinner. #birthday #family

Sent from my iPhone

> On May 9, 2026, at 9:00 PM, Driftnote <you@example.com> wrote:
>
> Hi,
> How was 2026-05-09?
```

- [ ] **Step 4: Create `tests/fixtures/emails/reply_french_locale.eml`**

```
From: you@example.com
To: you+driftnote@example.com
Subject: Re: [Driftnote] How was 2026-05-09?
Message-ID: <reply-french-locale@example.com>
In-Reply-To: <prompt-2026-05-09@driftnote>
Date: Sat, 09 May 2026 21:30:00 +0000
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 7bit

Mood: ☕

Journée tranquille au café. #lecture

Le 9 mai 2026 à 21:00, Driftnote <you@example.com> a écrit :
> Bonjour,
> Comment s'est passée ta journée du 2026-05-09 ?
```

- [ ] **Step 5: Create `tests/fixtures/emails/reply_outlook_separator_line.eml`**

```
From: you@example.com
To: you+driftnote@example.com
Subject: Re: [Driftnote] How was 2026-05-09?
Message-ID: <reply-outlook-sep@example.com>
In-Reply-To: <prompt-2026-05-09@driftnote>
Date: Sat, 09 May 2026 21:30:00 +0000
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 7bit

Mood: 😴

Old-school Outlook reply with the separator. #work

-----Original Message-----
From: Driftnote <you@example.com>
Sent: Saturday, May 9, 2026 9:00 PM
To: you+driftnote@example.com
Subject: [Driftnote] How was 2026-05-09?

Hi,
How was 2026-05-09?
```

- [ ] **Step 6: Commit fixtures**

```bash
git add tests/fixtures/emails/reply_outlook_web.eml \
        tests/fixtures/emails/reply_apple_mail_macos.eml \
        tests/fixtures/emails/reply_iphone_gmail_app.eml \
        tests/fixtures/emails/reply_french_locale.eml \
        tests/fixtures/emails/reply_outlook_separator_line.eml
git commit -m "test(fixtures): add reply .eml fixtures for non-Gmail clients"
```

---

### Task 2: Write the failing parse-test that exercises every fixture

**Files:**
- Modify: `tests/unit/test_ingest_parse.py` (add a parametrised test)

- [ ] **Step 1: Append the test**

```python
import pytest as _pytest
from pathlib import Path as _Path

_FIXTURE_DIR = _Path(__file__).parent.parent / "fixtures" / "emails"


@_pytest.mark.parametrize(
    "fixture_name,expected_body_substr,expected_mood",
    [
        ("reply_outlook_web.eml", "Outlook web reply body", "💪"),
        ("reply_apple_mail_macos.eml", "Apple Mail macOS reply body", "🌧️"),
        ("reply_iphone_gmail_app.eml", "iPhone Gmail body", "🎉"),
        ("reply_french_locale.eml", "Journée tranquille au café", "☕"),
        ("reply_outlook_separator_line.eml", "Old-school Outlook reply", "😴"),
    ],
)
def test_parse_strips_quoted_block_for_real_clients(
    fixture_name: str, expected_body_substr: str, expected_mood: str
) -> None:
    raw = (_FIXTURE_DIR / fixture_name).read_bytes()
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.mood == expected_mood
    assert expected_body_substr in parsed.body
    # The original prompt should never bleed into the parsed body.
    assert "How was 2026-05-09" not in parsed.body
    assert "Comment s'est passée" not in parsed.body  # French prompt
    # Outlook's "From: <sender> Sent: ... Subject: ..." block must be stripped.
    assert "Sent: Saturday" not in parsed.body
    # The "Sent from my iPhone" signature is treated as user content here —
    # acceptable; the intent of this test is the QUOTED prompt is stripped.
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/unit/test_ingest_parse.py::test_parse_strips_quoted_block_for_real_clients -v`
Expected: at least 3 of the 5 cases FAIL — current `_QUOTE_HEADER_PATTERNS` doesn't cover Outlook's full header block, the locale-translated `a écrit :`, or the `-----Original Message-----` separator.

---

### Task 3: Expand `_QUOTE_HEADER_PATTERNS` to cover the new cases

**Files:**
- Modify: `src/driftnote/ingest/parse.py` (lines around `_QUOTE_HEADER_PATTERNS`)

- [ ] **Step 1: Replace the pattern tuple**

In `src/driftnote/ingest/parse.py`, locate `_QUOTE_HEADER_PATTERNS` (around line 41):

```python
_QUOTE_HEADER_PATTERNS = (
    re.compile(r"^On\s+.+\s+wrote:\s*$", re.MULTILINE),
    re.compile(r"^From:\s+.+$", re.MULTILINE),  # Outlook-style "From:" thread headers
)
```

Replace with:

```python
# Each pattern matches the FIRST line of a quoted-reply header block. The
# stripper truncates the body at the earliest such line. Order does not
# matter — we pick the earliest position regardless of which pattern matched.
_QUOTE_HEADER_PATTERNS = (
    # Gmail / many clients: "On <date>, <name> wrote:"
    re.compile(r"^On\s+.+\s+wrote:\s*$", re.MULTILINE),
    # French locale (Apple Mail / Gmail FR): "Le <date> ..., <name> a écrit :"
    re.compile(r"^Le\s+.+\s+a\s+écrit\s*:\s*$", re.MULTILINE),
    # German locale: "Am <date> schrieb <name>:"
    re.compile(r"^Am\s+.+\s+schrieb\s+.+:\s*$", re.MULTILINE),
    # Polish locale: "<date> <name> napisał(a):"
    re.compile(r"^.+\s+napisał(?:a|\(a\))?\s*:\s*$", re.MULTILINE),
    # Outlook web: long underscore separator above the From: block.
    re.compile(r"^_{3,}\s*$", re.MULTILINE),
    # Outlook desktop / Exchange: explicit "-----Original Message-----" separator.
    re.compile(r"^-{3,}\s*Original\s+Message\s*-{3,}\s*$", re.MULTILINE),
    # Outlook bare "From:" header (kept last as a defensive catch — only
    # fires if none of the more specific separators above matched).
    re.compile(r"^From:\s+.+$", re.MULTILINE),
)
```

- [ ] **Step 2: Run the parametrised test**

Run: `uv run pytest tests/unit/test_ingest_parse.py::test_parse_strips_quoted_block_for_real_clients -v`
Expected: 5 passed.

- [ ] **Step 3: Run the full parse suite**

Run: `uv run pytest tests/unit/test_ingest_parse.py -v`
Expected: all (10 prior + 5 new = 15) tests pass.

- [ ] **Step 4: Run the full suite + lint + types**

Run: `uv run pytest -m "not live" -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy`
Expected: 180 passed (175 prior + 5 new); lint/types clean.

- [ ] **Step 5: Commit**

```bash
git add src/driftnote/ingest/parse.py tests/unit/test_ingest_parse.py
git commit -m "$(cat <<'EOF'
feat(ingest): broaden quote-stripping to Outlook, Apple Mail, locales

_strip_quoted previously matched only Gmail-style "On ... wrote:" and a
bare "From:" header. Replies from Outlook web/desktop, Apple Mail iOS,
and locale-translated clients (FR/DE/PL) were leaking the entire quoted
prompt block into the journal entry body.

New patterns:
  - "Le ... a écrit :" (French)
  - "Am ... schrieb ...:" (German)
  - "... napisał(a):" (Polish)
  - "________________________________" (Outlook web separator)
  - "-----Original Message-----" (Outlook desktop / Exchange separator)

The existing Gmail "On ... wrote:" and bare "From:" patterns stay; the
stripper continues to pick the earliest matching position.

Five new fixture-driven tests cover real-client output.

Closes #7
EOF
)"
```

### Closeout

**Acceptance criteria:**
- [ ] All five fixture-driven tests pass
- [ ] No regression on the existing Gmail-style tests
- [ ] No new dependencies introduced
- [ ] Closes #7 via the commit message
