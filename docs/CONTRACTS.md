# Shared contracts — v0.2 (frozen after window 0)

The source of truth is `conferge/core/schemas.py` + `contracts.py`. Schema v0.2 has backwards-compatible optional fields for roles/topics, event registration capacity, lodging fees, flight baggage, and opportunity paths. These classes, field names, and async signatures are **not** edited by workstreams.

## Source interface

```python
class Source(Protocol):
    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult: ...
    async def fetch_details(self, ref: SourceRef) -> SourceRecord: ...
```

`DiscoveryResult.items` contains raw `SourceRecord` objects with provider IDs and payload preserved. `run_report` must state `status`, `termination`, `pages`, counts, warnings and source mode. Normalization to `Event`, `Person`, `Lodging`, `FlightOffer` is owned by each domain adapter. A public SERP hit is a **candidate URL**, not a confirmed event.

`DataEnvelope[T]` is the standard normalized list shape: `items`, `source_mode`, `status`, `collected_at`, `reports`, `errors`. Missing record properties use `None`, never fictional defaults.

## Agent interface

```python
class Agent(Protocol):
    async def run(self, ctx: AgentContext) -> AgentResult: ...
```

`AgentContext` contains known conference, goals, normalized events/people/opportunities and user budget. `AgentResult` includes opportunities, decisions, explanations, status and source mode.

## Data rules

- Clock times are timezone-aware; keep source timezone (IANA) where available and UTC instant. No naive time substitution.
- `SourceMode` is `live`, `cached` or `fixture` (a mixed list uses envelope mode `mixed`). `fixture` may never be used as a live claim.
- `RunReport.status == ok` is allowed only for `exhausted` or `not_applicable`; a partially paginated run is `degraded` or `failed`.
- Events need evidence to claim `official` or `confirmed_side_event` relation to the anchor conference. Nearby in time and location is only `candidate`.
- `FlightOffer.total_price` is a *decimal string*, `collected_at` is required, and metasearch output is `observed_live`, not a confirmed airline offer.
- `Lodging.price_status=verified_bookable` needs an exact-stay verified availability, full total and source URL; unknown charges remain unknown.
- Person `confirmed_speaker` is not attendance evidence outside that speaking session; public guest information must respect source access controls.
- Graph nodes are always canonical stable IDs; graph writes go via `GraphStore.merge_node` and `.merge_edge` only.
- Data stored under `raw/` is ignored by Git, contains no tokens, and may be represented via `SourceRecord.raw_ref` when archived.

## Probe contract

`make probe-<name>` loads `scripts/probes/<name>.py`, each owned by its window and writing `probes/<name>.md`. Include source, collected_at, raw/unique counts, status/termination, whether fixture or live, source references and errors. No probe exists in window 0; feature windows implement them.
