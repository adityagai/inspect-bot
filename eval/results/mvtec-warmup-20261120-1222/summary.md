# MVTec AD static-image evaluation (20261120-1222)

4 held-out test images (2 defective, 2 good) from the bottle and tile categories, fixed by seed before any run. Single runs; pilot results.

| Metric | InspectBot | Prompt-only baseline | Target | Met |
| --- | --- | --- | --- | --- |
| Precision (defect) | 100% | 67% | ≥ 85% | ✓ |
| Recall (defect; abstain = miss) | 100% | 100% | ≥ 85% | ✓ |
| Decision coverage | 100% | 100% | ≥ 80% | ✓ |
| Accuracy | 100% | 75% | — |  |

| Counts | InspectBot | Baseline |
| --- | --- | --- |
| Defects found | 2 | 2 |
| Defects → insufficient evidence | 0 | 0 |
| Defects cleared as no defect | 0 | 0 |
| Good images flagged | 0 | 1 |
| Good images cleared | 2 | 1 |
| Good images → insufficient evidence | 0 | 0 |
| Errors | 0 | 0 |
| Mean latency (s) | 33.0 | 2.6 |

Grounding (definitive InspectBot reports citing the image and a category procedure): 4/4. Reference image used: 4/4.

## Recall by defect type

| Defect type | InspectBot | Baseline |
| --- | --- | --- |
| bottle/broken_large | 1/1 | 1/1 |
| tile/crack | 1/1 | 1/1 |

## Per image

| Image | Label | InspectBot | Baseline |
| --- | --- | --- | --- |
| bottle/test/broken_large/016.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| bottle/test/good/017.png | good | ✓ no_defect_detected | ✗ suspected_defect |
| tile/test/crack/006.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| tile/test/good/014.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
