# Ten minutes before the stage

One laptop, wifi optional, charger plugged in. Tick in order. If a line fails twice, go to the backup line at the bottom.

## 10:00 to go, services

- [ ] Docker running. `make up`. Then `docker ps` shows `falkordb/falkordb:6.0.3` with ports 6379 (or 6380, see below) and 3000.
- [ ] FalkorDB answers: `redis-cli -p 6379 GRAPH.LIST` returns a list (empty is fine). If a local Redis holds 6379, put `FALKORDB_PORT=6380` in `.env` (the rehearsal laptop has it) and use `-p 6380` in every command below.
- [ ] `make demo` in a terminal you keep visible. Wait for the three lines `assembled data_mode=fixture: 207 events, 183 people, 10 opportunities`, `graph conferge_demo: 701 node writes, 2199 edge writes, 0 skipped` and `indexes: 14 labels, status ['OPERATIONAL']`. Measured: 3.3 s from the command to the first API answer with cached travel, 14.6 s with `DEMO_ARGS="--travel live"`. Do not use `--travel live` on stage.
- [ ] `curl -s http://127.0.0.1:8000/api/v1/plan | head -c 300` returns JSON with `"data_source"` and `"collected_at"`.
- [ ] `redis-cli -p 6379 GRAPH.QUERY conferge_demo "MATCH (n) RETURN count(n)"` says 711 and `"MATCH ()-[r]->() RETURN count(r)"` says 2238, the numbers on slide 6. If not, update slide 6 and `PITCH.md` to what you read, do not say the old ones.

## 7:00 to go, reset and tabs

- [ ] `curl -s -X POST http://127.0.0.1:8000/api/v1/reset` so no meeting or simulation from rehearsal remains. Or, in the app: **Replan** (header) then **Reset session**, confirm **Reset session**.
- [ ] Browser tab 1: http://127.0.0.1:8000, **Discover** tab, scrolled to the top. In the right column, **Your priorities** shows the goal sentence and three chips (45 %, 35 %, 20 %). The counters read 207 events, 32 on your agenda, 50 suggested connections, **0 conversations saved**. The button at **Keep the connection going** reads **I met Ryan Hecht**.
- [ ] Click the round info button in the header: **Sources and how it works** says **Data provenance: Mixed sources** and **Last collected** today. Close it.
- [ ] Click **See why** on the first card once, so the **Connections** tab has loaded (**Powered by: FalkorDB connected** top right). Open **How your planning agents coordinate** once, then click **Discover** to go back.
- [ ] Browser tab 2, FalkorDB Browser, plan A only: http://127.0.0.1:3000 shows a login form. Host `localhost`, port `6379` (the port inside the container, whatever the host port is), no password, **Log in**. Close the "FalkorDB Browser for macOS" popup. Select graph `conferge_demo`. Paste the path query from `PITCH.md` with the real person id, run it once with the Run button, not ctrl+Enter (the editor autocompletes and corrupts the query). If the Browser answers "An unexpected error occurred", close the tab: the stage uses plan B, the **Connections** tab of the app. Today, October 24, it fails on the rehearsal laptop.
- [ ] Browser tab 3: `docs/submission/slides.html` on slide 1, full screen (press F or the browser's full screen), arrow keys tested.
- [ ] Tab order left to right: slides, Conferge, FalkorDB Browser (if plan A). The Driver knows the shortcut to move between tabs.

## 4:00 to go, backup

- [ ] `docs/submission/demo-backup.mp4` (35 s) opens in QuickTime, paused on the first frame, window ready behind the browser.
- [ ] Slide 3 shows the goal to person path, in case the Connections tab fails.

## 2:00 to go, machine

- [ ] Do not disturb on. Notifications off. Screen never sleeps for the next 15 minutes.
- [ ] Display mirrored to the projector, resolution checked on slide 1 (text fits, nothing cut).
- [ ] Browser zoom at 100 percent on the Conferge tab. Font large enough from the back of the room, zoom to 125 percent if not. At 125 percent the right column (priorities, counters) must still be visible next to the cards.
- [ ] Mic check with the first sentence of the hook.

## 0:30 to go

- [ ] Speaker has `PITCH.md` open on the phone for the timings only. The sentences are known by heart.
- [ ] Driver has the mouse on the slides tab, slide 1.

## If a line fails twice

- FalkorDB not up: `make demo` stops with one line (`nothing answers on 127.0.0.1:6379`, or `port 6379 is a plain Redis`). `make demo DEMO_ARGS=--no-graph` still serves, but **the page looks the same, there is no banner**: the only signs are the missing `graph conferge_demo: ... node writes` line in the terminal and a Connections tab without evidence. Do not demo in that mode. Restart Docker once; if it fails again, run the backup video and show the path on slide 3.
- API not up: backup video for the whole demo, slides for the numbers.
- Projector refuses the laptop: the video and the slides are on the phone too, sent before leaving for the venue.
