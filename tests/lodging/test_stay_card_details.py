"""Source schema regression coverage: rich cards, discovery hydration, cache roundtrip."""

import json
from datetime import date, datetime, timezone

import httpx

from conferge.api.travel_cards import view
from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import Lodging, SourceRecord
from conferge.integration import travel_cache
from conferge.lodging.airbnb import BrightDataAirbnbBackend, to_lodging as airbnb_stay
from conferge.lodging.booking import to_lodging
from conferge.lodging.card_details import compact
from conferge.lodging.google_hotels import GoogleHotelsSource
from conferge.lodging.models import LodgingQuery

NOW = datetime(2026, 10, 24, 19, tzinfo=timezone.utc)
Q = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30))


def booking_record(**changes):
    row = {
        "title": "Fictional Test Inn",
        "star_rating": 4,
        "review_score": 8.9,
        "review_count": "120",
        "image": "https://images.example.test/property.jpg",
        "final_price": 600,
        "currency": "USD",
        "bed_type": "1 double bed",
        "check_in": "2026-10-27",
        "check_out": "2026-10-30",
        "adults": 1,
        "no_prepayment": True,
    }
    row.update(changes)
    return SourceRecord(
        provider="booking",
        source_id="123",
        source_mode="live",
        collected_at=NOW,
        source_url="https://www.booking.com/hotel/us/test.html",
        payload={"search": row},
    )


def test_stars_do_not_replace_guest_reviews_and_core_stays_valid():
    stay = to_lodging(booking_record(), Q)
    assert (stay.rating, stay.rating_scale) == (8.9, 10)
    assert stay.card_details.star_rating == 4
    assert stay.card_details.image_urls == ["https://images.example.test/property.jpg"]
    assert stay.card_details.bed_description == "1 double bed"
    assert stay.card_details.no_prepayment is True
    assert view(stay)["card_details"]["star_rating"] == 4
    assert Lodging.model_validate_json(stay.model_dump_json()).total_price == stay.total_price
    assert "card_details" not in stay.model_dump()


def test_missing_stars_never_inferred_and_wrong_dates_drop_rate_facts():
    stay = to_lodging(booking_record(star_rating=None, review_score=9.9), Q)
    assert stay.card_details.star_rating is None
    wrong = to_lodging(booking_record(check_in="2027-01-01", breakfast_included=True), Q)
    assert wrong.total_price is None and wrong.card_details.bed_description is None
    assert wrong.card_details.no_prepayment is None
    assert wrong.card_details.breakfast_included is None and wrong.card_details.image_urls


def test_bounded_metadata_excludes_unsafe_urls_and_host_data():
    data = compact(
        {
            "images": [
                "javascript:alert(1)",
                "data:image/png,test",
                "https://secret@example.test/x",
            ]
            + [f"https://images.example.test/{i}.jpg" for i in range(50)],
            "star_rating": True,
            "host_image": "https://host.example.test/a.jpg",
            "amenities": [{"name": str(i)} for i in range(30)],
        }
    )
    assert len(data["image_urls"]) == 5 and len(data["amenities"]) == 6
    assert data["star_rating"] is None and "host_image" not in data
    assert compact({"most_popular_facilities": ["WiFi"]})["amenities"] == ["WiFi"]
    assert compact({"popular_amenities": ["Pool"]})["amenities"] == ["Pool"]


def test_property_detail_never_promotes_an_unmatched_room_rate():
    record = booking_record()
    record.payload["detail"] = {"room_type": "Different suite", "breakfast_included": True}
    stay = to_lodging(record, Q)
    assert stay.card_details.room_type is None
    assert stay.card_details.breakfast_included is None


