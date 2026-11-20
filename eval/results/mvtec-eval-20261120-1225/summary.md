# MVTec AD static-image evaluation (20261120-1225)

40 held-out test images (20 defective, 20 good) from the bottle and tile categories, fixed by seed before any run. Single runs; pilot results.

| Metric | InspectBot | Prompt-only baseline | Target | Met |
| --- | --- | --- | --- | --- |
| Precision (defect) | 86% | 75% | ≥ 85% | ✓ |
| Recall (defect; abstain = miss) | 95% | 90% | ≥ 85% | ✓ |
| Decision coverage | 92% | 100% | ≥ 80% | ✓ |
| Accuracy | 82% | 80% | — |  |

| Counts | InspectBot | Baseline |
| --- | --- | --- |
| Defects found | 19 | 18 |
| Defects → insufficient evidence | 0 | 0 |
| Defects cleared as no defect | 1 | 2 |
| Good images flagged | 3 | 6 |
| Good images cleared | 14 | 14 |
| Good images → insufficient evidence | 3 | 0 |
| Errors | 0 | 0 |
| Mean latency (s) | 25.3 | 2.5 |

Grounding (definitive InspectBot reports citing the image and a category procedure): 37/37. Reference image used: 40/40.

## Recall by defect type

| Defect type | InspectBot | Baseline |
| --- | --- | --- |
| bottle/broken_large | 4/4 | 4/4 |
| bottle/broken_small | 3/3 | 3/3 |
| bottle/contamination | 2/3 | 2/3 |
| tile/crack | 2/2 | 2/2 |
| tile/glue_strip | 2/2 | 2/2 |
| tile/gray_stroke | 2/2 | 2/2 |
| tile/oil | 2/2 | 2/2 |
| tile/rough | 2/2 | 1/2 |

## Per image

| Image | Label | InspectBot | Baseline |
| --- | --- | --- | --- |
| bottle/test/broken_large/000.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| bottle/test/broken_large/003.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| bottle/test/broken_large/007.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| bottle/test/broken_large/008.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| bottle/test/broken_small/006.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| bottle/test/broken_small/017.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| bottle/test/broken_small/021.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| bottle/test/contamination/008.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| bottle/test/contamination/011.png | defect | ✓ suspected_defect | ✗ no_defect_detected |
| bottle/test/contamination/020.png | defect | ✗ no_defect_detected | ✓ suspected_defect |
| bottle/test/good/000.png | good | ✓ no_defect_detected | ✗ suspected_defect |
| bottle/test/good/001.png | good | ✗ suspected_defect | ✗ suspected_defect |
| bottle/test/good/004.png | good | ✗ suspected_defect | ✗ suspected_defect |
| bottle/test/good/006.png | good | ✓ no_defect_detected | ✗ suspected_defect |
| bottle/test/good/009.png | good | ✓ no_defect_detected | ✗ suspected_defect |
| bottle/test/good/011.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| bottle/test/good/015.png | good | ✗ suspected_defect | ✓ no_defect_detected |
| bottle/test/good/016.png | good | ✗ insufficient_evidence | ✗ suspected_defect |
| bottle/test/good/018.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| bottle/test/good/019.png | good | ✗ insufficient_evidence | ✓ no_defect_detected |
| tile/test/crack/005.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| tile/test/crack/014.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| tile/test/glue_strip/006.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| tile/test/glue_strip/010.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| tile/test/good/005.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| tile/test/good/006.png | good | ✗ insufficient_evidence | ✓ no_defect_detected |
| tile/test/good/012.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| tile/test/good/013.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| tile/test/good/017.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| tile/test/good/022.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| tile/test/good/024.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| tile/test/good/025.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| tile/test/good/026.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| tile/test/good/027.png | good | ✓ no_defect_detected | ✓ no_defect_detected |
| tile/test/gray_stroke/005.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| tile/test/gray_stroke/012.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| tile/test/oil/012.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| tile/test/oil/017.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| tile/test/rough/002.png | defect | ✓ suspected_defect | ✓ suspected_defect |
| tile/test/rough/007.png | defect | ✓ suspected_defect | ✗ no_defect_detected |
