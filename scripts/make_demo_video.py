"""Build the captioned demo video from the replay app (no narration track).

    streamlit run app/streamlit_app.py --server.port 8599 &      # replay mode, demo_runs/
    python scripts/make_demo_video.py --url http://localhost:8599 --out docs/demo/inspectbot_demo.mp4

Needs: playwright (pip install playwright; uses an installed Chrome via --chrome, or
`playwright install chromium`), ffmpeg, Pillow. Captures each moment with URL parameters
(?run=S1&step=11), adds a caption bar, adds title/architecture cards, and encodes
one file per scene joined with the concat demuxer. Narration can be recorded over it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
CAP_H = 150                       # caption bar height
SHOT_W, SHOT_H = 1728, 846        # browser viewport; scaled x1.111 to 1920 x 940
BG, PANEL, ACCENT, TEXT, MUTED = (17, 20, 26), (24, 28, 36), (79, 140, 255), (240, 242, 246), (160, 168, 182)
GREEN, AMBER, RED = (47, 179, 122), (224, 160, 48), (217, 83, 79)
FONT_DIRS = ["/usr/share/fonts/opentype/inter", "/Library/Fonts", "/System/Library/Fonts/Supplemental"]


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for d in FONT_DIRS:
        p = Path(d) / f"Inter-{weight}.otf"
        if p.exists():
            return ImageFont.truetype(str(p), size)
    for name in ("Arial Bold.ttf" if weight in ("Bold", "SemiBold") else "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


@dataclass
class Shot:
    tag: str          # small label on the caption bar, e.g. "S1 · fixture shadow"
    caption: str
    seconds: float
    run: str | None = None
    step: int | None = None
    anchor: str = "Robot cell"   # text to scroll to the top of the view
    extra: str = ""              # extra URL params, e.g. "&open=rag"
    tab: str | None = None       # click a tab first (e.g. "Evaluation")
    card: str | None = None      # draw a card instead of capturing the app


SHOTS: list[Shot] = [
    Shot("", "", 6, card="title"),
    Shot("", "", 12, card="problem"),
    Shot("", "", 14, card="architecture"),
    Shot("S1 · fixture shadow", "The first image shows a dark vertical line. The Inspection agent records it as a hypothesis "
         "(crack, shadow or seam), not a verdict. The baseline sees only this image.", 10, "S1", 5),
    Shot("S1 · fixture shadow", "Retrieval returns bracket procedure MB-1. Tree-of-Thought compares three next steps; changing "
         "the light from the same pose scores 10/10 because a shadow moves and a crack does not.", 11, "S1", 11,
         "Tree-of-Thought search"),
    Shot("S1 · fixture shadow", "One lighting change. From the same camera pose the line is gone, so it was the fixture shadow.",
         8, "S1", 16),
    Shot("S1 · fixture shadow", "Report: No defect detected for the inspected region, citing obs_01, obs_02 and PROC-MB-001. "
         "The prompt-only baseline called the same image a crack.", 11, "S1", 18, "#report-anchor"),
    Shot("S3 · mold seam", "Bottle: procedure GB-1 says the mold seam sits on the centre line and appears on the approved "
         "reference. InspectBot fetches the reference, with no robot move needed.", 11, "S3", 15),
    Shot("S3 · mold seam", "The line matches the reference: No defect detected (GB-1). The baseline called it a crack.",
         8, "S3", 18, "#report-anchor"),
    Shot("S2 · real crack", "Tile: the line stays put under left and right light, and the low oblique view shows a raised "
         "edge along it: criterion CT-1 for a crack.", 10, "S2", 21),
    Shot("S2 · real crack", "Suspected defect, citing the observations for each CT-1 condition and the reference that "
         "lacks the line.", 9, "S2", 30, "#report-anchor"),
    Shot("S4 · hidden target", "A clamp hides the target. Procedure MB-2 says only left_45 sees past it, but that pose is "
         "unreachable. The failed move is logged and leaves no image, so it can never be cited.", 12, "S4", 13),
    Shot("S4 · hidden target", "Tree-of-Thought keeps the camera move and drops the lighting idea: light cannot see under a clamp.",
         9, "S4", 11, "Tree-of-Thought search"),
    Shot("S4 · hidden target", "Insufficient evidence goes to human review: uninspected region, failed actions and the "
         "question for the reviewer, whose decision is recorded.", 12, "S4", 30, "#report-anchor"),
    Shot("S5 · no procedure", "No procedure exists for pump housings. A tile procedure matched the query best but is rejected "
         "by the category filter. InspectBot escalates in 4 s with zero robot moves; the baseline guessed 'crack'.",
         13, "S5", 9, "Retrieved procedures", "&open=rag"),
    Shot("Evaluation · 20 scenarios", "20 scenarios: InspectBot 20/20 correct, prompt-only baseline 8/20. "
         "Zero incorrect definitive outcomes versus 12.", 10, "S1", None, "Evaluation results", tab="Evaluation"),
    Shot("Evaluation · 20 scenarios", "All Checkpoint 2.1 and 6.1 targets met: no false clears, 10/10 escalations, every "
         "conclusion grounded, 1.3 robot actions per resolvable case.", 10, "S1", None, "Targets (Checkpoints 2.1 and 6.1)",
         tab="Evaluation"),
    Shot("", "", 12, card="closing"),
]


# ---------------------------------------------------------------- capture


async def capture(shots: list[Shot], url: str, out: Path, chrome: str | None) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        kw = {"executable_path": chrome, "args": ["--no-sandbox"]} if chrome else {}
        browser = await p.chromium.launch(**kw)
        page = await browser.new_page(viewport={"width": SHOT_W, "height": SHOT_H})
        for i, s in enumerate(shots):
            if s.card:
                continue
            q = f"?run={s.run}&sidebar=collapsed" + (f"&step={s.step}" if s.step else "") + s.extra
            await page.goto(url.rstrip("/") + "/" + q)
            await page.wait_for_selector("text=Agent timeline", timeout=60000)
            await page.wait_for_timeout(2500)
            if s.tab:
                await page.get_by_role("tab", name=s.tab).click()
                await page.wait_for_timeout(2500)
            if s.anchor.startswith("#"):  # an element id placed in the app for scrolling
                target = page.locator(s.anchor).first
            else:  # headings may start with an emoji or end with a date ("🌳 Tree-of-Thought search")
                target = page.get_by_text(re.compile(r"^\W*" + re.escape(s.anchor) + r"(\s*\(.*\))?\s*$")).first
            await target.evaluate("el => el.scrollIntoView({block: 'start'})")
            await page.wait_for_timeout(1200)
            await page.screenshot(path=str(out / f"shot_{i:02d}.jpg"), type="jpeg", quality=92)
            print(f"captured {i:02d} {s.tag}")
        await browser.close()


# ---------------------------------------------------------------- frames


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=f) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def captioned(shot_path: Path, s: Shot) -> Image.Image:
    frame = Image.new("RGB", (W, H), BG)
    shot = Image.open(shot_path).convert("RGB").resize((W, H - CAP_H), Image.LANCZOS)
    frame.paste(shot, (0, 0))
    d = ImageDraw.Draw(frame)
    d.rectangle([0, H - CAP_H, W, H], fill=PANEL)
    d.rectangle([0, H - CAP_H, W, H - CAP_H + 4], fill=ACCENT)
    tag_f, cap_f = font("SemiBold", 26), font("Regular", 33)
    d.text((48, H - CAP_H + 22), s.tag.upper(), font=tag_f, fill=ACCENT)
    for k, line in enumerate(wrap(d, s.caption, cap_f, W - 96)[:2]):
        d.text((48, H - CAP_H + 60 + k * 42), line, font=cap_f, fill=TEXT)
    return frame


def _box(d, xy, label, fill, sub="", tf=None, sf=None):
    d.rounded_rectangle(xy, radius=18, fill=fill)
    x0, y0, x1, y1 = xy
    tf, sf = tf or font("SemiBold", 30), sf or font("Regular", 22)
    tw = d.textlength(label, font=tf)
    d.text(((x0 + x1 - tw) / 2, y0 + (22 if sub else (y1 - y0 - 34) / 2)), label, font=tf, fill=TEXT)
    for k, line in enumerate(sub.split("\n") if sub else []):
        lw = d.textlength(line, font=sf)
        d.text(((x0 + x1 - lw) / 2, y0 + 64 + k * 28), line, font=sf, fill=MUTED)


def _arrow(d, a, b, color=MUTED):
    d.line([a, b], fill=color, width=4)
    import math
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (-0.45, 0.45):
        d.line([b, (b[0] - 18 * math.cos(ang + s), b[1] - 18 * math.sin(ang + s))], fill=color, width=4)


def card(kind: str) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    if kind == "title":
        d.text((140, 330), "InspectBot", font=font("Bold", 120), fill=TEXT)
        d.text((146, 480), "A multi-agent research assistant for robotic visual inspection", font=font("Medium", 44), fill=TEXT)
        d.text((146, 550), "Simulated robot cell  ·  CrewAI  ·  LangChain RAG  ·  MCP  ·  Claude", font=font("Regular", 34),
               fill=MUTED)
        d.rectangle([146, 640, 420, 646], fill=ACCENT)
        d.text((146, 680), "Agentic AI capstone  ·  MVP demo", font=font("Regular", 30), fill=MUTED)
    elif kind == "problem":
        d.text((140, 150), "The problem", font=font("Bold", 64), fill=TEXT)
        d.text((140, 250), "One image often cannot tell a crack from a shadow or a seam.", font=font("Medium", 42), fill=TEXT)
        rows = [("A one-shot model guesses.", "It must answer from the single image it was given."),
                ("InspectBot investigates.", "It treats the line as a hypothesis, picks the observation that would tell the "
                                             "explanations apart, and checks the result against an approved procedure."),
                ("Or it says it cannot know.", "When the target can't be seen or no procedure applies, it escalates to a human.")]
        y = 380
        for head, body in rows:
            d.text((140, y), head, font=font("SemiBold", 36), fill=ACCENT)
            lines = textwrap.wrap(body, 56)
            for k, line in enumerate(lines):
                d.text((140, y + 50 + k * 40), line, font=font("Regular", 32), fill=MUTED)
            y += 100 + 40 * len(lines)
        x, y = 1300, 400
        d.text((x, y - 70), "Three possible outcomes", font=font("SemiBold", 30), fill=MUTED)
        for label, color in (("Suspected defect", RED), ("No defect detected", GREEN), ("Insufficient evidence", AMBER)):
            d.rounded_rectangle([x, y, x + 480, y + 72], radius=14, fill=color)
            d.text((x + 24, y + 16), label, font=font("SemiBold", 32), fill=(255, 255, 255))
            y += 100
        d.text((x, y + 10), "every outcome cites its evidence;", font=font("Regular", 26), fill=MUTED)
        d.text((x, y + 44), "'insufficient' always goes to a human", font=font("Regular", 26), fill=MUTED)
    elif kind == "architecture":
        d.text((120, 70), "How it works", font=font("Bold", 60), fill=TEXT)
        d.rounded_rectangle([90, 180, 1010, 980], radius=24, outline=(60, 66, 78), width=3)
        d.text((120, 196), "CrewAI Flow  ·  the Coordinator", font=font("SemiBold", 28), fill=MUTED)
        _box(d, (330, 260, 770, 400), "Coordinator", (52, 60, 76), "budgets · guards · stop rules")
        _box(d, (120, 520, 400, 680), "Planning", (36, 70, 140), "Claude Haiku\n+ bounded Tree-of-Thought")
        _box(d, (420, 520, 680, 680), "Inspection", (30, 110, 80), "Claude Sonnet\nvision")
        _box(d, (700, 520, 980, 680), "Verification", (140, 100, 30), "Claude Sonnet\nprocedures + evidence")
        for x in (260, 550, 840):
            _arrow(d, (550, 400), (x, 520))
        d.text((120, 730), "Loop: inspect → verify → plan one action → act → inspect …", font=font("Regular", 28), fill=TEXT)
        d.text((120, 778), "until the procedure's criterion is met, or nothing left can change the answer.",
               font=font("Regular", 28), fill=MUTED)
        d.text((120, 850), "Agents propose; the Coordinator executes every action through MCP.",
               font=font("Regular", 28), fill=MUTED)
        _arrow(d, (1010, 330), (1150, 330), ACCENT)
        d.text((1030, 280), "MCP", font=font("SemiBold", 28), fill=ACCENT)
        d.rounded_rectangle([1150, 180, 1830, 980], radius=24, outline=(60, 66, 78), width=3)
        d.text((1180, 196), "MCP server", font=font("SemiBold", 28), fill=MUTED)
        _box(d, (1190, 250, 1790, 400), "Simulated inspection cell", (52, 60, 76),
             "camera arm: 5 poses · light: 4 settings\nfailures: unreachable, timeout")
        _box(d, (1190, 430, 1790, 580), "Procedure retrieval", (52, 60, 76),
             "LangChain + Chroma · filtered by category\nversioned, cited, missing guidance flagged")
        _box(d, (1190, 610, 1790, 760), "Shared task record", (52, 60, 76),
             "attempts ≠ observations · budget: 5 actions\nToT: once, ≤ 15 evaluations")
        _box(d, (1190, 790, 1790, 940), "Report", (52, 60, 76), "outcome · evidence obs_ids · procedures\nscope · human review")
    elif kind == "closing":
        d.text((140, 150), "Results, limits and next steps", font=font("Bold", 60), fill=TEXT)
        items = [("Pilot result", "20/20 correct vs 8/20 for a prompt-only baseline; 0 incorrect definitive calls vs 12."),
                 ("Cost", "About 43 s per inspection vs 2.5 s: several model calls per evidence step."),
                 ("Limits", "Single runs on 20 synthetic scenarios; synthetic procedures; simulation / advisory only."),
                 ("Next", "MVTec AD static-image study, AI2-THOR viewpoints, repeated runs for variance, "
                          "a real arm with human-authorized actions.")]
        y = 290
        for head, body in items:
            d.text((140, y), head, font=font("SemiBold", 36), fill=ACCENT)
            for k, line in enumerate(textwrap.wrap(body, 70)):
                d.text((520, y + 2 + k * 44), line, font=font("Regular", 34), fill=TEXT)
            y += 150
        d.text((140, 930), "github.com/adityagai/inspect-bot-rag", font=font("Medium", 32), fill=MUTED)
    return img


# ---------------------------------------------------------------- encode


def encode_still(png: Path, seconds: float, out: Path) -> None:
    tmp = out.with_suffix(".partial.mp4")
    fade = f"fade=t=in:st=0:d=0.35,fade=t=out:st={seconds - 0.35:.2f}:d=0.35"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(png),
           "-vf", f"format=yuv420p,loop=-1:1,trim=duration={seconds},{fade}",
           "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(FPS), str(tmp)]
    subprocess.run(cmd, check=True)
    tmp.rename(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--out", default="docs/demo/inspectbot_demo.mp4")
    ap.add_argument("--chrome", default=shutil.which("google-chrome") or None,
                    help="path to an installed Chrome/Chromium (else Playwright's own)")
    ap.add_argument("--frames-only", action="store_true", help="write the frames and stop (for checking)")
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="inspectbot_video_"))
    asyncio.run(capture(SHOTS, a.url, work, a.chrome))
    files = []
    for i, s in enumerate(SHOTS):
        frame = card(s.card) if s.card else captioned(work / f"shot_{i:02d}.jpg", s)
        png = work / f"frame_{i:02d}.png"
        frame.save(png)
        files.append((png, s.seconds))
    if a.frames_only:
        print(f"frames in {work}")
        return
    scenes = []
    for i, (png, secs) in enumerate(files):
        mp4 = work / f"scene_{i:02d}.mp4"
        encode_still(png, secs, mp4)
        scenes.append(mp4)
    (work / "list.txt").write_text("".join(f"file '{p}'\n" for p in scenes))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".partial.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(work / "list.txt"),
                    "-c", "copy", "-movflags", "+faststart", str(tmp)], check=True)
    os.replace(tmp, out)
    total = sum(s.seconds for s in SHOTS)
    print(f"wrote {out} ({total:.0f} s, {len(SHOTS)} scenes); frames in {work}")


if __name__ == "__main__":
    main()
