"""Optional airline artwork and fare labels, without changing core schemas."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from conferge.core.schemas import FlightOffer


class AirlineImage(BaseModel):
    carrier: str = Field(max_length=100)
    url: str = Field(max_length=4096)


class FlightCardDetails(BaseModel):
    airline_images: list[AirlineImage] = Field(default_factory=list, max_length=8)
    cabin: str | None = Field(default=None, max_length=100)
    fare_name: str | None = Field(default=None, max_length=100)


class FlightWithCard(FlightOffer):
    card_details: FlightCardDetails = Field(default_factory=FlightCardDetails, exclude=True)


def from_row(row: dict[str, Any]) -> dict[str, Any]:
    images = []
    legs = row.get("legs") if isinstance(row.get("legs"), list) else []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        segments = leg.get("segments", leg.get("flights", []))
        for segment in segments if isinstance(segments, list) else []:
            if not isinstance(segment, dict):
                continue
            carrier = next(
                (
                    segment.get(k)
                    for k in (
                        "marketing_code",
                        "airline_code",
                        "carrier_code",
                        "marketing_carrier",
                        "airline_name",
                        "airline",
                    )
                    if segment.get(k)
                ),
                None,
            )
            if isinstance(carrier, dict):
                carrier = carrier.get("iata") or carrier.get("name")
            logo = segment.get("airline_logo") or segment.get("carrier_logo")
            if not isinstance(logo, str) or not isinstance(carrier, str) or len(logo) > 4096:
                continue
            try:
                url = urlsplit(logo)
                valid = url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password
            except ValueError:
                continue
            entry = {"carrier": carrier[:100], "url": logo}
            if valid and entry not in images:
                images.append(entry)
    search = row.get("search") if isinstance(row.get("search"), dict) else {}

    def text(value: Any) -> str | None:
        return value.strip()[:100] if isinstance(value, str) and value.strip() else None

    return FlightCardDetails(
        airline_images=images[:8],
        cabin=text(search.get("cabin")),
        fare_name=text(row.get("fare_name")),
    ).model_dump()
