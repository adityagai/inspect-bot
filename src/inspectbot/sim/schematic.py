"""Top-down SVG schematic of the inspection cell, redrawn after each action.

Shows the part on its fixture, the arm reaching to the current camera pose with
its view cone, the light direction, and any failed move as a red X at the pose
that was attempted. Used by the Streamlit app and exported as GIF frames.
"""

from __future__ import annotations

import math

from inspectbot.core.models import Lighting, Pose

W, H = 360, 270
PART_C = (180, 120)
ARM_BASE = (40, 240)

# Camera position in the schematic for each pose (top-down view).
POSE_XY: dict[Pose, tuple[float, float]] = {
    Pose.FRONT: (180, 225),
    Pose.LEFT_45: (85, 200),
    Pose.RIGHT_45: (275, 200),
    Pose.TOP: (180, 120),
    Pose.OBLIQUE_LOW: (180, 252),
}


def _cone(cam: tuple[float, float], target: tuple[float, float], spread: float = 0.38, length: float = 70) -> str:
    ang = math.atan2(target[1] - cam[1], target[0] - cam[0])
    p1 = (cam[0] + length * math.cos(ang - spread), cam[1] + length * math.sin(ang - spread))
    p2 = (cam[0] + length * math.cos(ang + spread), cam[1] + length * math.sin(ang + spread))
    return f"{cam[0]:.0f},{cam[1]:.0f} {p1[0]:.0f},{p1[1]:.0f} {p2[0]:.0f},{p2[1]:.0f}"


def _light(light: Lighting) -> str:
    if light == Lighting.LEFT:
        return ('<line x1="20" y1="120" x2="110" y2="120" stroke="#f5b942" stroke-width="4" '
                'marker-end="url(#arrow)"/><text x="16" y="108" class="lbl">light: left</text>')
    if light == Lighting.RIGHT:
        return ('<line x1="340" y1="120" x2="250" y2="120" stroke="#f5b942" stroke-width="4" '
                'marker-end="url(#arrow)"/><text x="268" y="108" class="lbl">light: right</text>')
    if light == Lighting.TOP:
        return ('<circle cx="180" cy="120" r="74" fill="none" stroke="#f5b942" stroke-width="3" '
                'stroke-dasharray="6 5"/><text x="150" y="38" class="lbl">light: top</text>')
    return ('<rect x="96" y="56" width="168" height="128" rx="18" fill="#f5b942" fill-opacity="0.12" '
            'stroke="#f5b942" stroke-opacity="0.5"/><text x="140" y="48" class="lbl">light: diffuse</text>')


def render_schematic(pose: Pose, light: Lighting, *, failed_pose: Pose | None = None,
                     category: str = "", step: int | None = None) -> str:
    cam = POSE_XY[pose]
    elbow = ((ARM_BASE[0] + cam[0]) / 2 - 10, (ARM_BASE[1] + cam[1]) / 2 + 18)
    overhead = pose == Pose.TOP
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        'font-family="Helvetica, Arial, sans-serif">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" '
        'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#f5b942"/></marker>'
        '<style>.lbl{font-size:11px;fill:#c9ccd3}.title{font-size:12px;fill:#ffffff;font-weight:bold}</style>'
        '</defs>',
        f'<rect width="{W}" height="{H}" rx="10" fill="#1f2228"/>',
        f'<text x="12" y="20" class="title">Inspection cell{f" - step {step}" if step is not None else ""}</text>',
        # fixture + part
        f'<rect x="{PART_C[0]-62}" y="{PART_C[1]-46}" width="124" height="92" rx="6" fill="#3a3f48"/>',
        f'<rect x="{PART_C[0]-50}" y="{PART_C[1]-36}" width="100" height="72" rx="4" fill="#a9b0ba"/>',
        f'<text x="{PART_C[0]-48}" y="{PART_C[1]+58}" class="lbl">{category}</text>',
        _light(light),
    ]
    # candidate poses
    for p, (x, y) in POSE_XY.items():
        if p == pose or p == Pose.TOP:
            continue
        parts.append(f'<circle cx="{x}" cy="{y}" r="4" fill="#59606b"/>')
    # failed attempt marker
    if failed_pose is not None:
        fx, fy = POSE_XY[failed_pose]
        parts.append(f'<g stroke="#ff5a5a" stroke-width="4"><line x1="{fx-9}" y1="{fy-9}" x2="{fx+9}" '
                     f'y2="{fy+9}"/><line x1="{fx-9}" y1="{fy+9}" x2="{fx+9}" y2="{fy-9}"/></g>')
        parts.append(f'<text x="{fx-30}" y="{fy+24}" class="lbl" fill="#ff5a5a">failed: {failed_pose.value}</text>')
    # arm + camera
    parts.append(f'<polyline points="{ARM_BASE[0]},{ARM_BASE[1]} {elbow[0]:.0f},{elbow[1]:.0f} {cam[0]},{cam[1]}" '
                 'fill="none" stroke="#7cc4ff" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" '
                 f'stroke-opacity="{0.55 if overhead else 1}"/>')
    parts.append(f'<circle cx="{ARM_BASE[0]}" cy="{ARM_BASE[1]}" r="12" fill="#2d6ea3"/>')
    if overhead:
        parts.append(f'<circle cx="{cam[0]}" cy="{cam[1]}" r="16" fill="none" stroke="#7cc4ff" stroke-width="3"/>')
    else:
        parts.append(f'<polygon points="{_cone(cam, PART_C)}" fill="#7cc4ff" fill-opacity="0.18"/>')
    parts.append(f'<rect x="{cam[0]-9}" y="{cam[1]-7}" width="18" height="14" rx="3" fill="#7cc4ff"/>')
    parts.append(f'<text x="{W-120}" y="{H-12}" class="lbl">camera: {pose.value}</text>')
    parts.append("</svg>")
    return "".join(parts)
