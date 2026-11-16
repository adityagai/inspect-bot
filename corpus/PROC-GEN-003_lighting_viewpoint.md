---
source_id: PROC-GEN-003
title: Lighting and viewpoint techniques for line-like features
category: general
doc_type: guideline
version: 1.0
synthetic: true
---
# Lighting and viewpoint techniques for line-like features

Synthetic technique note for InspectBot experiments.

## Separating shadows from surface features
A cast shadow depends on the light direction. From a fixed camera pose, changing the light from one side to the other moves a shadow. Switching to top or diffuse light usually removes it. A feature on the surface stays in the same place on the part whatever the light.

## Revealing surface relief
Raking light, or a low oblique camera view, exaggerates relief. A crack with a broken or raised edge shows a bright lip or a gap along the line. A printed mark or stain shows neither.

## Occlusion
Lighting cannot reveal a region that something covers. Only a camera move to a pose that sees past the obstruction can. If no reachable pose sees the region, the region is uninspected.

## Zoom
Digital zoom enlarges captured pixels. It cannot recover detail the camera did not capture.
