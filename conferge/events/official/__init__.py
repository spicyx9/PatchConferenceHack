"""Window 03: official GitHub Universe 2026 program (RainFocus) plus a generic Sessionize adapter."""

from conferge.events.official.normalize import CONFERENCE_ID, OfficialCatalog, normalize_catalog
from conferge.events.official.source import (
    OfficialCollection,
    OfficialConferenceSource,
    load_fixture,
    run,
)

__all__ = [
    "CONFERENCE_ID",
    "OfficialCatalog",
    "OfficialCollection",
    "OfficialConferenceSource",
    "load_fixture",
    "normalize_catalog",
    "run",
]
