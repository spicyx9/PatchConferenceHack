from datetime import datetime, timezone

from conferge.api.travel_cards import view
from conferge.core.schemas import FlightOffer
from conferge.flights.card_details import from_row
from conferge.flights.normalize import RawOffer, RawSegment, RawSlice, build_offer
from conferge.integration import travel_cache


def test_airline_images_flow_to_api_without_changing_core_financial_payload():
    card = from_row(
        {
            "search": {"cabin": "Economy"},
            "legs": [
                {
                    "segments": [
                        {
                            "marketing_code": "ZZ",
                            "airline_logo": "https://images.example.test/zz.png",
                        },
                        {"marketing_code": "XX", "airline_logo": "javascript:alert(1)"},
                    ]
                }
            ],
        }
    )
    assert len(card["airline_images"]) == 1
    offer = build_offer(
        RawOffer(
            provider="brightdata_google_flights",
            trip_type="one_way",
            slices=[RawSlice([RawSegment("JFK", "SFO")])],
            card_details=card,
        ),
        datetime(2026, 10, 24, tzinfo=timezone.utc),
    )
    assert view(offer)["card_details"]["cabin"] == "Economy"
    assert FlightOffer.model_validate_json(offer.model_dump_json()).total_price is None
    assert offer.carry_on_included is None and offer.checked_bags_included is None
    assert (
        travel_cache.build("flights", [offer], sources=[], generated_at=offer.collected_at)[
            "records"
        ][0]["card_details"]["cabin"]
        == "Economy"
    )


def test_missing_nested_details_stay_unknown():
    card = from_row({"search": "unknown", "legs": [None, {"segments": [{"marketing_code": "ZZ"}]}]})
    assert card["airline_images"] == [] and card["cabin"] is None
