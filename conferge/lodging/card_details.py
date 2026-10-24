"""Bounded presentation data, kept separate from the frozen financial contract."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, Field, HttpUrl

from conferge.core.schemas import Lodging, SourceRecord


class StayCardDetails(BaseModel):
    image_urls: list[str] = Field(default_factory=list, max_length=5)
    # Property imagery may be collected separately from a dated room quote.
    image_source_url: HttpUrl | None = None
    image_collected_at: AwareDatetime | None = None
    star_rating: int | None = Field(default=None, ge=1, le=5)
    amenities: list[str] = Field(default_factory=list, max_length=6)
    room_type: str | None = Field(default=None, max_length=160)
    bed_description: str | None = Field(default=None, max_length=160)
    breakfast_included: bool | None = None
    no_prepayment: bool | None = None
    free_cancellation_until: str | None = Field(default=None, max_length=160)


class LodgingWithCard(Lodging):
    card_details: StayCardDetails = Field(default_factory=StayCardDetails, exclude=True)


def image_urls(value: Any) -> list[str]:
    out = []
    for item in (value if isinstance(value, list) else [value])[:30]:
        if isinstance(item, dict):
            item = item.get("url") or item.get("image_url") or item.get("src")
        if not isinstance(item, str) or len(item) > 4096:
            continue
        try:
            url = urlsplit(item)
            valid = url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password
        except ValueError:
            continue
        if valid and item not in out:
            out.append(item)
    return out[:5]


def _text(value: Any) -> str | None:
    return value.strip()[:160] if isinstance(value, str) and value.strip() else None


def compact(row: dict[str, Any], *, rate_facts: bool = True) -> dict[str, Any]:
    images = []
    for key in ("image", "images", "image_url", "photos", "property_photos"):
        images.extend(image_urls(row.get(key)))
    stars = row.get("star_rating", row.get("star_classification", row.get("stars")))
    try:
        number = float(stars) if not isinstance(stars, bool) else 0.0
        stars = int(number) if number.is_integer() and 1 <= number <= 5 else None
    except (TypeError, ValueError, OverflowError):
        stars = None
    amenities = (
        row.get("amenities")
        or row.get("most_popular_facilities")
        or row.get("popular_amenities")
        or row.get("facilities")
        or []
    )
    names = []
    queue = list(amenities[:30]) if isinstance(amenities, list) else []
    # Only bounded public facilities; omit descriptions, host profiles and reviews.
    for amenity in queue[:30]:
        children = amenity.get("values") if isinstance(amenity, dict) else None
        entries = children[:10] if isinstance(children, list) else [amenity]
        for entry in entries:
            if isinstance(entry, dict):
                entry = entry.get("name") or entry.get("title")
            text = _text(entry)
            if text and text not in names:
                names.append(text)
    fields = {}
    for key in ("breakfast_included", "no_prepayment"):
        fields[key] = row.get(key) if rate_facts and isinstance(row.get(key), bool) else None
    return StayCardDetails(
        image_urls=list(dict.fromkeys(images))[:5],
        star_rating=stars,
        amenities=names[:6],
        room_type=_text(row.get("room_type")) if rate_facts else None,
        bed_description=_text(row.get("bed_description") or row.get("bed_type"))
        if rate_facts
        else None,
        free_cancellation_until=_text(row.get("free_cancellation_until")) if rate_facts else None,
        **fields,
    ).model_dump()


def from_record(record: SourceRecord, *, rate_facts: bool = True) -> StayCardDetails:
    payload = record.payload
    search = payload.get("search") or {}
    detail = payload.get("detail") or payload.get("details") or {}
    search = search if isinstance(search, dict) else {}
    detail = detail if isinstance(detail, dict) else {}
    base = compact(
        {**detail, **{k: v for k, v in search.items() if v not in (None, "", [])}}, rate_facts=False
    )
    rate_keys = (
        "room_type",
        "bed_description",
        "breakfast_included",
        "no_prepayment",
        "free_cancellation_until",
    )
    search_card = compact(search, rate_facts=rate_facts)
    for key in rate_keys:
        base[key] = search_card[key]
    retained = payload.get("card_details")
    if isinstance(retained, dict):
        base.update(retained)
    if not rate_facts:
        for key in rate_keys:
            base[key] = None
    return StayCardDetails.model_validate(base)
