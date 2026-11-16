"""Render every pose x light view of a scenario as a labelled contact sheet.

    python -m inspectbot.sim.preview S1            # writes runs/preview/S1/
    python -m inspectbot.sim.preview --all
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from inspectbot.core.models import Lighting, Pose
from inspectbot.sim.renderer import render_reference, render_view
from inspectbot.sim.scenario import Scenario, list_scenarios, load_scenario
from inspectbot.sim.schematic import render_schematic

THUMB = (320, 240)


def preview(scn: Scenario, out_root: Path) -> Path:
    out = out_root / scn.id
    out.mkdir(parents=True, exist_ok=True)
    poses, lights = list(Pose), list(Lighting)
    sheet = Image.new("RGB", (THUMB[0] * len(lights), (THUMB[1] + 22) * len(poses) + 30), (24, 26, 30))
    d = ImageDraw.Draw(sheet)
    d.text((8, 8), f"{scn.id} - {scn.name} ({scn.category})  |  unreachable: "
                   f"{[p.value for p in scn.unreachable_poses] or 'none'}", fill=(235, 235, 235))
    for r, pose in enumerate(poses):
        for c, light in enumerate(lights):
            img = render_view(scn, pose, light)
            img.save(out / f"{pose.value}__{light.value}.png")
            x, y = c * THUMB[0], 30 + r * (THUMB[1] + 22)
            sheet.paste(img.resize(THUMB), (x, y + 22))
            tag = " (unreachable)" if pose in scn.unreachable_poses else ""
            d.text((x + 6, y + 4), f"{pose.value} / {light.value}{tag}", fill=(200, 205, 215))
    sheet.save(out / "contact_sheet.png")
    if scn.reference_available:
        render_reference(scn).save(out / "reference.png")
    (out / "schematic.svg").write_text(render_schematic(scn.initial_pose, scn.initial_light, category=scn.category))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scenario", nargs="?", help="scenario id (e.g. S1) or YAML path")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default="runs/preview")
    a = ap.parse_args()
    scenarios = list_scenarios() if a.all or not a.scenario else [load_scenario(a.scenario)]
    for s in scenarios:
        print(f"{s.id}: {preview(s, Path(a.out))}")


if __name__ == "__main__":
    main()
