# Day 7: MVTec AD static-image evaluation

This is the real-image experiment from Checkpoint 2.1. InspectBot and the prompt-only baseline classify held-out MVTec AD test photos. Both use the same model (claude-sonnet-5-5).

## Setup

- **Images:** 40 test images from **bottle** (top view of a glass bottle) and **tile** (ceramic tile texture): 20 defective and 20 good.
  - The set was drawn with seed 42 and written to `eval/mvtec_selection.json` before any model run.
  - Bottle defect types: broken_large, broken_small, contamination.
  - Tile defect types: crack, glue_strip, gray_stroke, oil, rough.
- **Labels:** taken from the MVTec folder names (`test/good` against `test/<defect>`) and used only for scoring.
- **Warm-up:** four separate images (one defective and one good per category) were used only to check that the pipeline runs, and no prompts were changed afterwards. They scored 4/4.
- **Static mode:**
  - Each run starts with the MCP tool `start_static_inspection`.
  - The camera can't move and the lighting can't change; both tools return `UNSUPPORTED`.
  - `get_reference` returns one approved good image from `train/good`. That image is never a test image.
- **Procedures:** two new versioned procedures cover a single fixed-camera image and replace the multi-view criteria:
  - `PROC-GB-004`: a broken rim or contamination that the reference doesn't have.
  - `PROC-CT-004`: a local break in the tile texture that the reference doesn't have.
- **Baseline:** a single prompt with the image and the category. It has no reference, retrieval or verification.

## Scoring

Suspected defect is the positive class.

- **Precision** = TP / (TP + FP).
- **Recall** = TP / defective images. An "insufficient evidence" answer on a defective image counts as a miss.
- **Decision coverage** = definitive outcomes / all images.

## Results (run `mvtec-eval-20261120-1225`)

| Metric | InspectBot | Baseline | Target |
| --- | --- | --- | --- |
| Precision | **86%** (19/22) | 75% (18/24) | ≥ 85% ✓ |
| Recall | **95%** (19/20) | 90% (18/20) | ≥ 85% ✓ |
| Decision coverage | **92%** (37/40) | 100% | ≥ 80% ✓ |
| Accuracy | 82% | 80% | — |
| Good images flagged as defects | **3** | 6 | — |
| Defects cleared as good | **1** | 2 | — |
| Grounded definitive reports | 37/37 | — | 100% |
| Mean latency | 25 s | 2.5 s | — |

Recall by defect type was perfect except for one type in each mode:

- **Bottle contamination:** InspectBot and the baseline each found 2/3. InspectBot missed 020 and the baseline missed 011.
- **Tile rough:** InspectBot found 2/2; the baseline found 1/2.

The per-image table is in [`summary.md`](../eval/results/mvtec-eval-20261120-1225/summary.md).

## Where InspectBot went wrong

- **False positive: 3 good bottles flagged** (001, 004, 015). In each one, InspectBot reported thin bright arcs or hairline marks on the rim that the single reference doesn't show. These are most likely normal variation in rim reflections, read as a defect. This is the main weakness, and it's the same error the baseline makes twice as often.
- **Miss: 1 contamination** (020). A small foreign particle inside the bottle was judged consistent with the reference.
- **3 abstentions, all on good images** (bottle 016 and 019, tile 006). The verifier wouldn't clear the image but found nothing that met the defect criterion, so it escalated to human review. This is the intended behavior when evidence is ambiguous. It costs decision coverage, but it never adds a false clear.

## Comparison and limits

InspectBot beats the baseline on precision (+11 points) and recall (+5 points), and halves the false alarms on good parts. The cost is 10× the latency and a few escalations.

With a single fixed image, the advantage is smaller than in the simulation (20/20 against 8/20). That is expected: the simulation advantage comes mostly from collecting new views, which a static image doesn't allow. Here the gains come from the approved reference, the category procedure and verification.

Limits:

- These are single runs on 2 of the 15 MVTec categories.
- Each category has 10 defective images, so one image changes recall by 5 points.
- The results aren't general performance claims.

## Reproduce

Download MVTec AD, then:

```bash
python eval/run_mvtec.py --root /path/to/MVTec-Dataset --set warmup   # 4 images
python eval/run_mvtec.py --root /path/to/MVTec-Dataset                # the 40-image set
```
