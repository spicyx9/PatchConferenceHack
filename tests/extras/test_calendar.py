from datetime import datetime, timezone

import pytest

from conferge.extras.calendar import _fold, export_plan_ics


def test_ics_filters_unselected_and_canceled_and_preserves_unknown_end():
    events = [
        {"id": "a", "title": "Meeting, R&D; Seed", "status": "scheduled",
         "start_at": "2026-10-28T10:00:00-07:00", "end_at": "2026-10-28T11:00:00-07:00",
         "venue": {"name": "Fort Mason", "city": "San Francisco"},
         "source_url": "https://example.org/event/a"},
        {"id": "b", "title": "Cancelled", "status": "cancelled", "start_at": "2026-10-29T10:00:00-07:00"},
        {"id": "c", "title": "Not chosen", "status": "scheduled", "start_at": "2026-10-29T11:00:00-07:00"},
        {"id": "d", "title": "No end", "status": "unknown", "start_at": "2026-10-29T09:00:00-07:00"},
    ]
    ics = export_plan_ics(events, {"a", "b", "d"}, generated_at=datetime(2026, 10, 24, tzinfo=timezone.utc))
    assert ics.count("BEGIN:VEVENT") == 2
    assert "DTSTART:20261028T170000Z" in ics
    assert "DTEND:20261028T180000Z" in ics
    assert "SUMMARY:Meeting\\, R&D\\; Seed" in ics
    assert "LOCATION:Fort Mason\\, San Francisco" in ics
    assert "https://example.org/event/a" in ics
    assert "Cancelled" not in ics and "Not chosen" not in ics
    assert ics.count("DTEND:") == 1
    assert ics.endswith("END:VCALENDAR\r\n")


def test_folding_uses_utf8_bytes():
    lines = _fold("SUMMARY:" + "Événement" * 20)
    assert len(lines) > 1
    assert all(len(line.encode("utf-8")) <= 75 for line in lines)
    assert lines[1].startswith(" ")


def test_naive_end_rejected():
    with pytest.raises(ValueError):
        export_plan_ics([{
            "id": "x", "start_at": "2026-10-28T10:00:00-07:00",
            "end_at": "2026-10-28T11:00:00", "title": "X",
        }], {"x"})


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        export_plan_ics([{"id": "x", "start_at": datetime(2026, 10, 28), "title": "X"}], {"x"})
