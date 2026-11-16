"""Agent roles and prompts.

GENERAL_CRITERIA is the built-in fallback guidance used until Day 4 adds
retrieved, object-specific procedures. It carries a source id so reports can
cite it like any other procedure.
"""

from __future__ import annotations

GENERAL_CRITERIA_ID = "GEN-001"
GENERAL_CRITERIA = """GEN-001 General visual-inspection guidance (synthetic, not an industry standard):
1. A dark line alone does not establish a defect. Treat it as a hypothesis.
2. Cast shadow: moves or disappears when the light direction changes. If a line vanishes under a
   different light while the camera has not moved, it is a shadow, not surface damage.
3. Crack: stays in the same place on the part under every light and viewpoint, and shows a surface
   discontinuity (raised or broken edge, gap) under raking light or from a low oblique view.
4. Expected seam/joint: straight, even width, at a regular position, and present on the approved
   reference image of the same category.
5. A definitive outcome needs: the target region visible, an applicable criterion, supporting
   observation ids, and no unresolved contradiction. 'No defect detected' covers only the inspected region.
6. If the target region cannot be seen, or the criteria cannot be checked, the outcome is Insufficient evidence."""

ROLES = {
    "planning": dict(
        role="Inspection Planning Agent",
        goal="Choose the single next robot action that best separates the competing explanations.",
        backstory=("You plan evidence gathering for a robotic inspection cell. You never assume the answer; "
                   "you pick the cheapest action whose result differs between hypotheses."),
    ),
    "inspection": dict(
        role="Visual Inspection Agent",
        goal="Describe what each camera image actually shows in the target region, with uncertainty.",
        backstory=("You analyse inspection images. You record what is visible, list plausible explanations "
                   "and never call a line a crack from appearance alone."),
    ),
    "verification": dict(
        role="Verification Agent",
        goal="Decide whether the recorded evidence supports an outcome under the inspection criteria.",
        backstory=("You audit inspection evidence. You accept a conclusion only when the cited observations "
                   "meet the criteria, and you prefer 'insufficient evidence' over an unsupported verdict."),
    ),
    "baseline": dict(
        role="Single-shot Inspector",
        goal="Classify the part from one image.",
        backstory="You look at one image and give your best classification.",
    ),
}


def inspection_prompt(task: dict, obs_id: str, pose: str, light: str, earlier: list[str]) -> str:
    comp = (f"Two images are attached in this order: FIRST = current observation {obs_id}; "
            f"SECOND = earlier observation {earlier[0]} (front view, initial light), for comparison only. "
            if earlier else f"One image is attached: observation {obs_id}. ")
    if earlier:
        comp += ("If the current image is the approved reference, set matches_reference to whether the line in "
                 "the SECOND image also appears on the reference at the same place. ")
    return (
        f"Inspection goal: {task['goal']}\nObject category: {task['object_category']}\n"
        f"Target region (normalized x0,y0,x1,y1 on the part face): {task['target_region']}\n\n"
        f"Current observation {obs_id}: camera pose '{pose}', light '{light}'. {comp}"
        "Analyse the FIRST (current) image. Ignore the fine background texture of the material. "
        "target_visible must be false if anything (clamp, plate, glare) covers the target region. "
        "Set surface_discontinuity=true only if a raised/broken edge, bright lip or gap is visible along the line. "
        "Report whether the target region is visible, "
        "whether a line or anomaly is present there, your neutral findings with plausible hypotheses, and how "
        "this view differs from the earlier one. Do not give a final verdict."
    )


