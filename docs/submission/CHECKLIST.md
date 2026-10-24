# Ten minutes before the stage

One laptop, wifi optional, charger plugged in. Tick in order. If a line fails twice, go to the backup line at the bottom.

## 10:00 to go, services

- [ ] Docker running. `make up`. Then `docker ps` shows two containers: `falkordb/falkordb:6.0.3` with ports 6379 (or 6380, see below) and 3000, and `falkordb/falkordb-browser:v2.6.2`. If the Browser container is missing, the compose file is old: the Browser bundled in the 6.0.3 image fails every query.
- [ ] FalkorDB answers: `redis-cli -p 6379 GRAPH.LIST` returns a list (empty is fine). If a local Redis holds 6379, put `FALKORDB_PORT=6380` in `.env` (the rehearsal laptop has it) and use `-p 6380` in every command below.
- [ ] `FALKORDB_PORT=6380 make predemo` in a terminal you keep visible. It starts the demo on a reset graph from the dated Bright Data cache (no Bright Data call at startup) and must end with every line OK, including agenda items, sold-out event and replacement compared with `STATUS.md`. Do not use `--travel live` on stage.
- [ ] `curl -s http://127.0.0.1:8000/api/v1/plan | head -c 300` returns JSON with `"data_source"` and `"collected_at"`.
- [ ] `redis-cli -p 6380 GRAPH.RO_QUERY conferge_demo "MATCH (n) RETURN count(n)"` says 691 and `"MATCH ()-[r]->() RETURN count(r)"` says 2213, the numbers in `STATUS.md` and on slide 6. If not, do not say the old ones.

## 7:00 to go, reset and tabs

- [ ] `curl -s -X POST http://127.0.0.1:8000/api/v1/reset` so no meeting or simulation from rehearsal remains. Or, in the app: **Replan** (header) then **Reset session**, confirm **Reset session**.
- [ ] Browser tab 1: http://127.0.0.1:8000, **Discover** tab, scrolled to the top. In the right column, **Your priorities** shows the goal sentence and three chips (45 %, 35 %, 20 %). The first card under **People to connect with** is Ryan Hecht. **Outside your agenda** shows the count 4. In the footer, **View your progress**: **Meetings recorded** reads 0 and the button under **Your latest meeting** reads **I met Ryan Hecht**; click **Discover** to come back.
- [ ] Click the round info button in the header: **Sources and how it works** says **Data provenance: Sample data, cached travel** and **Last collected** today. Close it.
- [ ] Click **View connection** on the first card once, open **Why this suggestion? View the sources** (the path and **Engine: FalkorDB** must show) and **Explore the relationship map** then **Planning details** once, so everything is loaded. Fold them back and click **Discover**.
- [ ] Browser tab 2, FalkorDB Browser: http://127.0.0.1:3000 opens on a login form. Keep the defaults (localhost, 6379, no user), **Log in**, then **Skip Tutorial**. The header must read Browser v2.6.2 (served by `make up`). Select graph `conferge_demo` (Select Graph, left panel). Paste the path query from `PITCH.md` with the real person id, run it once with the blue **Run** arrow, not ctrl+Enter (the editor autocompletes and corrupts the query): 4 nodes, 3 edges, layout stable. The Graph Info panel on the right reads NODES 691, EDGES 2213, the same numbers as slide 6. If the Browser answers "An unexpected error occurred", close the tab and use plan B, the **Connections** tab of the app.
- [ ] Browser tab 3: `docs/submission/slides.html` on slide 1, full screen (press F or the browser's full screen), arrow keys tested.
- [ ] Tab order left to right: slides, Conferge, FalkorDB Browser. The Driver knows the shortcut to move between tabs.

## 4:00 to go, backup

- [ ] `docs/submission/demo-backup.mp4` (35 s) opens in QuickTime, paused on the first frame, window ready behind the browser.
- [ ] Slide 3 shows the goal to person path, in case the Browser and the Connections tab both fail.

## 2:00 to go, machine

- [ ] Do not disturb on. Notifications off. Screen never sleeps for the next 15 minutes.
- [ ] Display mirrored to the projector, resolution checked on slide 1 (text fits, nothing cut).
- [ ] Browser zoom at 100 percent on the Conferge tab. Font large enough from the back of the room, zoom to 125 percent if not. At 125 percent the right column (priorities, counters) must still be visible next to the cards.
- [ ] Mic check with the first sentence of the hook.

## 0:30 to go

- [ ] Speaker has `PITCH.md` open on the phone for the timings only. The sentences are known by heart.
- [ ] Driver has the mouse on the slides tab, slide 1.

## If a line fails twice

- FalkorDB not up: `make demo` stops with one line (`nothing answers on 127.0.0.1:6379`, or `port 6379 is a plain Redis`). `make demo DEMO_ARGS=--no-graph` still serves: the right column of **Discover** shows the grey line **Graph unavailable · fallback ranking active.** and **Planning details** on Connections reads **Engine: fallback mode** (verified on `e6c08e4`, capture `docs/demo/screens/8-degraded-no-graph.png` shows the page, the line sits below the priorities). Do not demo in that mode. Restart Docker once; if it fails again, run the backup video and show the path on slide 3.
- API not up: backup video for the whole demo, slides for the numbers.
- Projector refuses the laptop: the video and the slides are on the phone too, sent before leaving for the venue.
