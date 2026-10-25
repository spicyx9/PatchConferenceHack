# Judge demo: three minutes

## Start

```bash
make up
make install
uv run python scripts/run_demo.py --travel fixture
```

Open `http://127.0.0.1:8000`; keep FalkorDB Browser at `http://localhost:3000` in a second tab. The fixture travel mode is deterministic and makes no live network request.

## Walkthrough

1. **Set the goal.** On **Discover**, enter “Meet seed investors, AI-agent founders, and Copilot PMs.” Show the weighted priorities.
2. **Rank people.** Under **People to connect with**, show Ryan Hecht and click **View connection**. Expand **Why this suggestion? View the sources**.
3. **Inspect the evidence path.** Point out Goal → Topic ← Event ← Person, the evidence on each edge, and **Engine: FalkorDB**. Use **Copy query**, then run that query against `conferge_demo` in FalkorDB Browser.
4. **Show the plan.** Open the agenda/map and **Outside your agenda** to explain conflict-aware inclusion and exclusion.
5. **Replan.** Open **My summary**, choose **Explore a sold-out scenario**, and show the removed event, replacement, reason, and retained items. State that the sold-out condition is simulated.
6. **Record memory.** Click **I met Ryan Hecht**, optionally add a note, then **Save conversation**. Return to **Discover**: Ryan leaves the next-contact ranking and the meeting remains in FalkorDB.
7. **Show acquisition evidence.** Open **Sources and how it works**. Point to cached Bright Data counts, timestamps, source modes, and the 21-site reachability experiment.

## Honest narration

Say: “These travel and enrichment records were collected through Bright Data on October 24 and replayed from a timestamped cache. FalkorDB performs the relationship traversals and stores meeting memory. Python makes the final schedule and replan.”

Do not call cached observations live, a quote bookable, a LinkedIn profile proof of attendance, or the sold-out simulation a real event change.

If the UI is unavailable, use the [backup video](../submission/demo-backup.mp4) and [captured screenshots](../demo/screens/0-overview.png). If FalkorDB Browser fails, keep the UI path and copied Cypher on screen and state that the browser view is unavailable.
