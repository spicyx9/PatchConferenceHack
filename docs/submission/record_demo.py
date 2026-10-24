"""Record the backup video of the demo and regenerate docs/demo/screens on the UI served by main.

Run, with `make demo` on http://127.0.0.1:8000 (FalkorDB up):

    uv run --no-project --with playwright python docs/submission/record_demo.py docs/submission/demo-backup.webm
    ffmpeg -y -i docs/submission/demo-backup.webm -c:v libx264 -crf 23 -pix_fmt yuv420p docs/submission/demo-backup.mp4

Environment: CONFERGE_URL (default http://127.0.0.1:8000), CONFERGE_SCREENS (default docs/demo/screens, empty
string to skip the PNGs), CONFERGE_NOGRAPH_URL (a `make demo DEMO_ARGS=--no-graph` server, for 8-degraded-no-graph.png).

The six recorded steps are the ones the stage script names, in order: priorities, people to connect with,
agenda and map, anti-FOMO, sold-out scenario, meeting saved. The session is reset before and after.
"""

import os
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
BASE = os.environ.get("CONFERGE_URL", "http://127.0.0.1:8000")
SCREENS = os.environ.get("CONFERGE_SCREENS", "docs/demo/screens")
NOGRAPH = os.environ.get("CONFERGE_NOGRAPH_URL", "")
PAUSE = 2000
VIEWPORT = {"width": 1280, "height": 720}
tmp = OUT.parent / "_video_tmp"
log = []


def shot(page, name):
    if SCREENS:
        Path(SCREENS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SCREENS) / f"{name}.png"))


def step(page, sel, label, screen=None):
    page.locator(sel).first.scroll_into_view_if_needed()
    page.evaluate("s => document.querySelector(s).scrollIntoView({behavior:'smooth', block:'start'})", sel)
    page.wait_for_timeout(PAUSE)
    if screen:
        shot(page, screen)
    log.append(f"ok {label}")


def wait_loaded(page):
    page.goto(BASE + "/#story", wait_until="networkidle")
    page.wait_for_selector("#story-goals .chip", timeout=20000)
    page.wait_for_selector("#story-opps button[data-action=showpath]", timeout=20000)
    page.wait_for_selector("#story-antifomo > *", timeout=20000)
    page.wait_for_timeout(PAUSE)


with sync_playwright() as p:
    b = p.chromium.launch()
    req = p.request.new_context()
    req.post(BASE + "/api/v1/reset", data={})
    ctx = b.new_context(viewport=VIEWPORT, record_video_dir=str(tmp), record_video_size=VIEWPORT)
    page = ctx.new_page()
    try:
        wait_loaded(page)
        shot(page, "0-overview")
        # 1. Priorities: the sidebar box, then the dialog and its "Update your agenda" button.
        step(page, "#step-goal", "1 priorities", "1-goal")
        page.click("#step-goal button.goal-adjust")
        page.wait_for_selector("#goal-dialog[open]", timeout=5000)
        page.wait_for_timeout(1500)
        page.click("#btn-goal")
        page.wait_for_function("!document.getElementById('goal-dialog').open", timeout=15000)
        page.wait_for_timeout(800)
        # 2. People to connect with, then "See why": the goal-to-person path on the Connections tab.
        step(page, "#step-opps", "2 people", "2-opps")
        page.click("#story-opps button[data-action=showpath]")
        page.wait_for_selector("#graph[data-layout-ready=true]", timeout=20000)
        page.wait_for_selector("#graph-detail .path, #graph-detail b", timeout=20000)
        page.evaluate("document.getElementById('graph').scrollIntoView({block:'start'})")
        page.wait_for_selector("#toast.hidden", state="attached", timeout=10000)
        page.wait_for_timeout(PAUSE)
        shot(page, "7-connections-path")
        page.click("a[data-tab=story]")
        page.wait_for_timeout(800)
        # 3 and 4. Agenda with the map, anti-FOMO.
        step(page, "#step-plan", "3 agenda", "3-plan")
        step(page, "#step-antifomo", "4 antifomo", "4-antifomo")
        # 5. Sold-out scenario.
        page.locator("#step-change").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        page.click("#story-simulate")
        page.wait_for_selector("#story-diff .diff-row", timeout=20000)
        step(page, "#step-change", "5 sold-out scenario", "5-change")
        # 6. I met <name>, then Save conversation in the dialog.
        page.locator("#step-met").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        page.click("#story-met button[data-action=met]")
        page.wait_for_selector("#meeting-dialog[open]", timeout=5000)
        page.wait_for_timeout(1200)
        page.click("#btn-met-save")
        page.wait_for_function("document.getElementById('roi-meetings').textContent.trim() === '1'", timeout=20000)
        step(page, "#step-met", "6 meeting saved", "6-met")
        page.wait_for_timeout(PAUSE)
    except Exception as e:
        log.append(f"FAILED after {log[-1] if log else 'start'}: {e}")
    finally:
        video = page.video
        ctx.close()
        shutil.move(video.path(), OUT)
        shutil.rmtree(tmp, ignore_errors=True)
        req.post(BASE + "/api/v1/reset", data={})

    # Screens outside the video: sources dialog (Bright Data counter, data pipeline) and the no-graph server.
    if SCREENS:
        try:
            ctx = b.new_context(viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            wait_loaded(page)
            page.click("header button[data-open=sources-dialog]")
            page.wait_for_selector("#sources-dialog[open]", timeout=5000)
            page.wait_for_selector("#bd-counter *", timeout=15000)
            page.wait_for_timeout(1000)
            shot(page, "9-home-brightdata-counter")
            page.locator("#pipeline-table").scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            shot(page, "10-data-pipeline")
            ctx.close()
            log.append("ok screens sources dialog")
            if NOGRAPH:
                ctx = b.new_context(viewport={"width": 1280, "height": 900})
                page = ctx.new_page()
                page.goto(NOGRAPH + "/#story", wait_until="networkidle")
                page.wait_for_selector("#story-goals .chip", timeout=20000)
                page.wait_for_timeout(PAUSE)
                shot(page, "8-degraded-no-graph")
                ctx.close()
                log.append("ok screen no-graph")
        except Exception as e:
            log.append(f"SCREENS FAILED: {e}")
    b.close()
print("\n".join(log))
