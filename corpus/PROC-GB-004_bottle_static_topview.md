---
source_id: PROC-GB-004
title: Glass bottle - static top-view image inspection
category: glass_bottle
doc_type: procedure
version: 1.0
synthetic: true
---
# Glass bottle: static top-view image inspection

Synthetic procedure for InspectBot experiments, written for single static top-view photos such as the public MVTec AD bottle category. It applies only when the lighting and viewpoint cannot be changed. In that setting it replaces the multi-view criteria of PROC-GB-001 and PROC-GB-002.

## Normal appearance
The bottle is photographed from directly above. A bright, continuous circular rim (the mouth) surrounds a darker interior with smooth, concentric shading. Small reflections that also appear on the approved reference image are normal.

## Criterion GB-4: suspected defect
Compare the image with the approved reference (get_reference). Report Suspected defect when either holds:
- **Broken rim:** the rim ring is interrupted, chipped, jagged or missing a section, large or small, where the reference shows a smooth continuous ring.
- **Contamination:** a distinct foreign object, particle, fibre or irregular blob is visible inside the bottle that the reference does not show.

## No defect
Report No defect detected when the rim is continuous and the interior shows only the smooth pattern of the reference.

## Insufficient evidence
Report Insufficient evidence only if the image is too blurred or dark to judge the rim and interior.
