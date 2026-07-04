"""Deadline parsing and the reminder engine."""

import datetime as dt

from deadlines import collect_reminders, mark_sent, parse_deadline

TODAY = dt.date(2026, 7, 4)


def test_parse_requires_trigger():
    assert parse_deadline("The event happened on 3 March 2020", TODAY) is None
    assert parse_deadline("", TODAY) is None


def test_parse_formats():
    assert parse_deadline("Submissions close on 15 August 2026", TODAY) == dt.date(2026, 8, 15)
    assert parse_deadline("Deadline: Aug 15, 2026", TODAY) == dt.date(2026, 8, 15)
    assert parse_deadline("apply by 2026-09-01", TODAY) == dt.date(2026, 9, 1)
    assert parse_deadline("registration closes 1st Sep", TODAY) == dt.date(2026, 9, 1)


def test_parse_rolls_year_forward_never_back():
    assert parse_deadline("Registration closes 5 Jan", TODAY) == dt.date(2027, 1, 5)
    assert parse_deadline("closes 5 Dec", TODAY) == dt.date(2026, 12, 5)


def test_reminder_windows_and_no_double_nag(store):
    cfg = {"deadline_reminder_days": [14, 7, 3, 1]}
    store.upsert_deadline("d7", "Seven out", "https://7", TODAY + dt.timedelta(days=7))
    store.upsert_deadline("d5", "Five out", "https://5", TODAY + dt.timedelta(days=5))
    store.upsert_deadline("d0", "Today", "https://0", TODAY)
    store.upsert_deadline("gone", "Expired", "https://g", TODAY - dt.timedelta(days=1))

    reminders = collect_reminders(store, cfg, TODAY)
    titles = [r["title"] for r in reminders]
    assert titles == ["Today", "Seven out"]  # 5-days-out not a window; expired dropped
    assert reminders[0]["line"] == "closes TODAY"
    assert "7 days left" in reminders[1]["line"]

    # not marked yet — collecting again still returns them (send could have failed)
    assert len(collect_reminders(store, cfg, TODAY)) == 2
    mark_sent(store, reminders, TODAY)
    assert collect_reminders(store, cfg, TODAY) == []  # no double nag same day
