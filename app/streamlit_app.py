"""InspectBot demo app.

    streamlit run app/streamlit_app.py

Replay: step through a saved run (demo_runs/ ships with S1-S5 and MVTec AD runs M1-M5).
Live:   run an inspection now (needs ANTHROPIC_API_KEY) and watch it update.

URL parameters (handy for demos and recording), e.g. http://localhost:8501/?run=S1&step=11
    run=<run folder name>   step=<event number>   open=rag   sidebar=collapsed
    eval=<results folder>   e.g. eval=mvtec-eval-20261120-1225 (with the Evaluation tab)
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from inspectbot.core.events import EventLog  # noqa: E402
from inspectbot.sim.scenario import list_scenarios, load_scenario  # noqa: E402
from inspectbot.ui.live_check import live_problems  # noqa: E402
from inspectbot.ui.replay import AGENT_COLORS, list_runs, run_label, tot_dot, view_at  # noqa: E402

DEMO_DIR, RUNS_DIR, EVAL_DIR = ROOT / "demo_runs", ROOT / "runs", ROOT / "eval" / "results"
OUTCOME_STYLE = {"suspected_defect": ("Suspected defect", "#d9534f"),
                 "no_defect_detected": ("No defect detected", "#2fb37a"),
                 "insufficient_evidence": ("Insufficient evidence: human review", "#e0a030")}

QP = st.query_params
st.set_page_config(page_title="InspectBot", page_icon="🔎", layout="wide",
                   initial_sidebar_state="collapsed" if QP.get("sidebar") == "collapsed" else "auto")
st.markdown("""<style>
.badge{display:inline-block;padding:6px 14px;border-radius:8px;color:white;font-weight:600;font-size:1.05rem}
.msg{border-left:4px solid #999;padding:4px 10px;margin:4px 0;background:rgba(127,127,127,.07);border-radius:4px;font-size:.88rem}
.msg b{font-size:.8rem;text-transform:uppercase;letter-spacing:.03em}
.small{font-size:.85rem;opacity:.85}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- live runs


def _live_worker(scenario_id: str, runs_root: Path, holder: dict) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        from inspectbot.agents.runner import CrewAIRunner
        from inspectbot.baseline.prompt_only import run_baseline
        from inspectbot.flow.gateway import LocalGateway
        from inspectbot.flow.inspection_flow import run_inspection
        from inspectbot.mcp_server.session import SessionManager

        mgr = SessionManager(runs_root)
        holder["manager"] = mgr
        runner = CrewAIRunner()
        if holder.get("baseline"):
            run_baseline(scenario_id, runner, runs_root)
        state = run_inspection(scenario_id, LocalGateway(mgr), runner)
        holder["task_id"] = state.task_id
    except Exception as e:  # noqa: BLE001 - shown in the UI
        holder["error"] = repr(e)
    finally:
        holder["done"] = True


def start_live(scenario_id: str, with_baseline: bool) -> None:
    runs_root = RUNS_DIR / "live"
    holder = {"done": False, "baseline": with_baseline, "started": time.time(), "scenario": scenario_id}
    threading.Thread(target=_live_worker, args=(scenario_id, runs_root, holder), daemon=True).start()
    st.session_state.live = holder


def live_run_dir() -> Path | None:
    h = st.session_state.get("live")
    if not h or "manager" not in h:
        return None
    sessions = h["manager"]._sessions
    if not sessions:
        return None
    tid = h.get("task_id") or next(iter(sessions))
    return h["manager"].store.root / tid


# ---------------------------------------------------------------- panels


def badge(outcome: str) -> str:
    label, color = OUTCOME_STYLE.get(outcome, (outcome, "#888"))
    return f'<span class="badge" style="background:{color}">{label}</span>'


def baseline_for(run_dir: Path, scenario_id: str) -> dict | None:
    for cand in (run_dir.parent / "baseline" / f"{scenario_id}.json", DEMO_DIR / "baseline" / f"{scenario_id}.json"):
        if cand.exists():
            return json.loads(cand.read_text())
    return None


def render_run(run_dir: Path, step: int | None) -> None:
    v = view_at(run_dir, step)
    if not v.task:
        st.info("Waiting for the inspection to start…")
        return
    t = v.task
    st.markdown(f"### {t['scenario_id']} · {t['object_category'].replace('_', ' ')}  "
                f"<span class='small'>task {v.task_id}</span>", unsafe_allow_html=True)
    st.markdown(f"**Goal:** {t['goal']}  ·  target region {t['target_region']}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Evidence actions", f"{v.actions_used} / 5")
    m2.metric("Failed attempts", sum(1 for a in v.attempts if a["status"] != "success"))
    m3.metric("Observations", len(v.observations))
    m4.metric("ToT evaluations", len(v.tot["candidates"]) if v.tot else 0, help="max 15, once per inspection")

    left, right = st.columns([1.05, 1])
    with left:
        if t.get("static_image"):
            st.markdown("#### Static image")
            st.caption("MVTec AD photo from a fixed camera: the camera cannot move and the lighting cannot change. "
                       "The only extra evidence is the approved reference image.")
        else:
            st.markdown("#### Robot cell")
            st.markdown(v.schematic_svg, unsafe_allow_html=True)
        if v.current_obs:
            o = v.current_obs
            cap = f"{o['obs_id']} · {o['kind']}" + (f" · {o['pose']}/{o['light']}" if o.get("pose") else "")
            if t.get("static_image"):
                st.image(str(v.image_path(o)), caption=cap, width=460)
            else:
                st.image(str(v.image_path(o)), caption=cap, use_container_width=True)
        if v.observations:
            st.markdown("**All observations** (failed attempts never produce an image)")
            cols = st.columns(6)
            for i, o in enumerate(v.observations):
                with cols[i % len(cols)]:
                    st.image(str(v.image_path(o)), caption=f"{o['obs_id']} " + (f"{o['pose']}/{o['light']}" if o.get("pose") else o["kind"]),
                             use_container_width=True)
    with right:
        st.markdown("#### Agent timeline")
        for e in v.messages[-14:]:
            color = AGENT_COLORS.get(e["sender"], "#999")
            refs = f" <span class='small'>[{', '.join(e['obs_refs'])}]</span>" if e.get("obs_refs") else ""
            src = f" <span class='small'>⟨{', '.join(e['source_ids'][:3])}⟩</span>" if e.get("source_ids") else ""
            st.markdown(f"<div class='msg' style='border-left-color:{color}'><b style='color:{color}'>"
                        f"{e['sender']} → {e['recipient']} · {e['type']}</b><br>{e['content'][:420]}{refs}{src}</div>",
                        unsafe_allow_html=True)
        with st.expander("Robot actions", expanded=False):
            for a in v.attempts:
                ok = "✅" if a["status"] == "success" else "❌"
                st.markdown(f"{ok} `{a['tool']}` {json.dumps(a['args'])} → **{a['status']}**"
                            + (f" — {a['error']}" if a.get("error") else ""))

    if v.retrieval:
        with st.expander("📚 Retrieved procedures",
                         expanded=bool(v.retrieval.get("missing_guidance")) or QP.get("open") == "rag"):
            for p in v.retrieval["passages"]:
                st.markdown(f"✅ **{p['source_id']}** v{p['version']} · {p['category']} · similarity {p['score']}")
            for r in v.retrieval["rejected"]:
                st.markdown(f"🚫 **{r['source_id']}** — {r['reason']}")
            if v.retrieval.get("missing_guidance"):
                st.warning(f"Missing guidance: {v.retrieval['missing_guidance']}")
    if v.tot:
        with st.expander("🌳 Tree-of-Thought search", expanded=True):
            st.graphviz_chart(tot_dot(v.tot), use_container_width=False)
            st.caption("Green = selected branch; grey = pruned (score < 5, invalid, or outside the beam of 2). "
                       "Expected evidence on each node is a prediction, never an observation.")

    if v.report:
        r = v.report
        st.markdown('<div id="report-anchor"></div>', unsafe_allow_html=True)  # scroll target for demos
        st.markdown("---")
        st.markdown(f"#### Report &nbsp; {badge(r['outcome'])}", unsafe_allow_html=True)
        st.write(r["summary"])
        for ev in r.get("evidence", []):
            st.markdown(f"- **Evidence:** {', '.join(ev['obs_ids'])} · procedures: {', '.join(ev.get('source_ids', [])) or '—'}")
        if r.get("scope_note"):
            scope = r["scope_note"]
            if t.get("static_image") and "viewed as" in scope:  # runs saved before the static scope wording existed
                scope = ("Covers only what is visible in this single fixed-camera image, compared with the approved "
                         "reference. Not a safety certification.")
            st.caption(f"Scope: {scope}")
        if r.get("remaining_uncertainty"):
            st.markdown("**Remaining uncertainty:** " + "; ".join(r["remaining_uncertainty"]))
        if r.get("failed_attempt_ids"):
            st.markdown(f"**Failed actions (not evidence):** {', '.join(r['failed_attempt_ids'])}")
        b = baseline_for(run_dir, t["scenario_id"])
        if b:
            truth = ""
            if t.get("static_image") and b.get("image"):
                truth = f" &nbsp; <span class='small'>dataset label: {b['image'].split('/')[2]}</span>"
            st.markdown(f"**Prompt-only baseline on the same first image:** {badge(b['outcome'])}{truth}",
                        unsafe_allow_html=True)
            st.caption(b["rationale"][:400])
        if r.get("needs_human_review"):
            human_review_panel(run_dir)


def human_review_panel(run_dir: Path) -> None:
    st.markdown("#### 🧑‍🔧 Human review")
    path = run_dir / "review.json"
    reviews = json.loads(path.read_text()) if path.exists() else []
    for rv in reviews:
        st.success(f"{rv['reviewer']} · {rv['decision']} · {rv['note']} ({rv['at'][:16]})")
    with st.form(f"review-{run_dir.name}"):
        decision = st.radio("Decision", ["Clarify the task", "Supply approved guidance",
                                         "Authorize one more bounded inspection", "Close the case"], horizontal=True)
        note = st.text_input("Note for the record")
        reviewer = st.text_input("Reviewer", value="reviewer")
        if st.form_submit_button("Record decision"):
            entry = {"reviewer": reviewer, "decision": decision, "note": note,
                     "at": datetime.now(timezone.utc).isoformat()}
            path.write_text(json.dumps(reviews + [entry], indent=2))
            EventLog(run_dir / "events.jsonl").emit("human_review", **entry)
            st.rerun()


def evaluation_tab() -> None:
    results = sorted(EVAL_DIR.glob("*/summary.md"), reverse=True) if EVAL_DIR.exists() else []
    if not results:
        st.info("No evaluation results yet. Run `python eval/run_eval.py`.")
        return
    def label(p: Path) -> str:
        n = p.parent.name
        if n.startswith("mvtec-eval"):
            return f"MVTec AD · 40 real images (bottle, tile) · {n}"
        if n.startswith("mvtec-warmup"):
            return f"MVTec AD · 4 warm-up images · {n}"
        return f"Simulation · 20 scenarios · {n}"

    rank = lambda p: (0 if not p.parent.name.startswith("mvtec") else 1 if "eval" in p.parent.name else 2)  # noqa: E731
    results = sorted(results, key=rank)  # stable: keeps the newest-first order inside each group
    wanted = QP.get("eval")
    idx = next((i for i, p in enumerate(results) if p.parent.name == wanted), 0)
    choice = st.selectbox("Evaluation run", results, index=idx, format_func=label)
    st.markdown(choice.read_text())


# ---------------------------------------------------------------- layout

st.title("🔎 InspectBot")
st.caption("Multi-agent visual inspection in a simulated robot cell and on real MVTec AD images · "
           "CrewAI · LangChain RAG · MCP · Claude")
tab_run, tab_eval, tab_about = st.tabs(["Inspection", "Evaluation", "How it works"])

with st.sidebar:
    mode = st.radio("Mode", ["Replay", "Live"], horizontal=True)
    if mode == "Replay":
        runs = list_runs(DEMO_DIR, RUNS_DIR)
        if not runs:
            st.warning("No saved runs found.")
            run_dir = None
        else:
            wanted = QP.get("run")
            idx = next((i for i, r in enumerate(runs) if r.name == wanted), 0)
            run_dir = st.selectbox("Saved run", runs, index=idx, format_func=run_label)
            total = view_at(run_dir).total_steps
            try:
                start = min(max(int(QP.get("step", total)), 1), total) if run_dir.name == wanted else total
            except ValueError:
                start = total
            step = st.slider("Step", 1, total, start)
            st.caption(f"Event {step} of {total}")
    else:
        scenarios = list_scenarios(include_eval=True)
        sid = st.selectbox("Scenario", [s.id for s in scenarios],
                           format_func=lambda i: f"{i} · {load_scenario(i).name}")
        with_baseline = st.checkbox("Also run the prompt-only baseline", value=True)
        live = st.session_state.get("live")
        running = bool(live and not live["done"])
        problems = live_problems(ROOT)
        if problems:
            st.warning("**Live mode isn't set up yet.** Replay mode works without any of this.\n\n"
                       + "\n".join(f"- {p}" for p in problems)
                       + "\n\nThen stop the app (Ctrl+C) and run `streamlit run app/streamlit_app.py` again.")
        if st.button("▶ Start inspection", disabled=running or bool(problems), type="primary"):
            start_live(sid, with_baseline)
            st.rerun()
        if live:
            st.caption(f"{live['scenario']}: {'running' if not live['done'] else 'finished'} · "
                       f"{time.time() - live['started']:.0f}s")
            if live.get("error"):
                st.error(live["error"])
        run_dir, step = live_run_dir(), None

with tab_run:
    if run_dir:
        render_run(run_dir, step)
    elif mode == "Live":
        st.info("Pick a scenario and press Start. Each step appears here as the agents work. "
                "Live runs call Claude and use your Anthropic credits.")

with tab_eval:
    evaluation_tab()

with tab_about:
    st.markdown((ROOT / "README.md").read_text().split("## Quick start")[0])

if mode == "Live" and st.session_state.get("live") and not st.session_state.live["done"]:
    time.sleep(1.5)
    st.rerun()
