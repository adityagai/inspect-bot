"""MCP server tests through a real in-memory MCP client session."""

import json

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from inspectbot.mcp_server.server import build_server
from inspectbot.mcp_server.session import SessionManager

EXPECTED_TOOLS = {
    "start_inspection", "move_camera", "set_lighting", "zoom_region", "get_reference",
    "get_observation_image", "get_task_record", "append_finding", "post_message", "submit_report",
}


def _payload(result):
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


async def _run(tmp_path, fn):
    server = build_server(SessionManager(tmp_path))
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        return await fn(client)


def run(tmp_path, fn):
    return anyio.run(_run, tmp_path, fn)


def test_lists_all_tools(tmp_path):
    async def go(c):
        return {t.name for t in (await c.list_tools()).tools}
    assert run(tmp_path, go) == EXPECTED_TOOLS


def test_s1_flow_over_mcp(tmp_path):
    async def go(c):
        start = _payload(await c.call_tool("start_inspection", {"scenario_id": "S1"}))
        tid = start["task_id"]
        assert "ground_truth" not in json.dumps(start)
        assert start["initial_observation"]["obs_id"] == "obs_01"
        lit = _payload(await c.call_tool("set_lighting", {"task_id": tid, "setting": "top"}))
        img = await c.call_tool("get_observation_image", {"task_id": tid, "obs_id": lit["observation"]["obs_id"]})
        rec = _payload(await c.call_tool("get_task_record", {"task_id": tid}))
        return lit, img, rec
    lit, img, rec = run(tmp_path, go)
    assert lit["status"] == "success" and lit["budget"]["actions_remaining"] == 4
    assert img.content[0].type == "image" and img.content[0].mimeType == "image/png"
    assert [a["tool"] for a in rec["attempts"]] == ["initial_capture", "set_lighting"]


def test_s4_failures_never_become_evidence(tmp_path):
    async def go(c):
        tid = _payload(await c.call_tool("start_inspection", {"scenario_id": "S4"}))["task_id"]
        r1 = _payload(await c.call_tool("move_camera", {"task_id": tid, "pose": "left_45"}))
        r2 = _payload(await c.call_tool("move_camera", {"task_id": tid, "pose": "right_45"}))
        bad_finding = await c.call_tool("append_finding", {"task_id": tid, "obs_ids": ["obs_02"],
                                                           "description": "crack seen from left"})
        rec = _payload(await c.call_tool("get_task_record", {"task_id": tid}))
        return r1, r2, bad_finding, rec
    r1, r2, bad_finding, rec = run(tmp_path, go)
    assert r1["status"] == "unreachable" and "observation" not in r1
    assert r2["status"] == "timeout" and "observation" not in r2
    assert r2["budget"]["actions_remaining"] == 3  # failures are charged
    assert bad_finding.isError  # obs_02 does not exist: failed moves produced nothing
    assert [o["obs_id"] for o in rec["observations"]] == ["obs_01"]


def test_budget_exhaustion_is_logged_not_executed(tmp_path):
    async def go(c):
        tid = _payload(await c.call_tool("start_inspection", {"scenario_id": "S1"}))["task_id"]
        for light in ["right", "top", "diffuse", "left", "top"]:
            _payload(await c.call_tool("set_lighting", {"task_id": tid, "setting": light}))
        sixth = _payload(await c.call_tool("move_camera", {"task_id": tid, "pose": "top"}))
        rec = _payload(await c.call_tool("get_task_record", {"task_id": tid}))
        return sixth, rec
    sixth, rec = run(tmp_path, go)
    assert sixth["status"] == "budget_exhausted" and "observation" not in sixth
    assert sixth["cell"]["pose"] == "front"  # the arm did not move
    assert rec["budget"]["actions_used"] == 5


def test_invalid_enum_rejected_by_schema(tmp_path):
    async def go(c):
        tid = _payload(await c.call_tool("start_inspection", {"scenario_id": "S1"}))["task_id"]
        return await c.call_tool("move_camera", {"task_id": tid, "pose": "upside_down"})
    assert run(tmp_path, go).isError


def test_unknown_task_is_tool_error(tmp_path):
    async def go(c):
        return await c.call_tool("get_task_record", {"task_id": "task_nope"})
    assert run(tmp_path, go).isError


def test_finding_and_message_roundtrip(tmp_path):
    async def go(c):
        tid = _payload(await c.call_tool("start_inspection", {"scenario_id": "S2"}))["task_id"]
        f = _payload(await c.call_tool("append_finding", {
            "task_id": tid, "obs_ids": ["obs_01"], "description": "dark jagged line",
            "hypotheses": ["crack", "scratch"], "uncertainty": "medium", "region": [0.4, 0.2, 0.55, 0.8]}))
        m = _payload(await c.call_tool("post_message", {
            "task_id": tid, "sender": "inspection", "recipient": "verification", "type": "finding",
            "content": "Suspected anomaly; needs oblique view", "obs_refs": ["obs_01"]}))
        bad = await c.call_tool("post_message", {
            "task_id": tid, "sender": "inspection", "recipient": "verification", "type": "finding",
            "content": "x", "obs_refs": ["obs_09"]})
        rec = _payload(await c.call_tool("get_task_record", {"task_id": tid}))
        return f, m, bad, rec
    f, m, bad, rec = run(tmp_path, go)
    assert f["recorded"] and m["message_id"].startswith("msg_")
    assert bad.isError
    assert rec["findings"][0]["hypotheses"] == ["crack", "scratch"]


def test_events_and_record_persisted(tmp_path):
    mgr = SessionManager(tmp_path)
    tid = mgr.start("S3")["task_id"]
    mgr.run_tool(tid, "get_reference", category="glass_bottle")
    events = mgr.get(tid).events.read()
    assert [e["kind"] for e in events] == ["task_started", "tool_result", "tool_result"]
    assert (tmp_path / tid / "task_record.json").exists()
    assert mgr.store.load(tid).observations[-1].source_id == "REF-GLASS_BOTTLE-v1"


@pytest.mark.parametrize("sid", ["S1", "S2", "S3", "S4", "S5"])
def test_every_scenario_starts(tmp_path, sid):
    out = SessionManager(tmp_path).start(sid)
    assert out["task"]["scenario_id"] == sid and out["budget"]["actions_remaining"] == 5


def test_submit_report_rules(tmp_path):
    mgr = SessionManager(tmp_path)
    tid = mgr.start("S4")["task_id"]
    mgr.run_tool(tid, "move_camera", pose="left_45")  # unreachable
    from inspectbot.mcp_server.session import SessionError
    from pydantic import ValidationError
    with pytest.raises(SessionError):  # cites an observation that never existed
        mgr.submit_report(tid, {"outcome": "suspected_defect", "summary": "s",
                                "evidence": [{"claim": "crack", "obs_ids": ["obs_02"]}]})
    with pytest.raises(ValidationError):  # insufficient evidence must request review
        mgr.submit_report(tid, {"outcome": "insufficient_evidence", "summary": "s"})
    out = mgr.submit_report(tid, {"outcome": "insufficient_evidence", "summary": "target hidden",
                                  "needs_human_review": True})
    assert out["outcome"] == "insufficient_evidence"
    saved = json.loads((tmp_path / tid / "report.json").read_text())
    assert saved["failed_attempt_ids"] == ["act_02"]
