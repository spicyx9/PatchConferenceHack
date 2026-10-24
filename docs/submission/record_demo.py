"""Record the 6-step demo backup video. Run: uv run --no-project --with playwright python docs/submission/record_demo.py docs/submission/demo-backup.webm"""
import os
import shutil
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
BASE = os.environ.get("CONFERGE_URL", "http://127.0.0.1:8000")
PAUSE = 2000
tmp = OUT.parent / "_video_tmp"
log = []

def step(page, sel, label):
    page.locator(sel).scroll_into_view_if_needed()
    page.evaluate("s => document.querySelector(s).scrollIntoView({behavior:'smooth', block:'start'})", sel)
    page.wait_for_timeout(PAUSE)
    log.append(f"ok {label}")

with sync_playwright() as p:
    b = p.chromium.launch()
    req = p.request.new_context()
    req.post(BASE + "/api/v1/reset", data={})
    ctx = b.new_context(viewport={"width": 1280, "height": 720},
                        record_video_dir=str(tmp), record_video_size={"width": 1280, "height": 720})
    page = ctx.new_page()
    try:
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_selector("#story-goals .chip, #story-goals *", timeout=15000)
        page.wait_for_timeout(PAUSE)
        step(page, "#step-goal", "1 goal")
        page.wait_for_selector("#story-opps > *", timeout=15000)
        page.wait_for_timeout(800)
        step(page, "#step-opps", "2 opps")
        step(page, "#step-plan", "3 plan")
        step(page, "#step-antifomo", "4 antifomo")
        page.locator("#step-change").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        page.click("#story-simulate")
        page.wait_for_selector("#story-diff > *", timeout=15000)
        step(page, "#step-change", "5 change")
        page.wait_for_selector("#story-met-btn", timeout=15000)
        page.locator("#step-met").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        page.click("#story-met-btn")
        page.wait_for_selector("#story-met .met-ok", timeout=15000)
        step(page, "#step-met", "6 met")
        page.wait_for_timeout(PAUSE)
    except Exception as e:
        log.append(f"FAILED after {log[-1] if log else 'start'}: {e}")
    finally:
        video = page.video
        ctx.close()
        shutil.move(video.path(), OUT)
        shutil.rmtree(tmp, ignore_errors=True)
        req.post(BASE + "/api/v1/reset", data={})
        b.close()
print("\n".join(log))
