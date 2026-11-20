"""Static-image mode (MVTec): session setup, tool behaviour and scoring, with no API calls."""

import sys
from pathlib import Path

import pytest
from PIL import Image

from inspectbot.mcp_server.session import SessionManager

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from run_mvtec import score  # noqa: E402


@pytest.fixture
def imgs(tmp_path):
    a, r = tmp_path / "a.png", tmp_path / "ref.png"
    Image.new("RGB", (64, 64), (120, 120, 120)).save(a)
    Image.new("RGB", (64, 64), (121, 121, 121)).save(r)
    return a, r


def test_static_session_tools(tmp_path, imgs):
    a, r = imgs
    mgr = SessionManager(tmp_path / "runs")
    task = mgr.start_static(str(a), "ceramic_tile", reference_path=str(r), case_id="t1")
    s = mgr.get(task["task_id"])
    assert s.cell.scenario.is_static
    pub = s.cell.scenario.public_view()
    assert pub["static_image"] is True and pub["poses"] == [] and pub["lights"] == []
    assert len(s.record.observations) == 1  # the photo itself
    ref = s.cell.get_reference("ceramic_tile")
    assert ref.observation is not None and ref.observation.kind == "reference"


def test_static_rejects_missing_or_bad_file(tmp_path):
    mgr = SessionManager(tmp_path / "runs")
    with pytest.raises(Exception):
        mgr.start_static(str(tmp_path / "nope.png"), "glass_bottle")
    bad = tmp_path / "x.txt"
    bad.write_text("hi")
    with pytest.raises(Exception):
        mgr.start_static(str(bad), "glass_bottle")


def test_score_abstain_on_defect_is_a_miss():
    mk = lambda lab, out: {"image": f"{lab}{out}", "category": "tile", "defect_type": "crack" if lab == "defect" else "good",  # noqa: E731
                           "label": lab, "mode": "baseline", "outcome": out, "latency_s": 1}
    cases = [mk("defect", "suspected_defect"), mk("defect", "insufficient_evidence"),
             mk("good", "no_defect_detected"), mk("good", "suspected_defect")]
    m = score(cases)
    assert m["precision"] == 0.5 and m["recall"] == 0.5
    assert m["decision_coverage"] == 0.75 and m["fn_abstained"] == 1 and m["fp"] == 1


def test_saved_mvtec_runs_replay():
    from inspectbot.ui.replay import view_at

    root = Path(__file__).resolve().parents[1] / "demo_runs"
    expected = {"M1": "no_defect_detected", "M2": "suspected_defect", "M3": "insufficient_evidence"}
    for name, outcome in expected.items():
        v = view_at(root / name)
        assert v.task["static_image"] is True
        assert v.report["outcome"] == outcome
        kinds = [o["kind"] for o in v.observations]
        assert kinds == ["camera", "reference"] and all(v.image_path(o).exists() for o in v.observations)
