"""Tests for the entries repository."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.entries import (
    EntryRecord,
    count_entries_in_range,
    delete_entry,
    get_entry,
    list_entries_by_month,
    list_entries_by_tag,
    list_entries_in_range,
    list_tags_for_date,
    replace_tags,
    search_fts,
    tag_frequencies_in_range,
    tags_by_date_in_range,
    tags_for_dates,
    upsert_entry,
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def _record(date: str = "2026-05-06", **overrides: object) -> EntryRecord:
    base = EntryRecord(
        date=date,
        mood="💪",
        body_text="cracked the migration bug today",
        body_md="cracked the migration bug today #work",
        created_at="2026-05-06T21:30:15Z",
        updated_at="2026-05-06T21:30:15Z",
    )
    return base.model_copy(update=overrides)


def test_upsert_inserts_new_entry(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record())
    with session_scope(engine) as session:
        got = get_entry(session, "2026-05-06")
    assert got is not None
    assert got.mood == "💪"
    assert got.body_text == "cracked the migration bug today"


def test_upsert_updates_existing_entry(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(mood="💪", body_text="v1", body_md="v1"))
        upsert_entry(session, _record(mood="🎉", body_text="v2", body_md="v2 #celebrate"))
    with session_scope(engine) as session:
        got = get_entry(session, "2026-05-06")
    assert got is not None
    assert got.mood == "🎉"
    assert got.body_text == "v2"


def test_replace_tags_overwrites_previous(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record())
        replace_tags(session, "2026-05-06", ["work", "cooking"])
        replace_tags(session, "2026-05-06", ["work", "rest"])
    with session_scope(engine) as session:
        entries = list_entries_by_tag(session, "rest")
        cooking = list_entries_by_tag(session, "cooking")
    assert [e.date for e in entries] == ["2026-05-06"]
    assert cooking == []


def test_replace_tags_lowercases(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record())
        replace_tags(session, "2026-05-06", ["Work", "COOKING"])
    with session_scope(engine) as session:
        ents_work = list_entries_by_tag(session, "work")
        ents_cooking = list_entries_by_tag(session, "cooking")
    assert ents_work and ents_cooking


def test_list_entries_by_month_orders_by_date(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-06"))
        upsert_entry(session, _record(date="2026-05-01"))
        upsert_entry(session, _record(date="2026-04-30"))
    with session_scope(engine) as session:
        may = list_entries_by_month(session, 2026, 5)
    assert [e.date for e in may] == ["2026-05-01", "2026-05-06"]


def test_count_and_tag_frequencies_in_range(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-01"))
        replace_tags(session, "2026-05-01", ["work", "cooking"])
        upsert_entry(session, _record(date="2026-05-02"))
        replace_tags(session, "2026-05-02", ["work"])
        upsert_entry(session, _record(date="2026-04-30"))
        replace_tags(session, "2026-04-30", ["cooking"])
    with session_scope(engine) as session:
        n = count_entries_in_range(session, "2026-05-01", "2026-05-31")
        freq = tag_frequencies_in_range(session, "2026-05-01", "2026-05-31")
    assert n == 2
    assert freq == {"work": 2, "cooking": 1}


def test_search_fts_matches_body(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-01", body_text="risotto night was great"))
        upsert_entry(session, _record(date="2026-05-02", body_text="rainy walk in the park"))
    with session_scope(engine) as session:
        hits = search_fts(session, "risotto")
    assert [e.date for e in hits] == ["2026-05-01"]


def test_delete_entry_cascades_tags(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record())
        replace_tags(session, "2026-05-06", ["work"])
        delete_entry(session, "2026-05-06")
    with session_scope(engine) as session:
        assert get_entry(session, "2026-05-06") is None
        assert list_entries_by_tag(session, "work") == []


def test_list_entries_in_range_inclusive(engine: Engine) -> None:
    with session_scope(engine) as session:
        for d in ("2026-05-01", "2026-05-02", "2026-05-03"):
            upsert_entry(session, _record(date=d))
    with session_scope(engine) as session:
        rs = list_entries_in_range(session, "2026-05-02", "2026-05-03")
    assert [e.date for e in rs] == ["2026-05-02", "2026-05-03"]


def test_list_tags_for_date_returns_sorted(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record())
        replace_tags(session, "2026-05-06", ["work", "cooking", "art"])
    with session_scope(engine) as session:
        tags = list_tags_for_date(session, "2026-05-06")
    assert tags == ["art", "cooking", "work"]


def test_list_tags_for_date_empty_for_unknown_date(engine: Engine) -> None:
    with session_scope(engine) as session:
        tags = list_tags_for_date(session, "1900-01-01")
    assert tags == []


def test_tags_by_date_in_range_groups_correctly(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-01"))
        replace_tags(session, "2026-05-01", ["work", "cooking"])
        upsert_entry(session, _record(date="2026-05-03"))
        replace_tags(session, "2026-05-03", ["rest"])
        upsert_entry(session, _record(date="2026-04-30"))
        replace_tags(session, "2026-04-30", ["outside_range"])
    with session_scope(engine) as session:
        result = tags_by_date_in_range(session, "2026-05-01", "2026-05-03")
    assert result == {"2026-05-01": ["cooking", "work"], "2026-05-03": ["rest"]}


def test_tags_by_date_in_range_excludes_out_of_range(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-04-30"))
        replace_tags(session, "2026-04-30", ["old"])
    with session_scope(engine) as session:
        result = tags_by_date_in_range(session, "2026-05-01", "2026-05-31")
    assert result == {}


def test_tags_for_dates_empty_input_returns_empty_dict(engine: Engine) -> None:
    """An empty list short-circuits to {} without hitting the DB."""
    with session_scope(engine) as session:
        result = tags_for_dates(session, [])
    assert result == {}


def test_tags_for_dates_returns_one_entry_per_listed_date(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-06"))
        upsert_entry(session, _record(date="2026-05-08"))
        upsert_entry(session, _record(date="2026-05-10"))
        replace_tags(session, "2026-05-06", ["work", "cooking"])
        replace_tags(session, "2026-05-08", ["holiday"])
        replace_tags(session, "2026-05-10", ["work", "rest"])
    with session_scope(engine) as session:
        result = tags_for_dates(session, ["2026-05-06", "2026-05-10"])
    # Only the listed dates appear; tags are sorted within each date.
    assert result == {
        "2026-05-06": ["cooking", "work"],
        "2026-05-10": ["rest", "work"],
    }


def test_tags_for_dates_omits_dates_with_no_tags(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-06"))
        upsert_entry(session, _record(date="2026-05-08"))
        replace_tags(session, "2026-05-06", ["work"])
    with session_scope(engine) as session:
        result = tags_for_dates(session, ["2026-05-06", "2026-05-08", "2026-05-09"])
    # 2026-05-08 has no tags; 2026-05-09 has no entry. Both absent.
    assert result == {"2026-05-06": ["work"]}
