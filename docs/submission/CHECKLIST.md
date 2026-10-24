# Ten minutes before the stage

One laptop, wifi optional, charger plugged in. Tick in order. If a line fails twice, go to the backup line at the bottom.

## 10:00 to go, services

- [ ] Docker running. `make up`. Then `docker ps` shows `falkordb/falkordb:6.0.3` with ports 6379 and 3000.
- [ ] FalkorDB answers: `redis-cli -p 6379 GRAPH.LIST` returns a list (empty is fine). If a local Redis holds 6379, use `FALKORDB_PORT=6380` for every command below.
- [ ] `make demo` in a terminal you keep visible. Wait for the line that says the API is on http://127.0.0.1:8000 and that the graph is loaded. About one second for the load.
- [ ] `curl -s http://127.0.0.1:8000/api/v1/plan | head -c 300` returns JSON with `"data_mode"` and `"collected_at"`.

## 7:00 to go, reset and tabs

- [ ] `curl -s -X POST http://127.0.0.1:8000/api/v1/reset` so no meeting or simulation from rehearsal remains.
- [ ] Browser tab 1: http://127.0.0.1:8000, **Demo** tab, scrolled to the top. The goal text is in the box. Header badge reads `fixture` (or `live` only if the live run worked at rehearsal), collection date shown.
- [ ] Browser tab 2: http://127.0.0.1:3000, graph `conferge_demo` selected, the path query from `PITCH.md` pasted with the real person id, run once so the result is cached and the layout is stable.
- [ ] Browser tab 3: `docs/submission/slides.html` on slide 1, full screen (press F or the browser's full screen), arrow keys tested.
- [ ] Tab order left to right: slides, Conferge, FalkorDB Browser. The Driver knows the shortcut to move between tabs.

## 4:00 to go, backup

- [ ] `docs/submission/demo-backup.mp4` opens in QuickTime, paused on the first frame, window ready behind the browser.
- [ ] Slide 3 shows the goal to person path, in case the FalkorDB Browser tab fails.

## 2:00 to go, machine

- [ ] Do not disturb on. Notifications off. Screen never sleeps for the next 15 minutes.
- [ ] Display mirrored to the projector, resolution checked on slide 1 (text fits, nothing cut).
- [ ] Browser zoom at 100 percent on the Conferge tab. Font large enough from the back of the room, zoom to 125 percent if not.
- [ ] Mic check with the first sentence of the hook.

## 0:30 to go

- [ ] Speaker has `PITCH.md` open on the phone for the timings only. The sentences are known by heart.
- [ ] Driver has the mouse on the slides tab, slide 1.

## If a line fails twice

- FalkorDB not up: `make demo` still serves, with a red banner "mode degrade". Do not demo in that mode. Restart Docker once; if it fails again, run the backup video and show the path on slide 3.
- API not up: backup video for the whole demo, slides for the numbers.
- Projector refuses the laptop: the video and the slides are on the phone too, sent before leaving for the venue.
