from __future__ import annotations

from collections.abc import Iterator

import pytest
from _resilience import BD_ENV, FakeBrightData


@pytest.fixture
def no_brightdata_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in BD_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def bd_429() -> Iterator[FakeBrightData]:
    server = FakeBrightData("429")
    yield server
    server.close()


@pytest.fixture
def bd_slow() -> Iterator[FakeBrightData]:
    server = FakeBrightData("slow")
    yield server
    server.close()