def planning_prompt(task: dict, state: dict, inspections: list[dict], verification: dict | None,
                    feedback: str | None) -> str:
    fb = f"\nYour previous proposal was rejected: {feedback}\nPropose a different action.\n" if feedback else ""
    return (
        f"{GENERAL_CRITERIA}\n\nTask: {task['goal']} (category {task['object_category']}).\n"
        f"Available poses: {task['poses']}. Available lights: {task['lights']}.\n"
        f"Current camera pose: {state['pose']}, light: {state['light']}.\n"
        f"Views already captured (pose/light): {state['observed_views']}.\n"
        "Note: move_camera keeps the current light; set_lighting keeps the current pose.\n"
        f"Candidate next actions (choose exactly one of these, or 'stop'):\n  - "
        + "\n  - ".join(state["candidates"]) + "\n"
        f"Failed attempts (do not repeat): {state['failed']}.\n"
        f"Evidence actions remaining: {state['actions_remaining']}.\n\n"
        f"Inspection results so far: {inspections}\n"
        f"Latest verification: {verification}\n{fb}\n"
        "Choose ONE next action that would produce different results under the competing hypotheses. "
        "If a line might be a shadow, a single lighting change from the SAME pose (e.g. 'top' or 'diffuse') "
        "is the cheapest test. If the target region is covered or hidden, lighting cannot reveal it: only a "
        "camera move can. If an expected seam is plausible, compare with get_reference. Use action 'stop' "
        "only if no available action could change the conclusion. State what each hypothesis predicts."
    )


def same_pose_table(inspections: list[dict]) -> str:
    """Deterministic summary: for each camera pose, which lights show the anomaly."""
    by_pose: dict[str, list[str]] = {}
    for i in inspections:
        v = i.get("view", {})
        if v.get("kind") == "camera":
            by_pose.setdefault(v["pose"], []).append(
                f"{i['obs_id']} light={v['light']} anomaly={i['anomaly_present']} discontinuity={i['surface_discontinuity']}")
    return "\n".join(f"  pose {p}: " + "; ".join(rows) for p, rows in by_pose.items()) or "  (none)"


def verification_prompt(task: dict, inspections: list[dict], attempts: list[dict]) -> str:
    return (
        f"{GENERAL_CRITERIA}\n\nTask: {task['goal']} (category {task['object_category']}).\n"
        "FACTS FROM THE ROBOT (authoritative): each observation's pose and light are recorded by the cell. "
        "Two observations with the same pose were taken from exactly the same camera position; the part is "
        "clamped and never moves. Ignore any speculation in inspection notes about camera or part movement.\n"
        f"Observations grouped by camera pose:\n{same_pose_table(inspections)}\n"
        f"Inspection results by observation: {inspections}\n"
        f"All tool attempts (failed ones have no observation and are NOT evidence): {attempts}\n\n"
        "Decide the outcome: suspected_defect, no_defect_detected or insufficient_evidence. "
        "Apply the criteria literally and be decisive when one is met:\n"
        "- A line seen under one light that is ABSENT under another light, or that appears at a DIFFERENT "
        "position under another light, from the same camera pose is a cast shadow (criterion 2): outcome "
        "no_defect_detected, evidence_sufficient=true, cite the two observations that show it. One clear "
        "pair is enough; other views do not block it unless they show the line fixed under a different light "
        "from that same pose.\n"
        "- A line that stays in place under two different lights AND an observation with "
        "surface_discontinuity=true (criterion 3): suspected_defect, evidence_sufficient=true.\n"
        "- A line with matches_reference=true on the approved reference (criterion 4): no_defect_detected, "
        "cite the observation and the reference.\n"
        "- Target region never visible: insufficient_evidence.\n"
        "Otherwise set evidence_sufficient=false and list the single most useful missing evidence. "
        f"Cite only observation ids that appear in the inspection results. List '{GENERAL_CRITERIA_ID}' "
        "items you checked in criteria_checked."
    )


def baseline_prompt(task: dict) -> str:
    return (
        f"Inspection goal: {task['goal']}\nObject category: {task['object_category']}\n"
        "Look at the attached image and classify the part as suspected_defect, no_defect_detected or "
        "insufficient_evidence, with a short rationale."
    )
