"""Provider-neutral normalization into `FlightOffer`.

Provider adapters turn raw payloads into `RawSlice`/`RawSegment` values; this
module builds the contract model. Rules (docs/knowledge/07-flights.md):
money stays a decimal string, the raw price text is kept, times are local with
the airport IANA zone (never naive), connection type defaults to unknown, and
baggage is tri-state (None means unknown).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from conferge.core.schemas import FlightOffer, FlightSegment, FlightSlice, SourceEvidence
from conferge.flights.airports import timezone_for
from conferge.flights.dedupe import itinerary_id, offer_id

PRICE_WARNING = "price_indicative: metasearch price observed at collected_at, not a ticket"
BAGGAGE_WARNING = "baggage_unverified: price may exclude bags and card fees"

_CURRENCY_SYMBOLS = {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "C$": "CAD", "CA$": "CAD"}
_IATA = re.compile(r"^[A-Z]{3}$")


@dataclass
class RawSegment:
    origin: str | None
    destination: str | None
    departure: Any = None  # str (local or ISO with offset) or datetime
    arrival: Any = None
    marketing_carrier: str | None = None
    operating_carrier: str | None = None
    flight_number: str | None = None
    aircraft: str | None = None
    duration_minutes: int | None = None


@dataclass
class RawSlice:
    segments: list[RawSegment]
    duration_minutes: int | None = None
    self_transfer: bool | None = None


@dataclass
class RawOffer:
    provider: str
    slices: list[RawSlice]
    trip_type: str
    price: Any = None
    currency: str | None = None
    price_scope: str = "unknown"
    booking_url: str | None = None
    booking_url_type: str = "unknown"
    carry_on_included: bool | None = None
    checked_bags_included: int | None = None
    fare: str | None = None
    evidence: list[SourceEvidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class NormalizationError(ValueError):
    """The payload cannot express a contract-valid offer (kept visible upstream)."""


def parse_price(value: Any, currency: str | None = None) -> tuple[str | None, str | None, str | None]:
    """Return (decimal string, ISO currency, raw text). Unknown stays None."""
    if value is None or value == "":
        return None, currency, None
    if isinstance(value, dict):
        amount = value.get("amount", value.get("price", value.get("value", value.get("total"))))
        return parse_price(amount, value.get("currency") or currency)
    if isinstance(value, bool):
        return None, currency, str(value)
    raw = str(value).strip()
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    else:
        symbol = re.match(r"^([A-Z]{0,3}[$€£])", raw)
        if symbol and not currency:
            currency = _CURRENCY_SYMBOLS.get(symbol.group(1))
        code = re.search(r"\b([A-Z]{3})\b", raw)
        if code and not currency:
            currency = code.group(1)
        digits = re.sub(r"[^0-9.]", "", raw.replace(",", ""))
        try:
            number = Decimal(digits)
        except InvalidOperation:
            return None, currency, raw
    if not number.is_finite() or number < 0:
        return None, currency, raw
    text = format(number.normalize(), "f") if number == number.to_integral() else format(number, "f")
    if "." in text and len(text.split(".")[1]) > 4:
        text = format(number.quantize(Decimal("0.0001")), "f")
    return text, currency.upper() if currency else None, raw


def to_aware(value: Any, iata: str | None) -> tuple[datetime | None, str | None]:
    """Parse a time into an aware datetime in the airport zone.

    Returns (datetime, warning). A string with its own offset is kept and
    converted to the airport zone; a naive local string is localized with the
    airport zone; if the zone is unknown the time stays None.
    """
    if value in (None, ""):
        return None, None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = None
        for candidate in (text, text.replace(" ", "T", 1)):
            try:
                parsed = datetime.fromisoformat(candidate)
                break
            except ValueError:
                continue
        if parsed is None:
            return None, f"unparsed_time: {value!r}"
    zone = timezone_for(iata)
    if parsed.tzinfo is not None:
        return (parsed.astimezone(zone) if zone else parsed), None
    if zone is None:
        return None, f"timezone_unknown: {iata}"
    return parsed.replace(tzinfo=zone), None


def _iata(value: str | None) -> str:
    code = (value or "").strip().upper()
    if not _IATA.match(code):
        raise NormalizationError(f"invalid airport code {value!r}")
    return code


def build_segment(raw: RawSegment, warnings: list[str]) -> FlightSegment:
    origin, destination = _iata(raw.origin), _iata(raw.destination)
    departure, w1 = to_aware(raw.departure, origin)
    arrival, w2 = to_aware(raw.arrival, destination)
    warnings.extend(w for w in (w1, w2) if w)
    if not raw.flight_number:
        warnings.append(f"missing_flight_number: {origin}-{destination}")
    duration = raw.duration_minutes
    if duration is None and departure and arrival and arrival >= departure:
        duration = int((arrival - departure).total_seconds() // 60)
    return FlightSegment(
        origin_iata=origin, destination_iata=destination,
        departure_at=departure, arrival_at=arrival,
        marketing_carrier=raw.marketing_carrier, operating_carrier=raw.operating_carrier,
        flight_number=raw.flight_number, aircraft=raw.aircraft,
        duration_minutes=duration,
    )


def build_offer(raw: RawOffer, collected_at: datetime, *, price_status: str = "observed_live") -> FlightOffer:
    """Build a `FlightOffer`; raise NormalizationError for incomplete itineraries."""
    warnings = list(raw.warnings)
    if raw.trip_type == "round_trip" and len(raw.slices) != 2:
        raise NormalizationError(f"partial_roundtrip: {len(raw.slices)} slice(s) in payload")
    slices: list[FlightSlice] = []
    for raw_slice in raw.slices:
        if not raw_slice.segments:
            raise NormalizationError("slice without segments")
        segments = [build_segment(s, warnings) for s in raw_slice.segments]
        if raw_slice.self_transfer:
            warnings.append("self_transfer: separate tickets, missed connection not protected")
        slices.append(FlightSlice(
            segments=segments, duration_minutes=raw_slice.duration_minutes,
            self_transfer=raw_slice.self_transfer,
        ))
    amount, currency, raw_text = parse_price(raw.price, raw.currency)
    if amount is None:
        warnings.append("price_missing")
    elif price_status == "observed_live":
        warnings.append(PRICE_WARNING)
    if raw.carry_on_included is None and raw.checked_bags_included is None:
        warnings.append(BAGGAGE_WARNING)
    if amount is not None and currency is None:
        warnings.append(f"currency_unknown: raw price {raw_text!r} dropped")
        amount = None
    itin = itinerary_id(slices)
    booking_url, url_type = raw.booking_url, raw.booking_url_type
    if booking_url and not str(booking_url).startswith(("http://", "https://")):
        warnings.append("booking_link_not_a_url: token kept out of booking_url")
        booking_url, url_type = None, "unknown"
    return FlightOffer(
        id=offer_id(itin, raw.provider, raw.fare, raw.carry_on_included, raw.checked_bags_included),
        dedup_key=itin,
        trip_type=raw.trip_type,
        slices=slices,
        total_price=amount,
        raw_price_text=raw_text,
        price_scope=raw.price_scope,
        currency=currency if amount is not None else None,
        price_status=price_status if amount is not None else "unknown",
        collected_at=collected_at,
        booking_url=booking_url,
        booking_url_type=url_type if booking_url else "unknown",
        baggage_verified=None,
        carry_on_included=raw.carry_on_included,
        checked_bags_included=raw.checked_bags_included,
        warnings=list(dict.fromkeys(warnings)),
        evidence=raw.evidence,
    )


def classify_url(url: str | None) -> str:
    if not url:
        return "unknown"
    if "google.com/travel/flights/booking" in url:
        return "google_flights_booking"
    if "google.com/travel/flights" in url or "google.com/flights" in url:
        return "google_flights_search"
    return "unknown"


def parse_duration(value: Any) -> int | None:
    """Accept minutes (int) or text such as '5 hr 40 min' / '5h 40m'."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    match = re.match(r"^\s*(?:(\d+)\s*h(?:r|rs|ours?)?)?\s*(?:(\d+)\s*m(?:in|ins)?)?\s*$", str(value))
    if not match or not any(match.groups()):
        return None
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)
