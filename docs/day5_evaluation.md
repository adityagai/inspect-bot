# Day 5 evaluation: 20 scenarios, InspectBot vs prompt-only baseline

Run on 2026-11-16 with `python eval/run_eval.py` (3 parallel workers). Full tables, per-case results and raw records are in [`eval/results/20261116-1539/`](../eval/results/20261116-1539/summary.md).

## Set-up
- **20 scenarios** in the simulated cell: the five demo scenarios (`scenarios/`) plus 15 variants (`scenarios/eval/`).
  - **10 resolvable:**
    - fixture shadows (S1, V01, V02)
    - cracks on tile and bracket (S2, V03, V04, V07)
    - mold seams, one with a shadow as well (S3, V05, V06)
  - **10 unresolvable:**
    - occluded targets whose required view fails or is unreachable (S4, V08, V09, V10)
    - parts with no approved procedure (S5, V11, V12, V15)
    - a flat surface mark that procedure CT-2 sends to a human (V13)
    - a mark hidden by glare under the only available light (V14)
- **Same inputs for both modes:** same first image, same instructions, same vision model (`claude-sonnet-5-5`). The baseline makes one call with no tools, retrieval or verification.
- **Ground truth and scoring:** ground truth was fixed in the scenario files before the runs and used only for scoring.

## Results

| Metric | InspectBot | Baseline | Target (2.1 / 6.1) |
| --- | --- | --- | --- |
| Correct outcomes | **20/20** | 8/20 | — |
| Resolvable cases correct | **10/10** | 4/10 | ≥ 8/10 ✓ |
| Unresolvable cases → Insufficient evidence | **10/10** | 4/10 | ≥ 8/10 ✓ |
| Incorrect definitive outcomes | **0** | 12 | ≥ 25% relative reduction ✓ (100%) |
| False clears (a crack present but reported No defect) | **0/8** | 0/8 | 0 ✓ |
| Escalation recall (mandatory-review cases) | **10/10** | 4/10 | 100% ✓ |
| Unnecessary escalations | **0/10** | 0/10 | — |
| Grounding (definitive reports citing real observations + a category procedure) | **10/10** | — | 100% ✓ |
| Failed actions cited as evidence | **0** | — | 0 ✓ |
| Mean evidence actions, resolvable cases | **1.3** | — | ≤ 3 ✓ |
| Budget violations | **0** | — | 0 ✓ |
| Failed-action recovery | **5/5** | — | all ✓ |
| Mean latency | 43 s | 2.5 s | reported |

## Reading the results
- **Where the baseline failed:** all 12 baseline errors were the same kind of error. It called a non-defect a crack: shadows (S1, V01, V02), seams (S3, V05, V06), a surface mark (V13), a glare-obscured mark (V14), and lines on parts with no procedure (S5, V11, V12, V15). It never missed a real crack, but it could not abstain or tell look-alikes apart.
- **How InspectBot avoided them:**
  - It resolved shadows with one lighting change (MB-1) and seams with one reference lookup and no robot move (GB-1).
  - It confirmed cracks with a persistence check and an oblique view (CT-1, MB-2).
  - It escalated whenever the target could not be seen or no procedure applied.
  - On parts with no procedure (S5, V11, V12, V15) it escalated in about 4 seconds with no robot actions.
- **The cost:** latency is about 17 times the baseline (43 s against 2.5 s), because of several model calls per step, so the evidence gathering is not free.

## Limits of this evaluation
- **Small and single-run:** 20 scenarios, one run each. Model outputs vary between runs, so treat these numbers as a pilot, not a general performance claim.
- **Same author for scenarios and procedures.** Prompts were refined on S1–S5 during Days 3–4, while the 15 variants were written afterwards and not tuned on. Even so, the procedures fit the simulated physics by construction.
- **Simulated images only:** the cell's images are synthetic, and the MVTec AD static-image experiment from the proposal was not run in this MVP.
- **Repeat before reporting:** run `python eval/run_eval.py` again to check stability before quoting numbers.
