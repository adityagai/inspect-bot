---
source_id: PROC-CT-004
title: Ceramic tile - static single-view image inspection
category: ceramic_tile
doc_type: procedure
version: 1.0
synthetic: true
---
# Ceramic tile: static single-view image inspection

Synthetic procedure for InspectBot experiments, written for single static photos of a tile surface such as the public MVTec AD tile category. It applies only when the lighting and viewpoint cannot be changed. In that setting it replaces the multi-view criteria of PROC-CT-001 and PROC-CT-003.

## Normal appearance
The tile surface is grey with a granular pattern of light and dark speckles. Natural variation in speckle size and density across the surface is normal when it matches the approved reference image.

## Criterion CT-4: suspected defect
Compare the image with the approved reference (get_reference). Report Suspected defect when a localized region clearly breaks the uniform speckle texture and has no counterpart on the reference. Typical examples:
- **Crack:** a sharp dark line or fracture
- **Glue strip:** a glossy or translucent smear or band
- **Gray stroke:** a grey streak or brush-like mark
- **Oil:** a dark, diffuse stain
- **Rough:** a patch whose texture is coarser or disturbed

## No defect
Report No defect detected when the texture is uniform across the whole tile and any variation is of the same kind as the reference.

## Insufficient evidence
Report Insufficient evidence only if the image is unusable, or if a region is genuinely ambiguous after comparison with the reference.
