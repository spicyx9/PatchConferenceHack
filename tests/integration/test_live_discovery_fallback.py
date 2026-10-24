"""w04 live discovery without a SERP zone: failed slice, no events, no network call."""

from __future__ import annotations

import asyncio

import pytest

from conferge.integration import sources


def test_live_discovery_without_serp_zone_is_a_visible_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from conferge.core import brightdata

    monkeypatch.setattr(brightdata.BrightDataClient, "from_env", classmethod(
        lambda cls: cls("key", serp_zone=None, unlocker_zone=None)))
    reset = brightdata.usage()["serp"]
    slice_ = asyncio.run(sources._live_discovery())
    assert slice_.status == "failed" and slice_.events == []
    assert slice_.errors == ["BRIGHTDATA_SERP_ZONE not configured"]
    assert brightdata.usage()["serp"] == reset  # nothing counted: nothing was collected
