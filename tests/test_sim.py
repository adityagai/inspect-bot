import numpy as np
import pytest

from inspectbot.core.models import ActionStatus, Lighting, Pose
from inspectbot.sim.cell import InspectionCell
from inspectbot.sim.renderer import part_to_image_xy, render_reference, render_view
from inspectbot.sim.scenario import list_scenarios, load_scenario
from inspectbot.sim.schematic import render_schematic


def _line_contrast(img, pose: Pose, x_norm: float, y_range=(0.3, 0.7), half=4, ring=18) -> float:
    """Mean brightness of a thin vertical band divided by its surroundings (lower = darker line)."""
    a = np.asarray(img.convert("L"), np.float32)
    vals_band, vals_ring = [], []
    for y in np.linspace(*y_range, 20):
        cx, cy = part_to_image_xy(pose, x_norm, y)
        cx, cy = int(round(cx)), int(round(cy))
        vals_band.append(a[cy, cx - half: cx + half + 1].min())
        vals_ring.append(np.r_[a[cy, cx - ring - 6: cx - ring], a[cy, cx + ring: cx + ring + 6]].mean())
    return float(np.mean(vals_band) / np.mean(vals_ring))


def test_all_scenarios_load():
    ids = [s.id for s in list_scenarios()]
    assert ids == ["S1", "S2", "S3", "S4", "S5"]


def test_render_is_deterministic():
    s = load_scenario("S1")
    a = np.asarray(render_view(s, Pose.FRONT, Lighting.LEFT))
    b = np.asarray(render_view(s, Pose.FRONT, Lighting.LEFT))
    assert a.shape == (480, 640, 3) and np.array_equal(a, b)


def test_s1_shadow_disappears_under_top_light():
    s = load_scenario("S1")
    left = _line_contrast(render_view(s, Pose.FRONT, Lighting.LEFT), Pose.FRONT, 0.47)
    top = _line_contrast(render_view(s, Pose.FRONT, Lighting.TOP), Pose.FRONT, 0.47)
    assert left < 0.75, "shadow should be a visible dark line under left light"
    assert top > 0.9, "shadow should vanish under top light"


def test_s2_crack_persists_under_top_light():
    s = load_scenario("S2")
    top = render_view(s, Pose.FRONT, Lighting.TOP)
    a = np.asarray(top.convert("L"), np.float32)
    # The crack polyline runs near x=0.42-0.53; the darkest pixels in the target region must be dark.
    x0, y0 = map(int, part_to_image_xy(Pose.FRONT, 0.35, 0.2))
    x1, y1 = map(int, part_to_image_xy(Pose.FRONT, 0.60, 0.8))
    assert a[y0:y1, x0:x1].min() < 0.45 * np.median(a[y0:y1, x0:x1])


def test_s3_seam_is_on_reference():
    s = load_scenario("S3")
    assert _line_contrast(render_reference(s), Pose.FRONT, 0.50) < 0.8


def test_s4_failures_leave_no_observation(tmp_path):
    cell = InspectionCell(load_scenario("S4"), tmp_path)
    cell.capture_initial()
    r1 = cell.move_camera("left_45")
    r2 = cell.move_camera("right_45")
    assert r1.attempt.status == ActionStatus.UNREACHABLE and r1.observation is None
    assert r2.attempt.status == ActionStatus.TIMEOUT and r2.observation is None
    assert cell.pose == Pose.FRONT  # failed moves do not change the arm pose
    r3 = cell.move_camera("top")
    assert r3.attempt.succeeded and r3.observation.pose == Pose.TOP


def test_scripted_failure_times(tmp_path, monkeypatch):
    s = load_scenario("S4")
    s.scripted_failures[0].times = 1
    cell = InspectionCell(s, tmp_path)
    assert cell.move_camera("right_45").attempt.status == ActionStatus.TIMEOUT
    assert cell.move_camera("right_45").attempt.succeeded


def test_invalid_args_and_unsupported(tmp_path):
    s = load_scenario("S1")
    s.supported_lights = [Lighting.LEFT, Lighting.TOP]
    cell = InspectionCell(s, tmp_path)
    assert cell.move_camera("upside_down").attempt.status == ActionStatus.INVALID_ARGS
    assert cell.set_lighting("diffuse").attempt.status == ActionStatus.UNSUPPORTED
    assert cell.set_lighting("top").attempt.counts_against_budget


def test_zoom_is_aux_and_links_parent(tmp_path):
    cell = InspectionCell(load_scenario("S1"), tmp_path)
    first = cell.capture_initial()
    z = cell.zoom_region(first.observation.obs_id, [250, 100, 350, 300])
    assert z.attempt.succeeded and not z.attempt.counts_against_budget
    assert z.observation.parent_obs_id == first.observation.obs_id
    assert z.image.size == (200, 400)
    bad = cell.zoom_region(first.observation.obs_id, [0, 0, 5, 5])
    assert bad.attempt.status == ActionStatus.INVALID_ARGS


@pytest.mark.parametrize("sid,expected", [("S3", ActionStatus.SUCCESS), ("S5", ActionStatus.NOT_FOUND)])
def test_reference_availability(tmp_path, sid, expected):
    s = load_scenario(sid)
    cell = InspectionCell(s, tmp_path)
    assert cell.get_reference(s.category).attempt.status == expected


def test_reference_wrong_category(tmp_path):
    cell = InspectionCell(load_scenario("S3"), tmp_path)
    assert cell.get_reference("ceramic_tile").attempt.status == ActionStatus.NOT_FOUND


def test_public_view_hides_ground_truth():
    view = load_scenario("S1").public_view()
    assert "ground_truth" not in view and "features" not in view


def test_schematic_svg():
    svg = render_schematic(Pose.LEFT_45, Lighting.TOP, failed_pose=Pose.RIGHT_45, category="metal_bracket", step=2)
    assert svg.startswith("<svg") and "failed: right_45" in svg
