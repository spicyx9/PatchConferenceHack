"""Source-independent lodging normalization and price-truth rules.

Rules (docs/knowledge/06-lodging.md, CLAUDE.md rule 6):
- the stay total is stored as given; ``nightly_avg`` is derived as total / nights, never
  the reverse (a nightly "from" rate is never multiplied into a total);
- taxes and fees that the source does not state stay ``None``; ``includes_all_fees`` is
  ``True`` only when the source says so explicitly;
- ``verified_bookable`` needs a dated detail re-check (< 30 min), verified availability for
  the exact stay and occupancy, an all-fees total and a deeplink. Otherwise the best a
  dated total can reach is ``quoted_total``; a "from" nightly rate is ``indicative``;
- a quote whose echoed dates or occupancy differ from the query is not a price for this
  stay: it is dropped (``unknown``) with a warning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from conferge.core.schemas import Lodging, SourceEvidence, SourceRecord, Venue
from conferge.lodging._common import now_utc, quantize
from conferge.lodging.models import LodgingQuery

QuoteKind = Literal["verified", "dated_total", "from_price", "none"]
VERIFY_TTL = timedelta(minutes=30)
PRICE_STATUS_RANK = {
    "verified_bookable": 0, "quoted_total": 1, "indicative": 2, "unknown": 3, "unavailable": 4,
}


@dataclass
class PriceQuote:
    total: Decimal | None = None
    base_total: Decimal | None = None
    taxes: Decimal | None = None
    fees_total: Decimal | None = None
    payable_at_property: Decimal | None = None
    nightly_rate: Decimal | None = None
    """Only for ``from_price`` quotes: the per-night rate as shown, never multiplied."""
    currency: str | None = None
    includes_all_fees: bool | None = None
    kind: QuoteKind = "none"
    verified_at: datetime | None = None


def decide_price_status(
    quote: PriceQuote, availability: str, booking_url: str | None, *, now: datetime | None = None,
) -> str:
    if availability == "unavailable":
        return "unavailable"
    now = now or now_utc()
    if (
        quote.kind == "verified"
        and quote.total is not None
        and availability == "verified_available"
        and booking_url
        and quote.includes_all_fees is True
        and quote.verified_at is not None
        and timedelta(0) <= now - quote.verified_at <= VERIFY_TTL
    ):
        return "verified_bookable"
    if quote.total is not None and quote.kind in {"verified", "dated_total"}:
        return "quoted_total"
    if quote.kind == "from_price" and quote.nightly_rate is not None:
        return "indicative"
    return "unknown"


def stay_matches(
    query: LodgingQuery, check_in: date | None, check_out: date | None, adults: int | None,
) -> tuple[bool, list[str]]:
    """Echoed stay must equal the query when the source echoes it; missing echo is allowed."""
    problems = []
    if check_in is not None and check_in != query.check_in:
        problems.append(f"check_in {check_in} != query {query.check_in}")
    if check_out is not None and check_out != query.check_out:
        problems.append(f"check_out {check_out} != query {query.check_out}")
    if adults is not None and adults != query.adults:
        problems.append(f"adults {adults} != query {query.adults}")
    return not problems, problems


def evidence_for(record: SourceRecord, confidence: float | None = None) -> SourceEvidence:
    return SourceEvidence(
        provider=record.provider, source_mode=record.source_mode, source_url=record.source_url,
        collected_at=record.collected_at, raw_ref=record.request_id,
        source_record_id=record.source_id, confidence=confidence,
    )


def build_lodging(
    record: SourceRecord,
    query: LodgingQuery,
    *,
    name: str,
    quote: PriceQuote,
    lodging_type: str = "other",
    availability: str = "unknown",
    lat: float | None = None,
    lng: float | None = None,
    coordinate_precision: str = "unknown",
    address: str | None = None,
    city: str | None = None,
    free_cancellation: bool | None = None,
    rating: float | None = None,
    rating_scale: int | None = None,
    rating_count: int | None = None,
    booking_url: str | None = None,
    echoed_check_in: date | None = None,
    echoed_check_out: date | None = None,
    echoed_adults: int | None = None,
    extra_evidence: list[SourceEvidence] | None = None,
    warnings: list[str] | None = None,
    now: datetime | None = None,
) -> Lodging:
    sink = warnings if warnings is not None else []
    ok, problems = stay_matches(query, echoed_check_in, echoed_check_out, echoed_adults)
    if not ok:
        sink.append(f"{record.provider}:{record.source_id}: stay mismatch ({'; '.join(problems)}); "
                    "price dropped")
        quote = PriceQuote(currency=quote.currency)
        availability = "unknown" if availability == "verified_available" else availability
    if quote.currency and quote.currency != query.currency:
        sink.append(f"{record.provider}:{record.source_id}: currency {quote.currency} != "
                    f"requested {query.currency}; not converted")
    if lat is not None and lng is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
        lat = lng = None
    venue = None
    if any(v is not None for v in (lat, lng, address, city)):
        venue = Venue(name=name, address=address, city=city, latitude=lat, longitude=lng,
                      coordinate_precision=coordinate_precision if lat is not None else "unknown")
    status = decide_price_status(quote, availability, booking_url, now=now)
    if status == "verified_bookable" and record.source_mode == "fixture":
        status = "quoted_total"  # a replayed fixture is never bookable, however recent
    total = quantize(quote.total)
    if total is not None:
        nightly = quantize(total / query.nights)
    elif status == "indicative":
        nightly = quantize(quote.nightly_rate)
    else:
        nightly = None
    return Lodging(
        id=f"{record.provider}:{record.source_id}",
        name=name,
        provider=record.provider,
        lodging_type=lodging_type if lodging_type in {"hotel", "apartment", "hostel"} else "other",
        check_in=query.check_in,
        check_out=query.check_out,
        adults=query.adults,
        rooms=query.rooms,
        venue=venue,
        total_price=total,
        nightly_avg=nightly,
        base_total=quantize(quote.base_total),
        taxes=quantize(quote.taxes),
        fees_total=quantize(quote.fees_total),
        payable_at_property=quantize(quote.payable_at_property),
        currency=quote.currency if (total is not None or nightly is not None) else None,
        price_status=status,
        availability=availability,
        verified_at=quote.verified_at if quote.kind == "verified" else None,
        includes_all_fees=quote.includes_all_fees,
        free_cancellation=free_cancellation,
        rating=rating,
        rating_scale=rating_scale if rating is not None else None,
        rating_count=rating_count,
        booking_url=booking_url,
        evidence=[evidence_for(record), *(extra_evidence or [])],
    )


def refresh_status(lodging: Lodging, *, now: datetime | None = None) -> Lodging:
    """Downgrade an expired ``verified_bookable`` (older than 30 min) to ``quoted_total``."""
    if lodging.price_status != "verified_bookable":
        return lodging
    now = now or now_utc()
    if lodging.verified_at is not None and now - lodging.verified_at <= VERIFY_TTL:
        return lodging
    return lodging.model_copy(update={"price_status": "quoted_total"})


def sort_key(lodging: Lodging) -> tuple[Any, ...]:
    total = lodging.total_price if lodging.total_price is not None else Decimal("Infinity")
    distance = lodging.distance_to_venue_m if lodging.distance_to_venue_m is not None else 10**9
    return (PRICE_STATUS_RANK.get(lodging.price_status, 9), distance, total, lodging.id)


def normalize(
    record: SourceRecord, query: LodgingQuery, *, warnings: list[str] | None = None,
    now: datetime | None = None,
) -> Lodging | None:
    """Dispatch to the provider adapter. Returns None when the record is not a stay."""
    from conferge.lodging import airbnb, booking, google_hotels, google_hotels_direct, unlocker

    adapters = {
        booking.PROVIDER: booking.to_lodging,
        google_hotels.PROVIDER: google_hotels.to_lodging,
        airbnb.PROVIDER: airbnb.to_lodging,
        unlocker.PROVIDER: unlocker.to_lodging,
        google_hotels_direct.PROVIDER: google_hotels_direct.to_lodging,
    }
    adapter = adapters.get(record.provider)
    if adapter is None:
        if warnings is not None:
            warnings.append(f"no lodging adapter for provider {record.provider!r}")
        return None
    return adapter(record, query, warnings=warnings, now=now)
