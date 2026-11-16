"""Day 1 sanity check: does GPT-4o see what the scenarios intend?

For each scenario it shows GPT-4o the *initial* image only (what the baseline
sees) and asks for a JSON description. For the S1 shadow we want it to see a
dark line it cannot confidently classify; for S2 a line that may be a crack.

    cp .env.example .env   # add OPENAI_API_KEY
    python scripts/vision_check.py            # all scenarios
    python scripts/vision_check.py S1 S2
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from inspectbot.sim.renderer import render_view
from inspectbot.sim.scenario import list_scenarios, load_scenario

PROMPT = (
    "You are inspecting one image of an industrial part from a robot camera. "
    "Describe any line-like or unusual features on the part surface. For each, list which of "
    "these explanations are plausible: crack, cast shadow, expected seam/joint, scratch, other. "
    "Say what extra observation (another viewpoint, different lighting, zoom, reference image) "
    "would best tell them apart. Reply as JSON: "
    '{"features": [{"description": str, "plausible": [str], "confidence_crack": "low|medium|high", '
    '"best_next_observation": str}], "notes": str}'
)


def _b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def main(ids: list[str]) -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set (copy .env.example to .env)")
    client = OpenAI()
    model = os.getenv("INSPECTBOT_VISION_MODEL", "gpt-4o")
    scenarios = [load_scenario(i) for i in ids] if ids else list_scenarios()
    for s in scenarios:
        img = render_view(s, s.initial_pose, s.initial_light)
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(img)}", "detail": "high"}},
            ]}],
        )
        print(f"\n=== {s.id} {s.name} (ground truth: {s.ground_truth.outcome.value}) ===")
        print(json.dumps(json.loads(resp.choices[0].message.content), indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
