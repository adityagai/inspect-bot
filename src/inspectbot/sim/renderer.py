"""CPU-only procedural renderer for the virtual inspection cell.

A part face is drawn in object space (512x384), shaded by the light, then warped
into a 640x480 camera image for the chosen pose. The rules that make features
distinguishable are deliberate and documented, because the scenarios depend on them:

- crack:       dark under every light; raking light (left/right) adds a highlight on
               the lit edge; oblique_low reveals a bright raised lip and a wider gap.
- cast_shadow: dark soft band only for the lights listed, at a light-dependent
               position; absent under top or diffuse light.
- mark:        like a crack under every light, but flat: no lip or gap from any view.
- seam:        straight, even-width line; also present on the reference sample.
- glare:       bright spot for the listed lights; hides detail underneath.
- occlusion:   clamp drawn over a region unless the pose is in `visible_from`.
"""

from __future__ import annotations

import hashlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from inspectbot.core.models import Lighting, Pose
from inspectbot.sim.scenario import CastShadow, Crack, Glare, Mark, Scenario, Seam

PART_W, PART_H = 512, 384
OUT_W, OUT_H = 640, 480

CATEGORY_STYLE: dict[str, tuple[tuple[int, int, int], str]] = {
    "metal_bracket": ((170, 174, 180), "brushed"),
    "ceramic_tile": ((228, 224, 214), "speckle"),
    "glass_bottle": ((128, 168, 156), "gradient"),
}
DEFAULT_STYLE = ((150, 146, 140), "speckle")

# Destination quad (TL, TR, BR, BL) of the part face in the camera image, per pose.
POSE_QUADS: dict[Pose, list[tuple[float, float]]] = {
    Pose.FRONT: [(64, 48), (576, 48), (576, 432), (64, 432)],
    Pose.LEFT_45: [(110, 30), (520, 92), (520, 388), (110, 450)],
    Pose.RIGHT_45: [(120, 92), (530, 30), (530, 450), (120, 388)],
    Pose.TOP: [(104, 78), (536, 78), (536, 402), (104, 402)],
    Pose.OBLIQUE_LOW: [(150, 168), (490, 168), (602, 404), (38, 404)],
}


def _seed(*parts: object) -> int:
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:8], 16)


# --------------------------------------------------------------------------- object space


def _albedo(scn: Scenario) -> np.ndarray:
    """Base colour + texture. Depends only on the part, never on the view."""
    base, texture = CATEGORY_STYLE.get(scn.category, DEFAULT_STYLE)
    rng = np.random.default_rng(_seed(scn.seed, scn.category, "texture"))
    img = np.ones((PART_H, PART_W, 3), np.float32) * np.array(base, np.float32)
    if texture == "brushed":
        streaks = rng.normal(0, 7, (PART_H, 1, 1)).astype(np.float32)
        img += streaks + rng.normal(0, 2, (PART_H, PART_W, 1)).astype(np.float32)
    elif texture == "speckle":
        img += rng.normal(0, 4, (PART_H, PART_W, 1)).astype(np.float32)
        dots = rng.random((PART_H, PART_W)) > 0.996
        img[dots] -= 35
    elif texture == "gradient":
        xs = np.linspace(-1, 1, PART_W, dtype=np.float32)
        img += (18 * (1 - xs**2))[None, :, None] + rng.normal(0, 2, (PART_H, PART_W, 1)).astype(np.float32)
    return img


def _shading(light: Lighting) -> np.ndarray:
    xs = np.linspace(-1, 1, PART_W, dtype=np.float32)
    ys = np.linspace(-1, 1, PART_H, dtype=np.float32)
    if light == Lighting.LEFT:
        row = 0.78 - 0.20 * xs
        s = np.tile(row, (PART_H, 1))
    elif light == Lighting.RIGHT:
        row = 0.78 + 0.20 * xs
        s = np.tile(row, (PART_H, 1))
    elif light == Lighting.TOP:
        s = 0.97 - 0.10 * (xs[None, :] ** 2 + ys[:, None] ** 2)
    else:  # diffuse
        s = np.full((PART_H, PART_W), 0.88, np.float32)
    return s[..., None]


