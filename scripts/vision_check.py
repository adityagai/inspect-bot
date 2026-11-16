"""Day 1 sanity check: does the vision model see what the scenarios intend?

For each scenario it shows Claude the *initial* image only (what the baseline
sees) and asks for a JSON description. For the S1 shadow we want it to see a
dark line it cannot confidently classify; for S2 a line that may be a crack.

    cp .env.example .env   # add ANTHROPIC_API_KEY
    python scripts/vision_check.py            # all scenarios
    python scripts/vision_check.py S1 S2
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

from inspectbot.sim.renderer import render_view
from inspectbot.sim.scenario import list_scenarios, load_scenario

PROMPT = (
    "You are inspecting one image of an industrial part from a robot camera. "
    "Describe any line-like or unusual features on the part surface. For each, list which of "
    "these explanations are plausible: crack, cast shadow, expected seam/joint, scratch, other. "
    "Say what extra observation (another viewpoint, different lighting, zoom, reference image) "
    "would best tell them apart. Reply with JSON only, no prose: "
    '{"features": [{"description": str, "plausible": [str], "confidence_crack": "low|medium|high", '
    '"best_next_observation": str}], "notes": str}'
)


def _b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1]) if start != -1 and end != -1 else {"raw": text}


def main(ids: list[str]) -> None:
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set (copy .env.example to .env)")
    client = Anthropic()
    model = os.getenv("INSPECTBOT_VISION_MODEL", "claude-sonnet-5-5")
    scenarios = [load_scenario(i) for i in ids] if ids else list_scenarios()
    for s in scenarios:
        img = render_view(s, s.initial_pose, s.initial_light)
        resp = client.messages.create(
            model=model,
            max_tokens=800,
            temperature=0,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(img)}},
                {"type": "text", "text": PROMPT},
            ]}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        print(f"\n=== {s.id} {s.name} (ground truth: {s.ground_truth.outcome.value}) ===")
        print(json.dumps(_parse_json(text), indent=2))
        print(f"[tokens in/out: {resp.usage.input_tokens}/{resp.usage.output_tokens}]")


if __name__ == "__main__":
    main(sys.argv[1:])
