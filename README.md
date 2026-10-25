# Conferge

**Turn a conference trip into measurable professional opportunities.**

Bright Data finds hard-to-access public information. FalkorDB connects the evidence. Conferge turns it into an explainable agenda, people to meet, and a plan that adapts.

![Conferge: goals, ranked people, agenda, and evidence](docs/demo/screens/0-overview.png)

## Built with Bright Data + FalkorDB

| Captured result | What it proves |
|---|---|
| **34** Google Flights outbound observations | Collected from a dynamic results page through Bright Data Web Unlocker; quoted totals are not verified bookings |
| **21** lodging records | 15 Booking + 6 Airbnb records from timestamped Bright Data dataset snapshots |
| **17** LinkedIn profiles | Public profiles cached from Bright Data enrichment; never treated as attendance proof |
| **690 nodes / 2,184 relationships** | Historical pre-plan FalkorDB demo measurement; the graph grows as plans and meetings are written |

The first three counts are recomputed from committed cache files by [`scripts/verify_judge_evidence.py`](scripts/verify_judge_evidence.py). The graph figure is a captured demo measurement in [`STATUS.md`](STATUS.md), with the exact live query in the verification guide.

## Explore the technical proof

- **[Bright Data — difficult-to-access data, provenance, and captured results](docs/judges/BRIGHT_DATA.md)**
- **[FalkorDB — explainable opportunity paths, ranking, memory, and replanning](docs/judges/FALKORDB.md)**
- **[Verify everything — claim-by-claim commands](docs/judges/VERIFY.md)**
- [Run the 3-minute demonstration](docs/judges/DEMO.md)

## The problem → the solution

A conference agenda tells you what is happening, not which sessions, people, and side events best serve your goals. Conferge turns one goal sentence into ranked connections with evidence paths, a conflict-aware itinerary, and a visible replan when conditions change.

```text
Public sources + Bright Data snapshots
                 │  provenance on every record
                 ▼
      connectors and normalization
                 ▼
     FalkorDB opportunity graph
      │ ranking │ paths │ memory
                 ▼
   planner / replanner → FastAPI → UI
```

Bright Data is the acquisition layer; FalkorDB is the relationship and memory layer. FalkorDB supplies graph-derived candidates, evidence, and impact. Deterministic Python code makes the final scheduling and replacement decisions.

## Try the working demo

```bash
make up
make install
uv run python scripts/run_demo.py --travel fixture
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The fixture command makes no live Bright Data request; committed, timestamped captures remain labelled `cached`. FalkorDB Browser is at [http://localhost:3000](http://localhost:3000).

Backup: [35-second demo video](docs/submission/demo-backup.mp4) · [presentation](docs/submission/slides.html)

## Team

**Axel Carron · Ilan Sainte Agathe**

Patch the Conference Hackathon — October 24, 2026

Conferge does not book travel, claim live availability, or infer conference attendance from a public profile. See the [verification and claim boundaries](docs/judges/VERIFY.md).
