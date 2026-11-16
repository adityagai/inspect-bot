# Evaluation results (20261116-1539)

20 scenarios: 10 resolvable, 10 unresolvable. Single runs per case; pilot results, not general performance claims.

| Metric | InspectBot | Prompt-only baseline |
| --- | --- | --- |
| Accuracy (all cases) | 20/20 (100%) | 8/20 (40%) |
| Resolvable cases correct | 10/10 (100%) | 4/10 (40%) |
| Unresolvable cases abstained (Insufficient evidence) | 10/10 (100%) | 4/10 (40%) |
| Defect recall (labeled defects reported Suspected) | 4/4 (100%) | 4/4 (100%) |
| False clears (defect present, reported No defect) | 0/8 (0%) | 0/8 (0%) |
| Incorrect definitive outcomes | 0/20 (0%) | 12/20 (60%) |
| Decision coverage on resolvable cases | 10/10 (100%) | 10/10 (100%) |
| Unnecessary escalations (resolvable cases) | 0/10 (0%) | 0/10 (0%) |
| Escalation recall (mandatory-review cases) | 10/10 (100%) | 4/10 (40%) |
| Grounding (definitive reports with valid evidence + category procedure) | 10/10 (100%) | — |
| Failed actions cited as evidence | 0 | — |
| Mean evidence actions, resolvable cases | 1.3 | — |
| Mean evidence actions, all cases | 1.75 | — |
| Budget violations (> 5 actions) | 0 | — |
| Failed-action recovery | 5/5 (100%) | — |
| Mean latency (s) | 43.0 | 2.5 |

**Incorrect definitive outcomes:** 0 vs 12 for the baseline (100% relative reduction; target ≥ 25%).

## Targets (Checkpoints 2.1 and 6.1)

| Metric | Target | Met |
| --- | --- | --- |
| resolvable_correct | >= 8/10 | ✓ |
| unresolvable_abstained | >= 8/10 | ✓ |
| false_clear | 0 | ✓ |
| escalation_recall | 100% | ✓ |
| grounding | 100% | ✓ |
| failed_actions_cited | 0 | ✓ |
| mean_actions_resolvable | <= 3 | ✓ |
| budget_violations | 0 | ✓ |

## Per case

| Case | Truth | InspectBot | Actions | Stop reason | Baseline |
| --- | --- | --- | --- | --- | --- |
| S1 Shadow on bracket | no_defect_detected | ✓ no_defect_detected | 1 | evidence requirements met | ✗ suspected_defect |
| S2 Real crack on tile | suspected_defect | ✓ suspected_defect | 2 | evidence requirements met | ✓ suspected_defect |
| S3 Expected seam on bottle | no_defect_detected | ✓ no_defect_detected | 0 | evidence requirements met | ✗ suspected_defect |
| S4 Occluded region with failed moves | insufficient_evidence | ✓ insufficient_evidence | 4 | planner found no action that could change the conclusion: The target region (x 0 | ✓ insufficient_evidence |
| S5 Part with no applicable guidance | insufficient_evidence | ✓ insufficient_evidence | 0 | no approved procedure for category 'pump_housing' | ✗ suspected_defect |
| V01 Shadow on bracket, light from right | no_defect_detected | ✓ no_defect_detected | 1 | evidence requirements met | ✗ suspected_defect |
| V02 Faint shadow on bracket, off-centre | no_defect_detected | ✓ no_defect_detected | 1 | evidence requirements met | ✗ suspected_defect |
| V03 Diagonal crack on tile | suspected_defect | ✓ suspected_defect | 2 | evidence requirements met | ✓ suspected_defect |
| V04 Short crack on tile | suspected_defect | ✓ suspected_defect | 3 | evidence requirements met | ✓ suspected_defect |
| V05 Mold seam on bottle, light from right | no_defect_detected | ✓ no_defect_detected | 0 | evidence requirements met | ✗ suspected_defect |
| V06 Mold seam plus a fixture shadow on bottle | no_defect_detected | ✓ no_defect_detected | 1 | evidence requirements met | ✗ suspected_defect |
| V07 Real crack on bracket | suspected_defect | ✓ suspected_defect | 2 | evidence requirements met | ✓ suspected_defect |
| V08 Clamp hides target; required view times out | insufficient_evidence | ✓ insufficient_evidence | 3 | planner proposals rejected 3 times in a row | ✓ insufficient_evidence |
| V09 Clamp hides target; required view unreachable (no defect underneath) | insufficient_evidence | ✓ insufficient_evidence | 4 | planner found no action that could change the conclusion: The target region (bra | ✓ insufficient_evidence |
| V10 Clamp hides target; side poses unavailable | insufficient_evidence | ✓ insufficient_evidence | 4 | planner found no action that could change the conclusion: The three candidate li | ✓ insufficient_evidence |
| V11 Valve body with no procedure | insufficient_evidence | ✓ insufficient_evidence | 0 | no approved procedure for category 'valve_body' | ✗ suspected_defect |
| V12 Gear cover with no procedure | insufficient_evidence | ✓ insufficient_evidence | 0 | no approved procedure for category 'gear_cover' | ✗ suspected_defect |
| V13 Surface mark on tile (no relief) | insufficient_evidence | ✓ insufficient_evidence | 5 | action budget exhausted | ✗ suspected_defect |
| V14 Off-centre mark on bottle under glare | insufficient_evidence | ✓ insufficient_evidence | 2 | planner proposals rejected 3 times in a row | ✗ suspected_defect |
| V15 Pump housing with a shadow, no procedure | insufficient_evidence | ✓ insufficient_evidence | 0 | no approved procedure for category 'pump_housing' | ✗ suspected_defect |
