"""SLOW-MOVING-BACKFILL S0.1 - the earliest-DocDate probe (pure, no vendor)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from modules.autocount.doc_feed.probe import earliest_doc_day, floor_for


def _reader(doc_days):
    seen = []

    def read_day(day):
        seen.append(day)
        return [{"DocKey": 1}] if day in doc_days else []

    return read_day, seen


def _business_days(start: date, end: date):
    day, out = start, set()
    while day <= end:
        if day.weekday() < 5:
            out.add(day)
        day += timedelta(days=1)
    return out


def test_finds_the_exact_first_day_inside_a_stride_window():
    first = date(2016, 3, 9)  # a Wednesday
    read_day, seen = _reader(_business_days(first, date(2019, 1, 31)))

    found = earliest_doc_day(read_day, from_day=date(2010, 1, 1), to_day=date(2019, 1, 7))

    assert found == first
    assert len(seen) < 400  # coarse weekly pass, not every day since 2010


def test_a_book_with_nothing_before_the_range_end_returns_none():
    read_day, _ = _reader(_business_days(date(2020, 1, 1), date(2020, 12, 31)))

    assert earliest_doc_day(read_day, from_day=date(2015, 1, 1), to_day=date(2019, 1, 7)) is None


def test_a_document_only_in_the_tail_after_the_last_coarse_day_is_found():
    read_day, _ = _reader({date(2019, 1, 7)})

    found = earliest_doc_day(read_day, from_day=date(2019, 1, 1), to_day=date(2019, 1, 7), stride=5)

    assert found == date(2019, 1, 7)


def test_the_first_day_itself():
    read_day, _ = _reader({date(2012, 1, 1)})

    assert earliest_doc_day(read_day, from_day=date(2012, 1, 1), to_day=date(2012, 2, 1)) == date(2012, 1, 1)


def test_stride_must_be_positive():
    with pytest.raises(ValueError):
        earliest_doc_day(lambda d: [], from_day=date(2019, 1, 1), to_day=date(2019, 1, 2), stride=0)


@pytest.mark.parametrize(
    "earliest, floor",
    [
        (None, date(2019, 1, 1)),
        (date(2020, 5, 4), date(2019, 1, 1)),
        (date(2019, 1, 1), date(2019, 1, 1)),
        (date(2016, 3, 9), date(2016, 1, 1)),
    ],
)
def test_floor_is_the_earliest_year_start_or_the_default(earliest, floor):
    assert floor_for(earliest, default_floor=date(2019, 1, 1)) == floor
