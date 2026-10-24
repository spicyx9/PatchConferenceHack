"""Query-bound comparisons from collected offers or an explicitly requested live search.

Search never changes a selected trip. Live collection requires mode=live; failures never
substitute cached offers. The flight cache has no occupancy/cabin query metadata, so its
known collection scope is explicit.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from conferge.api.provenance import source_of
from conferge.core.schemas import FlightOffer, Lodging
from conferge.core.settings import env_value
from conferge.flights.airports import airports_for
from conferge.flights.round_trip_total import display as flight_display
from conferge.integration import travel_cache
from conferge.integration.stays_flights import dedupe_flights, pick_stays

router = APIRouter(prefix="/api/v1/travel", tags=["travel"])


class TravelSearch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["flights", "stays"]
    trip_type: Literal["round_trip", "one_way"] = "round_trip"
    mode: Literal["cached", "live"] = "cached"
    origin: str = Field(default="", max_length=80)
    destination: str = Field(default="San Francisco", min_length=1, max_length=80)
    depart: date
    return_date: date
    adults: int = Field(default=1, ge=1, le=9)
    cabin: Literal["economy", "premium_economy", "business", "first"] = "economy"
    rooms: int = Field(default=1, ge=1, le=9)
    radius_km: float = Field(default=5, gt=0, le=50)
    budget: Decimal | None = Field(default=None, gt=0, le=100000)

    @model_validator(mode="after")
    def valid_trip(self) -> TravelSearch:
        if (self.kind == "stays" or self.trip_type == "round_trip") and self.return_date <= self.depart:
            raise ValueError("Return/check-out must be after departure/check-in.")
        if self.kind == "flights" and not self.origin:
            raise ValueError("Choose a departure city or airport.")
        return self


def fallback_url(query: TravelSearch) -> str:
    if query.kind == "flights":
        route = f"Flights from {query.origin} to {query.destination} on {query.depart}"
        dates = (f" returning {query.return_date}" if query.trip_type == "round_trip"
                 else " one way")
        text = f"{route}{dates}, {query.adults} adults, {query.cabin}"
        return "https://www.google.com/travel/flights?" + urlencode({"q": text})
    return "https://www.booking.com/searchresults.html?" + urlencode({
        "ss": query.destination, "checkin": query.depart, "checkout": query.return_date,
        "group_adults": query.adults, "no_rooms": query.rooms, "group_children": 0,
        "selected_currency": "USD",
    })


def _records(kind: str, directory: Path) -> list[FlightOffer | Lodging]:
    path = directory / travel_cache.FILES[kind]
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("kind") != "conferge.travel_cache" or document.get("domain") != kind:
        raise ValueError("Unrecognized travel cache")
    model = FlightOffer if kind == "flights" else Lodging
    records = [model.model_validate(row["record"]) for row in document["records"]]
    # A fixture cannot become a collected offer simply because it was put in this file.
    return [item.model_copy(update={"evidence": [ev.model_copy(update={"source_mode": "cached"})
            for ev in item.evidence]}) for item in records if item.evidence
            and all(ev.source_mode in {"live", "cached"} for ev in item.evidence)]


def _airports(value: str) -> set[str]:
    try:
        return set(airports_for(value))
    except KeyError:
        return set()


def search_cached(query: TravelSearch, directory: Path | None = None) -> dict:
    warnings = ["Previously collected offers; confirm current price and availability with the provider."]
    items: list[dict] = []
    supported = True
    try:
        records = _records(query.kind, directory if directory is not None else travel_cache.CACHE_DIR)
        if query.kind == "flights":
            origins, destinations = _airports(query.origin), _airports(query.destination)
            supported = (query.trip_type == "round_trip"
                         and query.depart == date(2026, 10, 27)
                         and query.return_date == date(2026, 10, 30)
                         and query.adults == 1 and query.cabin == "economy"
                         and bool(origins) and origins <= {"JFK", "LGA", "EWR"}
                         and bool(destinations) and destinations <= {"SFO", "OAK"})
            if supported:
                offers = []
                for offer in records:
                    first = offer.slices[0].segments[0]
                    last = offer.slices[0].segments[-1]
                    if (first.origin_iata not in origins or last.destination_iata not in destinations
                            or first.departure_at is None
                            or first.departure_at.date() != query.depart):
                        continue
                    if offer.trip_type == "round_trip":
                        back = offer.slices[1].segments[0]
                        if back.departure_at is None or back.departure_at.date() != query.return_date:
                            continue
                    offers.append(offer)
                items = [{**offer.model_dump(mode="json"), **flight_display(offer),
                          "source": source_of(offer.evidence), "source_mode": "cached"}
                         for offer in dedupe_flights(offers)]
        else:
            supported = query.destination.casefold() in {
                "san francisco", "san francisco, ca", "san francisco, usa", "sf", "sfo"}
            if supported:
                matched = [stay for stay in records
                           if stay.check_in == query.depart and stay.check_out == query.return_date
                           and stay.adults == query.adults and stay.rooms == query.rooms
                           and stay.distance_to_venue_m is not None
                           and stay.distance_to_venue_m <= query.radius_km * 1000
                           and stay.venue is not None and stay.venue.city is not None
                           and "san francisco" in stay.venue.city.casefold()]
                items = [{**stay.model_dump(mode="json"), "source": source_of(stay.evidence),
                          "source_mode": "cached"} for stay in pick_stays(matched, limit=200)]
        if query.budget is not None:
            items = [item for item in items if item.get("currency") == "USD"
                     and item.get("total_price") is not None
                     and Decimal(str(item["total_price"])) <= query.budget]
            warnings.append("Budget filters known USD totals only; offers with unknown totals are excluded.")
    except (OSError, ValueError, KeyError, TypeError):
        warnings.append("Collected travel offers could not be read. Search with the provider instead.")
    if not supported:
        warnings.append("No collected search covers these criteria. Continue with the provider for a new search.")
    elif not items:
        warnings.append("No collected offers match these dates, travelers and filters.")
    stamps = [ev.get("collected_at") for item in items for ev in item["evidence"]
              if ev.get("collected_at")]
    return {"query": query.model_dump(mode="json"), "items": items, "count": len(items),
            "data_source": "cached" if items else "unknown",
            "status": "ok" if items else "degraded", "supported": supported,
            "collected_at": max(stamps) if stamps else None, "warnings": warnings,
            "fallback_url": fallback_url(query)}


LIVE_TIMEOUT_SECONDS = 50


async def _run_live_flights(query: TravelSearch):
    from conferge.flights.fastflights_provider import FastFlightsProvider
    from conferge.flights.service import FlightService, run

    # Generic adapters construct the requested route. Unlocker is safe only within its
    # explicitly collected NYC–SFO query scope; historical snapshots are never live.
    providers = [("fastflights", FastFlightsProvider())]
    if env_value("SERPAPI_KEY"):
        from conferge.flights.serpapi_provider import SerpApiFlightsProvider
        providers.insert(0, ("serpapi", SerpApiFlightsProvider(api_key=env_value("SERPAPI_KEY"))))
    unlocker_client = None
    if (env_value("BRIGHTDATA_API_KEY") and env_value("BRIGHTDATA_UNLOCKER_ZONE")
            and query.trip_type == "round_trip" and query.adults == 1
            and query.cabin == "economy" and query.depart == date(2026, 10, 27)
            and query.return_date == date(2026, 10, 30)
            and bool(_airports(query.origin))
            and _airports(query.origin) <= {"JFK", "LGA", "EWR"}
            and "SFO" in _airports(query.destination)
            and _airports(query.destination) <= {"SFO", "OAK"}):
        from conferge.core.brightdata import BrightDataClient
        from conferge.flights.unlocker_provider import GoogleFlightsUnlockerProvider
        unlocker_client = BrightDataClient(
            env_value("BRIGHTDATA_API_KEY"),
            unlocker_zone=env_value("BRIGHTDATA_UNLOCKER_ZONE"))
        providers.insert(0, ("brightdata_unlocker", GoogleFlightsUnlockerProvider(
            client=unlocker_client, timeout=30)))
    try:
        return await run({"origin_city": query.origin, "destination_city": query.destination,
                          "departure_date": query.depart, "return_date": query.return_date,
                          "adults": query.adults, "cabin": query.cabin},
                         service=FlightService(providers=providers, provider_timeout=35),
                         allow_fixture=False)
    finally:
        if unlocker_client is not None:
            await unlocker_client.aclose()


async def _run_live_stays(query: TravelSearch):
    from conferge.lodging import run
    from conferge.lodging.models import LodgingQuery

    return await run(LodgingQuery(
        check_in=query.depart, check_out=query.return_date, adults=query.adults,
        rooms=query.rooms, radius_km=query.radius_km, location="San Francisco",
        search_term="hotels near Fort Mason Center San Francisco", currency="USD",
        limit=30, verify_top=0))


def _flight_matches(offer: FlightOffer, query: TravelSearch) -> bool:
    origins, destinations = _airports(query.origin), _airports(query.destination)
    first = offer.slices[0].segments[0]
    last = offer.slices[0].segments[-1]
    if first.departure_at is None:
        return False
    if offer.trip_type == "round_trip":
        back_first = offer.slices[1].segments[0]
        back_last = offer.slices[1].segments[-1]
        return (first.origin_iata in origins and last.destination_iata in destinations
                and first.departure_at.date() == query.depart
                and back_first.origin_iata in destinations and back_last.destination_iata in origins
                and back_first.departure_at is not None
                and back_first.departure_at.date() == query.return_date)
    return ((first.origin_iata in origins and last.destination_iata in destinations
             and first.departure_at.date() == query.depart)
            or (first.origin_iata in destinations and last.destination_iata in origins
                and first.departure_at.date() == query.return_date))


async def search_live(query: TravelSearch) -> dict:
    result = {"query": query.model_dump(mode="json"), "items": [], "count": 0,
              "data_source": "unknown", "status": "failed", "supported": True,
              "collected_at": None, "warnings": [], "fallback_url": fallback_url(query)}
    warnings = result["warnings"]
    if query.kind == "flights" and query.trip_type == "one_way":
        result["supported"] = False
        warnings.append("This collector currently supports round-trip research only. Search the provider for a one-way flight.")
        return result
    if query.kind == "stays":
        if query.destination.casefold() not in {
                "san francisco", "san francisco, ca", "san francisco, usa", "sf", "sfo"}:
            result["supported"] = False
            warnings.append("Hotel search currently covers San Francisco near Fort Mason. Search the provider for another destination.")
            return result
        if not env_value("BRIGHTDATA_API_KEY"):
            warnings.append("Bright Data is not configured; direct and fallback hotel sources will be attempted.")
    elif not (_airports(query.origin) and _airports(query.destination)):
        result["supported"] = False
        warnings.append("Choose a supported departure and destination airport or search with the provider.")
        return result
    try:
        envelope = await asyncio.wait_for(
            _run_live_flights(query) if query.kind == "flights" else _run_live_stays(query),
            timeout=LIVE_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, TimeoutError):
        warnings.append("The provider did not finish within 50 seconds. No cached offers were substituted.")
        return result
    except Exception:  # Provider messages can contain credentials: expose only the outcome.
        warnings.append("The live provider could not complete this search. No cached offers were substituted.")
        return result
    items = []
    for record in envelope.items:
        if not record.evidence or any(e.source_mode not in {"live", "cached"}
                                      for e in record.evidence):
            continue
        if query.kind == "flights":
            if not _flight_matches(record, query):
                continue
            item = {**record.model_dump(mode="json"), **flight_display(record)}
        else:
            if (record.check_in != query.depart or record.check_out != query.return_date
                    or record.adults != query.adults or record.rooms != query.rooms
                    or record.distance_to_venue_m is None
                    or record.distance_to_venue_m > query.radius_km * 1000):
                continue
            item = record.model_dump(mode="json")
        modes = {e.source_mode for e in record.evidence}
        item.update(source=source_of(record.evidence),
                    source_mode=next(iter(modes)) if len(modes) == 1 else "mixed")
        if query.budget is not None and (item.get("currency") != "USD"
                or item.get("total_price") is None
                or Decimal(str(item["total_price"])) > query.budget):
            continue
        items.append(item)
    if envelope.errors:
        warnings.append("Some provider requests failed; only matching observed results are shown.")
    if query.kind == "flights" and any(i["trip_type"] == "one_way" for i in items):
        warnings.append("One-way fares are shown separately for each direction, not as a quoted round-trip total.")
    if query.budget is not None:
        warnings.append("Budget filters known USD totals only; unknown totals are excluded.")
    if not items:
        warnings.append("No matching live offers were collected. No cached offers were substituted.")
    else:
        warnings.append("Prices were collected for this search; confirm availability and final fees with the provider.")
    modes = {item["source_mode"] for item in items}
    result.update(items=items, count=len(items),
                  data_source=next(iter(modes)) if len(modes) == 1 else "mixed" if modes else "unknown",
                  status=envelope.status if items else "failed",
                  collected_at=envelope.collected_at.isoformat() if envelope.collected_at else None,
                  providers=[{"provider": r.provider, "status": r.status,
                              "source_mode": r.source_mode, "count": r.unique_count}
                             for r in envelope.reports])
    return result


@router.post("/search")
async def search(query: TravelSearch) -> dict:
    return await search_live(query) if query.mode == "live" else search_cached(query)
