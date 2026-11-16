"""Run InspectBot (and optionally the baseline) on a scenario.

    python -m inspectbot.flow.run S1                     # in-process tools (no server needed)
    python -m inspectbot.flow.run S1 --mcp               # through the running MCP server
    python -m inspectbot.flow.run S1 S4 --baseline       # also run the prompt-only baseline
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import warnings

from dotenv import load_dotenv


def _trace(state, gateway) -> None:
    rec = gateway.call("get_task_record", task_id=state.task_id)
    for a in rec["attempts"]:
        mark = "ok " if a["status"] == "success" else "XX "
        print(f"   {mark}{a['tool']:<16} {json.dumps(a['args']):<28} -> {a['status']}"
              + (f"  [{a['obs_id']}]" if a["obs_id"] else ""))
    for p in state.plans:
        if not p["accepted"]:
            print(f"   (rejected plan: {p['action']} - {p['guard']})")
    for oid, i in state.inspections.items():
        v = i["view"]
        print(f"   {oid} {v['kind']} {v['pose']}/{v['light']}: visible={i['target_visible']} "
              f"anomaly={i['anomaly_present']} discontinuity={i['surface_discontinuity']} "
              f"matches_ref={i['matches_reference']}")


def main() -> None:
    load_dotenv()
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenarios", nargs="+")
    ap.add_argument("--mcp", action="store_true", help="use the MCP server over HTTP")
    ap.add_argument("--url", default=f"http://127.0.0.1:{os.getenv('INSPECTBOT_MCP_PORT', '8765')}/mcp")
    ap.add_argument("--baseline", action="store_true")
    a = ap.parse_args()

    from inspectbot.agents.runner import CrewAIRunner
    from inspectbot.baseline.prompt_only import run_baseline
    from inspectbot.flow.gateway import LocalGateway, MCPGateway
    from inspectbot.flow.inspection_flow import run_inspection

    gateway = MCPGateway(a.url) if a.mcp else LocalGateway()
    runner = CrewAIRunner()
    for sid in a.scenarios:
        t0 = time.time()
        state = run_inspection(sid, gateway, runner)
        r = state.report or {}
        print(f"\n== {sid}  task {state.task_id}  ({time.time() - t0:.0f}s)")
        _trace(state, gateway)
        print(f"   OUTCOME: {r.get('outcome')}  | stop: {state.stop_reason}")
        print(f"   {r.get('summary', '')[:400]}")
        if a.baseline:
            b = run_baseline(sid, runner)
            print(f"   BASELINE: {b['outcome']}  | {b['rationale'][:200]}")


if __name__ == "__main__":
    main()
