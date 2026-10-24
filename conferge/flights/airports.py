"""City to airport expansion and IATA to IANA timezone lookup.

The `airportsdata` package is not a project dependency (pyproject is owned by
window 0), so a small static table covers the demo cities. Unknown airports
return None: callers must keep the time unknown rather than guess a zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

# IATA -> IANA timezone. Facts only; extend when a new city is needed.
AIRPORT_TZ: dict[str, str] = {
    # New York area
    "JFK": "America/New_York", "LGA": "America/New_York", "EWR": "America/New_York",
    # San Francisco Bay Area
    "SFO": "America/Los_Angeles", "OAK": "America/Los_Angeles", "SJC": "America/Los_Angeles",
    # Other US
    "BOS": "America/New_York", "IAD": "America/New_York", "DCA": "America/New_York",
    "BWI": "America/New_York", "PHL": "America/New_York", "ATL": "America/New_York",
    "MIA": "America/New_York", "FLL": "America/New_York", "MCO": "America/New_York",
    "CLT": "America/New_York", "DTW": "America/Detroit", "ORD": "America/Chicago",
    "MDW": "America/Chicago", "DFW": "America/Chicago", "DAL": "America/Chicago",
    "IAH": "America/Chicago", "HOU": "America/Chicago", "AUS": "America/Chicago",
    "MSP": "America/Chicago", "DEN": "America/Denver", "SLC": "America/Denver",
    "PHX": "America/Phoenix", "LAS": "America/Los_Angeles", "LAX": "America/Los_Angeles",
    "BUR": "America/Los_Angeles", "SAN": "America/Los_Angeles", "SEA": "America/Los_Angeles",
    "PDX": "America/Los_Angeles", "SMF": "America/Los_Angeles", "HNL": "Pacific/Honolulu",
    "YYZ": "America/Toronto", "YVR": "America/Vancouver",
    # US connection hubs seen in live NYC-SF results (probe 2026-10-24) and peers
    "RDU": "America/New_York", "CMH": "America/New_York", "CLE": "America/New_York",
    "PIT": "America/New_York", "CVG": "America/New_York", "TPA": "America/New_York",
    "JAX": "America/New_York", "RSW": "America/New_York", "BDL": "America/New_York",
    "PVD": "America/New_York", "RIC": "America/New_York", "ORF": "America/New_York",
    "BUF": "America/New_York", "ALB": "America/New_York", "SYR": "America/New_York",
    "IND": "America/Indiana/Indianapolis", "MSY": "America/Chicago",
    "BNA": "America/Chicago", "STL": "America/Chicago", "MCI": "America/Chicago",
    "MKE": "America/Chicago", "SAT": "America/Chicago", "OMA": "America/Chicago",
    "ABQ": "America/Denver", "BOI": "America/Boise", "ONT": "America/Los_Angeles",
    "SNA": "America/Los_Angeles", "LGB": "America/Los_Angeles", "RNO": "America/Los_Angeles",
    "OGG": "Pacific/Honolulu", "ANC": "America/Anchorage", "SJU": "America/Puerto_Rico",
    "YUL": "America/Toronto", "YYC": "America/Edmonton", "MEX": "America/Mexico_City",
    # Europe
    "LHR": "Europe/London", "LGW": "Europe/London", "STN": "Europe/London",
    "CDG": "Europe/Paris", "ORY": "Europe/Paris", "AMS": "Europe/Amsterdam",
    "FRA": "Europe/Berlin", "MUC": "Europe/Berlin", "BER": "Europe/Berlin",
    "MAD": "Europe/Madrid", "BCN": "Europe/Madrid", "LIS": "Europe/Lisbon",
    "DUB": "Europe/Dublin", "ZRH": "Europe/Zurich", "FCO": "Europe/Rome",
    "MXP": "Europe/Rome", "CPH": "Europe/Copenhagen", "ARN": "Europe/Stockholm",
}


@dataclass(frozen=True)
class CityAirports:
    """Primary airports are searched by default; secondary only on request."""

    primary: tuple[str, ...]
    secondary: tuple[str, ...] = ()


# Decision: SJC is about 75 minutes from Fort Mason by road, so it is secondary
# for San Francisco and only searched with include_secondary=True.
CITY_AIRPORTS: dict[str, CityAirports] = {
    "new york": CityAirports(("JFK", "LGA", "EWR")),
    "san francisco": CityAirports(("SFO", "OAK"), ("SJC",)),
    "boston": CityAirports(("BOS",)),
    "washington": CityAirports(("DCA", "IAD"), ("BWI",)),
    "philadelphia": CityAirports(("PHL",)),
    "atlanta": CityAirports(("ATL",)),
    "miami": CityAirports(("MIA",), ("FLL",)),
    "chicago": CityAirports(("ORD", "MDW")),
    "dallas": CityAirports(("DFW", "DAL")),
    "houston": CityAirports(("IAH", "HOU")),
    "austin": CityAirports(("AUS",)),
    "denver": CityAirports(("DEN",)),
    "seattle": CityAirports(("SEA",)),
    "los angeles": CityAirports(("LAX",), ("BUR",)),
    "san diego": CityAirports(("SAN",)),
    "las vegas": CityAirports(("LAS",)),
    "toronto": CityAirports(("YYZ",)),
    "london": CityAirports(("LHR", "LGW"), ("STN",)),
    "paris": CityAirports(("CDG", "ORY")),
    "amsterdam": CityAirports(("AMS",)),
    "berlin": CityAirports(("BER",)),
    "madrid": CityAirports(("MAD",)),
    "lisbon": CityAirports(("LIS",)),
    "dublin": CityAirports(("DUB",)),
}

_ALIASES = {"nyc": "new york", "sf": "san francisco", "bay area": "san francisco",
            "la": "los angeles", "dc": "washington"}


def airports_for(city_or_iata: str, *, include_secondary: bool = False) -> list[str]:
    """Return IATA codes for a city name or a single IATA code."""
    value = city_or_iata.strip()
    if len(value) == 3 and value.isalpha() and value.upper() in AIRPORT_TZ:
        return [value.upper()]
    key = value.lower().split(",")[0].strip()
    key = _ALIASES.get(key, key)
    city = CITY_AIRPORTS.get(key)
    if city is None:
        raise KeyError(f"unknown city or airport: {city_or_iata!r}")
    return list(city.primary + (city.secondary if include_secondary else ()))


def airport_pairs(
    origin: str, destination: str, *, include_secondary: bool = False
) -> list[tuple[str, str]]:
    return [
        (o, d)
        for o in airports_for(origin, include_secondary=include_secondary)
        for d in airports_for(destination, include_secondary=include_secondary)
        if o != d
    ]


def timezone_for(iata: str | None) -> ZoneInfo | None:
    if not iata:
        return None
    name = AIRPORT_TZ.get(iata.upper())
    return ZoneInfo(name) if name else None