def test_cache_retains_cards_as_optional_sibling_with_same_provenance(tmp_path):
    stay = to_lodging(booking_record(), Q)
    doc = travel_cache.build("stays", [stay], sources=["mocked"], generated_at=NOW)
    record = doc["records"][0]
    assert record["card_details"]["star_rating"] == 4
    assert Lodging.model_validate(record["record"]).total_price == stay.total_price
    (tmp_path / "stays.json").write_text(json.dumps(doc))
    restored = travel_cache.load(tmp_path)["stays"].items[0]
    assert restored.evidence[0].source_mode == "cached"
    assert restored.evidence[0].collected_at == NOW
    assert view(restored)["card_details"]["image_urls"] == stay.card_details.image_urls
    del record["card_details"]
    (tmp_path / "stays.json").write_text(json.dumps(doc))
    legacy = travel_cache.load(tmp_path)["stays"].items[0]
    assert legacy.card_details.image_urls == [] and legacy.card_details.star_rating is None


def client(handler):
    return BrightDataClient(
        "test-key",
        client=httpx.AsyncClient(
            base_url="https://api.brightdata.com", transport=httpx.MockTransport(handler)
        ),
    )


async def test_airbnb_documented_url_only_discovery_hydrates_and_keeps_images():
    requests = []

    def handler(req):
        requests.append(req)
        if req.url.params.get("discover_by") == "location":
            return httpx.Response(200, json=[{"url": "https://www.airbnb.com/rooms/123"}])
        inputs = json.loads(req.content)["input"]
        assert "check_in=2026-10-27" in inputs[0]["url"]
        return httpx.Response(
            200,
            json=[
                {
                    "url": "https://www.airbnb.com/rooms/123",
                    "property_id": "123",
                    "name": "Test apartment",
                    "images": [{"url": "https://images.example.test/123.jpg"}],
                    "amenities": ["WiFi"],
                    "ratings": 4.8,
                    "property_number_of_reviews": 40,
                    "travel_details": {
                        "check_in": "2026-10-27",
                        "check_out": "2026-10-30",
                        "num_of_adults": 1,
                    },
                    "total_price": 500,
                    "currency": "USD",
                }
            ],
        )

    bd = client(handler)
    result = await BrightDataAirbnbBackend(bd, clock=lambda: NOW).search(Q)
    assert len(requests) == 2 and result.run_report.pages == 2
    assert result.run_report.status == "ok"
    assert "images" not in result.items[0].payload["search"]
    stay = airbnb_stay(result.items[0], Q)
    assert stay.card_details.image_urls == ["https://images.example.test/123.jpg"]
    assert stay.card_details.amenities == ["WiFi"] and stay.card_details.star_rating is None
    from conferge.api.provenance import source_of

    assert source_of(stay.evidence)["provider"] == "brightdata"
    assert source_of(stay.evidence)["snapshot_id"] is None
    await bd.aclose()


async def test_google_url_discovery_hydrates_details():
    requests = []
    url = "https://www.google.com/travel/hotels/entity/test123?checkin=2026-10-27"

    def handler(req):
        requests.append(req)
        if req.url.params.get("discover_by") == "search":
            return httpx.Response(200, json=[{"url": url}])
        return httpx.Response(
            200,
            json=[
                {
                    "url": url,
                    "hotel_id": "123",
                    "hotel_name": "Test hotel",
                    "photos": [{"url": "https://images.example.test/hotel.jpg"}],
                    "star_classification": 3,
                }
            ],
        )

    bd = client(handler)
    result = await GoogleHotelsSource(bd, clock=lambda: NOW).search(Q)
    assert len(requests) == 2 and result.run_report.pages == 2
    assert result.items[0].payload["search"]["star_classification"] == 3
    await bd.aclose()


async def test_failed_details_stay_visible_without_inventing_stays():
    def handler(req):
        if req.url.params.get("discover_by") == "location":
            return httpx.Response(200, json=[{"url": "https://www.airbnb.com/rooms/123"}])
        return httpx.Response(403, json={})

    bd = client(handler)
    result = await BrightDataAirbnbBackend(bd, clock=lambda: NOW).search(Q)
    assert not result.items and result.run_report.status != "ok"
    assert any("detail collection failed" in w for w in result.run_report.warnings)
    await bd.aclose()
