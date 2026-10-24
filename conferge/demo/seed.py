"""Synthetic demo world, validated against ``conferge.core.schemas``.

Rules applied here:
- every record and every evidence entry is ``source_mode="fixture"``;
- people and companies are fictional personas (bio / categories say so), no
  LinkedIn URL is attached, URLs use the reserved ``.invalid`` TLD;
- side events are ``candidate`` (no evidence of conference affiliation);
- prices are simulated: lodging is never ``verified_bookable``, flights use
  ``price_status="sandbox"``; unknown values stay ``None``.

The builder uses no randomness and no clock: two calls return equal objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from conferge.core.schemas import (
    Company,
    Conference,
    Event,
    FlightOffer,
    FlightSegment,
    FlightSlice,
    Goal,
    Lodging,
    Person,
    SourceEvidence,
    Venue,
)

PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")
TZ_NAME = "America/Los_Angeles"
FIXED_COLLECTED_AT = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
PROVIDER = "conferge-demo-seed"
BASE_URL = "https://demo.conferge.invalid"
SEED = 42  # recorded for traceability; the builder itself is randomness-free
FIXTURE_NOTE = "fixture-demo: synthetic record, not collected from any provider"
CONFERENCE_ID = "conf-github-universe-2026"


def _evidence(kind: str, record_id: str, confidence: float = 1.0) -> list[SourceEvidence]:
    return [
        SourceEvidence(
            provider=PROVIDER,
            source_mode="fixture",
            source_url=f"{BASE_URL}/{kind}/{record_id}",
            collected_at=FIXED_COLLECTED_AT,
            raw_ref=f"fixtures/demo.json#{kind}/{record_id}",
            source_record_id=record_id,
            confidence=confidence,
        )
    ]


def _pt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PT)


@dataclass(frozen=True)
class DemoUser:
    id: str = "demo-user"
    label: str = "Fictional founder of an AI developer tool"
    home_city: str = "New York"
    origin_airports: tuple[str, ...] = ("JFK", "LGA", "EWR")
    destination_airports: tuple[str, ...] = ("SFO", "OAK", "SJC")
    depart_on: date = date(2026, 10, 27)
    return_on: date = date(2026, 10, 30)
    adults: int = 1
    cabin: str = "economy"
    budget_usd: Decimal = Decimal("2500")
    goal_text: str = (
        "Founder of an AI dev tool going to GitHub Universe to meet seed investors, "
        "AI agent founders and Copilot PMs."
    )


@dataclass(frozen=True)
class DemoWorld:
    user: DemoUser
    conference: Conference
    goals: list[Goal]
    companies: list[Company]
    people: list[Person]
    events: list[Event]
    lodging: list[Lodging]
    flights: list[FlightOffer]


def build_conference() -> Conference:
    # Anchor facts from docs/knowledge/03-demo-scenario.md; not live-verified here.
    return Conference(
        id=CONFERENCE_ID,
        name="GitHub Universe 2026",
        start_date=date(2026, 10, 28),
        end_date=date(2026, 10, 29),
        city="San Francisco",
        venue_name="Fort Mason Center",
        timezone=TZ_NAME,
        official_url="https://githubuniverse.com/",
        latitude=37.8060,
        longitude=-122.4320,
        topics=["ai agents", "developer tools", "copilot", "mcp"],
        evidence=[
            SourceEvidence(
                provider=PROVIDER,
                source_mode="fixture",
                source_url=None,
                collected_at=FIXED_COLLECTED_AT,
                raw_ref="docs/knowledge/03-demo-scenario.md",
                source_record_id=CONFERENCE_ID,
                confidence=None,
            )
        ],
    )


def build_goals() -> list[Goal]:
    return [
        Goal(
            id="goal-seed-investors",
            description="Meet seed investors active in developer tools",
            priority=0.45,
            tags=["fundraising"],
            topics=["developer tools", "ai agents"],
            target_roles=["investor"],
            target_count=5,
        ),
        Goal(
            id="goal-agent-founders",
            description="Meet founders building AI agents",
            priority=0.35,
            tags=["peers"],
            topics=["ai agents", "mcp"],
            target_roles=["founder"],
            target_count=4,
        ),
        Goal(
            id="goal-copilot-pms",
            description="Meet Copilot product managers",
            priority=0.20,
            tags=["distribution"],
            topics=["copilot", "mcp"],
            target_roles=["pm"],
            target_count=2,
        ),
    ]


_COMPANIES: list[tuple[str, str, str, bool, list[str]]] = [
    ("co-lanternseed", "Lanternseed Ventures", "venture capital", True, ["seed"]),
    ("co-quarry-capital", "Quarry Lane Capital", "venture capital", True, ["seed"]),
    ("co-tidepool", "Tidepool Partners", "venture capital", True, ["pre-seed"]),
    ("co-orbitloop", "Orbitloop Agents", "software", False, ["ai agents"]),
    ("co-patchwork", "Patchwork Labs", "software", False, ["developer tools"]),
    ("co-kiteframe", "Kiteframe", "software", False, ["mcp"]),
    ("co-wingmate", "Wingmate Labs", "software", False,
     ["copilot"]),
    ("co-hollowbyte", "Hollowbyte", "software", False, ["infrastructure"]),
]


def build_companies() -> list[Company]:
    return [
        Company(
            id=cid,
            name=name,
            domain=None,
            linkedin_url=None,
            industry=industry,
            is_investor=investor,
            categories=["fictional-demo", *cats],
            evidence=_evidence("companies", cid),
        )
        for cid, name, industry, investor, cats in _COMPANIES
    ]


# id, name, company, title, roles, topics, participation, event_ids
_PEOPLE: list[tuple[str, str, str, str, list[str], list[str], str, list[str]]] = [
    ("p-inv-ada", "Ada Lanternwood", "co-lanternseed", "Partner", ["investor"],
     ["developer tools", "ai agents"], "confirmed_speaker", ["evt-s-funding-devtools"]),
    ("p-inv-bram", "Bram Quillfeather", "co-quarry-capital", "General Partner", ["investor"],
     ["ai agents", "mcp"], "confirmed_organizer", ["evt-side-agents-after-hours"]),
    ("p-inv-cleo", "Cleo Marrowind", "co-tidepool", "Principal", ["investor"],
     ["developer tools"], "confirmed_organizer", ["evt-side-devtools-dinner"]),
    ("p-inv-dov", "Dov Embersley", "co-lanternseed", "Associate", ["investor"],
     ["developer tools", "copilot"], "confirmed_organizer", ["evt-side-seed-office-hours"]),
    ("p-fnd-elin", "Elin Orbitson", "co-orbitloop", "Founder and CEO", ["founder"],
     ["ai agents", "mcp"], "confirmed_speaker", ["evt-s-agents-production"]),
    ("p-fnd-faro", "Faro Patchley", "co-patchwork", "Co-founder", ["founder", "engineer"],
     ["developer tools", "ai agents"], "confirmed_organizer", ["evt-side-builders-meetup"]),
    ("p-fnd-gwen", "Gwen Kitesong", "co-kiteframe", "Founder", ["founder"],
     ["mcp", "ai agents"], "confirmed_speaker", ["evt-s-mcp-tooling"]),
    ("p-fnd-hale", "Hale Driftmoor", "co-orbitloop", "Co-founder and CTO", ["founder"],
     ["ai agents"], "confirmed_organizer", ["evt-side-agents-after-hours"]),
    ("p-pm-ines", "Ines Copperfield", "co-wingmate", "Product Manager, Copilot integrations", ["pm"],
     ["copilot", "mcp"], "confirmed_speaker", ["evt-s-copilot-extensions"]),
    ("p-pm-jory", "Jory Lumenhall", "co-wingmate", "Senior PM, Copilot integrations", ["pm"],
     ["copilot"], "confirmed_organizer", ["evt-side-copilot-breakfast"]),
    ("p-pm-kael", "Kael Windmere", "co-wingmate", "Product Manager, Copilot integrations", ["pm"],
     ["copilot", "developer tools"], "confirmed_organizer", ["evt-side-devtools-dinner"]),
    ("p-eng-lio", "Lio Hollowell", "co-hollowbyte", "Staff Engineer", ["engineer"],
     ["infrastructure"], "confirmed_speaker", ["evt-s-agents-production"]),
    ("p-dr-mara", "Mara Fenwick", "co-patchwork", "Developer Advocate", ["devrel"],
     ["developer tools"], "relevant_candidate", []),
    ("p-exe-nils", "Nils Ashgrove", "co-hollowbyte", "VP Engineering", ["executive"],
     ["infrastructure"], "unknown", []),
]


def build_people() -> list[Person]:
    people = []
    for pid, name, company, title, roles, topics, participation, event_ids in _PEOPLE:
        people.append(
            Person(
                id=pid,
                name=name,
                company_id=company,
                role=roles[0],
                title=title,
                public_profile_url=f"{BASE_URL}/people/{pid}",
                linkedin_url=None,
                github_url=None,
                x_handle=None,
                bio="Fictional demo persona. Not a real person; attendance is simulated.",
                topics=topics,
                roles=roles,
                participation=participation,
                event_ids=event_ids,
                match_confidence=None,
                evidence=_evidence("people", pid),
            )
        )
    return people


_FORT_MASON = Venue(
    name="Fort Mason Center",
    address=None,
    city="San Francisco",
    latitude=37.8060,
    longitude=-122.4320,
    coordinate_precision="approximate",
)


def _side_venue(name: str, lat: float, lng: float) -> Venue:
    return Venue(
        name=name,
        address=None,
        city="San Francisco",
        latitude=lat,
        longitude=lng,
        coordinate_precision="approximate",
    )


def _session(
    eid: str, title: str, start: datetime, end: datetime, room: str,
    speakers: list[str], topics: list[str],
) -> Event:
    return Event(
        id=eid,
        conference_id=CONFERENCE_ID,
        title=title,
        description="Synthetic session for the offline demo; not from the official program.",
        event_type="session",
        start_at=start,
        end_at=end,
        timezone=TZ_NAME,
        venue=_FORT_MASON,
        speaker_ids=speakers,
        topics=topics,
        room=room,
        status="scheduled",
        conference_relation="official",
        relation_score=1.0,
        relation_evidence=[f"{FIXTURE_NOTE}; official within the demo world only"],
        source_url=f"{BASE_URL}/events/{eid}",
        evidence=_evidence("events", eid),
    )


def _side_event(
    eid: str, title: str, event_type: str, start: datetime, end: datetime, venue: Venue,
    organizers: list[str], organizer_names: list[str], topics: list[str],
    relation_score: float,
) -> Event:
    return Event(
        id=eid,
        conference_id=CONFERENCE_ID,
        title=title,
        description="Synthetic side event for the offline demo.",
        event_type=event_type,
        start_at=start,
        end_at=end,
        timezone=TZ_NAME,
        venue=venue,
        organizer_ids=organizers,
        organizer_names=organizer_names,
        topics=topics,
        status="scheduled",
        conference_relation="candidate",
        relation_score=relation_score,
        relation_evidence=["fixture-demo: same city and dates as the anchor conference"],
        registration_url=f"{BASE_URL}/register/{eid}",
        source_url=f"{BASE_URL}/events/{eid}",
        is_free=None,
        capacity=None,
        registered_count=None,
        evidence=_evidence("events", eid, confidence=relation_score),
    )


def build_events() -> list[Event]:
    return [
        _side_event(
            "evt-side-builders-meetup", "Pre-Universe Builders Meetup", "meetup",
            _pt(27, 18, 30), _pt(27, 21, 0),
            _side_venue("Builders Loft (synthetic venue)", 37.7609, -122.4194),
            ["p-fnd-faro"], ["Patchwork Labs"], ["developer tools", "ai agents"], 0.6,
        ),
        _session(
            "evt-s-agents-production", "Agents in Production", _pt(28, 10), _pt(28, 10, 45),
            "Pavilion A (synthetic room)", ["p-fnd-elin", "p-eng-lio"], ["ai agents"],
        ),
        _session(
            "evt-s-copilot-extensions", "Building Copilot Extensions with MCP",
            _pt(28, 14), _pt(28, 14, 45), "Pavilion B (synthetic room)", ["p-pm-ines"],
            ["copilot", "mcp"],
        ),
        _side_event(
            "evt-side-agents-after-hours", "Agents After Hours", "party",
            _pt(28, 18, 30), _pt(28, 21, 30),
            _side_venue("Harbor Hall (synthetic venue)", 37.7989, -122.4006),
            ["p-inv-bram", "p-fnd-hale"], ["Quarry Lane Capital", "Orbitloop Agents"],
            ["ai agents"], 0.6,
        ),
        _side_event(
            "evt-side-devtools-dinner", "Devtools Founders Dinner", "side_event",
            _pt(28, 19), _pt(28, 21, 30),
            _side_venue("Union Table (synthetic venue)", 37.7880, -122.4075),
            ["p-inv-cleo", "p-pm-kael"], ["Tidepool Partners"],
            ["developer tools", "copilot"], 0.5,
        ),
        _side_event(
            "evt-side-copilot-breakfast", "Copilot Extensions Breakfast", "meetup",
            _pt(29, 8), _pt(29, 9, 30),
            _side_venue("Marina Cafe (synthetic venue)", 37.8030, -122.4370),
            ["p-pm-jory"], ["Wingmate Labs"], ["copilot"], 0.5,
        ),
        _session(
            "evt-s-mcp-tooling", "MCP Tooling for Agent Builders", _pt(29, 11), _pt(29, 11, 45),
            "Pavilion A (synthetic room)", ["p-fnd-gwen"], ["mcp", "ai agents"],
        ),
        _session(
            "evt-s-funding-devtools", "Funding Developer Tools in 2027", _pt(29, 15),
            _pt(29, 15, 45), "Pavilion C (synthetic room)", ["p-inv-ada"],
            ["developer tools"],
        ),
        _side_event(
            "evt-side-seed-office-hours", "Seed Office Hours", "meetup",
            _pt(29, 18), _pt(29, 20),
            _side_venue("Lanternseed Studio (synthetic venue)", 37.7765, -122.3950),
            ["p-inv-dov"], ["Lanternseed Ventures"], ["developer tools", "copilot"], 0.5,
        ),
        _side_event(
            "evt-side-infra-mixer", "Infra Engineers Mixer", "party",
            _pt(29, 18, 30), _pt(29, 20, 30),
            _side_venue("Rack Room (synthetic venue)", 37.7850, -122.4000),
            [], ["Hollowbyte"], ["infrastructure"], 0.3,
        ),
    ]


def _stay(
    lid: str, name: str, lat: float, lng: float, distance_m: int, total: str, status: str,
    rating: float | None,
) -> Lodging:
    total_price = Decimal(total)
    return Lodging(
        id=lid,
        name=name,
        provider=PROVIDER,
        lodging_type="hotel",
        check_in=date(2026, 10, 27),
        check_out=date(2026, 10, 30),
        adults=1,
        rooms=1,
        venue=_side_venue(name, lat, lng),
        distance_to_venue_m=distance_m,
        total_price=total_price,
        nightly_avg=(total_price / 3).quantize(Decimal("0.01")),
        base_total=None,
        taxes=None,
        fees_total=None,
        payable_at_property=None,
        currency="USD",
        price_status=status,
        availability="unknown",
        verified_at=None,
        includes_all_fees=None,
        free_cancellation=None,
        rating=rating,
        rating_scale=10 if rating is not None else None,
        rating_count=None,
        booking_url=f"{BASE_URL}/stays/{lid}",
        evidence=_evidence("lodging", lid),
    )


def build_lodging() -> list[Lodging]:
    return [
        _stay("stay-marina-inn", "Marina Courtyard Inn (synthetic)", 37.8005, -122.4370, 900,
              "897.00", "quoted_total", 8.4),
        _stay("stay-northpoint", "Northpoint Rooms (synthetic)", 37.8050, -122.4150, 1500,
              "771.00", "indicative", 7.9),
        _stay("stay-soma-pods", "SoMa Pods (synthetic)", 37.7790, -122.4000, 4300,
              "498.00", "indicative", None),
    ]


def _seg(
    origin: str, dest: str, dep: datetime, arr: datetime, number: str, minutes: int,
) -> FlightSegment:
    return FlightSegment(
        origin_iata=origin,
        destination_iata=dest,
        departure_at=dep,
        arrival_at=arr,
        marketing_carrier="Fixture Air (fictional)",
        operating_carrier=None,
        flight_number=number,
        aircraft=None,
        duration_minutes=minutes,
        connection_type="unknown",
    )


def _offer(
    fid: str, out_seg: FlightSegment, back_seg: FlightSegment, price: str,
) -> FlightOffer:
    return FlightOffer(
        id=fid,
        dedup_key=f"{out_seg.flight_number}|{back_seg.flight_number}",
        trip_type="round_trip",
        slices=[
            FlightSlice(segments=[out_seg], duration_minutes=out_seg.duration_minutes),
            FlightSlice(segments=[back_seg], duration_minutes=back_seg.duration_minutes),
        ],
        total_price=price,
        raw_price_text=f"${price} (simulated)",
        price_scope="total_all_passengers",
        currency="USD",
        price_status="sandbox",
        collected_at=FIXED_COLLECTED_AT,
        booking_url=f"{BASE_URL}/flights/{fid}",
        booking_url_type="unknown",
        baggage_verified=None,
        carry_on_included=None,
        checked_bags_included=None,
        warnings=["Simulated fixture fare; not an observed or bookable offer."],
        evidence=_evidence("flights", fid),
    )


def build_flights() -> list[FlightOffer]:
    back_am = _seg("SFO", "JFK", _pt(30, 13), datetime(2026, 10, 30, 21, 35, tzinfo=ET),
                   "FX202", 335)
    back_pm = _seg("SFO", "EWR", _pt(30, 15, 30), datetime(2026, 10, 31, 0, 5, tzinfo=ET),
                   "FX208", 335)
    return [
        _offer("flt-jfk-sfo-morning",
               _seg("JFK", "SFO", datetime(2026, 10, 27, 8, 0, tzinfo=ET), _pt(27, 11, 25),
                    "FX101", 385), back_am, "512.40"),
        _offer("flt-ewr-sfo-noon",
               _seg("EWR", "SFO", datetime(2026, 10, 27, 12, 0, tzinfo=ET), _pt(27, 15, 20),
                    "FX105", 380), back_pm, "468.90"),
        _offer("flt-lga-oak-evening",
               _seg("LGA", "OAK", datetime(2026, 10, 27, 17, 0, tzinfo=ET), _pt(27, 20, 30),
                    "FX111", 390), back_pm, "401.15"),
    ]


def build_world() -> DemoWorld:
    return DemoWorld(
        user=DemoUser(),
        conference=build_conference(),
        goals=build_goals(),
        companies=build_companies(),
        people=build_people(),
        events=build_events(),
        lodging=build_lodging(),
        flights=build_flights(),
    )
