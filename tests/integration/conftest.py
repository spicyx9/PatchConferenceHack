from __future__ import annotations

import socket

import pytest


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if anything in the offline path opens a socket."""

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("network access attempted in an offline integration test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
