from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from conferge.core.schemas import DiscoveryQuery, Lodging, SourceRecord, Venue
from conferge.lodging._common import parse_money, parse_signed_money, worst_status
from conferge.lodging.dedupe import dedupe, normalize_name, same_property
from conferge.lodging.distance import distances, haversine_m, walk_minutes, with_venue_distance
from conferge.lodging.models import FORT_MASON, LodgingQuery, Place
from conferge.lodging.normalize import (
    PriceQuote,
    build_lodging,
    decide_price_status,
    refresh_status,
)

NOW = datetime(2026, 10, 24, 17, 0, tzinfo=timezone.utc)
Q = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30))


def _record(provider: str = "booking", source_id: str = "1") -> SourceRecord:
    return SourceRecord(provider=provider, source_id=source_id, source_mode="live",
                        collected_at=NOW, source_url="https://www.booking.com/hotel/us/x.html")


def _stay(pid: str, provider: str, name: str, lat: float | None, lng: float | None) -> Lodging:
    venue = Venue(name=name, latitude=lat, longitude=lng, coordinate_precision="exact") \
        if lat is not None else None
    return Lodging(id=f"{provider}:{pid}", name=name, provider=provider,
                   check_in=Q.check_in, check_out=Q.check_out, adults=1, venue=venue)


@pytest.mark.parametrize("raw,expected", [
    (953, Decimal("953")), ("1,322.50", Decimal("1322.50")), ("$292", Decimal("292")),
    ("US$ 410 total", Decimal("410")), (0, None), ("0", None), ("", None), (None, None),
    ("free", None), (True, None), (-5, None),
])
def test_parse_money_never_accepts_zero(raw, expected):
    assert parse_money(raw) == expected


def test_parse_signed_money_keeps_discounts():
    assert parse_signed_money(-20.5) == Decimal("-20.5")
    assert parse_signed_money("-$20") == Decimal("-20")
    assert parse_signed_money(0) is None


def test_query_nights_and_mapping_from_core_query():
    core = DiscoveryQuery(domain="lodging", latitude=37.8, longitude=-122.43, radius_km=2,
                          start_date=date(2026, 10, 27), end_date=date(2026, 10, 30),
                          filters={"adults": 1, "currency": "USD",
                                   "venues": [{"id": "e1", "name": "Party", "lat": 37.79,
                                               "lng": -122.41}]})
    q = LodgingQuery.from_discovery(core)
    assert q.nights == 3 and q.radius_km == 2 and q.venues[0].id == "e1"
    assert LodgingQuery.from_discovery(q.to_discovery()) == q
    with pytest.raises(ValueError):
        LodgingQuery.from_discovery(DiscoveryQuery(domain="lodging"))
    ne_lat, ne_lng, sw_lat, sw_lng = Q.bounding_box()
    assert sw_lat < Q.lat < ne_lat and sw_lng < Q.lng < ne_lng


def test_dated_total_is_quoted_and_nightly_is_derived():
    stay = build_lodging(_record(), Q, name="Fictional Bay Hotel", now=NOW,
                         quote=PriceQuote(total=Decimal("1000"), currency="USD",
                                          kind="dated_total"),
                         booking_url="https://www.booking.com/hotel/us/x.html")
    assert stay.price_status == "quoted_total"
    assert stay.total_price == Decimal("1000.00") and stay.nightly_avg == Decimal("333.33")
    assert stay.taxes is None and stay.fees_total is None and stay.includes_all_fees is None
    assert stay.evidence[0].source_mode == "live" and stay.evidence[0].collected_at == NOW


def test_from_price_is_indicative_and_never_multiplied():
    stay = build_lodging(_record(), Q, name="Fictional", now=NOW,
                         quote=PriceQuote(nightly_rate=Decimal("199"), currency="USD",
                                          kind="from_price"))
    assert stay.price_status == "indicative"
    assert stay.total_price is None and stay.nightly_avg == Decimal("199.00")


def test_verified_bookable_needs_every_condition():
    url = "https://www.booking.com/hotel/us/x.html"
    good = PriceQuote(total=Decimal("900"), currency="USD", includes_all_fees=True,
                      kind="verified", verified_at=NOW - timedelta(minutes=5))
    assert decide_price_status(good, "verified_available", url, now=NOW) == "verified_bookable"
    assert decide_price_status(good, "unknown", url, now=NOW) == "quoted_total"
    assert decide_price_status(good, "verified_available", None, now=NOW) == "quoted_total"
    fees_unknown = PriceQuote(**{**good.__dict__, "includes_all_fees": None})
    assert decide_price_status(fees_unknown, "verified_available", url, now=NOW) == "quoted_total"
    stale = PriceQuote(**{**good.__dict__, "verified_at": NOW - timedelta(minutes=31)})
    assert decide_price_status(stale, "verified_available", url, now=NOW) == "quoted_total"
    assert decide_price_status(good, "unavailable", url, now=NOW) == "unavailable"
    assert decide_price_status(PriceQuote(), "unknown", url, now=NOW) == "unknown"


