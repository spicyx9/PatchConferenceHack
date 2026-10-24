"""Calendar export route: the plan the user sees, as an iCalendar file.

Ported from HTest PR #43 (calendar only; the coworking and activities routes are not ported).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from conferge.extras.calendar import export_plan_ics

router = APIRouter(prefix="/api/v1", tags=["trip-extras"])


@router.get("/calendar.ics", response_class=Response)
def calendar(request: Request) -> Response:
    """Export the optimized plan only (My agenda), not every discovered event.

    ``state.plan()`` is the agenda after Anti-FOMO choices (conflicts resolved, events the
    user skipped left out) and after any replanning (a simulated sold-out event is dropped
    and its replacement added), so the file always matches what the agenda shows.
    """
    state = request.app.state.demo
    selected = {item["event_id"] for day in state.plan()["days"] for item in day["items"]}
    content = export_plan_ics(state.data.events, selected)
    return Response(
        content, media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="conferge-plan.ics"'},
    )
