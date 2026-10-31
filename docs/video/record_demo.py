"""Records the Terms Desk demo video (silent, 1920x1080). Voiceover is added separately.
Usage: python3 -m http.server 8765 -d web &  then  python3 docs/video/record_demo.py"""
import time, glob, os, shutil, subprocess
from playwright.sync_api import sync_playwright
BASE = "http://localhost:8765"
OUT = os.path.dirname(os.path.abspath(__file__))
CURSOR = """(()=>{if(document.getElementById('demoCursor'))return;const c=document.createElement('div');c.id='demoCursor';
c.innerHTML='<svg width="22" height="22" viewBox="0 0 24 24"><path d="M3 2l7 19 2.6-7.6L20 11z" fill="#0B1530" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
c.style.transform='translate(1500px,700px)';document.body.appendChild(c);})()"""
def setup(pg): pg.evaluate(CURSOR)
def move(pg, sel, dx=0, dy=0, t=0.9):
    b = pg.locator(sel).first.bounding_box()
    x, y = b["x"] + b["width"] / 2 + dx, b["y"] + b["height"] / 2 + dy
    pg.evaluate(f"document.getElementById('demoCursor').style.transform='translate({x}px,{y}px)'")
    time.sleep(t)
def click(pg, sel, pause=0.5):
    move(pg, sel)
    pg.evaluate("(()=>{const c=document.getElementById('demoCursor');c.classList.remove('click');void c.offsetWidth;c.classList.add('click')})()")
    pg.locator(sel).first.click(); time.sleep(pause)
def slide(pg, key, to, steps=24, dur=1.6):
    sel = f"#sl-{key}"; move(pg, sel, t=0.7)
    cur = float(pg.eval_on_selector(sel, "e=>e.value"))
    for i in range(1, steps + 1):
        v = cur + (to - cur) * i / steps
        pg.eval_on_selector(sel, f"e=>{{e.value={v};e.dispatchEvent(new Event('input'))}}")
        time.sleep(dur / steps)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--no-proxy-server"])
    ctx = b.new_context(viewport={"width": 1440, "height": 810}, device_scale_factor=4/3, timezone_id="Asia/Kolkata", record_video_dir="/tmp/vid", record_video_size={"width": 1920, "height": 1080})
    pg = ctx.new_page()
    T0 = time.time(); marks = []
    mark = lambda n: marks.append((round(time.time() - T0, 1), n))
    pg.goto(BASE + "/title.html?m=start"); mark("Title"); time.sleep(7)
    pg.goto(BASE + "/index.html"); setup(pg); mark("Overview"); time.sleep(2)
    move(pg, ".hero-value", t=1.2); time.sleep(4); move(pg, "#cashChart", t=1); time.sleep(5)
    mark("Run agent"); click(pg, "#runAgent", pause=6.5); move(pg, "#feed", t=1); time.sleep(4)
    mark("Approval queue"); click(pg, "nav a[data-view=queue]", pause=2)
    move(pg, "#prop-lm .pill", t=1); time.sleep(5); move(pg, "#prop-nw .pill", t=1); time.sleep(5)
    mark("Approve Northwind"); click(pg, "#prop-nw button[data-a=approve]", pause=1)
    move(pg, "#mSteps", t=1); time.sleep(5.5); move(pg, "#mPaid", t=1); time.sleep(4)
    click(pg, "#mDone", pause=1)
    click(pg, "#prop-lm button[data-a=plain]", pause=2.5)
    mark("The Skeptic"); click(pg, "nav a[data-view=skeptic]", pause=2); move(pg, "#skEV", t=1); time.sleep(3)
    slide(pg, "p0", 0.84, dur=2.2); time.sleep(3); move(pg, "#skReason", t=1); time.sleep(3)
    slide(pg, "s", 1.0, dur=1.5); time.sleep(3)
    mark("Money ledger"); click(pg, "nav a[data-view=ledger]", pause=2); move(pg, "#ledgerProtected", t=1); time.sleep(6)
    pg.goto(BASE + "/title.html?m=end"); mark("End card"); time.sleep(8)
    mark("End")
    vpath = pg.video.path(); ctx.close(); b.close()
    shutil.copy(vpath, os.path.join(OUT, "raw.webm"))
    open(os.path.join(OUT, "marks.txt"), "w").write("\n".join(f"{t:>6}s  {n}" for t, n in marks))
    print("\n".join(f"{t:>6}s  {n}" for t, n in marks))