def test_fixture_record_is_never_bookable():
    quote = PriceQuote(total=Decimal("900"), currency="USD", includes_all_fees=True,
                       kind="verified", verified_at=NOW)
    record = _record().model_copy(update={"source_mode": "fixture"})
    stay = build_lodging(record, Q, name="Fictional", quote=quote,
                         availability="verified_available", now=NOW,
                         booking_url="https://www.booking.com/hotel/us/x.html")
    assert stay.price_status == "quoted_total"


def test_refresh_downgrades_expired_verification():
    quote = PriceQuote(total=Decimal("900"), currency="USD", includes_all_fees=True,
                       kind="verified", verified_at=NOW)
    stay = build_lodging(_record(), Q, name="Fictional", quote=quote,
                         availability="verified_available", now=NOW,
                         booking_url="https://www.booking.com/hotel/us/x.html")
    assert stay.price_status == "verified_bookable"
    assert refresh_status(stay, now=NOW + timedelta(minutes=10)).price_status == "verified_bookable"
    assert refresh_status(stay, now=NOW + timedelta(minutes=45)).price_status == "quoted_total"


def test_stay_mismatch_drops_price_with_warning():
    warnings: list[str] = []
    stay = build_lodging(_record(), Q, name="Fictional", now=NOW, warnings=warnings,
                         quote=PriceQuote(total=Decimal("700"), currency="USD",
                                          kind="dated_total"),
                         echoed_check_in=date(2026, 10, 28), echoed_adults=1)
    assert stay.total_price is None and stay.price_status == "unknown"
    assert "stay mismatch" in warnings[0]


def test_currency_never_converted():
    warnings: list[str] = []
    stay = build_lodging(_record(), Q, name="Fictional", now=NOW, warnings=warnings,
                         quote=PriceQuote(total=Decimal("700"), currency="EUR",
                                          kind="dated_total"))
    assert stay.currency == "EUR" and stay.total_price == Decimal("700.00")
    assert "not converted" in warnings[0]


def test_distance_and_walk_estimate():
    fort_mason = Place(**FORT_MASON)
    ghirardelli = (37.8059, -122.4229)
    meters = haversine_m(fort_mason.lat, fort_mason.lng, *ghirardelli)
    assert 750 < meters < 850
    assert walk_minutes(1000) == 12 and walk_minutes(None) is None
    stay = with_venue_distance(_stay("1", "booking", "Fictional", *ghirardelli), fort_mason)
    assert 750 < stay.distance_to_venue_m < 850
    no_coords = with_venue_distance(_stay("2", "booking", "Fictional", None, None), fort_mason)
    assert no_coords.distance_to_venue_m is None
    rows = distances(stay, [fort_mason, Place(id="e", name="Event", lat=37.79, lng=-122.40)])
    assert rows[0]["place_id"] == FORT_MASON["id"] and rows[1]["walk_minutes_estimate"] > 0


def test_normalize_name_strips_brands_and_noise():
    assert normalize_name("The Fictional Marina Hotel, Autograph Collection") == "fictional marina"
    assert normalize_name("Hôtel Fictional Marina SF") == "fictional marina"


def test_dedupe_merges_close_same_name_across_providers_only():
    a = _stay("1", "booking", "The Fictional Marina Hotel", 37.8030, -122.4370)
    b = _stay("g1", "google_hotels", "Fictional Marina Hotel SF", 37.8032, -122.4371)
    far = _stay("g2", "google_hotels", "Fictional Marina Hotel", 37.8100, -122.4370)
    other = _stay("g3", "google_hotels", "Another Fictional Inn", 37.8030, -122.4370)
    bnb = _stay("9", "airbnb", "The Fictional Marina Hotel", 37.8030, -122.4370)
    rows, groups = dedupe([a, b, far, other, bnb])
    by_id = {r.id: r.dedup_group for r in rows}
    assert by_id["booking:1"] == by_id["google_hotels:g1"]
    assert len({by_id["google_hotels:g2"], by_id["google_hotels:g3"], by_id["airbnb:9"],
                by_id["booking:1"]}) == 4
    assert len(groups) == 1 and len(rows) == 5
    assert same_property(a, bnb) == (False, "airbnb never merged across providers")
    assert same_property(a, _stay("2", "booking", "x", None, None))[0] is False


def test_worst_status():
    assert worst_status(["ok", "ok"]) == "ok"
    assert worst_status(["ok", "failed"]) == "degraded"
    assert worst_status(["failed", "failed"]) == "failed"
    assert worst_status([]) == "failed"
