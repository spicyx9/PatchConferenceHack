"""Reference places for the GitHub Universe 2026 demo.

Coordinates are public reference points (airport terminals / venue entrance), marked
approximate. Fort Mason coordinates come from docs/knowledge/03-demo-scenario.md.
BART station codes are the official abbreviations used by api.bart.gov.
"""

from __future__ import annotations

from conferge.travel.models import Place

SF_TIMEZONE = "America/Los_Angeles"

FORT_MASON = Place(
    id="venue-fort-mason", name="Fort Mason Center", kind="venue",
    latitude=37.8060, longitude=-122.4320, source_url="https://fortmason.org/",
)
SFO = Place(
    id="airport-sfo", name="San Francisco International Airport", kind="airport",
    latitude=37.6213, longitude=-122.3790, iata="SFO", bart_station="SFIA",
)
OAK = Place(
    id="airport-oak", name="Oakland International Airport", kind="airport",
    latitude=37.7126, longitude=-122.2197, iata="OAK", bart_station="OAKL",
)
SJC = Place(
    id="airport-sjc", name="San Jose Mineta International Airport", kind="airport",
    latitude=37.3639, longitude=-121.9289, iata="SJC",
)
EMBARCADERO = Place(
    id="station-bart-embr", name="Embarcadero BART", kind="station",
    latitude=37.7929, longitude=-122.3975, bart_station="EMBR",
)

AIRPORTS: dict[str, Place] = {p.iata: p for p in (SFO, OAK, SJC) if p.iata}
