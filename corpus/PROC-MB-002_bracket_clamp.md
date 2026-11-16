---
source_id: PROC-MB-002
title: Metal bracket - inspecting regions under the hold-down clamp
category: metal_bracket
doc_type: procedure
version: 1.0
synthetic: true
---
# Metal bracket: inspecting regions under the hold-down clamp

Synthetic procedure for InspectBot experiments.

## Situation
In some fixtures a hold-down clamp plate covers the centre of the bracket face. The covered region cannot be inspected from the front, top or oblique-low poses.

## Required view
Only the left_45 pose sees past the clamp edge. Request it once. Changing the lighting does not help, because the clamp blocks the camera's line of sight.

## If the required view is unavailable
If left_45 is unreachable or keeps failing, do not infer the condition of the covered region from the surrounding surface. A clean surface around the clamp says nothing about the surface under it.

Report Insufficient evidence. Name the uninspected region and the failed actions, and ask the reviewer to re-fixture the part or authorize a different cell.
