from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from conferge.core.schemas import DiscoveryQuery, DiscoveryResult, SourceRecord, SourceRef
from conferge.lodging import LodgingService, LodgingSource, run
from conferge.lodging._common import report
from conferge.lodging.models import LodgingQuery

T0 = datetime(2026, 10, 24, 17, 0, tzinfo=timezone.utc)
Q = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), verify_top=2)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _booking_record(i: int, total: int, lat: float, lng: float, name: str) -> SourceRecord:
    url = (f"https://www.booking.com/hotel/us/fictional-{i}.html?checkin=2026-10-27"
           "&checkout=2026-10-30&group_adults=1&no_rooms=1&selected_currency=USD")
    row = {"id": str(i), "title": name, "final_price": total, "currency": "USD",
           "check_in": "2026-10-27T00:00:00.000Z", "check_out": "2026-10-30T00:00:00.000Z",
           "adults": 1, "map_coordinates": {"lat": lat, "lon": lng}, "url": url}
    return SourceRecord(provider="booking", source_id=str(i), source_mode="live",
                        collected_at=T0, source_url=url,
                        payload={"search": row, "detail": None, "detail_collected_at": None})


def _google_record(i: int, total: str, lat: float, lng: float, name: str) -> SourceRecord:
    url = f"https://www.google.com/travel/hotels/entity/fictional-{i}"
    row = {"hotel_id": f"g{i}", "hotel_name": name, "lat": lat, "long": lng, "currency": "USD",
           "check_in_date": "2026-10-27", "check_out_date": "2026-10-30", "guest_number": 1,
           "booking_options": [{"source": "Fictional OTA", "total_price": total}], "url": url}
    return SourceRecord(provider="google_hotels", source_id=f"g{i}", source_mode="live",
                        collected_at=T0, source_url=url, payload={"search": row})


class FakeSource:
    def __init__(self, name: str, records: list[SourceRecord], *, fail: bool = False,
                 verify_status: str = "ok") -> None:
        self.name, self.records, self.fail, self.verify_status = name, records, fail, verify_status
        self.search_calls = self.verify_calls = 0
        self.closed = False

    async def search(self, q: LodgingQuery) -> DiscoveryResult:
        self.search_calls += 1
        if self.fail:
            raise RuntimeError("provider exploded")
        rep = report(self.name, T0, status="ok", termination="exhausted",
                     fetched=len(self.records), unique=len(self.records), pages=1)
        return DiscoveryResult(items=list(self.records), run_report=rep)

    async def verify(self, records, q):
        self.verify_calls += 1
        status = self.verify_status
        rep = report(f"{self.name}:verify", T0, status=status,
                     termination="exhausted" if status == "ok" else "error",
                     fetched=len(records), unique=len(records),
                     errors=[] if status == "ok" else ["missing_credentials: test"])
        return records, rep

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        return self.records[0]

    async def aclose(self) -> None:
        self.closed = True


def _sources(**kw):
    booking = FakeSource("booking", [
        _booking_record(1, 900, 37.8030, -122.4375, "The Fictional Marina Hotel"),
        _booking_record(2, 1500, 37.7700, -122.4100, "Fictional Far Away Hotel"),
    ], **kw.get("booking", {}))
    google = FakeSource("google_hotels", [
        _google_record(1, "$880 total", 37.8031, -122.4374, "Fictional Marina Hotel"),
    ], **kw.get("google", {}))
    return {"booking": booking, "google_hotels": google}


async def test_search_normalizes_ranks_dedupes_and_measures():
    svc = LodgingService(_sources(), clock=Clock())
    res = await svc.search(Q)
    env = res.envelope
    assert env.status == "ok" and env.source_mode == "live"
    assert [s.price_status for s in env.items] == ["quoted_total"] * 3
    assert env.items[0].distance_to_venue_m < env.items[-1].distance_to_venue_m
    assert len(res.groups) == 1 and set(res.groups[0].member_ids) == {"booking:1",
                                                                      "google_hotels:g1"}
    assert res.distances["booking:1"][0]["walk_minutes_estimate"] is not None
    assert all(s.evidence[0].collected_at == T0 for s in env.items)


async def test_one_failing_provider_degrades_without_hiding_others():
    svc = LodgingService(_sources(google={"fail": True}), clock=Clock())
    env = (await svc.search(Q)).envelope
    assert env.status == "degraded"
    assert {s.provider for s in env.items} == {"booking"}
    assert any("provider exploded" in e for e in env.errors)


async def test_all_failing_is_failed_and_empty():
    svc = LodgingService(_sources(google={"fail": True}, booking={"fail": True}), clock=Clock())
    env = (await svc.search(Q)).envelope
    assert env.status == "failed" and env.items == []


async def test_failed_verification_degrades_status():
    svc = LodgingService(_sources(booking={"verify_status": "failed"}), clock=Clock())
    env = (await svc.search(Q)).envelope
    assert env.status == "degraded"
    assert any("missing_credentials" in e for e in env.errors)


async def test_cache_serves_cached_label_then_expires():
    clock = Clock()
    sources = _sources()
    svc = LodgingService(sources, clock=clock)
    await svc.search(Q)
    clock.now = T0 + timedelta(minutes=10)
    again = (await svc.search(Q)).envelope
    assert sources["booking"].search_calls == 1 and sources["booking"].verify_calls == 1
    assert again.source_mode == "cached"
    assert all(s.evidence[0].source_mode == "cached" for s in again.items)
    clock.now = T0 + timedelta(minutes=45)  # verification expired, discovery still cached
    await svc.search(Q)
    assert sources["booking"].search_calls == 1 and sources["booking"].verify_calls == 2
    clock.now = T0 + timedelta(hours=7)
    await svc.search(Q)
    assert sources["booking"].search_calls == 2


async def test_run_accepts_dict_query_and_closes_nothing_it_does_not_own():
    sources = _sources()
    svc = LodgingService(sources, clock=Clock())
    env = await run({"check_in": "2026-10-27", "check_out": "2026-10-30", "adults": 1,
                     "lat": 37.806, "lon": -122.432, "venues": [
                         {"name": "Fictional party", "lat": 37.79, "lng": -122.40}]},
                    service=svc)
    assert len(env.items) == 3 and not sources["booking"].closed


async def test_aggregate_source_contract():
    sources = _sources(google={"fail": True})
    src = LodgingSource(sources)
    res = await src.discover(DiscoveryQuery(domain="lodging", start_date=date(2026, 10, 27),
                                            end_date=date(2026, 10, 30)))
    assert len(res.items) == 2 and res.run_report.status == "degraded"
    assert res.run_report.termination == "error"
    bad = await src.discover(DiscoveryQuery(domain="lodging"))
    assert bad.run_report.status == "failed" and not bad.items
    rec = await src.fetch_details(SourceRef(provider="booking", source_id="1"))
    assert rec.source_id == "1"
    await src.aclose()
    assert sources["booking"].closed
