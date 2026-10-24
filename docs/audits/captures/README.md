# Bright Data audit gaps: captures

Local, `make demo` on FalkorDB port 6380, 2026-10-24. "before" = `origin/main` at `ad0671f` on http://127.0.0.1:8021; "after" = branch `fix/brightdata-gaps` (on top of `bb6951e`) on http://127.0.0.1:8024.

| File | What it shows |
|---|---|
| `bdgaps-panel-before.jpg` | Sources dialog: "Records collected through Bright Data: 70", collection range ending at the demo start time (02:06 PM) |
| `bdgaps-pipeline-before.jpg` | Data pipeline table with an "Est. cost" column |
| `bdgaps-flight-before.jpg` | Flight card: "Unknown source", 773 USD round trip total shown as a price, status `quoted_total` |
| `bdgaps-panel-after.jpg` | Sources dialog: requests and records per product, records' own collection time, no USD |
| `bdgaps-pipeline-after.jpg` | Data pipeline table without a cost column |
| `bdgaps-flight-after.jpg` | Flight card: "Cached · 11:18 AM", "773 USD (round trip total), return not collected", status `quoted_total` as stored in FalkorDB (PR 46) |
| `bdgaps-stay-after.jpg` | Stay card: "Cached · 11:41 AM", "Bright Data · dataset · Booking", collection time in the details |
