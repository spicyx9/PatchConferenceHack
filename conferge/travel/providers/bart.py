"""BART schedule provider (api.bart.gov `sched.aspx?cmd=depart`).

Returns one RouteLeg per scheduled trip, with times and the adult Clipper fare exactly
as published by BART. Nothing is estimated: a trip without a parsable time is skipped
with a warning, and a missing adult Clipper fare leaves the price unknown.

The API key is never written into URLs, warnings, errors or logs. When no key is given
and `BART_API_KEY` is unset, BART's officially published public key is used.
Public key source: https://api.bart.gov/api/register.aspx
"""

from __future__ import annotations

import os
from datetime import datetime
from types import TracebackType
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from conferge.core.schemas import SourceEvidence
from conferge.travel.models import Mode, Place, Price, ProviderOutcome, RouteLeg, utcnow
from conferge.travel.providers.base import failed, report

# Officially published BART public API key, see https://api.bart.gov/api/register.aspx
BART_PUBLIC_KEY = "MW9S-E7SL-26DU-VV8V"
BART_SCHED_URL = "https://api.bart.gov/api/sched.aspx"
BART_TZ = ZoneInfo("America/Los_Angeles")
TIMEOUT_S = 20.0
PROVIDER = "bart"


def _as_list(value: Any) -> list[Any]:
    """BART returns a dict instead of a list when there is a single element."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _bart_time(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    suffix = "am" if dt.hour < 12 else "pm"
    return f"{hour}:{dt.minute:02d}{suffix}"


def _parse_local(date_str: Any, time_str: Any) -> datetime:
    if not isinstance(date_str, str) or not isinstance(time_str, str):
        raise ValueError("missing trip date or time")
    naive = datetime.strptime(f"{date_str.strip()} {time_str.strip()}", "%m/%d/%Y %I:%M %p")
    return naive.replace(tzinfo=BART_TZ)


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        parts = [str(v) for v in message.values() if v]
        return "; ".join(parts)
    return str(message or "").strip()


class BartProvider:
    name = PROVIDER
    modes: frozenset[Mode] = frozenset({"bart"})

    def __init__(
        self, api_key: str | None = None, *, client: httpx.AsyncClient | None = None,
        max_trips: int = 3,
    ) -> None:
        self._key = api_key or os.environ.get("BART_API_KEY") or BART_PUBLIC_KEY
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT_S)
        self.max_trips = max_trips

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    async def __aenter__(self) -> BartProvider:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _scrub(self, text: str) -> str:
        return text.replace(self._key, "***") if self._key else text

    async def route(
        self, origin: Place, destination: Place, *, mode: Mode,
        depart_at: datetime | None = None,
    ) -> ProviderOutcome:
        started = utcnow()
        if mode != "bart":
            return failed(PROVIDER, started, f"mode {mode!r} not supported by BART provider")
        for place in (origin, destination):
            if not place.bart_station:
                return failed(PROVIDER, started, f"no BART station for {place.id}")

        warnings: list[str] = []
        if depart_at is None:
            date_param, time_param = "now", "now"
            warnings.append("departure time not given, used BART 'now'")
        else:
            if depart_at.tzinfo is None or depart_at.utcoffset() is None:
                return failed(PROVIDER, started, "depart_at must be timezone aware")
            local = depart_at.astimezone(BART_TZ)
            date_param, time_param = local.strftime("%m/%d/%Y"), _bart_time(local)

        public_params = {
            "cmd": "depart", "orig": origin.bart_station, "dest": destination.bart_station,
            "date": date_param, "time": time_param, "b": "0", "a": str(self.max_trips),
            "json": "y",
        }
        source_url = str(httpx.URL(BART_SCHED_URL, params=public_params))

        try:
            resp = await self._client.get(
                BART_SCHED_URL, params={**public_params, "key": self._key}, timeout=TIMEOUT_S,
            )
        except httpx.TimeoutException:
            return failed(PROVIDER, started, "BART request timed out")
        except httpx.HTTPError as exc:
            return failed(PROVIDER, started, f"BART network error: {type(exc).__name__}")

        if resp.status_code >= 400:
            termination = "rate_limited" if resp.status_code == 429 else "error"
            return failed(
                PROVIDER, started, f"BART HTTP {resp.status_code}", termination=termination,
            )

        try:
            payload = resp.json()
        except ValueError:
            return failed(
                PROVIDER, started, "BART response is not JSON", termination="schema_changed",
            )

        root = payload.get("root") if isinstance(payload, dict) else None
        schedule = root.get("schedule") if isinstance(root, dict) else None
        if not isinstance(schedule, dict):
            detail = _message_text(root.get("message")) if isinstance(root, dict) else ""
            msg = "BART response has no schedule"
            if detail:
                msg += f": {self._scrub(detail)}"
            return failed(PROVIDER, started, msg, termination="schema_changed")
        request = schedule.get("request")
        if not isinstance(request, dict):
            return failed(
                PROVIDER, started, "BART schedule has no request block",
                termination="schema_changed",
            )

        trips = _as_list(request.get("trip"))
        if not trips:
            return failed(PROVIDER, started, "zero trips")

        collected = utcnow()
        evidence = SourceEvidence(
            provider=PROVIDER, source_mode="live", source_url=source_url,
            collected_at=collected, raw_ref=None,
        )
        legs: list[RouteLeg] = []
        for idx, trip in enumerate(trips[: self.max_trips]):
            try:
                legs.append(
                    self._trip_leg(trip, origin, destination, source_url, collected, evidence)
                )
            except (ValueError, TypeError, AttributeError) as exc:
                warnings.append(f"trip {idx} skipped: {self._scrub(str(exc))}")

        if not legs:
            return failed(PROVIDER, started, "zero trips parsed", termination="schema_changed")
        return ProviderOutcome(
            legs=legs,
            run_report=report(
                PROVIDER, started, status="ok", termination="exhausted", fetched=len(trips),
                unique=len(legs), pages=1, warnings=warnings,
            ),
        )

    def _trip_leg(
        self, trip: dict[str, Any], origin: Place, destination: Place, source_url: str,
        collected: datetime, evidence: SourceEvidence,
    ) -> RouteLeg:
        departure = _parse_local(trip.get("@origTimeDate"), trip.get("@origTimeMin"))
        arrival = _parse_local(trip.get("@destTimeDate"), trip.get("@destTimeMin"))
        trip_time = trip.get("@tripTime")
        duration = int(trip_time) if trip_time not in (None, "") else None

        price = Price()
        fares = trip.get("fares")
        fare_list = _as_list(fares.get("fare")) if isinstance(fares, dict) else []
        for fare in fare_list:
            if isinstance(fare, dict) and fare.get("@class") == "clipper" and fare.get("@amount"):
                price = Price(
                    amount=str(fare["@amount"]).strip(), currency="USD", status="exact",
                    fare_class="adult_clipper", note="BART published fare for adult Clipper",
                )
                break

        sub_legs = [leg for leg in _as_list(trip.get("leg")) if isinstance(leg, dict)]
        lines = [str(leg["@line"]) for leg in sub_legs if leg.get("@line")]
        # The transfer station is the next leg's @origin. Live data for the OAK airport
        # connector reports @destination "OAKL" on leg 1 while leg 2 starts at COLS.
        leg_warnings = [
            f"transfer at {nxt.get('@origin') or cur.get('@destination')}"
            for cur, nxt in zip(sub_legs, sub_legs[1:], strict=False)
        ]
        return RouteLeg(
            from_place=origin, to_place=destination, mode="bart",
            departure_local=departure, arrival_local=arrival,
            duration_minutes=duration,
            duration_status="scheduled" if duration is not None else "unknown",
            price=price, provider=PROVIDER, source_mode="live", collected_at=collected,
            source_url=source_url, line=" + ".join(lines) or None, warnings=leg_warnings,
            evidence=[evidence],
        )