def _mask(draw_fn, blur: float = 0.0) -> np.ndarray:
    m = Image.new("L", (PART_W, PART_H), 0)
    draw_fn(ImageDraw.Draw(m))
    if blur:
        m = m.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(m, np.float32)[..., None] / 255.0


def _px(pt: tuple[float, float]) -> tuple[float, float]:
    return (pt[0] * PART_W, pt[1] * PART_H)


def _jagged(crack: Crack, seed: int) -> list[tuple[float, float]]:
    rng = np.random.default_rng(seed)
    pts: list[tuple[float, float]] = []
    for (x0, y0), (x1, y1) in zip(crack.points, crack.points[1:]):
        for t in np.linspace(0, 1, 9, endpoint=False):
            x = x0 + (x1 - x0) * t + rng.normal(0, crack.jitter)
            y = y0 + (y1 - y0) * t + rng.normal(0, crack.jitter * 0.5)
            pts.append(_px((x, y)))
    pts.append(_px(crack.points[-1]))
    return pts


def _band(orientation: str, pos: float, extent: tuple[float, float], seed: int) -> list[tuple[float, float]]:
    """Slightly wavy straight band, so a shadow is neither a perfect seam nor jagged."""
    rng = np.random.default_rng(seed)
    phase = rng.uniform(0, 2 * np.pi)
    ts = np.linspace(extent[0], extent[1], 40)
    wobble = 0.004 * np.sin(ts * 9 + phase)
    if orientation == "vertical":
        return [_px((pos + w, t)) for t, w in zip(ts, wobble)]
    return [_px((t, pos + w)) for t, w in zip(ts, wobble)]


def render_part(scn: Scenario, pose: Pose, light: Lighting, *, include_defects: bool = True) -> np.ndarray:
    img = _albedo(scn) * _shading(light)

    for i, feat in enumerate(scn.features):
        if isinstance(feat, Seam):
            if feat.orientation == "vertical":
                x = feat.position * PART_W
                line = [(x, 0), (x, PART_H)]
            else:
                y = feat.position * PART_H
                line = [(0, y), (PART_W, y)]
            m = _mask(lambda d, ln=line, w=feat.width_px: d.line(ln, fill=255, width=w))
            img = img * (1 - 0.42 * m)

        elif isinstance(feat, Crack) and include_defects:
            pts = _jagged(feat, _seed(scn.seed, "crack", i))
            width = feat.width_px * (2 if pose == Pose.OBLIQUE_LOW else 1)
            m = _mask(lambda d, p=pts, w=width: d.line(p, fill=255, width=w, joint="curve"))
            img = img * (1 - 0.68 * m)
            # Raking light catches the broken edge; oblique_low shows the raised lip.
            if light in (Lighting.LEFT, Lighting.RIGHT) or pose == Pose.OBLIQUE_LOW:
                dx = -width if light != Lighting.RIGHT else width
                dy = -3 if pose == Pose.OBLIQUE_LOW else 0
                lip = [(x + dx, y + dy) for x, y in pts]
                strength = 0.55 if pose == Pose.OBLIQUE_LOW else 0.22
                hm = _mask(lambda d, p=lip: d.line(p, fill=255, width=2), blur=0.6)
                img = img + (255 - img) * strength * hm

        elif isinstance(feat, Mark) and include_defects:
            # Same darkness and path style as a crack, but flat: no lip, no widening at oblique_low.
            pts = _jagged(Crack(points=feat.points, width_px=feat.width_px, jitter=feat.jitter),
                          _seed(scn.seed, "mark", i))
            m = _mask(lambda d, p=pts, w=feat.width_px: d.line(p, fill=255, width=w, joint="curve"))
            img = img * (1 - 0.62 * m)

        elif isinstance(feat, CastShadow) and include_defects:
            if light in feat.positions:
                pts = _band(feat.orientation, feat.positions[light], feat.extent, _seed(scn.seed, "shadow", i))
                m = _mask(lambda d, p=pts, w=feat.width_px: d.line(p, fill=255, width=w), blur=1.4)
                img = img * (1 - 0.62 * m)

        elif isinstance(feat, Glare) and include_defects:
            if light in feat.lights:
                cx, cy = _px(feat.center)
                r = feat.radius * PART_W
                yy, xx = np.mgrid[0:PART_H, 0:PART_W]
                g = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * (r / 2) ** 2)))[..., None]
                img = img + (255 - img) * 0.92 * g

    occ = scn.occlusion
    if include_defects and occ is not None and pose not in occ.visible_from:
        x0, y0 = _px((occ.region[0], occ.region[1]))
        x1, y1 = _px((occ.region[2], occ.region[3]))
        clamp = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(clamp)
        d.rounded_rectangle([x0, y0, x1, y1], radius=10, fill=(72, 74, 80), outline=(40, 40, 44), width=3)
        for bx in (x0 + 16, x1 - 16):
            d.ellipse([bx - 7, y0 + 10, bx + 7, y0 + 24], fill=(120, 122, 128))
        img = np.asarray(clamp, np.float32)

    return np.clip(img, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- camera space


def _perspective_coeffs(dst: list[tuple[float, float]], src: list[tuple[float, float]]) -> list[float]:
    """Coefficients mapping output pixels (dst quad) back to input pixels (src quad)."""
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    return np.linalg.solve(np.array(a, float), np.array(b, float)).tolist()


def _background(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    ys = np.linspace(0, 1, OUT_H, dtype=np.float32)[:, None, None]
    bg = 34 + 18 * ys + rng.normal(0, 1.5, (OUT_H, OUT_W, 1)).astype(np.float32)
    bg = np.repeat(bg, 3, axis=2) * np.array([1.0, 1.02, 1.06], np.float32)
    return Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8))


def render_view(scn: Scenario, pose: Pose, light: Lighting, *, include_defects: bool = True) -> Image.Image:
    part = Image.fromarray(render_part(scn, pose, light, include_defects=include_defects)).convert("RGBA")
    src = [(0, 0), (PART_W, 0), (PART_W, PART_H), (0, PART_H)]
    coeffs = _perspective_coeffs(POSE_QUADS[pose], src)
    warped = part.transform((OUT_W, OUT_H), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    out = _background(_seed(scn.seed, "bg"))
    out.paste(warped, (0, 0), warped)
    # Sensor noise varies by view, so two captures are never pixel-identical.
    rng = np.random.default_rng(_seed(scn.seed, pose.value, light.value, include_defects))
    arr = np.asarray(out, np.float32) + rng.normal(0, 2.5, (OUT_H, OUT_W, 1)).astype(np.float32)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def render_reference(scn: Scenario) -> Image.Image:
    """Golden sample: same part and expected features (seams), no defects, front + diffuse."""
    return render_view(scn, Pose.FRONT, Lighting.DIFFUSE, include_defects=False)


def part_to_image_xy(pose: Pose, x: float, y: float) -> tuple[float, float]:
    """Map a normalized part-face point into camera-image pixels for a pose."""
    src = [(0, 0), (PART_W, 0), (PART_W, PART_H), (0, PART_H)]
    c = _perspective_coeffs(src, POSE_QUADS[pose])  # forward mapping part -> image
    px, py = x * PART_W, y * PART_H
    den = c[6] * px + c[7] * py + 1
    return ((c[0] * px + c[1] * py + c[2]) / den, (c[3] * px + c[4] * py + c[5]) / den)
